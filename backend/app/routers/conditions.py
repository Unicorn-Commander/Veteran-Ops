"""Claimed conditions CRUD + the deterministic evidence-gap analysis."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..analysis.gaps import analyze_gaps, map_dbq
from ..deps import current_user_id, get_db
from ..kb.store import cached_max_ratings, load_dbq_catalog
from ..models import ChecklistItem, ClaimedCondition, EvidenceItem, VeteranProfile
from ..schemas import (
    ChecklistOut,
    ConditionCreate,
    ConditionOut,
    ConditionUpdate,
    GapItem,
    GapsOut,
)
from ..strategy.coach import find_duplicate_clusters

router = APIRouter(prefix="/conditions", tags=["conditions"])


class ParkDuplicatesIn(BaseModel):
    """Mark duplicate claimed conditions as parked (status=decided, note tagged).

    Does not change va_status. Keep row is left alone. Educational cleanup only.
    """

    park_ids: list[uuid.UUID] = Field(min_length=1, max_length=40)
    keep_id: uuid.UUID | None = None
    keep_name: str | None = Field(default=None, max_length=255)


class ParkDuplicatesOut(BaseModel):
    parked: int = 0
    park_ids: list[str] = Field(default_factory=list)
    note: str = (
        "Parked rows stay in your list but drop out of “ready to file.” "
        "This is file cleanup, not a VA action."
    )


class DuplicateClustersOut(BaseModel):
    clusters: list[dict] = Field(default_factory=list)
    note: str = (
        "Similar names often come from C-file extract. Keep one working row per "
        "contention; park the rest so Claim Plan stays readable."
    )


async def _get_condition(
    db: AsyncSession, condition_id: uuid.UUID, uid: str
) -> ClaimedCondition:
    """Fetch the caller's own condition. Isolation is defense-in-depth: an explicit
    user_id filter PLUS RLS, so a wrong-owner (or guessed) id is a 404 even if the
    RLS layer is ever misconfigured — never RLS-only."""
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


@router.get("", response_model=list[ConditionOut])
async def list_conditions(
    uid: str = Depends(current_user_id), db: AsyncSession = Depends(get_db)
):
    rows = (
        await db.execute(
            select(ClaimedCondition)
            .where(ClaimedCondition.user_id == uuid.UUID(uid))
            .order_by(ClaimedCondition.created_at.desc())
        )
    ).scalars().all()
    return rows


@router.get("/duplicates", response_model=DuplicateClustersOut)
async def list_duplicate_clusters(
    uid: str = Depends(current_user_id), db: AsyncSession = Depends(get_db)
):
    """Cluster similarly named claimed conditions for cleanup (read-only)."""
    rows = (
        await db.execute(
            select(ClaimedCondition).where(ClaimedCondition.user_id == uuid.UUID(uid))
        )
    ).scalars().all()
    conds = [
        {
            "id": str(r.id),
            "name": r.name,
            "va_status": r.va_status or "unknown",
            "current_rating": r.current_rating,
            "claim_type": r.claim_type,
            "status": r.status,
        }
        for r in rows
    ]
    return DuplicateClustersOut(clusters=find_duplicate_clusters(conds))


@router.post("/park-duplicates", response_model=ParkDuplicatesOut)
async def park_duplicates(
    payload: ParkDuplicatesIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Park duplicate rows: status=decided, notes tagged. Keep id is never parked."""
    keep = payload.keep_id
    keep_name = (payload.keep_name or "primary row").strip()
    parked_ids: list[str] = []
    for cid in payload.park_ids:
        if keep and cid == keep:
            continue
        obj = await _get_condition(db, cid, uid)
        tag = f"[PARKED duplicate of {keep_name}]"
        notes = (obj.notes or "").strip()
        if tag not in notes:
            obj.notes = f"{tag} {notes}".strip() if notes else tag
        obj.status = "decided"
        parked_ids.append(str(obj.id))
    await audit.log(
        db,
        uid,
        "condition.park_duplicates",
        entity="claimed_condition",
        meta={"parked": len(parked_ids), "keep_id": str(keep) if keep else None},
    )
    await db.flush()
    return ParkDuplicatesOut(parked=len(parked_ids), park_ids=parked_ids)


