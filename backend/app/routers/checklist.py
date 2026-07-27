"""Checklist — action items, optionally tied to a condition (gap analysis
auto-generates per-condition items; users add their own too)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import current_user_id, get_db
from ..models import ChecklistItem
from ..schemas import ChecklistCreate, ChecklistOut, ChecklistUpdate

router = APIRouter(prefix="/checklist", tags=["checklist"])


# Defense-in-depth: explicit user_id filter on every fetch-by-id (not RLS-only).
async def _get_item(db: AsyncSession, item_id: uuid.UUID, uid: str) -> ChecklistItem:
    obj = (
        await db.execute(
            select(ChecklistItem).where(
                ChecklistItem.id == item_id,
                ChecklistItem.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Checklist item not found")
    return obj


@router.get("", response_model=list[ChecklistOut])
async def list_checklist(
    condition_id: uuid.UUID | None = None,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ChecklistItem)
        .where(ChecklistItem.user_id == uuid.UUID(uid))
        .order_by(ChecklistItem.sort, ChecklistItem.created_at)
    )
    if condition_id is not None:
        stmt = stmt.where(ChecklistItem.condition_id == condition_id)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.post("", response_model=ChecklistOut, status_code=status.HTTP_201_CREATED)
async def create_item(
    payload: ChecklistCreate,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = ChecklistItem(user_id=uuid.UUID(uid), **payload.model_dump(exclude_unset=True))
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await audit.log(db, uid, "checklist.create", entity="checklist_item", entity_id=str(obj.id))
    return obj


@router.patch("/{item_id}", response_model=ChecklistOut)
async def update_item(
    item_id: uuid.UUID,
    payload: ChecklistUpdate,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = await _get_item(db, item_id, uid)
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(obj, key, value)
    await db.flush()
    await db.refresh(obj)
    await audit.log(
        db, uid, "checklist.update", entity="checklist_item", entity_id=str(obj.id),
        meta={"fields": sorted(changes.keys())},
    )
    return obj


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(
    item_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = await _get_item(db, item_id, uid)
    await db.delete(obj)
    await audit.log(db, uid, "checklist.delete", entity="checklist_item", entity_id=str(item_id))
