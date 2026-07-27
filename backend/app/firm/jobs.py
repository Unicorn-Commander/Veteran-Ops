"""Best-effort, RLS-scoped runners for proactive deep-dive sweeps.

There is deliberately no external action here: jobs only refresh the veteran's
local GamePlanFirmCache payload.  Intake/analysis enqueue one scope; the optional
schedule and curated-rule refresh walk users with bounded concurrency and open a
fresh ``session_for_user`` transaction for every veteran.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal, session_for_user
from ..models import OrganizationMember, User
from .enumerate import enumerate_candidates

log = logging.getLogger("veteran_ops.firm.jobs")


def _candidate_dcs(dossier) -> set[str]:
    direct = {
        str(condition.get("diagnostic_code") or "").strip()
        for condition in dossier.conditions
    }
    try:
        enumerated = {
            str(candidate.diagnostic_code or "").strip()
            for candidate in enumerate_candidates(dossier)
        }
    except Exception:  # noqa: BLE001 — direct dossier DCs remain a safe fallback
        enumerated = set()
    return {dc for dc in direct | enumerated if dc}


async def run_deep_dive_for_user(
    user_id: str,
    workspace_id: str | None = None,
    *,
    trigger: str,
    force: bool,
    changed_dcs: set[str] | None = None,
) -> bool:
    """Refresh one user's cache.  Returns whether this scope was affected/run."""
    try:
        scoped_session = asynccontextmanager(session_for_user)
        async with scoped_session(str(user_id), workspace_id) as db:
            return await run_deep_dive_in_session(
                db,
                str(user_id),
                trigger=trigger,
                force=force,
                changed_dcs=changed_dcs,
            )
    except Exception:  # noqa: BLE001 — proactive work never affects serving/intake
        log.warning(
            "deep-dive %s sweep failed for user %s; it can retry later.",
            trigger,
            user_id,
            exc_info=True,
        )
        return False


async def run_deep_dive_in_session(
    db,
    user_id: str,
    *,
    trigger: str,
    force: bool,
    changed_dcs: set[str] | None = None,
) -> bool:
    """Core runner for callers that already opened a fresh scoped transaction."""
    # Lazy import avoids making the router/job relationship an import cycle.
    from ..routers.strategy import _assemble_strategy, _run_cached_deep_dive

    _, facts_hash, _, dossier = await _assemble_strategy(db, str(user_id))
    if not dossier.conditions and not dossier.documents and not dossier.profile:
        return False
    if changed_dcs and _candidate_dcs(dossier).isdisjoint(changed_dcs):
        return False
    await _run_cached_deep_dive(
        db,
        str(user_id),
        dossier,
        facts_hash,
        force=force,
        trigger=trigger,
    )
    return True


async def _all_user_scopes() -> list[tuple[str, str | None]]:
    """Enumerate global user ids, then discover each user's workspaces through a
    user-scoped membership read.  No fenced veteran table is ever scanned globally."""
    try:
        async with SessionLocal() as db:
            rows = (await db.execute(select(User.id).order_by(User.created_at))).scalars().all()
    except Exception:  # noqa: BLE001
        log.warning("deep-dive sweep could not enumerate users.", exc_info=True)
        return []
    scoped_session = asynccontextmanager(session_for_user)
    scopes: list[tuple[str, str | None]] = []
    for raw_user_id in rows:
        user_id = str(raw_user_id)
        try:
            async with scoped_session(user_id) as db:
                workspace_ids = (
                    await db.execute(
                        select(OrganizationMember.org_id).where(
                            OrganizationMember.user_id == raw_user_id
                        )
                    )
                ).scalars().all()
        except Exception:  # noqa: BLE001
            log.warning("could not enumerate workspaces for user %s", user_id, exc_info=True)
            workspace_ids = []
        if workspace_ids:
            scopes.extend((user_id, str(workspace_id)) for workspace_id in workspace_ids)
        else:
            # session_for_user's documented fallback is the deterministic personal
            # workspace, which also covers a just-created user before membership bootstraps.
            scopes.append((user_id, None))
    return scopes


async def sweep_users(
    *,
    trigger: str,
    force: bool,
    changed_dcs: set[str] | None = None,
) -> int:
    """Bounded fan-out across user/workspace scopes."""
    scopes = await _all_user_scopes()
    limit = max(1, int(getattr(settings, "deep_dive_concurrency", 4)))
    semaphore = asyncio.Semaphore(limit)

    async def one(user_id: str, workspace_id: str | None) -> bool:
        async with semaphore:
            return await run_deep_dive_for_user(
                user_id,
                workspace_id,
                trigger=trigger,
                force=force,
                changed_dcs=changed_dcs,
            )

    results = await asyncio.gather(
        *(one(user_id, workspace_id) for user_id, workspace_id in scopes)
    )
    return sum(bool(result) for result in results)


async def sweep_changed_dcs(diagnostic_codes: list[str] | set[str]) -> int:
    """Map changed rating-card DCs to scoped candidate sets, then force re-dives."""
    changed = {str(dc).strip() for dc in diagnostic_codes if str(dc).strip()}
    if not changed or not settings.deep_dive_on_rule_change:
        return 0
    return await sweep_users(trigger="rule_change", force=True, changed_dcs=changed)


async def run_periodic_sweeps(interval_hours: float | None = None) -> None:
    """Immediate sweep then repeat, mirroring the KB freshness-loop pattern."""
    interval = (
        settings.deep_dive_schedule_interval_hours
        if interval_hours is None
        else interval_hours
    )
    if not settings.deep_dive_on_schedule or interval <= 0:
        log.info("Deep-dive scheduler disabled.")
        return
    while True:
        await sweep_users(trigger="schedule", force=True)
        await asyncio.sleep(max(interval, 0.01) * 3600)
