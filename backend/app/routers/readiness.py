"""Evidence readiness — a single deterministic % per condition + overall.

Reuses the gap engine (analysis/gaps.py) via readiness/score.py, so the score can
never disagree with the gap checklist the veteran sees. Educational only: a
readiness score reflects how much of the core evidence is identified, not a
prediction of the VA's decision.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user_id, get_db
from ..kb.store import cached_max_ratings
from ..models import ClaimedCondition, EvidenceItem, VeteranProfile
from ..readiness.score import overall_readiness, score_condition
from ..schemas import (
    ReadinessConditionOut,
    ReadinessOut,
    ReadinessOverallOut,
)

router = APIRouter(prefix="/readiness", tags=["readiness"])

_DISCLAIMER = (
    "A readiness score reflects how much of the core service-connection evidence "
    "you've identified for each claim — it is not a prediction of the VA's "
    "decision and not legal advice. A VSO can review your evidence for free."
)


@router.get("", response_model=ReadinessOut)
async def readiness(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    conditions = (
        await db.execute(
            select(ClaimedCondition).where(ClaimedCondition.user_id == uuid.UUID(uid))
        )
    ).scalars().all()

    # One query for all evidence, grouped by condition — avoids N+1 across the
    # veteran's whole condition list.
    ev_by_cond: dict[uuid.UUID, list[dict]] = defaultdict(list)
    evidence = (
        await db.execute(
            select(EvidenceItem).where(EvidenceItem.user_id == uuid.UUID(uid))
        )
    ).scalars().all()
    for e in evidence:
        ev_by_cond[e.condition_id].append({"kind": e.kind, "status": e.status})

    profile = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid))
        )
    ).scalar_one_or_none()
    prof_dict = (
        {"service_periods": profile.service_periods, "exposures": profile.exposures}
        if profile
        else None
    )

    max_ratings = cached_max_ratings()
    scored: list[dict] = []
    for cond in conditions:
        cond_dict = {
            "id": str(cond.id),
            "name": cond.name,
            "claim_type": cond.claim_type,
            "secondary_to": str(cond.secondary_to) if cond.secondary_to else None,
            "in_service_event": cond.in_service_event,
            "nexus_notes": cond.nexus_notes,
            "diagnostic_code": cond.diagnostic_code,
            "current_rating": cond.current_rating,
        }
        scored.append(
            score_condition(cond_dict, ev_by_cond.get(cond.id, []), prof_dict, max_ratings)
        )

    return ReadinessOut(
        overall=ReadinessOverallOut(**overall_readiness(scored)),
        conditions=[ReadinessConditionOut(**s) for s in scored],
        disclaimer=_DISCLAIMER,
    )
