"""Symptom log — the veteran's own dated lay evidence, mirroring the §4
rating-criteria fields for a condition.

This is the natural Glitter Mane bridge: a veteran who already tracks day-to-day
symptoms in Glitter Mane can pull those check-ins in (tagged source="glitter"),
and everything they log here can be exported as a dated "Statement in Support of
Claim"-style lay statement — PREPARED FOR THE VETERAN'S OWN REVIEW AND SIGNATURE,
never auto-filed and never submitted on their behalf.

Legal lane: a symptom log is the veteran's own lay evidence (competent under
38 CFR §3.159(a)(2) / Layno). We never fabricate symptoms — the export only
restates what the veteran entered. Educational self-help; the letter/VA controls.

Fencing: `symptom_log_entries` is an RLS FENCED table — the GUC-pinned request
session is the primary isolation. Queries here ALSO filter by user_id explicitly
(defense-in-depth, and it keeps cross-user 404 behavior testable without a live
Postgres).
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..analysis.mapping import extract_tiers
from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, KBCard, SymptomLogEntry
from ..schemas import (
    SymptomCriteriaOut,
    SymptomCriteriaTierOut,
    SymptomLogEntryIn,
    SymptomLogEntryOut,
    SymptomLogEntryUpdate,
    SymptomLogExportOut,
    SymptomLogImportOut,
)

router = APIRouter(prefix="/symptomlog", tags=["symptomlog"])


# ── Helpers ──────────────────────────────────────────────────────────────────
async def _get_entry(
    db: AsyncSession, uid: str, entry_id: uuid.UUID
) -> SymptomLogEntry:
    obj = (
        await db.execute(
            select(SymptomLogEntry).where(
                SymptomLogEntry.id == entry_id,
                SymptomLogEntry.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Symptom-log entry not found")
    return obj


async def _get_condition(
    db: AsyncSession, uid: str, condition_id: uuid.UUID
) -> ClaimedCondition:
    obj = (
        await db.execute(
            select(ClaimedCondition).where(
                ClaimedCondition.id == condition_id,
                ClaimedCondition.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found")
    return obj


async def _condition_or_none(
    db: AsyncSession, uid: str, condition_id: uuid.UUID | None
) -> ClaimedCondition | None:
    """User-scoped condition lookup that never raises — returns None when the id
    is absent or isn't the veteran's (so read-only surfaces degrade, never leak)."""
    if condition_id is None:
        return None
    return (
        await db.execute(
            select(ClaimedCondition).where(
                ClaimedCondition.id == condition_id,
                ClaimedCondition.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()


# The §4 criteria text packs several alternative findings into one sentence,
# separated by "; or", ";", or ", or". Split into concise chips the UI can offer
# as tags — one alternative per chip.
_PHRASE_SPLIT = re.compile(r"\s*;\s*(?:or\s+)?|\s*,\s+or\s+", re.IGNORECASE)


def _split_phrases(criteria: str) -> list[str]:
    """One rating-criteria sentence → concise tag phrases (deduped, trimmed)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in _PHRASE_SPLIT.split(criteria or ""):
        phrase = raw.strip().strip(".").strip()
        if not phrase:
            continue
        # Keep chips readable — the full sentence still lives in the criteria text.
        if len(phrase) > 120:
            phrase = phrase[:117].rstrip() + "…"
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(phrase)
    return out


