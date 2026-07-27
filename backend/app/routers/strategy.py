"""Game Plan — GET /strategy. Gathers everything the app knows (via the canonical
`VeteranDossier`) and hands PLAIN data to the pure strategy engine
(app/strategy/plan.py), then lets the specialist firm (app/firm/) enrich the
result.

Reuses the same building blocks the rest of the app is tested against — the gap /
readiness engine, the §4.25 combine, the secondary/presumptive matchers, the decoder
cache, and the ITF countdown — so the Game Plan can never disagree with the pages it
summarizes. Educational only; nothing here files or predicts.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..config import settings
from ..deps import current_user_id, get_db
from ..firm import DeepDiveResult, VeteranDossier, build_dossier, deep_dive, run_firm
from ..firm.context import plan_decision_status_updates
from ..models import ClaimedCondition, GamePlanBriefingCache, GamePlanFirmCache
from ..rating.rates_data import Dependents, monthly_rate, rate_year_for
from ..schemas import (
    CaseBriefOut,
    DecisionStatusApplyOut,
    DecisionStatusUpdateOut,
    DeepDiveResultOut,
    GamePlanBriefing,
    GamePlanOut,
    InterviewSeedOut,
)
from ..strategy.briefing import build_briefing
from ..strategy.coach import enrich_plan_with_coach
from ..strategy.plan import build_game_plan

log = logging.getLogger("veteran_ops.strategy")

router = APIRouter(prefix="/strategy", tags=["strategy"])


def _facts_hash(
    *,
    snapshot: dict,
    condition_lines: list[dict],
    money: dict | None,
    denials: list[dict],
    suggestions: list[dict],
    focus: dict | None,
    cautions: list[dict] | None = None,
    tdiu: dict | None = None,
    opportunities: list[dict] | None = None,
    dossier_facts: dict | None = None,
) -> str:
    """Stable cache key for the exact facts that drive the local-LLM briefing AND
    the specialist firm — both regenerate only when the veteran's facts change."""
    payload = {
        "snapshot": snapshot,
        "condition_lines": condition_lines,
        "money": money,
        "denials": denials,
        "suggestions": suggestions,
        "focus": focus,
        "cautions": cautions or [],
        "tdiu": tdiu,
        "opportunities": opportunities or [],
        # The deep dive reads more of the canonical dossier than the fast plan
        # renders.  In particular, a diagnostic-code/profile/document change may
        # leave the visible condition line unchanged while materially changing the
        # candidate space or its record grounding.
        "dossier_facts": dossier_facts or {},
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _cached_briefing(db: AsyncSession, uid: str, facts_hash: str) -> dict | None:
    try:
        row = (
            await db.execute(
                select(GamePlanBriefingCache.payload)
                .where(
                    GamePlanBriefingCache.user_id == uuid.UUID(uid),
                    GamePlanBriefingCache.facts_hash == facts_hash,
                )
                .order_by(GamePlanBriefingCache.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row if isinstance(row, dict) else None
    except SQLAlchemyError:
        return None


async def _store_briefing(db: AsyncSession, uid: str, facts_hash: str, payload: dict) -> None:
    try:
        db.add(GamePlanBriefingCache(user_id=uuid.UUID(uid), facts_hash=facts_hash, payload=payload))
        await db.flush()
    except SQLAlchemyError:
        await db.rollback()


# ── Specialist-firm cache (mirrors the briefing cache, keyed on the SAME facts) ──
async def _firm_cache_payload(
    db: AsyncSession, uid: str, facts_hash: str
) -> dict | None:
    """Read the namespaced cache payload in this request's RLS scope."""
    try:
        row = (
            await db.execute(
                select(GamePlanFirmCache.payload)
                .where(
                    GamePlanFirmCache.user_id == uuid.UUID(uid),
                    GamePlanFirmCache.facts_hash == facts_hash,
                )
                .order_by(GamePlanFirmCache.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row if isinstance(row, dict) else None
    except SQLAlchemyError:
        return None


async def _cached_firm(db: AsyncSession, uid: str, facts_hash: str) -> list[dict] | None:
    payload = await _firm_cache_payload(db, uid, facts_hash)
    if isinstance(payload, dict) and isinstance(payload.get("findings"), list):
        return payload["findings"]
    return None


async def _cached_deep_dive(db: AsyncSession, uid: str, facts_hash: str) -> dict | None:
    payload = await _firm_cache_payload(db, uid, facts_hash)
    if isinstance(payload, dict) and isinstance(payload.get("deep_dive"), dict):
        return payload["deep_dive"]
    return None


async def _cached_notification(db: AsyncSession, uid: str, facts_hash: str) -> dict | None:
    payload = await _firm_cache_payload(db, uid, facts_hash)
    if isinstance(payload, dict) and isinstance(payload.get("notification"), dict):
        return payload["notification"]
    return None


async def _deep_dive_response(
    db: AsyncSession, uid: str, facts_hash: str, result: dict
) -> dict:
    """Attach the readable notification while keeping it a sibling cache namespace."""
    return {
        **result,
        "notification": await _cached_notification(db, uid, facts_hash),
    }


async def _latest_firm_payload(db: AsyncSession, uid: str) -> dict | None:
    """Latest firm-cache payload carrying a deep dive, ordered by the RESULT's ISO
    run time — forced rule/schedule runs update an existing facts-hash row, so
    row.created_at is not the run time. Exposes the whole payload (deep_dive AND its
    sibling notification namespace) so status reads can pull both from one row."""
    try:
        rows = (
            await db.execute(
                select(GamePlanFirmCache.payload)
                .where(GamePlanFirmCache.user_id == uuid.UUID(uid))
            )
        ).scalars().all()
    except SQLAlchemyError:
        return None
    payloads = [
        payload
        for payload in rows
        if isinstance(payload, dict) and isinstance(payload.get("deep_dive"), dict)
    ]
    return max(
        payloads,
        key=lambda payload: str(payload["deep_dive"].get("generated_at") or ""),
        default=None,
    )


async def _latest_deep_dive(db: AsyncSession, uid: str) -> dict | None:
    """Latest prior deep-dive result across fact hashes, used only to flag newly
    found keys."""
    payload = await _latest_firm_payload(db, uid)
    return payload["deep_dive"] if payload else None


async def _patch_firm_cache(
    db: AsyncSession, uid: str, facts_hash: str, patch: dict
) -> bool:
    """Atomically merge one namespace into GamePlanFirmCache.

    GET /strategy and GET /strategy/deepdive start concurrently in the frontend,
    and proactive jobs can race either request.  PostgreSQL's JSONB upsert preserves
    the sibling namespace and the unique scope/hash index resolves that race.  The
    generic path keeps the SQLite test harness usable.
    """
    try:
        async with db.begin_nested():
            bind = db.get_bind()
            if bind.dialect.name == "postgresql":
                stmt = pg_insert(GamePlanFirmCache).values(
                    user_id=uuid.UUID(uid), facts_hash=facts_hash, payload=patch
                )
                stmt = stmt.on_conflict_do_update(
                    index_elements=[
                        GamePlanFirmCache.user_id,
                        GamePlanFirmCache.workspace_id,
                        GamePlanFirmCache.facts_hash,
                    ],
                    set_={
                        "payload": GamePlanFirmCache.payload.op("||")(stmt.excluded.payload)
                    },
                )
                await db.execute(stmt)
            else:
                row = (
                    await db.execute(
                        select(GamePlanFirmCache)
                        .where(
                            GamePlanFirmCache.user_id == uuid.UUID(uid),
                            GamePlanFirmCache.facts_hash == facts_hash,
                        )
                        .order_by(GamePlanFirmCache.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if row is None:
                    db.add(
                        GamePlanFirmCache(
                            user_id=uuid.UUID(uid), facts_hash=facts_hash, payload=patch
                        )
                    )
                else:
                    row.payload = {**(row.payload or {}), **patch}
            await db.flush()
        return True
    except SQLAlchemyError:
        log.warning("firm cache update failed; result remains available in-memory.", exc_info=True)
        return False


async def _store_firm(db: AsyncSession, uid: str, facts_hash: str, findings: list[dict]) -> None:
    await _patch_firm_cache(db, uid, facts_hash, {"findings": findings})


async def _store_deep_dive(
    db: AsyncSession,
    uid: str,
    facts_hash: str,
    result: dict,
    notification: dict,
) -> None:
    await _patch_firm_cache(
        db,
        uid,
        facts_hash,
        {"deep_dive": result, "notification": notification},
    )


def _merge_firm(plan: dict, findings: list[dict]) -> None:
    """Merge the firm's reviewed findings into the Battle Plan.

    Phase 1 wires the firm's ENRICHMENT into `opportunities`: for a secondary/
    under-rating finding whose deterministic seed already produced the matching
    opportunity (same stable `key`), overlay the reviewed (possibly warmer) body.
    The key/kind/reg/severity/needs_nexus are the seed's, untouched — so the
    render shape and the derived priority_actions stay byte-identical to today;
    only the opportunity's prose can differ. Deterministic-only findings
    (pyramiding / TDIU / presumptive) already render identically via the pure
    engine, so they need no re-merge here."""
    opp_index = {o.get("key"): o for o in plan.get("opportunities") or []}
    for f in findings:
        if f.get("kind") not in ("secondary", "underrating"):
            continue
        opp = opp_index.get(f.get("key"))
        if opp is not None and isinstance(f.get("body"), str) and f["body"].strip():
            opp["body"] = f["body"]


def _merge_deep_dive(plan: dict, payload: dict | None) -> None:
    """Overlay reviewed deep-dive prose only where the deterministic plan already
    owns the exact same opportunity key.  It never appends, reorders, or changes a
    seed's kind/reg/severity, so the fast Battle Plan remains non-regressing."""
    if not isinstance(payload, dict):
        return
    opp_index = {o.get("key"): o for o in plan.get("opportunities") or []}
    for finding in payload.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        opportunity = opp_index.get(finding.get("key"))
        body = finding.get("body")
        if opportunity is not None and isinstance(body, str) and body.strip():
            opportunity["body"] = body


def _active_finding_keys(payload: dict | None) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    return {
        str(finding.get("key"))
        for finding in payload.get("findings") or []
        if isinstance(finding, dict)
        and finding.get("key")
        and finding.get("active") is not False
    }


_deep_dive_locks: dict[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = {}


def _deep_dive_lock(uid: str, facts_hash: str) -> asyncio.Lock:
    """Coalesce same-process analysis/intake/schedule races for one veteran.

    One lock per user (rather than per ever-changing hash) also bounds the lock map.
    """
    loop = asyncio.get_running_loop()
    for stale in [item for item in _deep_dive_locks if item.is_closed()]:
        del _deep_dive_locks[stale]
    del facts_hash  # part of the caller-facing cache seam; coalescing is broader
    return _deep_dive_locks.setdefault(loop, {}).setdefault(uid, asyncio.Lock())


async def _run_cached_deep_dive(
    db: AsyncSession,
    uid: str,
    dossier: VeteranDossier,
    facts_hash: str,
    *,
    force: bool,
    trigger: str,
) -> dict:
    """Run the exhaustive batch once per facts hash unless explicitly forced.

    The notification is deliberately local cache metadata: no email, filing, or
    external action.  Proactive runs compare active reviewed keys to the prior cached
    result so the UI can later surface "the sweep found something new."
    """
    async with _deep_dive_lock(uid, facts_hash):
        cached = await _cached_deep_dive(db, uid, facts_hash)
        if cached is not None and not force:
            return cached
        previous = await _latest_deep_dive(db, uid)
        try:
            result = (await deep_dive(db, dossier)).to_dict()
        except Exception:  # noqa: BLE001 — additive analysis never blocks the plan
            log.warning("deep-dive batch failed; serving the last safe result.", exc_info=True)
            return cached or DeepDiveResult.empty(dossier.current_combined).to_dict()

        new_keys = sorted(_active_finding_keys(result) - _active_finding_keys(previous))
        proactive = trigger in {"intake", "schedule", "rule_change"}
        notification = {
            "has_new_findings": bool(proactive and new_keys),
            "new_finding_keys": new_keys if proactive else [],
            "trigger": trigger,
            "generated_at": result.get("generated_at") or datetime.now(timezone.utc).isoformat(),
        }
        await _store_deep_dive(db, uid, facts_hash, result, notification)
        return result


async def _apply_firm(
    db: AsyncSession, uid: str, dossier: VeteranDossier, plan: dict, facts_hash: str,
    *, run: bool = False,
) -> None:
    """Merge the firm's cached findings into the plan. By default CACHE-ONLY — a plain
    GET (Dashboard, Battle Plan load) NEVER runs the local LLM, so viewing a page can't
    spin the GPU. The firm (LLM-enriched) runs only when `run=True` (an explicit
    refresh action). Best-effort — a firm failure never blocks the Battle Plan."""
    try:
        findings = await _cached_firm(db, uid, facts_hash)
        if findings is None and run:
            objs = await run_firm(dossier, db)
            findings = [f.to_dict() for f in objs]
            await _store_firm(db, uid, facts_hash, findings)
        if findings is not None:
            _merge_firm(plan, findings)
        _merge_deep_dive(plan, await _cached_deep_dive(db, uid, facts_hash))
    except Exception:  # noqa: BLE001 — the firm is additive, never a blocker
        log.warning("firm merge failed — serving the deterministic Battle Plan.", exc_info=True)


def _money(current_combined, today) -> dict | None:
    """VA's published monthly amount for the veteran's CURRENT combined rating,
    single-veteran baseline. None when there's no rating yet; a null-amount dict
    (with basis) when the rate year isn't loaded. Never estimates an amount."""
    if not isinstance(current_combined, int) or current_combined <= 0:
        return None
    pct = max(0, min(100, round(current_combined / 10) * 10))  # VA ratings are multiples of 10
    ry = rate_year_for(today)
    try:
        amt = monthly_rate(today, pct, Dependents())
    except ValueError:
        return None
    if amt is None:
        return {
            "current_combined": pct,
            "current_monthly": None,
            "basis": f"VA's {ry} rate table isn't loaded for this month, so no amount is shown.",
            "rate_year": ry,
        }
    return {
        "current_combined": pct,
        "current_monthly": float(amt),
        "basis": (
            "VA's published monthly amount at this combined rating for a single veteran "
            "with no dependents — you may receive more with a spouse, children, or "
            "dependent parents. Your VA award letter is the authority."
        ),
        "rate_year": ry,
    }


def _safe_orm_attr(obj: object, name: str, default=None):
    """Read an ORM attribute without triggering a deferred async lazy-load.

    If the column was omitted from load_only / not loaded, return default instead
    of raising MissingGreenlet (sqlalchemy.me/e/20/xd2s).
    """
    try:
        from sqlalchemy import inspect as sa_inspect

        state = sa_inspect(obj, raiseerr=False)
        if state is not None and name in getattr(state, "unloaded", set()):
            return default
        return getattr(obj, name, default)
    except Exception:  # noqa: BLE001 — never let cache-key assembly crash analysis
        return default


def _dossier_facts(dossier: VeteranDossier) -> dict:
    """Stable, compact facts the deep dive reads but GamePlanOut does not expose.

    Document text is intentionally not copied into the cache key.  Its immutable
    digest plus updated_at identify the exact ready-document revision without
    duplicating veteran record content in a hash payload.
    """
    conditions = sorted(
        (dict(condition) for condition in dossier.conditions),
        key=lambda item: (str(item.get("id") or ""), str(item.get("name") or "")),
    )
    documents = sorted(
        (
            {
                "id": str(getattr(document, "id", "") or ""),
                "sha256": str(getattr(document, "sha256", "") or ""),
                "doc_type": getattr(document, "doc_type", None),
                # Must be eager-loaded in build_dossier (load_only includes updated_at).
                # Never trigger a deferred lazy load under async (MissingGreenlet).
                "updated_at": _safe_orm_attr(document, "updated_at")
                or _safe_orm_attr(document, "created_at"),
            }
            for document in dossier.documents
        ),
        key=lambda item: item["id"],
    )
    return {
        "conditions": conditions,
        "profile": dossier.profile or {},
        "documents": documents,
    }


async def _assemble_strategy(
    db: AsyncSession, uid: str
) -> tuple[dict, str, dict, VeteranDossier]:
    """Build the canonical dossier, then derive the Battle Plan, the facts-hash,
    and the briefing args from it — so the plan, the briefing, and the firm all
    read IDENTICAL data (no drift)."""
    dossier = await build_dossier(db, uid)
    today = datetime.now(timezone.utc).date()

    plan = build_game_plan(
        conditions=dossier.conditions,
        denials=dossier.denials,
        suggestions=dossier.suggestions,
        active_itf=dossier.active_itf,
        current_combined=dossier.current_combined,
        generated_at=dossier.generated_at,
    )

    # Decision-status pending: raw DB unknown that letters could fill (not overlay).
    pending_n = 0
    try:
        user_uuid = uuid.UUID(uid)
        raw_rows = (
            await db.execute(
                select(ClaimedCondition).where(ClaimedCondition.user_id == user_uuid)
            )
        ).scalars().all()
        raw_conds = [
            {
                "id": str(r.id),
                "name": r.name,
                "va_status": r.va_status or "unknown",
                "current_rating": r.current_rating,
            }
            for r in raw_rows
        ]
        pending_n = len(plan_decision_status_updates(raw_conds, dossier.documents))
    except Exception:  # noqa: BLE001 — coach enrichment never blocks the plan
        log.warning("coach pending-status count failed", exc_info=True)

    enrich_plan_with_coach(
        plan,
        conditions=dossier.conditions,
        denials=dossier.denials,
        decision_status_pending=pending_n,
    )

    # Money anchor + the exact facts that drive the optional local-LLM briefing.
    money = _money(dossier.current_combined, today)
    plan["money"] = money
    briefing_args = {
        "snapshot": plan["snapshot"],
        "condition_lines": plan["condition_lines"],
        "money": money,
        "denials": dossier.denials,
        "suggestions": dossier.suggestions,
        "focus": plan["focus"],
        "cautions": plan.get("cautions") or [],
        "tdiu": plan.get("tdiu"),
        "opportunities": plan.get("opportunities") or [],
    }
    return (
        plan,
        _facts_hash(**briefing_args, dossier_facts=_dossier_facts(dossier)),
        briefing_args,
        dossier,
    )


@router.get("", response_model=GamePlanOut)
async def get_strategy(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    # CACHE-ONLY: viewing the Dashboard or Battle Plan never runs the LLM (no GPU on
    # load). The deterministic plan is always complete; cached firm/briefing/deep-dive
    # enrich it when present. Explicit refresh (POST /strategy/refresh) runs the analysis.
    plan, facts_hash, _, dossier = await _assemble_strategy(db, uid)
    plan["briefing"] = await _cached_briefing(db, uid, facts_hash)
    await _apply_firm(db, uid, dossier, plan, facts_hash)  # run=False → cache-only
    return GamePlanOut(**plan)


@router.post("/refresh", response_model=GamePlanOut)
async def refresh_strategy(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Explicit 'refresh my analysis' — RUNS the specialist firm + briefing on the
    local model and caches them, then returns the enriched plan. This is the button
    behind re-analysis; a plain GET stays LLM-free so pages never spin the GPU."""
    plan, facts_hash, briefing_args, dossier = await _assemble_strategy(db, uid)
    # (Re)generate the briefing on the local model if this facts snapshot has none.
    briefing = await _cached_briefing(db, uid, facts_hash)
    if briefing is None:
        try:
            briefing = await build_briefing(**briefing_args)
            await _store_briefing(db, uid, facts_hash, briefing)
        except Exception:  # noqa: BLE001 — enrichment is additive, never a blocker
            log.warning("briefing refresh failed", exc_info=True)
            briefing = None
    plan["briefing"] = briefing
    await _apply_firm(db, uid, dossier, plan, facts_hash, run=True)
    await db.commit()
    return GamePlanOut(**plan)


@router.get("/briefing", response_model=GamePlanBriefing | None)
async def get_strategy_briefing(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """CACHE-ONLY: returns the cached plain-language briefing for the current facts
    snapshot if one exists, else null. A plain GET NEVER spins the GPU — the briefing
    is written by the explicit POST /strategy/refresh button or the comprehensive
    analysis run, so opening the Battle Plan can't silently start work."""
    _, facts_hash, _, _ = await _assemble_strategy(db, uid)
    cached = await _cached_briefing(db, uid, facts_hash)
    return GamePlanBriefing(**cached) if cached is not None else None


@router.get("/deepdive", response_model=DeepDiveResultOut)
async def get_strategy_deep_dive(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """CACHE-ONLY: returns the facts-keyed deep dive if one is cached, else the empty
    result. A plain GET NEVER spins the GPU — the deep dive is produced by the explicit
    POST /deepdive/run button or the comprehensive analysis run, so opening the Battle
    Plan can't silently start work on the GPU."""
    _, facts_hash, _, dossier = await _assemble_strategy(db, uid)
    cached = await _cached_deep_dive(db, uid, facts_hash)
    if cached is not None:
        return DeepDiveResultOut(**await _deep_dive_response(db, uid, facts_hash, cached))
    return DeepDiveResultOut(**DeepDiveResult.empty(dossier.current_combined).to_dict())


@router.post("/deepdive/run", response_model=DeepDiveResultOut)
async def run_strategy_deep_dive(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Veteran-requested forced re-dive.  It organizes only; it files nothing."""
    _, facts_hash, _, dossier = await _assemble_strategy(db, uid)
    result = await _run_cached_deep_dive(
        db,
        uid,
        dossier,
        facts_hash,
        force=True,
        trigger="manual",
    )
    return DeepDiveResultOut(**await _deep_dive_response(db, uid, facts_hash, result))


@router.get("/case-brief", response_model=CaseBriefOut)
async def get_case_brief(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Printable case brief one-pager payload (coach.case_brief)."""
    plan, _, _, dossier = await _assemble_strategy(db, uid)
    coach = plan.get("coach") or {}
    brief = coach.get("case_brief") or {}
    return CaseBriefOut(**brief) if brief else CaseBriefOut()


@router.get("/interview-seed", response_model=InterviewSeedOut)
async def get_strategy_interview_seed(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Same interview seed as GET /raider/interview-seed (Claim Plan CTA)."""
    plan, _, _, _ = await _assemble_strategy(db, uid)
    interview = (plan.get("coach") or {}).get("interview") or {}
    return InterviewSeedOut(**interview) if interview else InterviewSeedOut()


@router.get("/decision-statuses", response_model=DecisionStatusApplyOut)
async def preview_decision_statuses(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Preview va_status updates from formal decision letters (dry-run).

    Does not write. Only conditions still `unknown` are proposed. C&P exams are
    ignored — same rules as the in-memory Claim Plan overlay.
    """
    dossier = await build_dossier(db, uid)
    # Plan against RAW DB statuses (not overlay-mutated), so preview matches apply.
    user_uuid = uuid.UUID(uid)
    rows = (
        await db.execute(
            select(ClaimedCondition).where(ClaimedCondition.user_id == user_uuid)
        )
    ).scalars().all()
    conds = [
        {
            "id": str(r.id),
            "name": r.name,
            "va_status": r.va_status or "unknown",
            "current_rating": r.current_rating,
        }
        for r in rows
    ]
    updates = plan_decision_status_updates(conds, dossier.documents)
    return DecisionStatusApplyOut(
        dry_run=True,
        updated=0,
        updates=[DecisionStatusUpdateOut(**u) for u in updates if u.get("condition_id")],
    )


@router.post("/decision-statuses/apply", response_model=DecisionStatusApplyOut)
async def apply_decision_statuses(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
    dry_run: bool = Query(
        False,
        description="When true, return the plan without writing (same as GET).",
    ),
):
    """Persist decision-letter va_status (and SC percent when known) onto claimed
    conditions that are still `unknown`. Opt-in; never overwrites explicit statuses.
    Educational organizing of the veteran's own letters — not a VA determination.
    """
    dossier = await build_dossier(db, uid)
    user_uuid = uuid.UUID(uid)
    rows = (
        await db.execute(
            select(ClaimedCondition).where(ClaimedCondition.user_id == user_uuid)
        )
    ).scalars().all()
    conds = [
        {
            "id": str(r.id),
            "name": r.name,
            "va_status": r.va_status or "unknown",
            "current_rating": r.current_rating,
        }
        for r in rows
    ]
    updates = plan_decision_status_updates(conds, dossier.documents)
    # Keep only rows with real condition ids
    updates = [u for u in updates if u.get("condition_id")]
    if dry_run or not updates:
        return DecisionStatusApplyOut(
            dry_run=True if dry_run or not updates else False,
            updated=0,
            updates=[DecisionStatusUpdateOut(**u) for u in updates],
        )

    by_id = {str(r.id): r for r in rows}
    applied = 0
    for u in updates:
        row = by_id.get(u["condition_id"])
        if row is None:
            continue
        if (row.va_status or "unknown") in ("service_connected", "denied", "pending"):
            continue
        row.va_status = u["to_status"]
        if u.get("set_current_rating") is not None and row.current_rating is None:
            row.current_rating = u["set_current_rating"]
        applied += 1

    await audit.log(
        db,
        uid,
        "strategy.decision_statuses.apply",
        entity="claimed_condition",
        entity_id=None,
        meta={"updated": applied, "names": [u["name"] for u in updates[:20]]},
    )
    await db.commit()
    return DecisionStatusApplyOut(
        dry_run=False,
        updated=applied,
        updates=[DecisionStatusUpdateOut(**u) for u in updates],
    )


@router.get("/evidence-review")
async def get_evidence_review(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Proactive evidence picture: what's already in the file (to link) + what's
    obviously worth adding (to draft). Deterministic — no GPU."""
    from ..evidence.proactive import evidence_review
    from ..firm.context import build_dossier
    dossier = await build_dossier(db, uid)
    return evidence_review(dossier)
