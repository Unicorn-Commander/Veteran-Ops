"""Records requests — SF-180 / VA 20-10206 prefill worksheets + provider
request letters.

Legal lane (BUILD-SPEC): everything here is PREPARED FOR THE VETERAN'S
SIGNATURE. The app prefills from their own profile and generates letter text;
the veteran reviews, signs, and submits it themselves. Free help exists at every
step from a VA-accredited VSO. Letters are a deterministic template — no LLM.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, EvidenceItem, User, VeteranProfile
from ..schemas import (
    EvidenceOut,
    RecordsPrefillOut,
    RequestLetterIn,
    RequestLetterOut,
)

router = APIRouter(prefix="/records", tags=["records"])

SIGNATURE_NOTE = (
    "Prepared for YOUR signature — you review, sign, and submit it yourself. "
    "Veteran-Ops never submits anything on your behalf. Free help is available "
    "at every step from a VA-accredited VSO (VFW, DAV, The American Legion, or "
    "your state/county veterans office)."
)

SF180_URL = "https://www.archives.gov/files/research/order/standard-form-180.pdf"
EVETRECS_URL = "https://www.archives.gov/veterans/military-service-records"
VA_20_10206_URL = "https://www.va.gov/find-forms/about-form-20-10206/"


async def _prefill_base(db: AsyncSession, uid: str) -> tuple[dict, VeteranProfile | None]:
    """Identity + service history from the veteran's own rows (users is not
    fenced; veteran_profiles is RLS-fenced to the caller)."""
    user = await db.get(User, uuid.UUID(uid))
    profile = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid))
        )
    ).scalar_one_or_none()
    periods = list((profile.service_periods if profile else None) or [])
    prefill = {
        "full_name": (user.full_name if user else "") or "",
        "email": (user.email if user else "") or "",
        "service_periods": periods,
        "branches": sorted({p.get("branch") for p in periods if p.get("branch")}),
        "discharge_characters": sorted(
            {p.get("discharge_character") for p in periods if p.get("discharge_character")}
        ),
        "state": profile.state if profile else None,
        "purpose": "Evidence for my VA disability compensation claim",
    }
    return prefill, profile


@router.get("/sf180", response_model=RecordsPrefillOut)
async def sf180_prefill(
    prefill: int = 1,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Prefill data for an SF-180 (NPRC request: DD-214 / OMPF / STRs) worksheet.
    The frontend renders this into a printable worksheet the veteran copies onto
    the official form (or brings to a VSO). Includes eVetRecs guidance."""
    data, _ = await _prefill_base(db, uid) if prefill else ({}, None)
    if prefill:
        data["records_requested"] = [
            "DD Form 214 (Certificate of Release or Discharge from Active Duty)",
            "Official Military Personnel File (OMPF) — complete copy",
            "Service Treatment Records (STRs) — complete copy",
        ]
    await audit.log(db, uid, "records.prefill", entity="records", meta={"form": "SF-180"})
    return RecordsPrefillOut(
        form="SF-180",
        form_title="Request Pertaining to Military Records",
        form_url=SF180_URL,
        prefill=data,
        guidance=[
            "Fastest path: request online via eVetRecs at "
            f"{EVETRECS_URL} — most veterans can skip the paper form entirely.",
            "If you use the paper SF-180: copy the details from this worksheet "
            "onto the official form, section by section.",
            "Section I: your name as it appears in your service records, SSN, "
            "date of birth, and each service period (branch, dates, component).",
            "Section II: check the records you need — DD-214, complete OMPF, and "
            "Service Treatment Records are the ones VA claims usually use.",
            "Section III: sign and date — the National Archives will not process "
            "an unsigned request.",
            "Mail or fax to the address for your branch on page 2 of the form, "
            "or hand it to your VSO to submit with you.",
        ],
        note=SIGNATURE_NOTE,
    )