# ── CRUD ─────────────────────────────────────────────────────────────────────
@router.get("", response_model=list[SymptomLogEntryOut])
async def list_entries(
    condition_id: uuid.UUID | None = None,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The veteran's symptom log, newest entry first. Optionally scoped to one
    condition."""
    stmt = select(SymptomLogEntry).where(SymptomLogEntry.user_id == uuid.UUID(uid))
    if condition_id is not None:
        stmt = stmt.where(SymptomLogEntry.condition_id == condition_id)
    rows = (
        await db.execute(
            stmt.order_by(
                SymptomLogEntry.entry_date.desc(),
                SymptomLogEntry.created_at.desc(),
            )
        )
    ).scalars().all()
    return rows


@router.post("", response_model=SymptomLogEntryOut, status_code=status.HTTP_201_CREATED)
async def create_entry(
    payload: SymptomLogEntryIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Log a new dated symptom entry (the veteran's own lay evidence)."""
    if payload.condition_id is not None:
        await _get_condition(db, uid, payload.condition_id)  # 404 if not theirs
    entry = SymptomLogEntry(
        user_id=uuid.UUID(uid),
        condition_id=payload.condition_id,
        entry_date=payload.entry_date,
        title=payload.title,
        symptoms=payload.symptoms,
        severity=payload.severity,
        functional_impact=payload.functional_impact,
        criteria_tags=payload.criteria_tags,
        source="manual",
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    await audit.log(
        db, uid, "symptomlog.create", entity="symptom_log_entry",
        entity_id=str(entry.id),
        meta={"condition_id": str(payload.condition_id) if payload.condition_id else None},
    )
    return entry


@router.patch("/{entry_id}", response_model=SymptomLogEntryOut)
async def update_entry(
    entry_id: uuid.UUID,
    payload: SymptomLogEntryUpdate,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Partial edit. condition_id must be the veteran's own (404 otherwise)."""
    entry = await _get_entry(db, uid, entry_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("condition_id") is not None:
        await _get_condition(db, uid, changes["condition_id"])  # 404 if not theirs
    for key, value in changes.items():
        setattr(entry, key, value)
    await db.flush()
    await db.refresh(entry)
    await audit.log(
        db, uid, "symptomlog.update", entity="symptom_log_entry",
        entity_id=str(entry.id), meta={"fields": sorted(changes.keys())},
    )
    return entry


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    entry = await _get_entry(db, uid, entry_id)
    await db.delete(entry)
    await audit.log(
        db, uid, "symptomlog.delete", entity="symptom_log_entry",
        entity_id=str(entry_id),
    )


# ── §4 criteria chips (registered before /{entry_id} so the literal path wins) ─
@router.get("/criteria", response_model=SymptomCriteriaOut)
async def condition_criteria(
    condition_id: uuid.UUID | None = None,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The §4 rating-criteria phrases for the condition's diagnostic code, pulled
    from the KB rating_criteria card and split into concise chips the UI offers as
    tags. Empty (never an error) when there's no condition, no diagnostic code, or
    no matching KB card — the log still works without chips."""
    cond = await _condition_or_none(db, uid, condition_id)
    if cond is None or not (cond.diagnostic_code or "").strip():
        return SymptomCriteriaOut(
            diagnostic_code=cond.diagnostic_code if cond else None,
            condition_name=cond.name if cond else None,
            tiers=[],
        )

    dc = cond.diagnostic_code.strip()
    card = (
        await db.execute(
            select(KBCard)
            .where(
                KBCard.card_type == "rating_criteria",
                KBCard.diagnostic_code == dc,
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    tiers: list[SymptomCriteriaTierOut] = []
    if card is not None:
        for tier in extract_tiers(card.data):
            phrases = _split_phrases(tier["criteria"])
            tiers.append(SymptomCriteriaTierOut(percent=tier["percent"], criteria=phrases))

    return SymptomCriteriaOut(
        diagnostic_code=dc,
        condition_name=cond.name,
        tiers=tiers,
    )


# ── Glitter Mane import (literal path — registered before /{entry_id}) ─────────
def _gm_entry_date(row: dict) -> date:
    """The check-in's date (created_at), degrading to today for a malformed row."""
    raw = str(row.get("created_at") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return datetime.utcnow().date()


def _gm_severity(row: dict) -> int | None:
    """GM logs pain 0–10 — map to our 0–10 severity, clamped; None when absent."""
    raw = row.get("pain")
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        return max(0, min(10, int(raw)))
    except (TypeError, ValueError):
        return None


def _gm_symptoms(row: dict) -> str:
    parts = [
        str(row.get("symptoms") or "").strip(),
        str(row.get("note") or "").strip(),
    ]
    joined = " — ".join(p for p in parts if p)
    return joined or "Check-in logged (no symptom detail recorded)."


@router.post("/import-from-glitter", response_model=SymptomLogImportOut)
async def import_from_glitter(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Pull the veteran's Glitter Mane check-ins into the symptom log, tagged
    source="glitter" and clearly labeled. Idempotent: a re-pull won't duplicate a
    check-in already imported (matched on date + symptom text). Degrades cleanly to
    imported:0 when the GM bridge is off or unreachable — never 500s, so the log
    works fully with or without Glitter Mane."""
    # Local import keeps the bridge optional and avoids a circular import.
    from ..routers.glitter import _user_email, fetch_continuity

    try:
        email = await _user_email(db, uid)
        rows = await fetch_continuity(email)
    except Exception:  # noqa: BLE001 — GM is optional; any failure degrades to empty
        return SymptomLogImportOut(
            imported=0,
            entries=[],
            detail=(
                "Glitter Mane isn't connected right now, so there was nothing to "
                "import. You can still log symptoms by hand."
            ),
        )

    if not rows:
        return SymptomLogImportOut(
            imported=0,
            entries=[],
            detail="No Glitter Mane check-ins found to import.",
        )

    # Existing glitter-sourced entries, so a repeat pull is a no-op.
    existing = {
        (e.entry_date, (e.symptoms or "").strip())
        for e in (
            await db.execute(
                select(SymptomLogEntry).where(
                    SymptomLogEntry.user_id == uuid.UUID(uid),
                    SymptomLogEntry.source == "glitter",
                )
            )
        ).scalars().all()
    }

    created: list[SymptomLogEntry] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry_date = _gm_entry_date(row)
        symptoms = _gm_symptoms(row)
        if (entry_date, symptoms.strip()) in existing:
            continue
        existing.add((entry_date, symptoms.strip()))
        entry = SymptomLogEntry(
            user_id=uuid.UUID(uid),
            condition_id=None,
            entry_date=entry_date,
            title=f"Glitter Mane check-in — {entry_date.isoformat()}",
            symptoms=symptoms,
            severity=_gm_severity(row),
            functional_impact=None,
            criteria_tags=None,
            source="glitter",
        )
        db.add(entry)
        created.append(entry)

    if created:
        await db.flush()
        for entry in created:
            await db.refresh(entry)
        await audit.log(
            db, uid, "symptomlog.import_glitter", entity="symptom_log_entry",
            meta={"imported": len(created)},
        )

    detail = (
        f"Imported {len(created)} check-in(s) from Glitter Mane."
        if created
        else "Glitter Mane check-ins are already in your log — nothing new to import."
    )
    return SymptomLogImportOut(
        imported=len(created),
        entries=[SymptomLogEntryOut.model_validate(e) for e in created],
        detail=detail,
    )


# ── Lay-statement export (literal path — registered before /{entry_id}) ────────
def _severity_words(severity: int | None) -> str:
    if severity is None:
        return ""
    if severity >= 8:
        return "severe"
    if severity >= 5:
        return "moderate"
    if severity >= 1:
        return "mild"
    return "none/absent"


def build_lay_statement(
    entries: list[SymptomLogEntry], condition_name: str | None
) -> str:
    """Assemble a dated "Statement in Support of Claim"-style lay statement from the
    veteran's own log entries, in chronological (oldest-first) order. This only
    restates what the veteran entered — it never adds or embellishes symptoms."""
    subject = condition_name or "my claimed conditions"
    lines: list[str] = []
    lines.append("# Statement in Support of Claim")
    lines.append("")
    lines.append("*Lay statement prepared from my own symptom log — for my review and signature.*")
    lines.append("")
    lines.append(f"**Regarding:** {subject}")
    lines.append(f"**Prepared:** {date.today().isoformat()}")
    lines.append("")
    lines.append(
        "I am the veteran making this statement. The following is a dated account, "
        "in my own words, of the symptoms I have personally experienced and how they "
        "affect my daily life and ability to work. I am competent to describe what I "
        "have felt, seen, and lived through."
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    ordered = sorted(entries, key=lambda e: (e.entry_date, e.created_at))
    for entry in ordered:
        lines.append(f"## {entry.entry_date.isoformat()} — {entry.title}")
        sev = _severity_words(entry.severity)
        if entry.severity is not None:
            lines.append(f"**Severity:** {entry.severity}/10 ({sev})")
        lines.append("")
        lines.append(f"**Symptoms:** {entry.symptoms}")
        if (entry.functional_impact or "").strip():
            lines.append("")
            lines.append(f"**How it affected me:** {entry.functional_impact}")
        if entry.criteria_tags:
            lines.append("")
            lines.append("**Relates to rating criteria:** " + "; ".join(entry.criteria_tags))
        if entry.source == "glitter":
            lines.append("")
            lines.append("*Source: imported from my Glitter Mane health check-ins.*")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append(
        "The statements above are true and accurate to the best of my knowledge and "
        "belief. I understand this is my own lay evidence describing my lived "
        "experience."
    )
    lines.append("")
    lines.append("**Signature:** ______________________________")
    lines.append("")
    lines.append("**Printed name:** ______________________________")
    lines.append("")
    lines.append("**Date:** ______________________________")
    lines.append("")
    lines.append(
        "> Prepared for your review and signature. This is your own lay evidence, "
        "not a document filed or submitted for you. Review it, edit anything that "
        "isn't exactly right, sign it, and submit it yourself (or with your VSO)."
    )
    return "\n".join(lines)


@router.get("/export", response_model=SymptomLogExportOut)
async def export_statement(
    condition_id: uuid.UUID | None = None,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """A printable, dated lay-evidence statement assembled from the veteran's log —
    "Statement in Support of Claim" style, chronological, FOR THE VETERAN'S REVIEW
    AND SIGNATURE. Never auto-filed or submitted."""
    stmt = select(SymptomLogEntry).where(SymptomLogEntry.user_id == uuid.UUID(uid))
    if condition_id is not None:
        stmt = stmt.where(SymptomLogEntry.condition_id == condition_id)
    entries = (
        await db.execute(stmt.order_by(SymptomLogEntry.entry_date.asc()))
    ).scalars().all()

    cond = await _condition_or_none(db, uid, condition_id)
    condition_name = cond.name if cond else None

    return SymptomLogExportOut(
        markdown=build_lay_statement(list(entries), condition_name),
        entries_count=len(entries),
        condition_name=condition_name,
    )
