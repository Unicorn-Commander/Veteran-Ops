"""Deadline Guardian — GET /deadlines + POST /deadlines/notify-me.

Every time-sensitive clock the veteran has, computed from their OWN data,
soonest-first, with a countdown and what to do about it. The 1-year clock is the
spine of a VA claim (veteran-workflows research, cross-cutting requirement #2), and
three of them can cost a veteran back pay or an appeal if missed:

  • Intent-to-File expiry    — filed_date + 1yr (ItfRecord); reuses the ITF math.
  • Decision-review window   — decision_date + 1yr (Document.extracted['decode']).
  • Dependency retroactivity — marriage/birth + 1yr (profile.dependents; §3.401).

Deterministic: no LLM; all date math is pure (app/deadlines.py) with `today` passed
in. RLS-scoped exactly like readiness.py — every query is fenced by user_id (and the
request's RLS GUCs via get_db). Legal lane: informs about the deadline + what the
veteran can do; it never predicts a decision and never files. We never invent a
deadline — a missing source date simply contributes nothing.

Email digests (POST /notify-me + `python -m app.deadlines_notify` cron) only cover
urgent clocks; delivery is best-effort via app/email.py.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deadlines_notify import load_deadlines_for_user, notify_user_deadlines
from ..deps import current_user_id, get_db
from ..models import User
from ..schemas import DeadlineNotifyOut, DeadlineOut, DeadlinesOut

router = APIRouter(prefix="/deadlines", tags=["deadlines"])

_DISCLAIMER = (
    "These countdowns are computed from the dates in your own records so you don't "
    "miss a deadline — they are educational reminders, not legal advice, and Rating "
    "Raider never files anything for you. VA deadlines and effective-date rules have "
    "exceptions; a free VA-accredited VSO can confirm your dates and help you file on "
    "time."
)


@router.get("", response_model=DeadlinesOut)
async def get_deadlines(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> DeadlinesOut:
    computed = await load_deadlines_for_user(db, uid)
    return DeadlinesOut(
        deadlines=[DeadlineOut(**asdict(d)) for d in computed],
        disclaimer=_DISCLAIMER,
    )


@router.post("/notify-me", response_model=DeadlineNotifyOut)
async def notify_me(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> DeadlineNotifyOut:
    """Send the caller a deadline digest now (testing + on-demand).

    Uses the console/log email backend when no provider is configured — still
    useful for verifying content. Only urgent clocks are emailed unless the
    instance has no urgent ones (then ``sent=false``, ``reason=no_urgent``).
    """
    user = (
        await db.execute(select(User).where(User.id == uuid.UUID(uid)))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    # On-demand "email me" includes all tracked clocks (not only urgent) so the
    # veteran can verify delivery even when nothing is due this week. Cron still
    # uses force=False (urgent only) via `python -m app.deadlines_notify`.
    result = await notify_user_deadlines(db, user, force=True)
    return DeadlineNotifyOut(
        sent=bool(result.get("sent")),
        reason=str(result.get("reason") or ""),
        urgent_count=int(result.get("urgent_count") or 0),
        deadline_count=int(result.get("deadline_count") or 0),
    )
