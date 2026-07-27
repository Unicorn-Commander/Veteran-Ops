"""§4.25/§4.26 rating calculator + saved what-if scenarios.

POST /rating/calculate is authed but DB-free (pure engine call) — the engine in
app/rating/engine.py is the ONLY place rating math lives; the server always
recomputes scenario results (client math is never trusted).
"""

from __future__ import annotations

import datetime as _dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import current_user_id, get_db
from ..models import RatingScenario
from ..rating import backpay as backpay_calc
from ..rating.engine import RatingEntry, combined_rating
from ..schemas import RatingCalculateIn, RatingEntryIn, ScenarioCreate, ScenarioOut

router = APIRouter(prefix="/rating", tags=["rating"])


# --- Back-pay estimator schemas (LOCAL by design: schemas.py is owned by
# another agent; these models belong to this endpoint only). ---------------

class BackpayDependentsIn(BaseModel):
    """Dependent status — only the dimensions VA's rate tables price."""

    spouse: bool = False
    children_under_18: int = Field(0, ge=0, le=20)
    children_in_school: int = Field(0, ge=0, le=20, description="children 18-23 in a qualifying school program")
    parents: int = Field(0, ge=0, le=2)
    spouse_aa: bool = Field(False, description="spouse receives Aid and Attendance")


class BackpayPeriodIn(BaseModel):
    """One segment of the rating timeline; from_date is the EFFECTIVE date."""

    model_config = ConfigDict(populate_by_name=True)

    from_date: _dt.date = Field(validation_alias=AliasChoices("from_date", "from"))
    to_date: _dt.date | None = Field(None, validation_alias=AliasChoices("to_date", "to"))
    combined_percent: int = Field(
        ge=0, le=100, multiple_of=10,
        validation_alias=AliasChoices("combined_percent", "percent"),
    )
    dependents: BackpayDependentsIn = Field(default_factory=BackpayDependentsIn)


class BackpayIn(BaseModel):
    periods: list[BackpayPeriodIn] = Field(min_length=1)
    payment_already_received: list[BackpayPeriodIn] = Field(default_factory=list)
    end_date: _dt.date | None = None


def _to_period(p: BackpayPeriodIn) -> backpay_calc.RatingPeriod:
    return backpay_calc.RatingPeriod(
        from_date=p.from_date,
        to_date=p.to_date,
        combined_percent=p.combined_percent,
        dependents=backpay_calc.Dependents(**p.dependents.model_dump()),
    )


@router.post("/backpay")
async def backpay(
    payload: BackpayIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Educational retro/back-pay ESTIMATE from official VA rate tables.

    Pure deterministic math (app/rating/backpay.py); months in rate years we
    lack verified official data for are excluded, never guessed. Access is
    audited — this endpoint sees a veteran's rating history.
    """
    try:
        result = backpay_calc.compute_backpay(
            [_to_period(p) for p in payload.periods],
            received=[_to_period(p) for p in payload.payment_already_received] or None,
            end_date=payload.end_date,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await audit.log(
        db, uid, "rating.backpay", entity="rating_backpay",
        meta={
            "periods": len(payload.periods),
            "months": len(result["months"]),
            "excluded_months": len(result["excluded_months"]),
        },
    )
    return result


def _compute(entries: list[RatingEntryIn]) -> dict:
    """Validate + run the engine. Pydantic already enforces percent 0–100 and
    side ∈ {left, right, None}; the engine re-asserts percent bounds."""
    try:
        rating_entries = [
            RatingEntry(label=e.label, percent=e.percent, side=e.side, group=e.group)
            for e in entries
        ]
        result = combined_rating(rating_entries)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return result.as_dict()


@router.post("/calculate")
async def calculate(
    payload: RatingCalculateIn,
    uid: str = Depends(current_user_id),  # noqa: ARG001 — authed, but no persistence
) -> dict:
    """Pure calculation — no persistence, no DB dependency; still authed."""
    return _compute(payload.entries)


@router.get("/scenarios", response_model=list[ScenarioOut])
async def list_scenarios(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(select(RatingScenario).order_by(RatingScenario.created_at.desc()))
    ).scalars().all()
    return rows


@router.post("/scenarios", response_model=ScenarioOut, status_code=status.HTTP_201_CREATED)
async def create_scenario(
    payload: ScenarioCreate,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Save a what-if; the result is recomputed server-side on save."""
    result = _compute(payload.entries)
    obj = RatingScenario(
        user_id=uuid.UUID(uid),
        name=payload.name,
        entries=[e.model_dump() for e in payload.entries],
        result=result,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await audit.log(
        db, uid, "scenario.create", entity="rating_scenario", entity_id=str(obj.id),
        meta={"name": obj.name, "combined": result.get("combined")},
    )
    return obj


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(
    scenario_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = (
        await db.execute(
            select(RatingScenario).where(
                RatingScenario.id == scenario_id,
                RatingScenario.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scenario not found")
    await db.delete(obj)
    await audit.log(db, uid, "scenario.delete", entity="rating_scenario", entity_id=str(scenario_id))
