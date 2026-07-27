"""Official VA form-fill endpoints (Wave 8) — the generalization of /form526/pdf.

  GET /api/forms                 → catalog of fillable forms (id, edition, OMB, title)
  GET /api/forms/{form_id}       → field preview: what we AUTO-FILL vs. what YOU
                                   COMPLETE, plus how many fields we'd stamp for you
  GET /api/forms/{form_id}/pdf   → the OFFICIAL fillable PDF, pre-filled with your
                                   high-confidence data, streamed as a DRAFT

Legal lane (identical to routers/form526.py): we fill ONLY glance-verifiable,
high-confidence fields we hold with confidence and leave SSN, VA file number, date of
birth, address, and the signature blank — the veteran completes and signs. The fill is
PURE and deterministic (no LLM). A value map written against a stale edition simply
UNDER-fills (pypdf ignores renamed fields) — it never mis-fills. Veteran-Ops never
files anything.

The old /form526/pdf endpoint (routers/form526.py) still works unchanged; this router
is additive and serves 21-526ez here too via the shared registry.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, User, VeteranProfile
from ..pdf.registry import REGISTRY, get_spec

router = APIRouter(prefix="/forms", tags=["forms"])

_DISCLAIMER = (
    "This is the OFFICIAL government PDF, pre-filled with the data Rating Raider holds "
    "with confidence. It downloads as a DRAFT — review every field, complete the "
    "blanks (SSN, VA file number, date of birth, address, and signature are always "
    "left for you), and sign it before you file. Veteran-Ops never files anything. "
    "Free help is available from a VA-accredited VSO (VFW, DAV, The American Legion, "
    "or your state/county veterans office)."
)


class FormCatalogEntry(BaseModel):
    form_id: str
    edition: str
    omb: str
    title: str


class FormPreviewOut(BaseModel):
    form_id: str
    edition: str
    omb: str
    title: str
    auto_filled: list[str]
    you_complete: list[str]
    fields_filled: int
    draft_filename: str
    disclaimer: str


async def _dossier(uid: str, db: AsyncSession) -> dict:
    """Assemble the veteran's high-confidence data once — the shared input every
    form's PURE build_field_values consumes (same reads as form526.py's /pdf)."""
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
    return {
        "full_name": (user.full_name if user else "") or "",
        "email": (user.email if user else "") or "",
        "service_periods": (profile.service_periods if profile else None) or [],
        "contentions": [
            {
                "name": c.name,
                "in_service_event": c.in_service_event,
                "onset_date": c.onset_date,
            }
            for c in conditions
        ],
        # Identity + household pre-fill the veteran's OWN draft (SSN/signature stay
        # blank — enforced in the fillers). is_own_draft gates the sensitive VA file
        # number. Fillers that don't use these absorb them via **_.
        "identity": (profile.identity if profile else None) or {},
        "dependents": (profile.dependents if profile else None) or [],
        "is_own_draft": True,
    }


@router.get("", response_model=list[FormCatalogEntry])
async def list_forms(uid: str = Depends(current_user_id)):
    """The forms Rating Raider can pre-fill (stable order)."""
    return [
        FormCatalogEntry(
            form_id=s.form_id, edition=s.edition, omb=s.omb, title=s.title
        )
        for s in REGISTRY.values()
    ]


@router.get("/{form_id}", response_model=FormPreviewOut)
async def preview_form(
    form_id: str,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """What we'd fill vs. what the veteran completes — so the UI labels the download
    honestly. `fields_filled` is how many AcroForm fields we'd stamp given the
    veteran's current data."""
    spec = get_spec(form_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown form '{form_id}'.")
    dossier = await _dossier(uid, db)
    values = spec.build_field_values(**dossier)
    return FormPreviewOut(
        form_id=spec.form_id,
        edition=spec.edition,
        omb=spec.omb,
        title=spec.title,
        auto_filled=spec.auto_filled,
        you_complete=spec.you_complete,
        fields_filled=len(values),
        draft_filename=spec.draft_filename,
        disclaimer=_DISCLAIMER,
    )


@router.get("/{form_id}/pdf")
async def get_form_pdf(
    form_id: str,
    download: int = Query(0, description="1 → attachment (download); 0 → inline"),
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The OFFICIAL fillable VA PDF for `form_id`, pre-filled with the veteran's
    high-confidence data and streamed as a DRAFT. SSN, VA file number, DOB, address,
    and the signature are left blank; Veteran-Ops never files it."""
    spec = get_spec(form_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown form '{form_id}'.")
    dossier = await _dossier(uid, db)
    values = spec.build_field_values(**dossier)
    pdf_bytes = spec.fill(values)
    disposition = "attachment" if download else "inline"
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{spec.draft_filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )
