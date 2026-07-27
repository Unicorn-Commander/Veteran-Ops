"""Durable comprehensive-analysis pipeline — the async twin of the synchronous
POST /analysis/comprehensive.

Runs the SAME pipeline (the exact strategy-router + comprehension helpers the sync
endpoint calls, in the same order with the same fail-safe per-step degradation), but
as a database-leased worker job that streams per-step progress + wall-clock into an
AnalysisRun row the UI polls. The dispatch/lease lifecycle lives in analysis/jobs.py;
this module only performs the tenant-scoped pipeline and returns its final payload.

SESSION DISCIPLINE — db.py sets the RLS GUCs with ``set_config(..., is_local => true)``
(SET LOCAL: per-transaction, cleared on commit), so a session can't commit mid-way and
keep its scope. Each step therefore runs in its OWN short ``user_session`` that commits
on close, and every progress write opens its own as well — only ONE session is ever open
at a time. That means no transaction held open across the minutes-long LLM calls,
incremental cache durability (a late failure keeps the earlier steps' results), and no
concurrent-writer contention. The dossier assembled in step 1 is plain data plus
fully-loaded (hence detached-safe) Document rows, so later steps reuse it across session
boundaries without a re-query.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Callable

from sqlalchemy import select

from ..db import session_for_user
from ..models import AnalysisRun

log = logging.getLogger("veteran_ops.analysis.comprehensive")

# db.py's session_for_user is an async generator; wrap it so we can `async with`.
user_session = asynccontextmanager(session_for_user)

# (key, label) in run order — kept here so the /start endpoint can seed the row and
# the UI can render pending rows before the task first touches them.
STEPS: list[tuple[str, str]] = [
    ("assemble", "Reading your file & building the dossier"),
    ("mapping", "Rating-floor mapping"),
    ("briefing", "Plain-language briefing"),
    ("firm", "Specialist firm review"),
    ("deep_dive", "Exhaustive deep dive"),
    ("comprehension", "Whole-C-file comprehension"),
]


def seed_steps() -> list[dict]:
    """The initial `steps` list stamped on a freshly-created run row."""
    return [
        {"key": k, "label": lbl, "status": "pending", "seconds": None, "detail": None}
        for k, lbl in STEPS
    ]


# Enrichment steps that may degrade without failing the whole run. Assemble is
# required for the success path (a crash there raises and the worker fails the job).
_ENRICHMENT_KEYS: tuple[str, ...] = (
    "mapping",
    "briefing",
    "firm",
    "deep_dive",
    "comprehension",
)
_ENRICHMENT_LABELS: dict[str, str] = {
    "mapping": "rating-floor mapping",
    "briefing": "plain-language briefing",
    "firm": "specialist firm review",
    "deep_dive": "exhaustive deep dive",
    "comprehension": "whole-C-file comprehension",
}


def classify_run_quality(ran: dict) -> dict:
    """Classify a successful comprehensive run's enrichment completeness.

    Call only after assemble has succeeded (the success-return path). Status stays
    ``completed`` regardless — quality lives on the summary so the UI can warn
    without treating the run as a failure.

    - full: firm + deep_dive both ran (core specialist enrichment present)
    - partial: assemble + any enrichment (briefing | firm | deep_dive | comprehension)
    - minimal: assemble only (every enrichment step false)
    """
    notes = [
        f"{_ENRICHMENT_LABELS.get(k, k)} unavailable"
        for k in _ENRICHMENT_KEYS
        if not ran.get(k)
    ]
    firm = bool(ran.get("firm"))
    deep_dive = bool(ran.get("deep_dive"))
    any_enrichment = any(bool(ran.get(k)) for k in _ENRICHMENT_KEYS)
    if firm and deep_dive:
        quality = "full"
    elif any_enrichment:
        quality = "partial"
    else:
        quality = "minimal"
    return {
        "quality": quality,
        "quality_notes": notes,
        "degraded": quality != "full",
    }


def _set_step(steps: list[dict], key: str, **changes) -> list[dict]:
    """Return a NEW steps list with `key`'s row updated — reassigning the whole list
    (rather than mutating a dict in place) is what makes SQLAlchemy track the JSONB
    change without a manual flag_modified."""
    out: list[dict] = []
    for s in steps:
        s = dict(s)
        if s.get("key") == key:
            s.update(changes)
        out.append(s)
    return out


async def _load(db, run_id: str) -> AnalysisRun | None:
    return (
        await db.execute(select(AnalysisRun).where(AnalysisRun.id == uuid.UUID(run_id)))
    ).scalar_one_or_none()


async def _update(
    run_id: str, uid: str, wsid: str | None, mutate: Callable[[AnalysisRun], None]
) -> None:
    """Apply `mutate` to the run row in its OWN short transaction and commit — the
    per-step progress writer. Best-effort: a progress-write failure must NEVER crash
    the run (the analysis matters more than its telemetry)."""
    try:
        async with user_session(uid, wsid) as db:
            run = await _load(db, run_id)
            if run is None:  # deleted mid-run, or not this user's row (RLS)
                return
            mutate(run)
    except Exception:  # noqa: BLE001 — telemetry is never load-bearing
        log.warning("comprehensive: progress write failed (run=%s)", run_id, exc_info=True)


async def run_comprehensive_job(run_id: str, uid: str, wsid: str | None) -> dict:
    """Execute one leased attempt and return its terminal payload.

    Expected enrichment failures degrade at their individual step. A fatal pipeline
    error propagates to the durable worker, which applies bounded retry/backoff or a
    final failure under the lease fencing token.
    """
    from ..analysis import comprehension as comprehension_mod
    from ..routers import strategy as strat
    from ..strategy.briefing import build_briefing

    t0 = time.monotonic()
    ran = {
        "mapping": False,
        "firm": False,
        "briefing": False,
        "deep_dive": False,
        "comprehension": False,
    }

    async def mark(key: str, **changes) -> None:
        await _update(
            run_id, uid, wsid,
            lambda r: setattr(r, "steps", _set_step(r.steps, key, **changes)),
        )

    # Carried across step sessions. `dossier` (built in step 1) holds fully-loaded,
    # detached-safe Document rows the firm + deep dive reuse without re-querying.
    conditions_total = 0
    pathways_n = 0
    findings_n = 0
    new_findings = 0

    try:
        # 1) Assemble the canonical dossier + deterministic plan (fast, no LLM).
        await mark("assemble", status="running")
        s = time.monotonic()
        async with user_session(uid, wsid) as db:
            plan, facts_hash, briefing_args, dossier = await strat._assemble_strategy(db, uid)
            previous_dive = await strat._latest_deep_dive(db, uid)
        conditions_total = int(
            (plan.get("snapshot") or {}).get("conditions_total") or len(dossier.conditions)
        )
        pathways_n = len(plan.get("pathways") or [])
        await mark(
            "assemble", status="complete",
            seconds=round(time.monotonic() - s, 2),
            detail=f"{len(dossier.conditions)} conditions",
        )

        # 1b) Rating-floor mapping — same saved cache as POST /analysis/map-conditions.
        await mark(
            "mapping",
            status="running",
            detail="Matching conditions to rating-floor maps (saved when done)…",
        )
        s = time.monotonic()
        map_detail = "unavailable"
        async with user_session(uid, wsid) as db:
            try:
                from ..analysis import map_conditions as mapmod

                blob = await mapmod.run_map_conditions(db, uid, force=False)
                n_items = len(blob.get("items") or [])
                ran["mapping"] = n_items > 0 or blob.get("cached") is True
                map_detail = (
                    f"{n_items} mapped"
                    + (" (cached)" if blob.get("cached") else " (saved)")
                )
            except Exception:  # noqa: BLE001 — additive
                log.warning("comprehensive: mapping failed", exc_info=True)
                ran["mapping"] = False
                map_detail = "unavailable"
        await mark(
            "mapping",
            status="complete" if ran["mapping"] else "failed",
            seconds=round(time.monotonic() - s, 2),
            detail=map_detail,
        )

        # 2) Plain-language briefing (local LLM) — build on a facts-hash miss.
        await mark(
            "briefing",
            status="running",
            detail="Writing plain-language Claim Plan briefing…",
        )
        s = time.monotonic()
        async with user_session(uid, wsid) as db:
            briefing = await strat._cached_briefing(db, uid, facts_hash)
            if briefing is None:
                try:
                    briefing = await build_briefing(**briefing_args)
                    await strat._store_briefing(db, uid, facts_hash, briefing)
                    ran["briefing"] = True
                    b_detail = "generated"
                except Exception:  # noqa: BLE001 — enrichment is additive, never a blocker
                    log.warning("comprehensive: briefing failed", exc_info=True)
                    briefing = None
                    b_detail = "unavailable"
            else:
                ran["briefing"] = True
                b_detail = "cached (unchanged facts)"
        plan["briefing"] = briefing
        await mark(
            "briefing",
            status="complete" if briefing is not None else "failed",
            seconds=round(time.monotonic() - s, 2), detail=b_detail,
        )

        # 3) Specialist firm (run=True) — best-effort; read the cache back to learn
        # whether it produced findings.
        await mark(
            "firm",
            status="running",
            detail=f"Specialists reviewing {conditions_total} conditions (TDIU, secondaries, underrating…)",
        )
        s = time.monotonic()
        async with user_session(uid, wsid) as db:
            try:
                await strat._apply_firm(db, uid, dossier, plan, facts_hash, run=True)
            except Exception:  # noqa: BLE001 — belt-and-suspenders; _apply_firm swallows
                log.warning("comprehensive: firm merge failed", exc_info=True)
            ran["firm"] = (await strat._cached_firm(db, uid, facts_hash)) is not None
        await mark(
            "firm", status="complete" if ran["firm"] else "failed",
            seconds=round(time.monotonic() - s, 2),
            detail="specialist review complete" if ran["firm"] else "specialists unavailable",
        )

        # 4) Forced exhaustive deep dive — never raises internally.
        # Live detail: veterans often stare at this step; name the work plainly.
        await mark(
            "deep_dive",
            status="running",
            detail=(
                f"Comparing {conditions_total} conditions to 38 CFR rating paths "
                "(enumerate candidates → score criteria → grounded findings). "
                "This can take several minutes."
            ),
        )
        s = time.monotonic()
        deep_dive_result: dict = {}
        async with user_session(uid, wsid) as db:
            try:
                deep_dive_result = await strat._run_cached_deep_dive(
                    db, uid, dossier, facts_hash, force=True, trigger="manual"
                )
            except Exception:  # noqa: BLE001 — additive analysis never blocks the job
                log.warning("comprehensive: deep dive failed", exc_info=True)
                deep_dive_result = {}
        ran["deep_dive"] = bool(deep_dive_result.get("generated_at"))
        findings_n = len(deep_dive_result.get("findings") or [])
        considered = int(
            deep_dive_result.get("candidates_considered")
            or deep_dive_result.get("candidates_total")
            or 0
        )
        new_findings = len(
            strat._active_finding_keys(deep_dive_result)
            - strat._active_finding_keys(previous_dive)
        )
        dd_detail = (
            f"{findings_n} findings ({new_findings} new)"
            + (f" · {considered} rating paths scored" if considered else "")
        )
        await mark(
            "deep_dive", status="complete" if ran["deep_dive"] else "failed",
            seconds=round(time.monotonic() - s, 2),
            detail=dd_detail if ran["deep_dive"] else "deep dive unavailable",
        )

        # 5) Whole-C-file comprehension — its own RLS-scoped session lives inside
        # (consent-aware PII model resolution + audit release). Never raises.
        await mark(
            "comprehension",
            status="running",
            detail=(
                "Building your case picture from the whole file (timeline, SC elements, "
                "contradictions). Usually the longest step — long-context model."
            ),
        )
        s = time.monotonic()
        try:
            ran["comprehension"] = await comprehension_mod.run_comprehension_for_user(
                uid, wsid, force=True
            )
        except Exception:  # noqa: BLE001 — comprehension is additive, never blocks
            log.warning("comprehensive: comprehension failed", exc_info=True)
            ran["comprehension"] = False
        await mark(
            "comprehension",
            status="complete" if ran["comprehension"] else "failed",
            seconds=round(time.monotonic() - s, 2),
            detail="case picture ready" if ran["comprehension"] else "case picture unavailable",
        )

        # Case-picture readiness for the summary (fresh short session).
        async with user_session(uid, wsid) as db:
            picture = await comprehension_mod.get_case_picture(db, uid)
        quality_meta = classify_run_quality(ran)
        summary_payload = {
            "conditions": conditions_total,
            "pathways": pathways_n,
            "deep_dive_findings": findings_n,
            "new_findings": new_findings,
            "case_picture_ready": picture is not None,
            **quality_meta,
        }

        total = round(time.monotonic() - t0, 2)

        log.info(
            "comprehensive job complete (run=%s, %.1fs, quality=%s)",
            run_id, total, quality_meta["quality"],
        )
        return {
            "ran": dict(ran),
            "summary": summary_payload,
            "total_seconds": total,
        }
    except Exception as exc:  # noqa: BLE001 — the whole job must fail-close on the row
        # Exception text can include a document path or extracted record content.
        # Keep operational logs PII-free; the tenant-fenced worker result retains
        # the bounded user-visible error for diagnosis.
        log.error(
            "comprehensive job crashed (run=%s, error_type=%s)",
            run_id,
            type(exc).__name__,
            exc_info=True,
        )
        raise
