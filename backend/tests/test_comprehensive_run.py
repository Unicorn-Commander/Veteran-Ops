"""Durable comprehensive analysis (router + DB lease worker + tenant pipeline).

  * POST /analysis/comprehensive/start   — commits a queued run/job immediately (202).
  * GET  /analysis/comprehensive/runs/{id} — poll live progress through terminal state.
  * GET  /analysis/comprehensive/latest    — resume the most recent run.
  * GET  /analysis/comprehensive/runs      — benchmark history.
  * GET  /analysis/intake-benchmark         — approximate document-intake cost.

Tests explicitly claim and process a durable lease after enqueueing; request teardown
can no longer run analysis work.

The gateway is dead (firm/briefing/deep-dive degrade to their deterministic floors),
comprehension is stubbed, and — crucially — the background job's `user_session` (which
in prod sets Postgres RLS GUCs) is redirected at the SQLite test session.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import deps, models  # noqa: E402
from app.analysis import comprehension as comprehension_mod  # noqa: E402
from app.analysis import comprehensive_run as crun  # noqa: E402
from app.analysis import jobs as analysis_jobs  # noqa: E402
from app.analysis import worker as analysis_worker  # noqa: E402
from app.db import Base  # noqa: E402
from app.llm.gateway import gateway as _gateway  # noqa: E402
from app.routers import analysis as analysis_mod  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover
    Vector = None


@compiles(PGUUID, "sqlite")
def _u(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _j(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


if Vector is not None:
    @compiles(Vector, "sqlite")
    def _v(type_, compiler, **kw):  # noqa: ANN001, ANN003
        return "TEXT"


_TABLES = [
    models.Organization.__table__, models.User.__table__, models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__, models.EvidenceItem.__table__,
    models.ItfRecord.__table__, models.Document.__table__,
    models.KBCard.__table__, models.GamePlanFirmCache.__table__,
    models.GamePlanBriefingCache.__table__, models.CFilePictureCache.__table__,
    models.AnalysisRun.__table__, models.AnalysisJob.__table__,
    models.AnalysisWorker.__table__, models.KBRefreshSignal.__table__,
    models.AuditLog.__table__,
]
for _t in _TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())

UA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
UB = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
WS = uuid.UUID("00000000-0000-0000-0000-0000000000c3")
C_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")


def _picture() -> dict:
    return {
        "timeline": [], "condition_roster": [], "exam_inventory": [],
        "nexus_inventory": [], "decision_inventory": [], "contradictions": [],
        "coverage_gaps": [], "read_completeness": {"complete": True},
        "grounding_excerpts": [], "generated_from_segments": 1, "facts_hash": "seed",
    }


def _seed(Session, *objs) -> None:
    async def _go():
        async with Session() as s:
            for o in objs:
                s.add(o)
            await s.commit()
    asyncio.run(_go())


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}", poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(UA)}

    # The background job's RLS-scoped session (Postgres SET LOCAL in prod) → the test
    # SQLite session, committing on clean exit exactly like db.py's session_for_user.
    @asynccontextmanager
    async def _fake_user_session(uid, wsid=None):
        async with Session() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise
    monkeypatch.setattr(crun, "user_session", _fake_user_session)
    monkeypatch.setattr(analysis_jobs, "tenant_session", _fake_user_session)
    monkeypatch.setattr(analysis_jobs, "global_sessionmaker", Session)
    monkeypatch.setattr(analysis_jobs, "job_engine", engine)

    # No live fleet: the gateway is dead so firm/briefing/deep-dive degrade to floors.
    def _boom(*a, **k):
        async def _raise():
            raise RuntimeError("gateway down")
        return _raise()
    monkeypatch.setattr(_gateway, "complete", _boom)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.Organization(id=WS, name="Personal", slug="personal-test",
                                    kind="personal", plan_tier="free", status="active"),
                models.User(id=UA, email="a@e.test", password_hash="x", full_name="Alex V"),
                models.User(id=UB, email="b@e.test", password_hash="x", full_name="Blair O"),
                models.VeteranProfile(user_id=UA, current_combined_rating=50,
                                      service_periods=[], exposures={}),
                models.ClaimedCondition(id=C_PTSD, user_id=UA, name="PTSD",
                                        claim_type="direct", current_rating=50,
                                        target_rating=70, in_service_event="IED blast"),
                models.Document(user_id=UA, filename="seed.txt", sha256="seed-ready",
                                size_bytes=24, status="ready", text_content="Service record text"),
            ])
            s.add(models.EvidenceItem(user_id=UA, condition_id=C_PTSD, kind="diagnosis",
                                      title="Dx", status="have"))
            s.add(models.EvidenceItem(user_id=UA, condition_id=C_PTSD, kind="nexus_letter",
                                      title="Nexus", status="have"))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(analysis_mod.router, prefix="/api")
    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.current_workspace_id] = lambda: str(WS)

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current, Session=Session, monkeypatch=monkeypatch)


def _ok_comprehension(monkeypatch, *, result=True):
    async def _run(uid, wsid=None, *, force=False):
        assert force is True
        return result
    monkeypatch.setattr(comprehension_mod, "run_comprehension_for_user", _run)


def _run_next(env, worker_id="test-worker"):
    async def _go():
        lease = await analysis_jobs.claim_one(worker_id)
        assert lease is not None
        return await analysis_worker.process_lease(lease, worker_id)
    return asyncio.run(_go())


# ── quality classification (unit — no pipeline) ───────────────────────────────
def test_classify_run_quality_full_when_firm_and_deep_dive():
    q = crun.classify_run_quality(
        {"firm": True, "briefing": True, "deep_dive": True, "comprehension": True}
    )
    assert q["quality"] == "full"
    assert q["degraded"] is False
    assert q["quality_notes"] == []


def test_classify_run_quality_full_ignores_optional_enrichment_gaps():
    # Briefing/comprehension optional — firm+deep_dive still counts as full.
    q = crun.classify_run_quality(
        {"firm": True, "briefing": False, "deep_dive": True, "comprehension": False}
    )
    assert q["quality"] == "full"
    assert q["degraded"] is False
    assert "plain-language briefing unavailable" in q["quality_notes"]
    assert "whole-C-file comprehension unavailable" in q["quality_notes"]


def test_classify_run_quality_partial_with_any_single_enrichment():
    for key in ("briefing", "firm", "deep_dive", "comprehension"):
        ran = {"firm": False, "briefing": False, "deep_dive": False, "comprehension": False}
        ran[key] = True
        q = crun.classify_run_quality(ran)
        assert q["quality"] == "partial", key
        assert q["degraded"] is True
        assert len(q["quality_notes"]) == 3


def test_classify_run_quality_minimal_when_all_enrichment_failed():
    q = crun.classify_run_quality(
        {"firm": False, "briefing": False, "deep_dive": False, "comprehension": False}
    )
    assert q["quality"] == "minimal"
    assert q["degraded"] is True
    assert len(q["quality_notes"]) == 4


# ── start → immediate queued row ──────────────────────────────────────────────
def test_start_returns_202_with_a_queued_run_and_seeded_pending_steps(env):
    _ok_comprehension(env.monkeypatch)
    r = env.client.post("/api/analysis/comprehensive/start")
    assert r.status_code == 202, r.text
    body = r.json()
    assert uuid.UUID(body["id"])                      # a real run id
    # The response is built from the seeded row BEFORE the background task mutates it.
    assert body["status"] == "queued"
    assert [s["key"] for s in body["steps"]] == [
        "assemble", "briefing", "firm", "deep_dive", "comprehension"]
    assert all(s["status"] == "pending" and s["seconds"] is None for s in body["steps"])


def test_prerequisites_explain_missing_inputs_and_start_fails_closed(env):
    ready = env.client.get("/api/analysis/comprehensive/prerequisites").json()
    assert ready["ready"] is True
    assert ready["conditions"] == 1 and ready["ready_documents"] == 1

    env.current["uid"] = str(UB)
    missing = env.client.get("/api/analysis/comprehensive/prerequisites").json()
    assert missing["ready"] is False
    assert {item["key"] for item in missing["missing"]} == {"conditions", "documents"}
    blocked = env.client.post("/api/analysis/comprehensive/start")
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["code"] == "analysis_prerequisites"
    assert detail["prerequisites"]["ready"] is False


def test_start_is_idempotent_and_does_not_duplicate_active_work(env):
    headers = {"Idempotency-Key": "analysis-click-1"}
    first = env.client.post("/api/analysis/comprehensive/start", headers=headers)

    async def _prerequisites_must_not_run(*args, **kwargs):
        raise AssertionError("an accepted durable enqueue must win over mutable prerequisites")

    env.monkeypatch.setattr(
        analysis_mod, "_require_comprehensive_prerequisites", _prerequisites_must_not_run
    )
    second = env.client.post("/api/analysis/comprehensive/start", headers=headers)
    different_key = env.client.post(
        "/api/analysis/comprehensive/start",
        headers={"Idempotency-Key": "analysis-click-2"},
    )
    assert first.status_code == second.status_code == different_key.status_code == 202
    assert first.json()["id"] == second.json()["id"] == different_key.json()["id"]

    async def _counts():
        async with env.Session() as db:
            return (
                len((await db.execute(models.AnalysisRun.__table__.select())).all()),
                len((await db.execute(models.AnalysisJob.__table__.select())).all()),
            )

    assert asyncio.run(_counts()) == (1, 1)


def test_queued_run_can_be_cancelled_and_is_not_claimed(env):
    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]
    cancelled = env.client.post(
        f"/api/analysis/comprehensive/runs/{run_id}/cancel"
    )
    assert cancelled.status_code == 202
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_requested"] is True
    assert asyncio.run(analysis_jobs.claim_one("test-worker")) is None


# ── the durable worker drives the run to completion with per-step timings ──────
def test_durable_worker_completes_the_run_with_timed_steps_and_summary(env):
    _ok_comprehension(env.monkeypatch)
    _seed(env.Session, models.CFilePictureCache(
        user_id=UA, facts_hash="fh", payload=_picture(),
        created_at=datetime(2026, 7, 11, tzinfo=timezone.utc)))

    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]
    assert _run_next(env) == "completed"
    body = env.client.get(f"/api/analysis/comprehensive/runs/{run_id}").json()

    assert body["status"] == "completed"
    assert body["error"] is None
    assert body["started_at"] and body["finished_at"]
    assert isinstance(body["total_seconds"], (int, float))
    # Every step reached a terminal state and carries a wall-clock number.
    for step in body["steps"]:
        assert step["status"] in ("complete", "failed"), step
        assert isinstance(step["seconds"], (int, float)), step
    # ran-map + summary mirror the synchronous ComprehensiveOut.
    assert set(body["ran"]) == {"firm", "briefing", "deep_dive", "comprehension"}
    assert body["ran"]["deep_dive"] is True           # deterministic floor still "runs"
    assert body["ran"]["comprehension"] is True
    assert body["summary"]["conditions"] == 1
    assert body["summary"]["case_picture_ready"] is True
    # Quality metadata is always present on a successful completion.
    assert body["summary"]["quality"] in ("full", "partial", "minimal")
    assert isinstance(body["summary"]["quality_notes"], list)
    assert isinstance(body["summary"]["degraded"], bool)
    # Gateway is dead in tests → firm/briefing usually degrade; deep_dive floor
    # + stubbed comprehension still run → partial (or full if firm also floors).
    assert body["summary"]["quality"] in ("full", "partial")


# ── a failing sub-step degrades that step, not the whole run ──────────────────
def test_comprehension_failure_marks_only_that_step_failed(env):
    async def _crash(uid, wsid=None, *, force=False):
        raise RuntimeError("comprehension crashed")
    env.monkeypatch.setattr(comprehension_mod, "run_comprehension_for_user", _crash)

    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]
    assert _run_next(env) == "completed"
    body = env.client.get(f"/api/analysis/comprehensive/runs/{run_id}").json()

    assert body["status"] == "completed"              # the RUN still completes
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["comprehension"]["status"] == "failed"
    assert body["ran"]["comprehension"] is False
    assert body["ran"]["deep_dive"] is True            # the others still ran
    assert body["summary"]["case_picture_ready"] is False
    # Degraded completion stays status=completed; quality reflects enrichment gaps.
    assert body["summary"]["quality"] in ("full", "partial", "minimal")
    assert body["error"] is None                      # soft note lives on summary only


# ── a fatal error before the steps → the run itself fails (recorded, not raised) ─
def test_fatal_error_marks_the_run_failed(env):
    _ok_comprehension(env.monkeypatch)
    env.monkeypatch.setattr(analysis_mod.settings, "analysis_job_max_attempts", 1)

    async def _boom_assemble(db, uid):
        raise RuntimeError("dossier build exploded")
    from app.routers import strategy as strat
    env.monkeypatch.setattr(strat, "_assemble_strategy", _boom_assemble)

    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]
    assert _run_next(env) == "failed"
    body = env.client.get(f"/api/analysis/comprehensive/runs/{run_id}").json()

    assert body["status"] == "failed"
    assert body["error"] and "exploded" in body["error"]
    assert body["finished_at"] and isinstance(body["total_seconds"], (int, float))

    async def _global_error():
        async with env.Session() as db:
            job = (
                await db.execute(
                    models.AnalysisJob.__table__.select().where(
                        models.AnalysisJob.run_id == uuid.UUID(run_id)
                    )
                )
            ).first()
            return job.last_error

    assert asyncio.run(_global_error()) == "Analysis attempt failed before completion."


def test_expired_running_lease_recovers_after_restart(env):
    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]

    async def _expire_and_recover():
        lease = await analysis_jobs.claim_one("worker-before-restart")
        assert lease is not None
        active = await analysis_jobs.mark_running(lease)
        assert active is not None
        async with env.Session() as db:
            job = (await db.execute(models.AnalysisJob.__table__.select())).first()
            await db.execute(
                models.AnalysisJob.__table__.update()
                .where(models.AnalysisJob.id == job.id)
                .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
            )
            await db.commit()
        assert await analysis_jobs.recover_and_sync() == 1

    asyncio.run(_expire_and_recover())
    body = env.client.get(f"/api/analysis/comprehensive/runs/{run_id}").json()
    assert body["status"] == "retryable"
    assert body["attempt_count"] == 1
    assert body["next_attempt_at"] is not None
    assert "lease expired" in body["error"].lower()


def test_restart_reconciliation_repairs_a_previously_committed_queue_transition(env):
    """Simulate a crash after queue recovery commits but before its RLS run repair."""
    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]

    async def _leave_split_brain_then_restart():
        lease = await analysis_jobs.claim_one("crash-window-worker")
        assert lease is not None
        active = await analysis_jobs.mark_running(lease)
        assert active is not None
        available = datetime.now(timezone.utc) + timedelta(seconds=30)
        async with env.Session() as db:
            job = (
                await db.execute(
                    models.AnalysisJob.__table__.select().where(
                        models.AnalysisJob.run_id == uuid.UUID(run_id)
                    )
                )
            ).first()
            await db.execute(
                models.AnalysisJob.__table__.update()
                .where(models.AnalysisJob.id == job.id)
                .values(
                    status="retryable",
                    available_at=available,
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                    last_error="simulated recovery commit",
                    run_synced_at=None,
                )
            )
            await db.commit()
        # The queue no longer qualifies as expired, so only the durable unsynced
        # marker can repair the still-running user-visible row on restart.
        assert await analysis_jobs.recover_and_sync() == 1
        assert await analysis_jobs.recover_and_sync() == 0

    asyncio.run(_leave_split_brain_then_restart())
    body = env.client.get(f"/api/analysis/comprehensive/runs/{run_id}").json()
    assert body["status"] == "retryable"
    assert body["error"] == "simulated recovery commit"
    assert body["lease_expires_at"] is None
    assert body["next_attempt_at"] is not None


def test_success_cannot_overwrite_a_concurrent_cancellation_request(env):
    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]

    async def _lease_and_start():
        lease = await analysis_jobs.claim_one("finish-cancel-worker")
        assert lease is not None
        active = await analysis_jobs.mark_running(lease)
        assert active is not None
        return active

    active = asyncio.run(_lease_and_start())
    assert env.client.post(f"/api/analysis/comprehensive/runs/{run_id}/cancel").status_code == 202
    status = asyncio.run(
        analysis_jobs.finish_success(
            active,
            {
                "ran": {"firm": True, "briefing": True, "deep_dive": True, "comprehension": True},
                "summary": {"conditions": 1, "case_picture_ready": True},
                "total_seconds": 2.5,
            },
        )
    )
    assert status == "cancelled"
    body = env.client.get(f"/api/analysis/comprehensive/runs/{run_id}").json()
    assert body["status"] == "cancelled"
    assert body["summary"] is None


def test_graceful_worker_shutdown_requeues_without_spending_an_attempt(env):
    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]

    async def _exercise_shutdown():
        lease = await analysis_jobs.claim_one("shutdown-worker")
        assert lease is not None
        stop = asyncio.Event()
        stop.set()

        async def _blocked_pipeline(*args, **kwargs):
            await asyncio.Event().wait()

        env.monkeypatch.setattr(crun, "run_comprehensive_job", _blocked_pipeline)
        env.monkeypatch.setattr(
            analysis_worker.freshness,
            "cached_effective_freshness",
            lambda: {"stale": False},
        )

        async def _fresh():
            return False

        env.monkeypatch.setattr(analysis_worker, "durable_kb_stale", _fresh)
        return await analysis_worker.process_lease(
            lease, "shutdown-worker", stop_event=stop
        )

    assert asyncio.run(_exercise_shutdown()) == "retryable"
    body = env.client.get(f"/api/analysis/comprehensive/runs/{run_id}").json()
    assert body["status"] == "retryable"
    assert body["attempt_count"] == 0
    assert "resume automatically" in body["error"]


def test_two_workers_cannot_claim_the_same_job(env):
    env.client.post("/api/analysis/comprehensive/start")

    async def _claim(worker_id):
        async with env.Session() as db:
            lease = await analysis_jobs.claim_next_job(db, worker_id)
            await db.commit()
            return lease

    async def _race():
        return await asyncio.gather(_claim("worker-a"), _claim("worker-b"))

    leases = asyncio.run(_race())
    assert sum(lease is not None for lease in leases) == 1


def test_queue_health_reports_worker_and_backlog(env):
    env.client.post("/api/analysis/comprehensive/start")

    async def _health():
        await analysis_jobs.worker_heartbeat("health-worker")
        return await analysis_jobs.queue_health()

    health = asyncio.run(_health())
    assert health["workers_alive"] == 1
    assert health["workers_stale"] == 0
    assert health["queued"] == 1
    assert health["running"] == 0
    assert health["retryable"] == 0
    assert health["expired_leases"] == 0
    assert health["unsynced_runs"] == 0
    assert health["failed_recent"] == 0
    assert health["retried_jobs"] == 0
    assert health["oldest_active_seconds"] >= 0
    assert health["status_counts"]["queued"] == 1


def test_persisted_stale_kb_signal_defers_without_consuming_attempt(env):
    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]
    _seed(
        env.Session,
        models.KBRefreshSignal(
            topic="38 CFR Title 38",
            status="open",
            reason="test update",
            kb_verified_as_of=datetime(2026, 7, 1).date(),
            detected_source_date=datetime(2026, 7, 2).date(),
            detail={},
        ),
    )
    assert _run_next(env) == "retryable"
    body = env.client.get(f"/api/analysis/comprehensive/runs/{run_id}").json()
    assert body["status"] == "retryable"
    assert body["attempt_count"] == 0
    assert "stale" in body["error"].lower()


def test_running_cancellation_is_observed_by_the_lease(env):
    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]

    async def _lease_and_start():
        lease = await analysis_jobs.claim_one("cancel-worker")
        assert lease is not None
        active = await analysis_jobs.mark_running(lease)
        assert active is not None
        return active

    active = asyncio.run(_lease_and_start())
    response = env.client.post(f"/api/analysis/comprehensive/runs/{run_id}/cancel")
    assert response.status_code == 202
    assert response.json()["cancel_requested"] is True
    state = asyncio.run(analysis_jobs.renew_lease(active))
    assert state.owned is True and state.cancel_requested is True


def test_legacy_complete_run_remains_readable_without_queue_metadata(env):
    legacy_id = uuid.uuid4()
    _seed(
        env.Session,
        models.AnalysisRun(
            id=legacy_id,
            user_id=UA,
            workspace_id=WS,
            status="complete",
            steps=crun.seed_steps(),
            ran={"firm": True, "briefing": True, "deep_dive": True, "comprehension": True},
            summary={
                "conditions": 1,
                "pathways": 1,
                "deep_dive_findings": 0,
                "new_findings": 0,
                "case_picture_ready": True,
            },
        ),
    )
    body = env.client.get(f"/api/analysis/comprehensive/runs/{legacy_id}").json()
    assert body["status"] == "complete"
    assert body["summary"]["case_picture_ready"] is True


# ── latest + history + per-user scoping ───────────────────────────────────────
def test_latest_and_history_and_user_scope(env):
    _ok_comprehension(env.monkeypatch)
    run_id = env.client.post("/api/analysis/comprehensive/start").json()["id"]

    latest = env.client.get("/api/analysis/comprehensive/latest").json()
    assert latest["id"] == run_id
    history = env.client.get("/api/analysis/comprehensive/runs").json()
    assert isinstance(history, list) and history[0]["id"] == run_id

    # UB owns no runs and must never see UA's run.
    env.current["uid"] = str(UB)
    assert env.client.get("/api/analysis/comprehensive/latest").json() is None
    assert env.client.get("/api/analysis/comprehensive/runs").json() == []
    assert env.client.get(f"/api/analysis/comprehensive/runs/{run_id}").status_code == 404


# ── intake benchmark: approximate per-file processing cost from doc timings ────
def test_intake_benchmark_reports_document_processing_span(env):
    async def _clear_seed():
        async with env.Session() as s:
            await s.execute(models.Document.__table__.delete())
            await s.commit()

    asyncio.run(_clear_seed())
    t0 = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)
    _seed(
        env.Session,
        models.Document(user_id=UA, filename="a.pdf", sha256="h1", size_bytes=1000,
                        status="ready", created_at=t0, updated_at=t0 + timedelta(seconds=5)),
        models.Document(user_id=UA, filename="b.pdf", sha256="h2", size_bytes=2000,
                        status="ready", created_at=t0 + timedelta(seconds=1),
                        updated_at=t0 + timedelta(seconds=10)),
        models.Document(user_id=UA, filename="c.pdf", sha256="h3", size_bytes=500,
                        status="failed", created_at=t0, updated_at=t0 + timedelta(seconds=2)),
    )
    b = env.client.get("/api/analysis/intake-benchmark").json()
    assert b["documents"] == 3
    assert b["ready"] == 2 and b["failed"] == 1 and b["processing"] == 0
    assert b["total_bytes"] == 3500
    # per-doc seconds: 5 + 9 (ready) + 2 (failed) = 16 raw compute.
    assert b["total_processing_seconds"] == pytest.approx(16.0, abs=0.5)
    # wall-clock: first upload (t0) → last ready (t0+10s) = 10s.
    assert b["wall_clock_seconds"] == pytest.approx(10.0, abs=0.5)
    assert b["avg_seconds_per_doc"] is not None