@router.post("", response_model=ConditionOut, status_code=status.HTTP_201_CREATED)
async def create_condition(
    payload: ConditionCreate,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = ClaimedCondition(user_id=uuid.UUID(uid), **payload.model_dump(exclude_unset=True))
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await audit.log(
        db, uid, "condition.create", entity="claimed_condition", entity_id=str(obj.id),
        meta={"name": obj.name, "claim_type": obj.claim_type},
    )
    return obj


@router.get("/{condition_id}", response_model=ConditionOut)
async def get_condition(
    condition_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await _get_condition(db, condition_id, uid)


@router.patch("/{condition_id}", response_model=ConditionOut)
async def update_condition(
    condition_id: uuid.UUID,
    payload: ConditionUpdate,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = await _get_condition(db, condition_id, uid)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(obj, key, value)
    await db.flush()
    await db.refresh(obj)
    await audit.log(
        db, uid, "condition.update", entity="claimed_condition", entity_id=str(obj.id),
        meta={"fields": sorted(changes.keys())},
    )
    return obj


@router.delete("/{condition_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_condition(
    condition_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = await _get_condition(db, condition_id, uid)
    await db.delete(obj)
    await audit.log(
        db, uid, "condition.delete", entity="claimed_condition", entity_id=str(condition_id),
    )


# ── Evidence-gap analysis (deterministic; see app/analysis/gaps.py) ──────────
@router.get("/{condition_id}/gaps", response_model=GapsOut)
async def condition_gaps(
    condition_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Three-element gap analysis (38 CFR §3.303 framing) + DBQ mapping.

    Also (idempotently) persists one checklist item per open gap — unique per
    condition + text — so the gaps become actionable next steps.
    """
    cond = await _get_condition(db, condition_id, uid)
    evidence = (
        await db.execute(
            select(EvidenceItem).where(EvidenceItem.condition_id == condition_id)
        )
    ).scalars().all()
    profile = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid))
        )
    ).scalar_one_or_none()

    cond_dict = {
        "name": cond.name,
        "claim_type": cond.claim_type,
        "secondary_to": str(cond.secondary_to) if cond.secondary_to else None,
        "in_service_event": cond.in_service_event,
        "nexus_notes": cond.nexus_notes,
        "diagnostic_code": cond.diagnostic_code,
        "current_rating": cond.current_rating,
    }
    ev_dicts = [{"kind": e.kind, "status": e.status} for e in evidence]
    prof_dict = (
        {"service_periods": profile.service_periods, "exposures": profile.exposures}
        if profile
        else None
    )
    gaps = analyze_gaps(cond_dict, ev_dicts, prof_dict, max_ratings=cached_max_ratings())

    # DBQ mapping from the authored catalog; persist onto the condition when unset.
    dbq_form = cond.dbq_form or map_dbq(cond.name, cond.body_system, load_dbq_catalog())
    if dbq_form and not cond.dbq_form:
        cond.dbq_form = dbq_form
        await db.flush()

    # Idempotent checklist generation: unique per (condition, text).
    existing = (
        await db.execute(
            select(ChecklistItem).where(ChecklistItem.condition_id == condition_id)
        )
    ).scalars().all()
    existing_texts = {c.text for c in existing}
    created = 0
    for i, gap in enumerate(gaps):
        text = f"{gap['label']}: {gap['detail']}"
        if text in existing_texts:
            continue
        db.add(
            ChecklistItem(
                user_id=uuid.UUID(uid),
                condition_id=condition_id,
                text=text,
                category="evidence",
                sort=i,
            )
        )
        created += 1
    if created:
        await db.flush()
        await audit.log(
            db, uid, "condition.gaps", entity="claimed_condition", entity_id=str(condition_id),
            meta={"gaps": len(gaps), "checklist_created": created},
        )

    checklist = (
        await db.execute(
            select(ChecklistItem)
            .where(ChecklistItem.condition_id == condition_id)
            .order_by(ChecklistItem.sort, ChecklistItem.created_at)
        )
    ).scalars().all()

    return GapsOut(
        condition_id=condition_id,
        gaps=[GapItem(**g) for g in gaps],
        dbq_form=dbq_form,
        checklist=[ChecklistOut.model_validate(c) for c in checklist],
    )
