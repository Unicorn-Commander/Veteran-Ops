"""Intent-to-File reminders — track ITFs and count down the 1-year window.

An ITF preserves the effective date for ONE YEAR. We store the filed date and
compute the deadline (filed_date + 1yr) with the SAME leap-year-correct math the
decoder uses for appeal windows (decoder/deadline.py) — no stored deadline to
drift. Educational reminder only; the veteran files the actual claim (or a VSO
helps, free).

VA-synced ITFs: the frontend surfaces the VA connector's active ITF
(GET /va/itf/active) alongside these; we keep this endpoint to stored records so
it never depends on a live VA call.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..decoder.deadline import appeal_window
from ..deps import current_user_id, get_db
from ..models import ItfRecord
from ..schemas import ItfIn, ItfOut, ItfRecordOut

router = APIRouter(prefix="/itf", tags=["itf"])

_DISCLAIMER = (
    "An Intent to File preserves your effective date for one year from the date "
    "you filed it — file the actual claim (or ask a free VSO to help) before the "
    "deadline. This reminder is educational, not legal advice."
)


def _to_out(rec: ItfRecord, today: date) -> ItfRecordOut:
    w = appeal_window(rec.filed_date, today)
    return ItfRecordOut(
        id=rec.id,
        type=rec.type,
        filed_date=rec.filed_date,
        source=rec.source,
        notes=rec.notes,
        deadline=w["deadline"],
        days_remaining=w["days_remaining"],
        expired=w["expired"],
    )


@router.get("", response_model=ItfOut)
async def list_itf(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    today = datetime.now(timezone.utc).date()
    rows = (
        await db.execute(
            select(ItfRecord)
            .where(ItfRecord.user_id == uuid.UUID(uid))
            .order_by(ItfRecord.filed_date.desc())
        )
    ).scalars().all()
    records = [_to_out(r, today) for r in rows]
    # Active = the soonest-expiring window that hasn't passed yet.
    active = min(
        (r for r in records if not r.expired),
        key=lambda r: r.days_remaining,
        default=None,
    )
    return ItfOut(records=records, active=active, disclaimer=_DISCLAIMER)


@router.post("", response_model=ItfRecordOut, status_code=status.HTTP_201_CREATED)
async def create_itf(
    payload: ItfIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rec = ItfRecord(
        user_id=uuid.UUID(uid),
        type=payload.type,
        filed_date=payload.filed_date,
        source=payload.source,
        notes=payload.notes,
    )
    db.add(rec)
    await db.flush()
    await db.refresh(rec)
    await audit.log(
        db, uid, "itf.create", entity="itf_record", entity_id=str(rec.id),
        meta={"type": rec.type, "filed_date": rec.filed_date.isoformat()},
    )
    return _to_out(rec, datetime.now(timezone.utc).date())


@router.delete("/{itf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_itf(
    itf_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rec = (
        await db.execute(
            select(ItfRecord).where(
                ItfRecord.id == itf_id, ItfRecord.user_id == uuid.UUID(uid)
            )
        )
    ).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "ITF record not found")
    await db.delete(rec)
    await audit.log(db, uid, "itf.delete", entity="itf_record", entity_id=str(itf_id))
