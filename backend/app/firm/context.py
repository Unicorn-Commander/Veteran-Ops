"""`VeteranDossier` — the single, canonical read of everything the firm and the
Battle Plan reason over, so the two can never disagree.

`build_dossier()` is the refactor of what `routers/strategy._assemble_strategy`
used to gather inline: the veteran's conditions (with readiness bands), their
uploaded documents, the denials decoded from decision letters, the active ITF,
the profile, the current combined rating, and the not-yet-claimed suggestions.
The router builds the dossier once and derives BOTH `build_game_plan(...)` and
`run_firm(...)` from it — identical data in, no drift.

Read-only assembly. No LLM, no writes.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analysis.presumptives import cumulative_service_days, match_presumptives
from ..analysis.secondaries import match_secondaries
from ..decoder.deadline import appeal_window
from ..kb.store import cards_by_type, load_cards, load_secondary_map
from ..models import (
    ClaimedCondition,
    Document,
    EvidenceItem,
    ItfRecord,
    VeteranProfile,
)
from ..readiness.score import score_condition
from ..strategy.plan import merge_denied_conditions

# Presumptive program → warm label (moved verbatim from routers/strategy).
_PROGRAM_LABELS = {
    "pact_burn_pits": "PACT Act — burn pits / airborne hazards",
    "agent_orange": "Agent Orange / herbicide exposure",
    "gulf_war": "Gulf War illness (§3.317)",
    "camp_lejeune": "Camp Lejeune contaminated water",
    "radiation": "Radiation-exposed veterans",
    "chronic_one_year": "Chronic diseases within 1 year of separation",
    "pow": "Former POW (§3.309(c))",
    "als": "ALS (§3.318)",
}


@dataclass
class VeteranDossier:
    """Everything the firm and the Claim Plan read — assembled ONCE."""

    uid: str
    conditions: list[dict] = field(default_factory=list)  # cond_data (with bands/missing)
    documents: list[Document] = field(default_factory=list)
    denials: list[dict] = field(default_factory=list)  # decoded + recorded, merged
    active_itf: dict | None = None
    profile: dict | None = None  # {service_periods, exposures, …}
    # Household dependents from the profile (for deadline / money context). Empty
    # list when none; never omit the field so tools don't fall back to getattr.
    dependents: list[dict] = field(default_factory=list)
    current_combined: int | None = None
    suggestions: list[dict] = field(default_factory=list)  # not-yet-claimed {name, relation, kind}
    generated_at: str = ""


def _active_itf(records: list[ItfRecord], today: date) -> dict | None:
    """Soonest not-yet-expired ITF (same logic as routers/itf.py / form526.py)."""
    best = None
    for rec in records:
        w = appeal_window(rec.filed_date, today)
        if w["expired"]:
            continue
        row = {"type": rec.type, "deadline": w["deadline"], "days_remaining": w["days_remaining"]}
        if best is None or row["days_remaining"] < best["days_remaining"]:
            best = row
    return best


def _denials(documents: list[Document]) -> list[dict]:
    """Denied decision rows across the veteran's decoded letters (decoder cache)."""
    out: list[dict] = []
    seen: set[str] = set()
    for doc in documents:
        extracted = doc.extracted or {}
        decode = extracted.get("decode") if isinstance(extracted, dict) else None
        if not isinstance(decode, dict):
            continue
        for row in decode.get("decisions") or []:
            if not isinstance(row, dict) or row.get("decision") != "denied":
                continue
            name = (row.get("name") or "").strip()
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append({"name": name, "missing_elements": row.get("missing_elements") or []})
    return out


def _decision_rows_from_extracted(extracted: dict) -> list[dict]:
    """Collect decision rows from the several shapes intake/decode leave on a doc.

    Preferred order (later sources within one doc overwrite earlier):
      1. extracted.decode.decisions  (formal decoder)
      2. extracted.rating_summary    (classify / intake)
      3. extracted.conditions_mentioned  (often richer when rating_summary is [])
    """
    rows: list[dict] = []
    decode = extracted.get("decode")
    if isinstance(decode, dict):
        for row in decode.get("decisions") or []:
            if isinstance(row, dict):
                rows.append(row)
    for key in ("rating_summary", "conditions_mentioned"):
        block = extracted.get(key)
        if isinstance(block, list):
            for row in block:
                if isinstance(row, dict):
                    rows.append(row)
    return rows


