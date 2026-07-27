"""Analysis Center endpoints (routers/analysis.py) on the SQLite harness:

  * GET  /analysis/case-picture     — cached whole-C-file picture, ready vs not_generated
  * POST /analysis/comprehensive    — orchestrate firm + briefing + forced deep dive +
                                       comprehension; ran-map + graceful sub-step failure
  * GET  /analysis/automation-status — what ran automatically + flag reflection

The firm / deep-dive run deterministically (no gateway needed); the LLM gateway,
the whole-C-file comprehension trigger, and — where a failure is being exercised —
the strategy deep-dive helper are monkeypatched so no live fleet is touched.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
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
from app.config import settings as app_settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.llm.gateway import gateway as _gateway  # noqa: E402
from app.routers import analysis as analysis_mod  # noqa: E402
from app.routers import strategy as strategy_mod  # noqa: E402

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
    models.User.__table__, models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__, models.EvidenceItem.__table__,
    models.ItfRecord.__table__, models.Document.__table__,
    models.KBCard.__table__, models.GamePlanFirmCache.__table__,
    models.GamePlanBriefingCache.__table__, models.CFilePictureCache.__table__,
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


def _picture(note: str = "PTSD noted") -> dict:
    """A build_case_picture-shaped payload (the documented keys) for cache seeding."""
    return {
        "timeline": [{"date": "2024-01-01", "kind": "decision", "label": "PTSD: granted",
                      "provenance": {"segment": 0}}],
        "condition_roster": [{
            "name": "PTSD", "diagnostic_code": "9411", "rating_percent": 50,
            "decision": "granted", "provenance": [{"segment": 0}],
            "sc_elements": {"current_diagnosis": {"present": True},
                            "nexus": {"present": True}, "in_service_event": {"present": True}},
            "missing_elements": [],
        }],
        "exam_inventory": [], "nexus_inventory": [], "decision_inventory": [],
        "contradictions": [], "coverage_gaps": [],
        "read_completeness": {"segments_total": 1, "segments_read": 1, "segments_failed": 0,
                              "pages_total": 1, "pages_read": 1, "pages_unreadable": 0,
                              "truncated": False, "complete": True, "note": note},
        "grounding_excerpts": [], "generated_from_segments": 1, "facts_hash": "seed",
    }


def _seed(Session, *objs) -> None:
    """Commit extra rows through a fresh session (before any request runs)."""
    async def _go():
        async with Session() as s:
            for o in objs:
                s.add(o)
            await s.commit()

    asyncio.run(_go())


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}", poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(UA)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=UA, email="a@e.test", password_hash="x", full_name="Alex V"),
                models.User(id=UB, email="b@e.test", password_hash="x", full_name="Blair O"),
                models.VeteranProfile(user_id=UA, current_combined_rating=50,
                                      service_periods=[], exposures={}),
                models.ClaimedCondition(id=C_PTSD, user_id=UA, name="PTSD",
                                        claim_type="direct", current_rating=50,
                                        target_rating=70, in_service_event="IED blast"),
                models.ClaimedCondition(user_id=UB, name="Back strain", claim_type="direct"),
                models.Document(user_id=UA, filename="seed.txt", sha256="seed-ready",
                                size_bytes=24, status="ready", text_content="Service record text"),
            ])
            # PTSD has all three §3.303 elements → readiness complete → file_now.
            s.add(models.EvidenceItem(user_id=UA, condition_id=C_PTSD, kind="diagnosis",
                                      title="Dx", status="have"))
            s.add(models.EvidenceItem(user_id=UA, condition_id=C_PTSD, kind="nexus_letter",
                                      title="Nexus", status="have"))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(analysis_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.current_workspace_id] = lambda: str(WS)
    app.dependency_overrides[deps.get_db] = _test_db
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current, Session=Session)


# ── GET /analysis/case-picture ────────────────────────────────────────────────
def test_case_picture_ready(env):
    ts = datetime(2026, 7, 11, 9, 30, tzinfo=timezone.utc)
    _seed(env.Session, models.CFilePictureCache(
        user_id=UA, facts_hash="fh1", payload=_picture("read in full"), created_at=ts))

    r = env.client.get("/api/analysis/case-picture")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ready"
    # SQLite drops the tz on round-trip (Postgres keeps it); assert the instant, not
    # the offset suffix.
    assert body["generated_at"].startswith("2026-07-11T09:30:00")
    assert body["picture"]["condition_roster"][0]["name"] == "PTSD"
    assert body["picture"]["read_completeness"]["note"] == "read in full"


def test_case_picture_not_generated(env):
    r = env.client.get("/api/analysis/case-picture")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"status": "not_generated", "generated_at": None, "picture": None}


def test_case_picture_is_read_only_and_user_scoped(env):
    # A GET never forces a build: an un-run picture stays not_generated (no side effect).
    assert env.client.get("/api/analysis/case-picture").json()["status"] == "not_generated"
    # UA has a picture; UB must never see it.
    _seed(env.Session, models.CFilePictureCache(
        user_id=UA, facts_hash="fh1", payload=_picture(),
        created_at=datetime(2026, 7, 11, tzinfo=timezone.utc)))
    assert env.client.get("/api/analysis/case-picture").json()["status"] == "ready"
    env.current["uid"] = str(UB)
    assert env.client.get("/api/analysis/case-picture").json()["status"] == "not_generated"


# ── POST /analysis/comprehensive ──────────────────────────────────────────────
def _boom(*a, **k):
    async def _raise():
        raise RuntimeError("gateway down")
    return _raise()


def test_comprehensive_runs_all_and_returns_ran_map(env, monkeypatch):
    # No live fleet: the gateway is dead (firm/briefing/deep-dive degrade to their
    # deterministic floors) and comprehension is stubbed to a successful run.
    monkeypatch.setattr(_gateway, "complete", _boom)

    async def _fake_comprehension(uid, wsid=None, *, force=False):
        assert force is True
        return True
    monkeypatch.setattr(comprehension_mod, "run_comprehension_for_user", _fake_comprehension)

    # A picture already exists → case_picture_ready reflects real availability.
    _seed(env.Session, models.CFilePictureCache(
        user_id=UA, facts_hash="fh1", payload=_picture(),
        created_at=datetime(2026, 7, 11, tzinfo=timezone.utc)))

    r = env.client.post("/api/analysis/comprehensive")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "complete"
    ran = body["ran"]
    assert set(ran) == {"firm", "briefing", "deep_dive", "comprehension"}
    # All four ran: the three strategy steps degrade deterministically, comprehension
    # returned True from the stub.
    assert ran["firm"] is True
    assert ran["briefing"] is True
    assert ran["deep_dive"] is True
    assert ran["comprehension"] is True

    summary = body["summary"]
    assert summary["conditions"] == 1            # UA's PTSD
    assert isinstance(summary["pathways"], int)
    assert isinstance(summary["deep_dive_findings"], int)
    assert isinstance(summary["new_findings"], int) and summary["new_findings"] >= 0
    assert summary["case_picture_ready"] is True


def test_comprehensive_survives_comprehension_failure(env, monkeypatch):
    monkeypatch.setattr(_gateway, "complete", _boom)

    async def _crash(uid, wsid=None, *, force=False):
        raise RuntimeError("comprehension crashed")
    monkeypatch.setattr(comprehension_mod, "run_comprehension_for_user", _crash)

    r = env.client.post("/api/analysis/comprehensive")
    assert r.status_code == 200, r.text          # a dead sub-step never 500s the call
    body = r.json()
    assert body["status"] == "complete"
    assert body["ran"]["comprehension"] is False  # recorded false, not raised
    # The other steps still ran.
    assert body["ran"]["briefing"] is True
    assert body["ran"]["deep_dive"] is True
    # No picture seeded and comprehension failed → not ready.
    assert body["summary"]["case_picture_ready"] is False


def test_comprehensive_survives_deep_dive_failure(env, monkeypatch):
    monkeypatch.setattr(_gateway, "complete", _boom)

    async def _ok(uid, wsid=None, *, force=False):
        return True
    monkeypatch.setattr(comprehension_mod, "run_comprehension_for_user", _ok)

    async def _dive_boom(*a, **k):
        raise RuntimeError("deep dive crashed")
    monkeypatch.setattr(strategy_mod, "_run_cached_deep_dive", _dive_boom)

    r = env.client.post("/api/analysis/comprehensive")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ran"]["deep_dive"] is False      # no generated_at → false
    assert body["summary"]["deep_dive_findings"] == 0
    assert body["summary"]["new_findings"] == 0
    assert body["ran"]["comprehension"] is True    # the others were unaffected


# ── GET /analysis/automation-status ───────────────────────────────────────────
def test_automation_status_reflects_state_and_flags(env, monkeypatch):
    monkeypatch.setattr(app_settings, "deep_dive_on_intake", True)
    monkeypatch.setattr(app_settings, "comprehension_on_intake", True)
    monkeypatch.setattr(app_settings, "intake_verify_default", True)
    monkeypatch.setattr(app_settings, "deep_dive_on_rule_change", True)
    monkeypatch.setattr(app_settings, "deep_dive_on_schedule", False)

    cp_ts = datetime(2026, 7, 11, 8, 0, tzinfo=timezone.utc)
    _seed(
        env.Session,
        # Latest deep dive + its proactive notification (one row).
        models.GamePlanFirmCache(user_id=UA, facts_hash="fh1", payload={
            "deep_dive": {"generated_at": "2026-07-10T12:00:00+00:00",
                          "findings": [{"key": "k1", "active": True}]},
            "notification": {"has_new_findings": True, "new_finding_keys": ["k1"]},
        }),
        # Whole-C-file picture available.
        models.CFilePictureCache(user_id=UA, facts_hash="fh1", payload=_picture(),
                                 created_at=cp_ts),
        # Doc A: a verify dispute (fields) + an OCR cross-read conflict (2 pages).
        models.Document(user_id=UA, filename="a.pdf", sha256="a", status="ready",
                        review_status="flagged", extracted={"review": {
                            "fields": [{"field_id": "0:rating_percent"}],
                            "crossread": {"pages_flagged": 2}}}),
        # Doc B: an OCR conflict only (1 page), no verify field dispute.
        models.Document(user_id=UA, filename="b.pdf", sha256="b", status="ready",
                        review_status="flagged", extracted={"review": {
                            "crossread": {"pages_flagged": 1}}}),
        # Doc C: clear — must not count anywhere.
        models.Document(user_id=UA, filename="c.pdf", sha256="c", status="ready",
                        review_status="clear", extracted={}),
    )

    body = env.client.get("/api/analysis/automation-status").json()

    assert body["deep_dive"] == {
        "last_run": "2026-07-10T12:00:00+00:00",
        "has_new_findings": True,
        "auto_on_intake": True,
    }
    assert body["comprehension"]["available"] is True
    assert body["comprehension"]["generated_at"].startswith("2026-07-11T08:00:00")
    assert body["comprehension"]["auto_on_intake"] is True
    # Only Doc A carries a verify field dispute; both A+B carry cross-read pages.
    assert body["verification"] == {"flagged_docs": 1, "enabled": True}
    assert body["cross_read"] == {"disagreement_pages": 3}
    assert body["review_queue"] == {"pending": 2}  # A + B flagged; C clear

    autos = {a["key"]: a for a in body["automations"]}
    assert set(autos) == {"deep_dive_on_intake", "comprehension_on_intake",
                          "intake_verify_default", "deep_dive_on_rule_change",
                          "deep_dive_on_schedule"}
    assert autos["deep_dive_on_intake"]["on"] is True
    assert autos["deep_dive_on_schedule"]["on"] is False
    # Every automation carries human-facing copy.
    for a in body["automations"]:
        assert a["label"] and a["plain"]


def test_automation_status_empty_account(env, monkeypatch):
    monkeypatch.setattr(app_settings, "deep_dive_on_intake", True)
    monkeypatch.setattr(app_settings, "comprehension_on_intake", False)
    monkeypatch.setattr(app_settings, "intake_verify_default", False)
    env.current["uid"] = str(UB)  # Blair has no picture, no firm cache, no flagged docs

    body = env.client.get("/api/analysis/automation-status").json()
    assert body["deep_dive"]["last_run"] is None
    assert body["deep_dive"]["has_new_findings"] is False
    assert body["deep_dive"]["auto_on_intake"] is True
    assert body["comprehension"]["available"] is False
    assert body["comprehension"]["generated_at"] is None
    assert body["comprehension"]["auto_on_intake"] is False
    assert body["verification"] == {"flagged_docs": 0, "enabled": False}
    assert body["cross_read"] == {"disagreement_pages": 0}
    assert body["review_queue"] == {"pending": 0}
    assert len(body["automations"]) == 5