@router.get("/va-20-10206", response_model=RecordsPrefillOut)
async def va_20_10206_prefill(
    prefill: int = 1,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Prefill data for VA Form 20-10206 (FOIA/Privacy Act request — your VA
    claims file, the C-file). Same worksheet pattern as /records/sf180."""
    data, _ = await _prefill_base(db, uid) if prefill else ({}, None)
    if prefill:
        data["records_requested"] = [
            "Complete copy of my VA claims file (C-file)",
        ]
    await audit.log(
        db, uid, "records.prefill", entity="records", meta={"form": "VA 20-10206"}
    )
    return RecordsPrefillOut(
        form="VA Form 20-10206",
        form_title="Freedom of Information Act (FOIA) or Privacy Act (PA) Request",
        form_url=VA_20_10206_URL,
        prefill=data,
        guidance=[
            "Your C-file holds everything VA used to decide your claims — prior "
            "rating decisions, exams, and the evidence on file. It's the "
            "foundation for an increase or appeal.",
            "Copy the details from this worksheet onto VA Form 20-10206 "
            "(download at the link above), or file it online through VA.gov.",
            "In the records-requested section, write: 'Complete copy of my VA "
            "claims file (C-file)'.",
            "Sign and date — VA will not process an unsigned request.",
            "Submit it yourself: upload via VA.gov, mail to the Evidence Intake "
            "Center on the form's instructions, or hand it to your VSO.",
            "Expect months, not days — request it early in your process.",
        ],
        note=SIGNATURE_NOTE,
    )


def _render_letter(
    veteran_name: str,
    provider_name: str,
    address: str | None,
    condition_names: list[str],
    today: date,
) -> str:
    """Deterministic provider records-request letter — a plain template the
    veteran prints and SIGNS. No LLM anywhere near this."""
    cond_lines = "\n".join(f"  - {n}" for n in condition_names)
    address_block = f"{provider_name}\n{address.strip()}" if address else provider_name
    name = veteran_name.strip() or "[Your full name]"
    return f"""{today.strftime("%B %-d, %Y")}

To: {address_block}

Re: Request for copies of my medical records

Dear Records Department,

I am requesting complete copies of my medical records from your practice,
including office visit notes, test and imaging results, diagnoses, and
treatment history, related to the following condition(s):

{cond_lines}

I am gathering these records to support my VA disability compensation claim.
Please include all records from my first visit through the present.

Under the HIPAA Privacy Rule (45 CFR 164.524), I am entitled to a copy of my
records, and any fee must be limited to a reasonable, cost-based amount.
Please send the records to me at the address below, or let me know if you
provide electronic copies.

If you require your own authorization form, please mail or email it to me and
I will return it promptly.

Thank you,


_________________________________
{name}
[Your mailing address]
[Your phone number]
Date of birth: [Your date of birth]
"""


@router.post(
    "/request-letter",
    response_model=RequestLetterOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_request_letter(
    payload: RequestLetterIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Per-provider private-records request letter (deterministic template). Also
    creates one evidence item per condition, status=requested, so the evidence
    organizer tracks the outstanding request."""
    user_uuid = uuid.UUID(uid)
    conditions = (
        (
            await db.execute(
                select(ClaimedCondition).where(
                    ClaimedCondition.id.in_(payload.condition_ids),
                    ClaimedCondition.user_id == user_uuid,
                )
            )
        )
        .scalars()
        .all()
    )
    found = {c.id for c in conditions}
    missing = [str(cid) for cid in payload.condition_ids if cid not in found]
    if missing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found")

    user = await db.get(User, user_uuid)
    names = [c.name for c in conditions]
    letter = _render_letter(
        (user.full_name if user else "") or "",
        payload.provider_name.strip(),
        payload.address,
        names,
        date.today(),
    )

    evidence_rows: list[EvidenceItem] = []
    for cond in conditions:
        item = EvidenceItem(
            user_id=user_uuid,
            condition_id=cond.id,
            kind="treatment_record",
            title=f"Records request — {payload.provider_name.strip()}"[:255],
            status="requested",
            source=payload.provider_name.strip()[:255],
            notes="Request letter generated; you print, sign, and send it.",
        )
        db.add(item)
        evidence_rows.append(item)
    await db.flush()
    for item in evidence_rows:
        await db.refresh(item)

    await audit.log(
        db, uid, "records.request_letter", entity="records",
        meta={
            "provider_name": payload.provider_name.strip(),
            "condition_ids": [str(c.id) for c in conditions],
            "evidence_ids": [str(e.id) for e in evidence_rows],
        },
    )
    return RequestLetterOut(
        letter=letter,
        provider_name=payload.provider_name.strip(),
        conditions=names,
        evidence=[EvidenceOut.model_validate(e) for e in evidence_rows],
        note=SIGNATURE_NOTE,
    )