def _is_va_rating_decision_doc(doc: Document, extracted: dict) -> bool:
    """True for formal VA rating/decision letters — NOT C&P exams, narratives, or STRs.

    C&P/classify extracts sometimes stamp decision=granted on exams (Aaron dogfood:
    C and P EXAM marked Unspecified Anxiety granted), which must not override a
    real denial letter.
    """
    if extracted.get("is_va_decision") is True:
        return True
    doc_type = (
        (getattr(doc, "doc_type", None) or extracted.get("doc_type") or "")
        .strip()
        .lower()
    )
    if doc_type in (
        "rating_decision",
        "decision_letter",
        "rating decision",
        "decision letter",
        "va_decision",
    ):
        return True
    fname = (getattr(doc, "filename", None) or "").lower()
    # Common C-file naming for rating decisions / claim letters
    if any(
        token in fname
        for token in (
            "claimletter",
            "claim_letter",
            "decision_letter",
            "decision-letter",
            "rating decision",
            "rating_decision",
        )
    ):
        # Exclude packets that are not decisions
        if "c and p" in fname or "c&p" in fname or "exam" in fname:
            return False
        return True
    return False


def _decision_dispositions(documents: list[Document]) -> list[dict]:
    """Granted + denied dispositions from formal VA decision letters only.

    Used to overlay va_status on claimed_conditions when the veteran has not yet
    reconciled VA status (common after C-file ingest — names land as unknown).
    Never invents ratings; only copies disposition (+ percent when present).
    Collapses by normalized condition name; later decision letters win.
    """
    by_norm: dict[str, dict] = {}
    for doc in documents:
        extracted = doc.extracted if isinstance(getattr(doc, "extracted", None), dict) else None
        if not extracted:
            continue
        if not _is_va_rating_decision_doc(doc, extracted):
            continue
        for row in _decision_rows_from_extracted(extracted):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            decision = (row.get("decision") or "").strip().lower()
            if decision in ("denied", "deny", "denial"):
                va_status = "denied"
            elif decision in (
                "granted", "grant", "service_connected", "service-connected",
                "increased", "increase", "continued", "continue",
            ):
                # "continued" / "increased" imply already SC.
                va_status = "service_connected"
            else:
                # deferred / empty — ignore
                continue
            percent = (
                row.get("rating_percent")
                or row.get("percent")
                or row.get("rating")
                or row.get("evaluation")
            )
            try:
                percent_i = int(percent) if percent is not None else None
            except (TypeError, ValueError):
                percent_i = None
            key = _norm_cond_name(name) or name.lower()
            by_norm[key] = {
                "name": name,
                "va_status": va_status,
                "current_rating": percent_i if va_status == "service_connected" else None,
            }
    return list(by_norm.values())


def _norm_cond_name(name: str | None) -> str:
    n = (name or "").lower().strip()
    # Decision letters often say "X, claimed as Y" or "history of X" — take the
    # primary phrase before comma / claimed-as so "depression" alone does not
    # match an anxiety denial's "claimed as … depression" tail.
    n = n.split(",", 1)[0].strip()
    for junk in ("history of ", "claimed as "):
        if n.startswith(junk):
            n = n[len(junk):]
    if "(" in n:
        n = n.split("(", 1)[0].strip()
    # light cleanup of residual punctuation
    n = n.replace(";", " ").replace("/", " ")
    return " ".join(n.split())


_SIGNAL_TOKENS = frozenset({
    "anxiety", "fibromyalgia", "fatigue", "bursitis", "depression", "depressive",
    "migraine", "hypertension", "ptsd", "traumatic", "knee", "tendonitis",
    "tenosynovitis", "mononucleosis", "encephalomyelitis", "gerd", "reflux",
})


def _names_match(cond_name: str, decision_name: str) -> bool:
    """Conservative fuzzy match: equality, containment of full phrase, or a
    high-signal token shared (never bare short tokens like 'disorder')."""
    cn = _norm_cond_name(cond_name)
    dn = _norm_cond_name(decision_name)
    if not cn or not dn:
        return False
    if cn == dn:
        return True
    # Full-phrase containment (min length so "knee" alone doesn't eat everything)
    if len(cn) >= 8 and (cn in dn or dn in cn):
        return True
    # Alias-ish: me/cfs / chronic fatigue
    c_toks = {t for t in cn.replace("-", " ").split() if len(t) > 3}
    d_toks = {t for t in dn.replace("-", " ").split() if len(t) > 3}
    shared = c_toks & d_toks
    if not shared:
        return False
    # Require a high-signal token so "disorder" / "history" never links unrelated rows
    if shared & _SIGNAL_TOKENS:
        return True
    # Multi-token overlap (≥2 meaningful tokens) without signal still OK
    return len(shared) >= 2


