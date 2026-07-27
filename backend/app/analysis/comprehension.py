"""C-file comprehension — REDUCE the per-segment map facts into ONE case picture.

Where intake/mappass.py is the MAP (facts per segment, with provenance), this is
the REDUCE: fold every segment's facts across the veteran's whole file into a
durable, structured CFilePicture — a timeline, a condition roster carrying the
three service-connection elements per condition, exam / nexus / decision
inventories, the contradictions, the coverage gaps, and an HONEST
read-completeness record. It runs as a best-effort background job (mirroring the
firm deep-dive) and caches its result in CFilePictureCache keyed on the exact
document revisions that drove it, so it regenerates only when the record changes.

The reduce (`build_case_picture`) is PURE and deterministic — it ORGANIZES what the
record says and names the gaps; it never decides service connection or authors a
medical opinion (the legal lane). The map facts are the model's; the picture is
arithmetic over them, so it can't hallucinate a rating the record doesn't contain.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from contextlib import asynccontextmanager

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

log = logging.getLogger("veteran_ops.comprehension")

# The three elements of a direct service-connection claim (Shedden/Caluza).
SC_ELEMENTS = ("current_diagnosis", "in_service_event", "nexus")


def _casefold(s) -> str:
    return (s or "").strip().casefold()


def _provenance(seg: dict) -> dict:
    """Compact source pointer for a fact — where in the file it was read."""
    prov = {
        "segment": seg.get("segment"),
        "page": seg.get("page"),
        "char_start": seg.get("char_start"),
        "char_end": seg.get("char_end"),
    }
    if seg.get("document_id"):
        prov["document_id"] = seg["document_id"]
    return prov


def _condition_key(name, dc) -> tuple[str, str]:
    return (_casefold(name), (dc or "").strip())


def _roster(segments: list[dict]) -> dict[tuple, dict]:
    """Dedup conditions across every segment, keeping the first non-null percent /
    decision and accumulating provenance."""
    roster: dict[tuple, dict] = {}
    for seg in segments:
        prov = _provenance(seg)
        for c in seg.get("conditions") or []:
            key = _condition_key(c.get("name"), c.get("diagnostic_code"))
            if not key[0]:
                continue
            entry = roster.get(key)
            if entry is None:
                entry = {
                    "name": c.get("name"),
                    "diagnostic_code": c.get("diagnostic_code"),
                    "rating_percent": c.get("rating_percent"),
                    "decision": c.get("decision"),
                    "provenance": [],
                }
                roster[key] = entry
            if entry["rating_percent"] is None and c.get("rating_percent") is not None:
                entry["rating_percent"] = c["rating_percent"]
            if entry["decision"] is None and c.get("decision") is not None:
                entry["decision"] = c["decision"]
            entry["provenance"].append(prov)
    return roster


def _inventory(segments: list[dict], key: str, fields: tuple[str, ...]) -> list[dict]:
    """Flatten one fact-type across segments, each item stamped with provenance."""
    out: list[dict] = []
    for seg in segments:
        prov = _provenance(seg)
        for item in seg.get(key) or []:
            if not isinstance(item, dict):
                continue
            row = {f: item.get(f) for f in fields}
            row["provenance"] = prov
            out.append(row)
    return out


def _sc_elements(name: str, nexus_inv: list[dict], decision_inv: list[dict]) -> tuple[dict, list[str]]:
    """Which of the three SC elements the RECORD (as read) evidences for a condition.

    Conservative + honest: a current diagnosis is present because the file names the
    condition; nexus is present when a nexus statement references it; the in-service
    element is treated as evidenced only when VA has GRANTED the condition (a grant
    accepts the in-service link). Absent elements become coverage gaps — this
    ORGANIZES evidence and flags gaps; it never rules the element legally met.
    """
    key = _casefold(name)
    nexus_hits = [n for n in nexus_inv if key and key in _casefold(n.get("text"))]
    granted = [
        d for d in decision_inv
        if d.get("decision") == "granted" and key and key in _casefold(d.get("condition"))
    ]
    elements = {
        "current_diagnosis": {"present": True, "basis": "named in the record"},
        "nexus": {
            "present": bool(nexus_hits),
            "basis": ("nexus opinion on file" if nexus_hits else None),
            "meets_standard": any(n.get("meets_standard") for n in nexus_hits),
        },
        "in_service_event": {
            "present": bool(granted),
            "basis": ("accepted (condition granted)" if granted else None),
        },
    }
    missing = [e for e in SC_ELEMENTS if not elements[e]["present"]]
    return elements, missing


def _timeline(
    exam_inv: list[dict],
    decision_inv: list[dict],
    segments: list[dict],
    *,
    exclude_dates: set[str] | frozenset[str] | None = None,
) -> list[dict]:
    """Dated claim events across the file, sorted oldest→newest.

    Undated events are dropped from the timeline (still in inventories).
    `exclude_dates` drops ISO dates that belong to household/dependents (spouse
    or child birthdays) so they never appear as the veteran's claim timeline.
    Generic map-pass "dates" only contribute when the segment is claim-relevant
    and the date is not excluded — exams/decisions always win if dated.
    """
    skip = {str(d) for d in (exclude_dates or set()) if d}
    events: list[dict] = []
    seen_keys: set[tuple[str, str, str]] = set()
    dates_with_primary: set[str] = set()  # exam/decision dates already on the timeline

    def _add(date: str, kind: str, label: str, provenance) -> None:
        iso = str(date or "").strip()[:10]
        if not iso or iso in skip:
            return
        # Generic map-pass dates are noise when an exam/decision already covers the day.
        if kind == "date" and iso in dates_with_primary:
            return
        key = (iso, kind, label)
        if key in seen_keys:
            return
        seen_keys.add(key)
        if kind in ("exam", "decision"):
            dates_with_primary.add(iso)
        events.append(
            {"date": iso, "kind": kind, "label": label, "provenance": provenance}
        )

    for e in exam_inv:
        if e.get("date"):
            label = e.get("type") or "exam"
            if e.get("provider"):
                label = f"{label} — {e['provider']}"
            _add(e["date"], "exam", label, e.get("provenance"))
    for d in decision_inv:
        if d.get("date"):
            cond = d.get("condition") or "claim"
            _add(
                d["date"],
                "decision",
                f"{cond}: {d.get('decision') or 'decided'}",
                d.get("provenance"),
            )
    for seg in segments:
        if not seg.get("claim_relevant"):
            continue
        # Soft noise: map-pass "dates" often include family DOBs from 686c forms.
        if float(seg.get("salience") or 0) < 0.25:
            continue
        prov = _provenance(seg)
        for iso in seg.get("dates") or []:
            _add(iso, "date", "record date", prov)
    events.sort(key=lambda ev: ev.get("date") or "")
    return events


def _read_completeness(read_coverage: dict | None, page_stats: dict | None, truncated: bool) -> dict:
    """Honest coverage record: how many segments/pages were actually read, how many
    were unreadable, and whether the file was truncated — never implying full
    coverage. Extends the read_coverage / TRUNCATION_NOTE mechanism from intake."""
    rc = read_coverage or {}
    ps = page_stats or {}
    total = int(rc.get("segments_total") or 0)
    read = int(rc.get("segments_read") or 0)
    failed = int(rc.get("segments_failed") or 0)
    pages_total = ps.get("pages_total")
    pages_read = ps.get("pages_read")
    pages_unreadable = int(ps.get("pages_unreadable") or 0)
    parts: list[str] = []
    if total:
        parts.append(f"Read {read} of {total} sections")
    if pages_total:
        parts.append(f"{pages_read if pages_read is not None else pages_total} of {pages_total} pages")
    if pages_unreadable:
        parts.append(f"{pages_unreadable} page(s) unreadable")
    if failed:
        parts.append(f"{failed} section(s) could not be analyzed (retry with Reprocess)")
    if truncated:
        parts.append("the file was large and read in part")
    note = ("; ".join(parts) + ".") if parts else "Full file read."
    return {
        "segments_total": total,
        "segments_read": read,
        "segments_failed": failed,
        "pages_total": pages_total,
        "pages_read": pages_read,
        "pages_unreadable": pages_unreadable,
        "truncated": bool(truncated),
        "complete": bool(total) and failed == 0 and pages_unreadable == 0 and not truncated,
        "note": note,
    }


def build_case_picture(
    segments: list[dict],
    *,
    read_coverage: dict | None = None,
    page_stats: dict | None = None,
    truncated: bool = False,
    chunks: list | None = None,
    exclude_timeline_dates: set[str] | frozenset[str] | list[str] | None = None,
) -> dict:
    """PURE REDUCE: fold validated per-segment map facts into one CFilePicture.

    `segments` is the list of validated facts from intake.mappass.run_map_pass
    (optionally across several documents, each fact carrying its provenance). The
    picture is a deterministic organization of what the record says + where it says
    it, plus the coverage gaps and an honest read-completeness record. `chunks` (RAG
    excerpts) are attached verbatim as grounding, never interpreted.
    `exclude_timeline_dates`: ISO dates (e.g. spouse/child DOBs from profile) that
    must not appear on the claim timeline.
    """
    segments = [s for s in (segments or []) if isinstance(s, dict)]
    exclude = {str(d) for d in (exclude_timeline_dates or []) if d}
    roster_map = _roster(segments)
    exam_inv = _inventory(segments, "exams", ("type", "date", "provider"))
    nexus_inv = _inventory(segments, "nexus_statements", ("text", "meets_standard"))
    decision_inv = _inventory(segments, "decisions", ("condition", "decision", "date"))

    # Contradictions are plain strings per segment, not dicts — collect with provenance.
    contradictions = []
    for seg in segments:
        prov = _provenance(seg)
        for note in seg.get("contradictions") or []:
            contradictions.append({"note": note, "provenance": prov})

    roster: list[dict] = []
    coverage_gaps: list[dict] = []
    for entry in roster_map.values():
        elements, missing = _sc_elements(entry["name"], nexus_inv, decision_inv)
        entry["sc_elements"] = elements
        entry["missing_elements"] = missing
        roster.append(entry)
        if missing:
            coverage_gaps.append(
                {
                    "condition": entry["name"],
                    "missing_elements": missing,
                    "note": (
                        "The record as read doesn't clearly show "
                        + ", ".join(m.replace("_", " ") for m in missing)
                        + " — worth confirming with your evidence or a VSO."
                    ),
                }
            )
    roster.sort(key=lambda r: _casefold(r.get("name")))

    completeness = _read_completeness(read_coverage, page_stats, truncated)
    # File-level gaps: unreadable/failed/truncated reads leave the picture partial.
    if not completeness["complete"]:
        coverage_gaps.append(
            {
                "condition": None,
                "missing_elements": ["full_read"],
                "note": "Read coverage is partial — " + completeness["note"],
            }
        )

    grounding = []
    for c in chunks or []:
        grounding.append(
            {
                "document_id": str(getattr(c, "document_id", "") or ""),
                "excerpt": (getattr(c, "content", "") or "")[:600],
                "char_start": getattr(c, "char_start", None),
            }
        )

    return {
        "timeline": _timeline(
            exam_inv, decision_inv, segments, exclude_dates=exclude
        ),
        "condition_roster": roster,
        "exam_inventory": exam_inv,
        "nexus_inventory": nexus_inv,
        "decision_inventory": decision_inv,
        "contradictions": contradictions,
        "coverage_gaps": coverage_gaps,
        "read_completeness": completeness,
        "grounding_excerpts": grounding,
        "generated_from_segments": len(segments),
    }


# ── Background job (best-effort, RLS-scoped) — mirrors firm.jobs deep-dive ────────


def _facts_hash(docs: list[dict]) -> str:
    """Stable key over the exact ready-document revisions the picture is built from
    (id + immutable sha + updated_at) — regenerates only when the record changes,
    the GamePlanFirmCache facts_hash pattern."""
    payload = [
        {"id": d["id"], "sha256": d.get("sha256"), "updated_at": str(d.get("updated_at"))}
        for d in docs
    ]
    payload.sort(key=lambda d: d["id"])
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iso_date(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()[:10]
        except Exception:  # noqa: BLE001
            return None
    s = str(value).strip()
    return s[:10] if len(s) >= 10 and s[4] == "-" else None


async def _household_exclude_dates(db, user_id: str, docs: list[dict]) -> set[str]:
    """ISO dates that must never appear on the claim timeline (spouse/child DOBs).

    Sources: profile.dependents + per-document identity_suggestion.dependents.
    """
    from ..models import VeteranProfile

    out: set[str] = set()
    try:
        profile = (
            await db.execute(
                select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(str(user_id)))
            )
        ).scalar_one_or_none()
    except SQLAlchemyError:
        profile = None
    if profile is not None:
        for dep in profile.dependents or []:
            if not isinstance(dep, dict):
                continue
            iso = _iso_date(dep.get("date_of_birth"))
            if iso:
                out.add(iso)
    for doc in docs:
        sug = (doc.get("extracted") or {}).get("identity_suggestion") or {}
        if not isinstance(sug, dict):
            continue
        for dep in sug.get("dependents") or []:
            if not isinstance(dep, dict):
                continue
            iso = _iso_date(dep.get("date_of_birth"))
            if iso:
                out.add(iso)
    return out


async def get_case_picture(db, user_id: str) -> dict | None:
    """Latest cached CFilePicture for the veteran (RLS-scoped read). None when the
    comprehension job hasn't run yet — the caller says so honestly."""
    from ..models import CFilePictureCache

    try:
        row = (
            await db.execute(
                select(CFilePictureCache.payload)
                .where(CFilePictureCache.user_id == uuid.UUID(str(user_id)))
                .order_by(CFilePictureCache.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row if isinstance(row, dict) else None
    except SQLAlchemyError:
        return None


async def _replace_document_facts(db, user_id: str, document_id: uuid.UUID, segments: list[dict]) -> int:
    """Delete a document's prior mapped facts and insert the fresh per-segment set
    (RLS-fenced; the trigger stamps workspace_id from the GUC). Idempotent so a
    re-map is clean."""
    from ..models import DocumentFact

    await db.execute(delete(DocumentFact).where(DocumentFact.document_id == document_id))
    uid = uuid.UUID(str(user_id))
    written = 0
    for seg in segments:
        db.add(
            DocumentFact(
                user_id=uid,
                document_id=document_id,
                segment_index=int(seg.get("segment") or 0),
                char_start=int(seg.get("char_start") or 0),
                char_end=int(seg.get("char_end") or 0),
                page=seg.get("page"),
                claim_relevant=bool(seg.get("claim_relevant")),
                salience=float(seg.get("salience") or 0.0),
                facts=seg,
            )
        )
        written += 1
    return written


async def run_comprehension_in_session(
    db,
    user_id: str,
    *,
    force: bool = False,
    model_extraction: str = "",
) -> dict | None:
    """Build (or serve the cached) whole-C-file picture for one veteran.

    Best-effort and additive: it maps every ready document, persists the per-segment
    facts (DocumentFact), reduces them into a CFilePicture, and caches it. On a
    facts-hash cache hit it returns the cached picture without re-running the model.
    `model_extraction` is resolved by the caller (overrides.effective_model_for(
    tier="extraction", touches_pii=True, ...)). Never raises.
    """
    from ..models import CFilePictureCache, Document, VeteranProfile
    from ..intake.mappass import run_map_pass
    from ..rag import retrieve_document_chunks

    rows = (
        await db.execute(
            select(
                Document.id, Document.text_content, Document.page_offsets,
                Document.sha256, Document.updated_at, Document.extracted,
            ).where(
                Document.user_id == uuid.UUID(str(user_id)),
                Document.status == "ready",
            )
        )
    ).all()
    docs = [
        {"id": str(r.id), "text": r.text_content, "page_offsets": r.page_offsets,
         "sha256": r.sha256, "updated_at": r.updated_at, "extracted": r.extracted or {}}
        for r in rows
        if (r.text_content or "").strip()
    ]
    if not docs:
        return None

    facts_hash = _facts_hash(docs)
    cached = await get_case_picture(db, user_id)
    if cached is not None and not force and cached.get("facts_hash") == facts_hash:
        return cached

    # Household DOBs must never land on the veteran's claim timeline.
    exclude_timeline_dates = await _household_exclude_dates(db, user_id, docs)

    all_segments: list[dict] = []
    seg_total = seg_read = seg_failed = 0
    truncated = False
    for doc in docs:
        mp = await run_map_pass(doc["text"], doc["page_offsets"], model=model_extraction)
        for seg in mp["segments"]:
            seg = {**seg, "document_id": doc["id"]}
            all_segments.append(seg)
        rc = mp["read_coverage"]
        seg_total += rc["segments_total"]
        seg_read += rc["segments_read"]
        seg_failed += rc["segments_failed"]
        if (doc["extracted"] or {}).get("truncated"):
            truncated = True
        try:
            await _replace_document_facts(db, user_id, uuid.UUID(doc["id"]), mp["segments"])
        except SQLAlchemyError:
            log.warning("could not persist document facts for %s", doc["id"], exc_info=True)

    chunks = []
    try:
        chunks = await retrieve_document_chunks(db, user_id, "diagnosis nexus service connection rating", k=6)
    except Exception:  # noqa: BLE001 — grounding is optional
        chunks = []

    picture = build_case_picture(
        all_segments,
        read_coverage={"segments_total": seg_total, "segments_read": seg_read, "segments_failed": seg_failed},
        truncated=truncated,
        chunks=chunks,
        exclude_timeline_dates=exclude_timeline_dates,
    )
    picture["facts_hash"] = facts_hash

    try:
        db.add(CFilePictureCache(user_id=uuid.UUID(str(user_id)), facts_hash=facts_hash, payload=picture))
        await db.flush()
    except SQLAlchemyError:
        await db.rollback()
        log.warning("could not cache CFilePicture for %s", user_id, exc_info=True)
    return picture


async def run_comprehension_for_user(
    user_id: str, workspace_id: str | None = None, *, force: bool = False
) -> bool:
    """Open a fresh RLS-scoped transaction and build the veteran's case picture.

    Resolves the extraction model through the consent-aware PII gate itself: the
    whole-C-file quality mode reads the veteran's raw record text, so it may only send
    that text to a frontier/cloud model when the workspace has privacy off AND has
    explicitly consented to PII→cloud (``overrides.resolve_pii_model``). Without both,
    the read stays on the local model. An actual release is recorded in the append-only
    audit trail. Never affects intake."""
    from .. import audit
    from ..db import session_for_user
    from ..overrides import resolve_pii_model

    try:
        scoped = asynccontextmanager(session_for_user)
        async with scoped(str(user_id), workspace_id) as db:
            model, _pm, released = await resolve_pii_model(db, tier="extraction")
            if released:
                # Consent gate satisfied: log the release of the veteran's C-file text
                # to a non-local model BEFORE the read runs (accountability for PII
                # leaving the fleet). flush()-only inside the RLS txn; the context
                # teardown commits once.
                await audit.log(
                    db,
                    str(user_id),
                    "privacy.pii_cloud_release",
                    entity="cfile_comprehension",
                    meta={"tier": "extraction", "model": model, "surface": "cfile_comprehension"},
                )
            await run_comprehension_in_session(db, str(user_id), force=force, model_extraction=model)
            return True
    except Exception:  # noqa: BLE001 — comprehension is additive, never blocks intake
        log.warning("comprehension job failed for user %s", user_id, exc_info=True)
        return False
