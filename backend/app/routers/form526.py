"""21-526EZ application packet — the veteran's completed Application for Disability
Compensation (VA Form 21-526EZ), ASSEMBLED from data already in the app (profile,
conditions, evidence, ITF) — like the per-condition packet and the records
worksheets.

Legal lane (BUILD-SPEC / WAVE6): this is NOT the fillable government PDF (no
reliable AcroForm map exists). It is a faithful, sectioned worksheet the veteran
REVIEWS, SIGNS, and either files themselves at VA.gov or hands to a free
VA-accredited VSO. Veteran-Ops never files anything — "prepared for your review
and signature." Educational, not legal advice.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..decoder.deadline import appeal_window
from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, EvidenceItem, ItfRecord, User, VeteranProfile
from ..pdf.form526_fill import build_field_values, fill_pdf
from ..schemas import (
    Form526Completeness,
    Form526Contention,
    Form526EvidenceRef,
    Form526ItfOut,
    Form526Out,
    Form526ServiceOut,
)

router = APIRouter(prefix="/form526", tags=["form526"])

# Known exposure flags on VeteranProfile.exposures → human labels. `other` (a
# free-text string) and `locations` (a list) are handled separately below.
_EXPOSURE_LABELS = {
    "burn_pits": "Burn pits",
    "agent_orange": "Agent Orange",
    "gulf_war": "Gulf War",
    "radiation": "Radiation",
    "camp_lejeune": "Camp Lejeune",
}

_DISCLAIMER = (
    "Veteran-Ops is self-help educational software — not legal advice, not a "
    "VA-accredited representative, and not affiliated with the VA. This application "
    "is prepared for YOUR review and signature. Veteran-Ops never files anything "
    "for you. Free help is available from a VA-accredited VSO (VFW, DAV, The "
    "American Legion, or your state/county veterans office)."
)

_SOURCE_NOTE = (
    "This is your own data — profile, conditions, evidence, and Intent to File — "
    "assembled into the shape of VA Form 21-526EZ for you to review. It is NOT the "
    "official fillable PDF and it is not submitted anywhere. Verify the current form "
    "and file online at VA.gov, or hand this to a free VSO who files it with you."
)

_GUIDANCE = [
    "File online: the fastest path is VA.gov → \"File for disability compensation\" "
    "(the 21-526EZ). Sign in with Login.gov or ID.me and transcribe each section "
    "below onto the online form.",
    "Or file with free help: bring this to a VA-accredited VSO (VFW, DAV, The "
    "American Legion, or your state/county veterans office) — they file it for you "
    "at no cost.",
    "File an Intent to File FIRST if you haven't: it locks in your effective date "
    "(and back pay) for one year while you gather evidence. You can start one on "
    "VA.gov before the full claim.",
    "Attach your evidence: upload the diagnoses, service records, nexus letters, "
    "DBQs, and lay/buddy statements listed under each condition. The \"still "
    "needed\" items are gaps to close before or after you file.",
    "Review every section for accuracy and completeness, then sign and date. You "
    "are the one who reviews, signs, and submits — Veteran-Ops never does.",
]


def _humanize_exposures(exposures: dict | None) -> list[str]:
    """Truthy exposure flags → human labels, plus any free-text `other` and
    `locations` entries."""
    if not exposures:
        return []
    out: list[str] = []
    for key, label in _EXPOSURE_LABELS.items():
        if exposures.get(key):
            out.append(label)
    other = exposures.get("other")
    if isinstance(other, str) and other.strip():
        out.append(other.strip())
    locations = exposures.get("locations")
    if isinstance(locations, list):
        for loc in locations:
            if isinstance(loc, str) and loc.strip():
                out.append(loc.strip())
    return out


def _soonest_active_itf(records: list[ItfRecord]) -> Form526ItfOut | None:
    """The soonest not-yet-expired ITF (same 'active' logic as routers/itf.py):
    reuse appeal_window for the 1-year countdown; pick the one with the fewest
    days remaining among those still open."""
    today = datetime.now(timezone.utc).date()
    best: Form526ItfOut | None = None
    for rec in records:
        w = appeal_window(rec.filed_date, today)
        if w["expired"]:
            continue
        out = Form526ItfOut(
            type=rec.type,
            filed_date=rec.filed_date,
            deadline=w["deadline"],
            days_remaining=w["days_remaining"],
            expired=w["expired"],
        )
        if best is None or out.days_remaining < best.days_remaining:
            best = out
    return best


@router.get("", response_model=Form526Out)
async def get_form526(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    user_uuid = uuid.UUID(uid)
    user = await db.get(User, user_uuid)
    profile = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == user_uuid)
        )
    ).scalar_one_or_none()

    conditions = (
        await db.execute(
            select(ClaimedCondition)
            .where(ClaimedCondition.user_id == user_uuid)
            .order_by(ClaimedCondition.created_at)
        )
    ).scalars().all()

    # One evidence query for the whole account, grouped by condition (avoids
    # N+1 across the condition list — the readiness.py pattern).
    ev_by_cond: dict[uuid.UUID, list[EvidenceItem]] = defaultdict(list)
    evidence = (
        await db.execute(
            select(EvidenceItem)
            .where(EvidenceItem.user_id == user_uuid)
            .order_by(EvidenceItem.created_at)
        )
    ).scalars().all()
    for e in evidence:
        ev_by_cond[e.condition_id].append(e)

    cond_name_by_id = {c.id: c.name for c in conditions}

    contentions: list[Form526Contention] = []
    with_evidence = 0
    for cond in conditions:
        items = ev_by_cond.get(cond.id, [])
        have = [
            Form526EvidenceRef(kind=e.kind, title=e.title)
            for e in items
            if e.status == "have"
        ]
        needed = [
            Form526EvidenceRef(kind=e.kind, title=e.title)
            for e in items
            if e.status in ("need", "requested")
        ]
        if have:
            with_evidence += 1
        secondary_to_name = (
            cond_name_by_id.get(cond.secondary_to) if cond.secondary_to else None
        )
        contentions.append(
            Form526Contention(
                name=cond.name,
                diagnostic_code=cond.diagnostic_code,
                claim_type=cond.claim_type,
                current_rating=cond.current_rating,
                onset_date=cond.onset_date,
                in_service_event=cond.in_service_event,
                secondary_to_name=secondary_to_name,
                evidence_have=have,
                evidence_needed=needed,
            )
        )

    itf_records = (
        await db.execute(
            select(ItfRecord).where(ItfRecord.user_id == user_uuid)
        )
    ).scalars().all()

    total = len(conditions)
    return Form526Out(
        veteran={
            "name": (user.full_name if user else "") or "",
            "email": (user.email if user else "") or "",
        },
        prepared_on=None,
        service=Form526ServiceOut(
            periods=list((profile.service_periods if profile else None) or []),
            combat=bool(profile.combat_service) if profile else False,
            exposures=_humanize_exposures(profile.exposures if profile else None),
        ),
        contentions=contentions,
        itf=_soonest_active_itf(list(itf_records)),
        completeness=Form526Completeness(
            conditions=total,
            with_evidence=with_evidence,
            missing_evidence=total - with_evidence,
        ),
        guidance=_GUIDANCE,
        disclaimer=_DISCLAIMER,
        source_note=_SOURCE_NOTE,
    )


@router.get("/pdf")
async def get_form526_pdf(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The OFFICIAL fillable VA Form 21-526EZ (JAN 2026), pre-filled with the
    veteran's high-confidence data (name, email, service dates, and each condition
    with how it relates to service). SSN, VA file number, DOB, address, and the
    signature are left blank for the veteran — we don't collect them. Returned as a
    DRAFT the veteran reviews, completes, and signs; Veteran-Ops never files it."""
    user_uuid = uuid.UUID(uid)
    user = await db.get(User, user_uuid)
    profile = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == user_uuid)
        )
    ).scalar_one_or_none()
    conditions = (
        await db.execute(
            select(ClaimedCondition)
            .where(ClaimedCondition.user_id == user_uuid)
            .order_by(ClaimedCondition.created_at)
        )
    ).scalars().all()

    values = build_field_values(
        full_name=(user.full_name if user else "") or "",
        email=(user.email if user else "") or "",
        service_periods=(profile.service_periods if profile else None) or [],
        contentions=[
            {
                "name": c.name,
                "in_service_event": c.in_service_event,
                "onset_date": c.onset_date,
            }
            for c in conditions
        ],
        identity=(profile.identity if profile else None) or {},
        is_own_draft=True,
    )
    pdf_bytes = fill_pdf(values)
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                'attachment; filename="VA-21-526EZ-DRAFT-review-and-sign.pdf"'
            ),
            "Content-Length": str(len(pdf_bytes)),
        },
    )