def plan_decision_status_updates(
    conditions: list[dict],
    documents: list[Document],
) -> list[dict]:
    """Propose va_status (+ optional rating) writes for conditions still `unknown`.

    Each item: {condition_id, name, from_status, to_status, decision_name,
    set_current_rating?}. Never proposes overwriting service_connected/denied/pending.
    Pure; does not mutate conditions.
    """
    dispositions = _decision_dispositions(documents)
    if not dispositions or not conditions:
        return []
    updates: list[dict] = []
    for c in conditions:
        cur = (c.get("va_status") or "unknown").strip().lower()
        if cur in ("service_connected", "denied", "pending"):
            continue
        if not (c.get("name") or "").strip():
            continue
        best = None
        for d in dispositions:
            if _names_match(c.get("name") or "", d.get("name") or ""):
                best = d
                break
        if not best:
            continue
        row = {
            "condition_id": c.get("id"),
            "name": c.get("name") or "",
            "from_status": cur or "unknown",
            "to_status": best["va_status"],
            "decision_name": best.get("name") or "",
            "set_current_rating": None,
        }
        if (
            best.get("current_rating") is not None
            and not isinstance(c.get("current_rating"), int)
        ):
            row["set_current_rating"] = best["current_rating"]
        updates.append(row)
    return updates


def apply_decision_overlay(conditions: list[dict], documents: list[Document]) -> list[dict]:
    """Overlay decision-letter dispositions onto claimed conditions when va_status
    is unknown. Does not overwrite explicit service_connected / denied / pending.
    Mutates conditions in place (same list returned) for Claim Plan / firm use.
    """
    for u in plan_decision_status_updates(conditions, documents):
        # Match by id when present, else by name (eval scripts without ids).
        target = None
        cid = u.get("condition_id")
        for c in conditions:
            if cid and c.get("id") == cid:
                target = c
                break
            if not cid and (c.get("name") or "") == u.get("name"):
                target = c
                break
        if target is None:
            # id-less rows in unit tests: match first unknown with same name
            for c in conditions:
                if (c.get("name") or "") == u.get("name"):
                    target = c
                    break
        if target is None:
            continue
        target["va_status"] = u["to_status"]
        if u.get("set_current_rating") is not None and not isinstance(
            target.get("current_rating"), int
        ):
            target["current_rating"] = u["set_current_rating"]
    return conditions


