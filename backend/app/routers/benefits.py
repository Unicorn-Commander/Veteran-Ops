"""GET /benefits — curated rating unlocks, filtered only by rating and state."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..benefits.filter import filter_benefits, load_benefits_data
from ..deps import current_user_id, get_db
from ..kb.refresh import benefit_from_row
from ..models import KBBenefit, VeteranProfile
from ..schemas import BenefitItem, BenefitsOut

router = APIRouter(prefix="/benefits", tags=["benefits"])


def _profile_defaults(profile: VeteranProfile | None) -> tuple[int, str | None]:
    rating = profile.current_combined_rating if profile and profile.current_combined_rating is not None else 0
    state = profile.state if profile and profile.state else None
    return rating, state


async def _benefits_dataset(db: AsyncSession) -> dict:
    dataset = load_benefits_data()
    verified_as_of = date.fromisoformat(dataset["verified_as_of"])
    merged: dict[str, dict] = {}
    for item in dataset.get("benefits", []):
        merged[item["id"]] = {
            **item,
            "effective_date": item.get("effective_date"),
            "verified_as_of": dataset["verified_as_of"],
        }
    rows = (await db.execute(select(KBBenefit).order_by(KBBenefit.category, KBBenefit.name))).scalars().all()
    for row in rows:
        item = benefit_from_row(row)
        verified_as_of = max(verified_as_of, row.verified_as_of)
        merged[row.id] = item
    return {
        "verified_as_of": verified_as_of.isoformat(),
        "benefits": list(merged.values()),
    }


@router.get("", response_model=BenefitsOut)
async def get_benefits(
    rating: int | None = Query(default=None, ge=0, le=100),
    state: str | None = Query(default=None, min_length=2, max_length=2),
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> BenefitsOut:
    profile = None
    if rating is None or state is None:
        profile = (
            await db.execute(
                select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid))
            )
        ).scalar_one_or_none()
    default_rating, default_state = _profile_defaults(profile)
    resolved_rating = rating if rating is not None else default_rating
    resolved_state = state.upper() if state else default_state

    dataset = await _benefits_dataset(db)
    grouped = filter_benefits(dataset, resolved_rating, resolved_state)
    return BenefitsOut(
        verified_as_of=date.fromisoformat(dataset["verified_as_of"]),
        federal=[BenefitItem(**item) for item in grouped["federal"]],
        state=[BenefitItem(**item) for item in grouped["state"]],
        commercial=[BenefitItem(**item) for item in grouped["commercial"]],
    )
