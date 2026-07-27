"""Concurrent pay — CRDP (10 U.S.C. §1414) / CRSC (10 U.S.C. §1413a).

A read-only surface for the "Ongoing" journey stage: a military retiree who also
draws VA disability compensation sees, in plain terms, which concurrent-receipt
program likely fits them, what to do about it, and a rough estimate of the retired
pay CRDP could restore.

Legal lane: DFAS restores CRDP automatically at a 50%+ rating; CRSC is a tax-free
payment the veteran APPLIES for on DD Form 2860 to their branch. This NEVER says a
veteran "qualifies" or "will receive" — DFAS and the branch decide eligibility and
the exact amount. The read and the estimate are DETERMINISTIC (pure §1414/§1413a
logic + VA's published rate table); no LLM anywhere near this. Veteran-Ops never
files anything.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user_id, get_db
from ..models import VeteranProfile
from ..rating.rates_data import Dependents, monthly_rate
from ..schemas import ConcurrentPayOut
from ..strategy.concurrent_pay import crdp_restoration_estimate, screen_concurrent_pay

router = APIRouter(prefix="/concurrent-pay", tags=["concurrent-pay"])

DISCLAIMER = (
    "Concurrent pay (CRDP and CRSC) is decided by DFAS and your branch of service — "
    "Veteran-Ops does not and cannot decide whether you qualify or what you'll be "
    "paid. This reads where you stand from the facts in your profile — your combined "
    "rating, whether you draw military retired pay, and whether a disability is combat-"
    "related — and explains what each program is and how to pursue it. CRDP is "
    "automatic through DFAS; CRSC you apply for on DD Form 2860 to your branch. Any "
    "dollar figure here is a rough estimate, not a promise. Veteran-Ops never files "
    "anything for you."
)

VSO_NOTE = (
    "A free VA-accredited Veterans Service Officer (VFW, DAV, The American Legion, or "
    "your state/county veterans office) — or your branch's CRSC office — can compare "
    "CRDP and CRSC for you and help you file the DD Form 2860, so you keep whichever "
    "pays more."
)


def _monthly_va_comp(combined: int | None, today: date) -> float | None:
    """VA's published monthly compensation at the veteran's combined rating, single-
    veteran baseline — the amount a retiree waives from retired pay (CRDP's ceiling).
    None when there's no rating or the rate year isn't loaded (we show a gap, never a
    guessed amount). Mirrors strategy.router._money's rounding + gap handling."""
    if not isinstance(combined, int) or isinstance(combined, bool) or combined <= 0:
        return None
    pct = max(0, min(100, round(combined / 10) * 10))  # VA ratings are multiples of 10
    try:
        amt = monthly_rate(today, pct, Dependents())
    except ValueError:
        return None
    return float(amt) if amt is not None else None


@router.get("", response_model=ConcurrentPayOut)
async def concurrent_pay_screen(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> ConcurrentPayOut:
    """Where the veteran stands on CRDP / CRSC, from their profile. Always returns
    educational content — even when neither program fits, it explains why and what
    would change the read. Deterministic; never a determination."""
    profile = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid))
        )
    ).scalar_one_or_none()

    combined = profile.current_combined_rating if profile else None
    retired = profile.receives_military_retired_pay if profile else None
    combat = profile.combat_related_disability if profile else None

    screen = screen_concurrent_pay(combined, retired, combat)

    waiver = _monthly_va_comp(combined, date.today())
    estimate = crdp_restoration_estimate(waiver, screen["crdp"]["likely_fits"])

    return ConcurrentPayOut(
        **screen,
        estimate=estimate,
        disclaimer=DISCLAIMER,
        vso_note=VSO_NOTE,
    )