async def _suggestions(
    db: AsyncSession, conditions: list[ClaimedCondition], profile
) -> list[dict]:
    """Not-yet-claimed secondaries + presumptives, as {name, relation, kind}."""
    claimed_lnames = {c.name.strip().lower() for c in conditions}
    names = [c.name for c in conditions]
    out: list[dict] = []
    seen: set[str] = set()

    if names:
        for m in match_secondaries(names, load_secondary_map()):
            sec = (m.get("secondary") or "").strip()
            if not sec or sec.lower() in claimed_lnames or sec.lower() in seen:
                continue
            seen.add(sec.lower())
            out.append({"name": sec, "relation": f"secondary to {m.get('primary')}", "kind": "secondary"})

    profile_dict = (
        {
            "service_periods": profile.service_periods or [],
            "exposures": profile.exposures or {},
            "combat_service": profile.combat_service,
            "receives_military_retired_pay": profile.receives_military_retired_pay,
            "combat_related_disability": profile.combat_related_disability,
            "medically_retired": profile.medically_retired,
            "medically_separated": profile.medically_separated,
        }
        if profile
        else {}
    )
    chronic_fired = False  # did the general matcher already surface §3.309(a) chronic-1yr?
    if profile_dict:
        try:
            rows = await cards_by_type(db, "presumptive")
        except Exception:  # noqa: BLE001 — KB not seeded → fall back to authored files
            rows = []
        if rows:
            cards = [{"title": r.title, "source": r.source, "data": r.data} for r in rows]
        else:
            cards = [c for c in load_cards() if c.get("card_type") == "presumptive"]
        # Pass claimed names so ALS (§3.318) condition-gates in the matcher; ALS
        # suggestions themselves use the dedicated block below (educational path
        # when the veteran already has/is claiming ALS — not "file a new condition").
        for m in match_presumptives(profile_dict, cards, condition_names=list(names)):
            if m.get("program") == "chronic_one_year":
                chronic_fired = True
            if m.get("program") == "als":
                continue  # dedicated ALS educational block below
            title = (m.get("title") or "").strip()
            if not title or title.lower() in claimed_lnames or title.lower() in seen:
                continue
            seen.add(title.lower())
            program = _PROGRAM_LABELS.get(m.get("program"), m.get("program") or "presumptive")
            out.append({"name": title, "relation": f"presumptive — {program}", "kind": "presumptive"})

    # ALS (§3.318): educational path when the veteran HAS or is claiming an
    # ALS/motor-neuron condition AND has 90+ cumulative active-service days.
    # Condition-gated so 90+ days alone never spam every veteran.
    als_keywords = ("als", "amyotrophic", "lou gehrig", "motor neuron")
    has_als_condition = any(
        any(kw in (c.name or "").lower() for kw in als_keywords)
        for c in conditions
    )
    if has_als_condition and "als" not in seen:
        service_days = cumulative_service_days(
            profile.service_periods if profile else None
        )
        if service_days >= 90:
            seen.add("als")
            out.append({
                "name": "ALS (amyotrophic lateral sclerosis)",
                "relation": (
                    "als — 38 CFR §3.318: ALS is on the VA presumptive list for "
                    "veterans with 90+ days of active service — a claim needs the "
                    "diagnosis, not a nexus opinion; confirm with a VSO"
                ),
                "kind": "presumptive",
            })

    # §3.309(a) chronic disease — the general matcher only fires within 1 year of
    # separation, so for OLDER separations surface an educational prompt when the
    # veteran actually HAS a §3.309(a) chronic condition (they self-assess the timing).
    if not chronic_fired and "chronic-1yr" not in seen:
        chronic_keywords = {
            "arthritis", "diabetes", "hypertension", "high blood pressure",
            "cardiovascular", "heart disease", "sensorineural hearing loss",
            "hearing loss", "tinnitus", "peptic ulcer", "epilepsy", "psychosis",
        }
        if any(any(kw in (c.name or "").lower() for kw in chronic_keywords) for c in conditions):
            seen.add("chronic-1yr")
            out.append({
                "name": "Chronic disease within a year of separation (§3.309(a))",
                "relation": (
                    "presumptive — §3.309(a): a chronic disease like this is on the VA "
                    "presumptive list if it manifested to 10%+ within ONE YEAR of your "
                    "separation — no nexus needed, even years later. If that fits your "
                    "timeline, tell a VSO."
                ),
                "kind": "presumptive",
            })

    return out[:8]


