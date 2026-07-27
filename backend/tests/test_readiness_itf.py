"""Wave-5 readiness-score + ITF-reminder tests — no Postgres, no network.

Pure tests exercise readiness/score.py directly (per-claim-type denominators,
band thresholds, and that the informational at-schedular-maximum item is NOT
counted as a missing element). Endpoint tests mount the real readiness + itf
routers on the same SQLite harness test_api_documents/test_decoder use (PG types
shimmed, gen_random_uuid()→uuid4, RLS not exercised — cross-user 404s ride the
routers' explicit user_id filters). ITF countdown expectations are computed from
the actual `date.today()` so the tests stay hermetic across calendar time.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.decoder.deadline import add_one_year
from app.readiness.score import band_for, overall_readiness, score_condition

_FULL_DIRECT = [
    {"kind": "diagnosis", "status": "have"},
    {"kind": "service_record", "status": "have"},
    {"kind": "nexus_letter", "status": "have"},
    {"kind": "treatment_record", "status": "have"},  # satisfies continuity
]


# ═══════════════════════════════════════════════════════════════════════════
# 1. readiness/score.py — pure
# ═══════════════════════════════════════════════════════════════════════════
def test_direct_claim_denominator_and_empty_is_zero():
    s = score_condition({"id": "1", "name": "PTSD", "claim_type": "direct"}, [])
    assert s["total"] == 4
    assert s["score"] == 0
    assert s["band"] == "early"
    assert s["satisfied"] == 0
    assert len(s["missing"]) == 4


def test_direct_claim_fully_evidenced_is_100():
    s = score_condition(
        {"id": "1", "name": "PTSD", "claim_type": "direct",
         "in_service_event": "combat", "nexus_notes": "linked"},
        _FULL_DIRECT,
    )
    assert s["score"] == 100
    assert s["band"] == "complete"
    assert s["missing"] == []


@pytest.mark.parametrize(
    "claim_type,total",
    [("direct", 4), ("secondary", 3), ("presumptive", 2), ("increase", 2)],
)
def test_denominator_per_claim_type(claim_type, total):
    s = score_condition({"id": "1", "name": "X", "claim_type": claim_type}, [])
    assert s["total"] == total


def test_schedular_maximum_info_item_not_counted_as_missing():
    # Tinnitus at its 10% ceiling, WITH diagnosis + treatment evidence: both
    # increase elements satisfied → 100, and the "at schedular maximum"
    # informational gap must NOT drag the score down or appear in `missing`.
    from app.kb.store import cached_max_ratings

    s = score_condition(
        {"id": "2", "name": "Tinnitus", "claim_type": "increase",
         "diagnostic_code": "6260", "current_rating": 10},
        [{"kind": "diagnosis", "status": "have"}, {"kind": "treatment_record", "status": "have"}],
        None,
        cached_max_ratings(),
    )
    assert s["score"] == 100
    assert s["missing"] == []
    assert not any("schedular maximum" in m.lower() for m in s["missing"])


def test_band_thresholds():
    assert band_for(0) == "early"
    assert band_for(33) == "early"
    assert band_for(34) == "building"
    assert band_for(66) == "building"
    assert band_for(67) == "strong"
    assert band_for(99) == "strong"
    assert band_for(100) == "complete"


def test_overall_average_and_empty():
    empty = overall_readiness([])
    assert empty["score"] == 0 and empty["conditions_scored"] == 0
    avg = overall_readiness([{"score": 100}, {"score": 0}])
    assert avg["score"] == 50 and avg["conditions_scored"] == 2 and avg["band"] == "building"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Endpoint tests — real readiness + itf routers, SQLite harness
# ═══════════════════════════════════════════════════════════════════════════
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
from app.db import Base  # noqa: E402
from app.routers import itf as itf_mod  # noqa: E402
from app.routers import readiness as readiness_mod  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover
    Vector = None


@compiles(PGUUID, "sqlite")
def _pg_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


if Vector is not None:
    @compiles(Vector, "sqlite")
    def _vector_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
        return "TEXT"


_TABLES = [
    models.User.__table__,
    models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__,
    models.EvidenceItem.__table__,
    models.ItfRecord.__table__,
    models.AuditLog.__table__,
]

for _t in _TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())


USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
COND_FULL = uuid.UUID("00000000-0000-0000-0000-00000000c001")
COND_EMPTY = uuid.UUID("00000000-0000-0000-0000-00000000c002")


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'rdy.db'}", poolclass=NullPool
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(USER_A)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=USER_A, email="a@x.com", password_hash="x", full_name="A"),
                models.User(id=USER_B, email="b@x.com", password_hash="x", full_name="B"),
                models.ClaimedCondition(
                    id=COND_FULL, user_id=USER_A, name="PTSD", claim_type="direct",
                    in_service_event="combat", nexus_notes="linked",
                ),
                models.ClaimedCondition(
                    id=COND_EMPTY, user_id=USER_A, name="Back", claim_type="direct",
                ),
            ])
            # Full evidence on COND_FULL → 100; nothing on COND_EMPTY → 0.
            for kind in ("diagnosis", "service_record", "nexus_letter", "treatment_record"):
                s.add(models.EvidenceItem(
                    user_id=USER_A, condition_id=COND_FULL, kind=kind,
                    title=kind, status="have",
                ))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(readiness_mod.router, prefix="/api")
    app.include_router(itf_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current)


def test_readiness_overall_and_per_condition(env):
    body = env.client.get("/api/readiness").json()
    assert body["overall"]["conditions_scored"] == 2
    assert body["overall"]["score"] == 50  # (100 + 0) / 2
    by_name = {c["name"]: c for c in body["conditions"]}
    assert by_name["PTSD"]["score"] == 100 and by_name["PTSD"]["missing"] == []
    assert by_name["Back"]["score"] == 0 and len(by_name["Back"]["missing"]) == 4
    assert body["disclaimer"]


def test_readiness_isolated_per_user(env):
    env.current["uid"] = str(USER_B)  # B has no conditions
    body = env.client.get("/api/readiness").json()
    assert body["overall"]["conditions_scored"] == 0
    assert body["conditions"] == []


def test_itf_create_list_countdown_and_delete(env):
    # A recent ITF (within the last year) → not expired, is the active one.
    filed = date.today() - timedelta(days=30)
    created = env.client.post(
        "/api/itf", json={"type": "compensation", "filed_date": filed.isoformat()}
    ).json()
    assert created["deadline"] == add_one_year(filed).isoformat()
    assert created["expired"] is False
    assert created["days_remaining"] > 0

    # An old ITF (2+ years ago) → expired.
    old = date.today() - timedelta(days=800)
    env.client.post("/api/itf", json={"type": "pension", "filed_date": old.isoformat()})

    body = env.client.get("/api/itf").json()
    assert len(body["records"]) == 2
    assert body["active"] is not None and body["active"]["type"] == "compensation"
    assert any(r["expired"] for r in body["records"])
    assert body["disclaimer"]

    # Delete the active one → 204, gone.
    assert env.client.delete(f"/api/itf/{created['id']}").status_code == 204
    after = env.client.get("/api/itf").json()
    assert len(after["records"]) == 1


def test_itf_all_expired_active_is_none(env):
    old = date.today() - timedelta(days=800)
    env.client.post("/api/itf", json={"type": "compensation", "filed_date": old.isoformat()})
    body = env.client.get("/api/itf").json()
    assert body["active"] is None


def test_itf_cross_user_isolation(env):
    filed = date.today() - timedelta(days=10)
    created = env.client.post(
        "/api/itf", json={"type": "compensation", "filed_date": filed.isoformat()}
    ).json()
    env.current["uid"] = str(USER_B)
    # B can't see A's record, and can't delete it (404).
    assert env.client.get("/api/itf").json()["records"] == []
    assert env.client.delete(f"/api/itf/{created['id']}").status_code == 404