async def build_dossier(db: AsyncSession, uid: str) -> VeteranDossier:
    """Assemble the canonical dossier — the identical data the Game Plan and the
    firm both read. Mirrors the gathering that lived in _assemble_strategy."""
    from ..kb.store import cached_max_ratings  # local: keep loaders importable w/o DB

    user_uuid = uuid.UUID(uid)

    conditions = (
        await db.execute(
            select(ClaimedCondition)
            .where(ClaimedCondition.user_id == user_uuid)
            .order_by(ClaimedCondition.created_at)
        )
    ).scalars().all()

    ev_by_cond: dict[uuid.UUID, list[dict]] = defaultdict(list)
    have_by_cond: dict[uuid.UUID, bool] = defaultdict(bool)
    evidence = (
        await db.execute(select(EvidenceItem).where(EvidenceItem.user_id == user_uuid))
    ).scalars().all()
    for e in evidence:
        ev_by_cond[e.condition_id].append({"kind": e.kind, "status": e.status})
        if e.status == "have":
            have_by_cond[e.condition_id] = True

    profile = (
        await db.execute(select(VeteranProfile).where(VeteranProfile.user_id == user_uuid))
    ).scalar_one_or_none()
    prof_dict = (
        {
            "service_periods": profile.service_periods,
            "exposures": profile.exposures,
            "combat_service": profile.combat_service,
            "receives_military_retired_pay": profile.receives_military_retired_pay,
            "combat_related_disability": profile.combat_related_disability,
            "medically_retired": profile.medically_retired,
            "medically_separated": profile.medically_separated,
        }
        if profile
        else None
    )
    max_ratings = cached_max_ratings()

    cond_data: list[dict] = []
    for c in conditions:
        cd = {
            "id": str(c.id),
            "name": c.name,
            "claim_type": c.claim_type,
            "secondary_to": str(c.secondary_to) if c.secondary_to else None,
            "in_service_event": c.in_service_event,
            "nexus_notes": c.nexus_notes,
            "diagnostic_code": c.diagnostic_code,
            "current_rating": c.current_rating,
        }
        scored = score_condition(cd, ev_by_cond.get(c.id, []), prof_dict, max_ratings)
        # Keep in_service_event / nexus_notes on the dossier so firm + tools can
        # re-run gaps without reloading ORM rows.
        cond_data.append({
            "id": str(c.id),
            "name": c.name,
            "body_system": c.body_system,
            "claim_type": c.claim_type,
            "status": c.status,
            "va_status": c.va_status,
            "diagnostic_code": c.diagnostic_code,
            "current_rating": c.current_rating,
            "target_rating": c.target_rating,
            "secondary_to": str(c.secondary_to) if c.secondary_to else None,
            "in_service_event": c.in_service_event,
            "nexus_notes": c.nexus_notes,
            "band": scored["band"],
            "missing": scored["missing"],
            "has_have_evidence": have_by_cond.get(c.id, False),
        })

    # Metadata + extracted only — never pull multi-MB OCR text_content into
    # every chat/strategy assemble. Decode lives on extracted JSONB.
    #
    # IMPORTANT: every column later read from dossier.documents (facts-hash,
    # firm, autolink, tools) MUST appear in load_only. Async SQLAlchemy raises
    # MissingGreenlet on deferred lazy-load of omitted columns (sqlalchemy.me/e/20/xd2s)
    # — that aborted comprehensive analysis when updated_at was used for the hash.
    from sqlalchemy.orm import load_only

    documents = (
        await db.execute(
            select(Document)
            .options(
                load_only(
                    Document.id,
                    Document.user_id,
                    Document.workspace_id,
                    Document.filename,
                    Document.content_type,
                    Document.status,
                    Document.doc_type,
                    Document.doc_date,
                    Document.title,
                    Document.summary,
                    Document.extracted,
                    Document.sha256,
                    Document.size_bytes,
                    Document.file_ref,
                    Document.review_status,
                    Document.created_at,
                    Document.updated_at,
                    Document.condition_id,
                )
            )
            .where(Document.user_id == user_uuid, Document.status == "ready")
            .order_by(Document.created_at)
        )
    ).scalars().all()

    # Detach so later pipeline steps (new sessions / LLM work) never trip a
    # deferred column load on these instances.
    doc_list = list(documents)
    for doc in doc_list:
        # Touch loaded attrs while the session is still open (no-ops if present).
        _ = (
            doc.id,
            doc.filename,
            doc.content_type,
            doc.status,
            doc.doc_type,
            doc.doc_date,
            doc.title,
            doc.summary,
            doc.extracted,
            doc.sha256,
            doc.size_bytes,
            doc.file_ref,
            doc.review_status,
            doc.created_at,
            doc.updated_at,
            doc.condition_id,
        )
        db.expunge(doc)

    itf_records = (
        await db.execute(
            select(ItfRecord).where(ItfRecord.user_id == user_uuid).order_by(ItfRecord.filed_date)
        )
    ).scalars().all()

    today = datetime.now(timezone.utc).date()
    # Overlay decision-letter grants/denials onto claimed conditions so reclaim /
    # secondaries / TDIU seeds fire even when va_status was never reconciled
    # after C-file ingest (Aaron dogfood: 45 conditions, mostly unknown).
    apply_decision_overlay(cond_data, doc_list)
    denials = merge_denied_conditions(_denials(doc_list), cond_data)
    suggestions = await _suggestions(db, list(conditions), profile)
    current_combined = profile.current_combined_rating if profile else None
    dependents = list(profile.dependents or []) if profile else []

    return VeteranDossier(
        uid=uid,
        conditions=cond_data,
        documents=doc_list,
        denials=denials,
        active_itf=_active_itf(list(itf_records), today),
        profile=prof_dict,
        dependents=dependents if isinstance(dependents, list) else [],
        current_combined=current_combined,
        suggestions=suggestions,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
