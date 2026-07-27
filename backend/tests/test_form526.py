"""WAVE6 F1 — 21-526EZ application-packet assembly tests. No Postgres, no network.

Endpoint tests mount the real form526 router on the same SQLite harness the other
DB-reading routers use (PG types shimmed, gen_random_uuid()→uuid4, pgvector
Vector→TEXT so create_all can compile the models module; RLS not exercised —
cross-user isolation rides the router's explicit user_id filter that backs the
Postgres policy). ITF countdown expectations are computed from the actual
date.today() so the test stays hermetic across calendar time.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
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
from app.db import Base  # noqa: E402
from app.routers import form526 as form526_mod  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover
    Vector = None


# ── SQLite shims (test-only; the app itself always runs on Postgres) ─────────
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
COND_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")   # A, has evidence
COND_SLEEP = uuid.UUID("00000000-0000-0000-0000-000000000012")  # A, secondary→PTSD, no evidence
COND_B = uuid.UUID("00000000-0000-0000-0000-000000000021")      # B


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / '526.db'}", poolclass=NullPool
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(USER_A)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=USER_A, email="alex@example.com",
                            password_hash="x", full_name="Alex Veteran"),
                models.User(id=USER_B, email="blair@example.com",
                            password_hash="x", full_name="Blair Other"),
                models.VeteranProfile(
                    user_id=USER_A,
                    service_periods=[
                        {"branch": "Army", "component": "Active",
                         "start_date": "2004-01-15", "end_date": "2008-06-30",
                         "discharge_character": "Honorable"},
                    ],
                    combat_service=True,
                    exposures={"burn_pits": True, "agent_orange": False,
                               "other": "JP-8 jet fuel", "locations": ["Balad, Iraq"]},
                    state="SC",
                ),
                models.ClaimedCondition(
                    id=COND_PTSD, user_id=USER_A, name="PTSD", claim_type="direct",
                    diagnostic_code="9411", current_rating=50,
                    onset_date=date(2007, 5, 1), in_service_event="IED blast",
                ),
                models.ClaimedCondition(
                    id=COND_SLEEP, user_id=USER_A, name="Sleep apnea",
                    claim_type="secondary", secondary_to=COND_PTSD,
                ),
                # User B's condition — must NEVER surface for A.
                models.ClaimedCondition(
                    id=COND_B, user_id=USER_B, name="Back strain", claim_type="direct",
                ),
            ])
            # PTSD has one 'have' and one 'need'; sleep apnea has nothing.
            s.add(models.EvidenceItem(
                user_id=USER_A, condition_id=COND_PTSD, kind="diagnosis",
                title="VA PTSD diagnosis 2019", status="have",
            ))
            s.add(models.EvidenceItem(
                user_id=USER_A, condition_id=COND_PTSD, kind="nexus_letter",
                title="Nexus letter (requested)", status="need",
            ))
            # An active ITF (recent) + an expired one → the recent must be chosen.
            s.add(models.ItfRecord(
                user_id=USER_A, type="compensation",
                filed_date=date.today() - timedelta(days=30),
            ))
            s.add(models.ItfRecord(
                user_id=USER_A, type="pension",
                filed_date=date.today() - timedelta(days=800),
            ))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(form526_mod.router, prefix="/api")

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


def test_full_assembly(env):
    body = env.client.get("/api/form526").json()

    # Veteran identity.
    assert body["veteran"]["name"] == "Alex Veteran"
    assert body["veteran"]["email"] == "alex@example.com"
    assert body["prepared_on"] is None

    # Service: periods pass through, combat flag, humanized exposures.
    svc = body["service"]
    assert svc["combat"] is True
    assert len(svc["periods"]) == 1 and svc["periods"][0]["branch"] == "Army"
    assert "Burn pits" in svc["exposures"]
    assert "Agent Orange" not in svc["exposures"]  # falsy flag dropped
    assert "JP-8 jet fuel" in svc["exposures"]      # free-text `other`
    assert "Balad, Iraq" in svc["exposures"]        # locations list

    # Contentions (ordered by created_at): PTSD then Sleep apnea.
    conts = {c["name"]: c for c in body["contentions"]}
    assert len(body["contentions"]) == 2
    ptsd = conts["PTSD"]
    assert ptsd["diagnostic_code"] == "9411"
    assert ptsd["current_rating"] == 50
    assert ptsd["onset_date"] == "2007-05-01"
    assert ptsd["in_service_event"] == "IED blast"
    assert [e["title"] for e in ptsd["evidence_have"]] == ["VA PTSD diagnosis 2019"]
    assert [e["kind"] for e in ptsd["evidence_needed"]] == ["nexus_letter"]

    sleep = conts["Sleep apnea"]
    assert sleep["claim_type"] == "secondary"
    assert sleep["secondary_to_name"] == "PTSD"   # resolved, not a UUID
    assert sleep["evidence_have"] == []
    assert sleep["evidence_needed"] == []

    # Completeness: 2 conditions, 1 with evidence, 1 missing.
    comp = body["completeness"]
    assert comp == {"conditions": 2, "with_evidence": 1, "missing_evidence": 1}

    # ITF: soonest-active (the recent compensation one, not the expired pension).
    assert body["itf"] is not None
    assert body["itf"]["type"] == "compensation"
    assert body["itf"]["expired"] is False
    assert body["itf"]["days_remaining"] > 0

    # Legal lane present.
    assert body["guidance"] and body["disclaimer"] and body["source_note"]
    assert "never files" in body["disclaimer"].lower()


def test_empty_account(env):
    # A fresh user with no profile, conditions, or ITF still gets a valid 200.
    empty_uid = uuid.uuid4()
    # Insert a bare user row via the app's own session dependency isn't exposed,
    # so reuse USER_B (who has a condition) is wrong — instead point at a user
    # with truly nothing: create one through the running DB.
    env.current["uid"] = str(empty_uid)
    # No user row exists → name/email fall back to "", everything else empties.
    body = env.client.get("/api/form526").json()
    assert body["veteran"]["name"] == ""
    assert body["contentions"] == []
    assert body["completeness"] == {
        "conditions": 0, "with_evidence": 0, "missing_evidence": 0,
    }
    assert body["itf"] is None
    assert body["service"]["periods"] == []
    assert body["service"]["exposures"] == []
    assert body["guidance"] and body["disclaimer"]


def test_cross_user_isolation(env):
    # User B sees ONLY their own condition — never A's PTSD/Sleep apnea/ITF.
    env.current["uid"] = str(USER_B)
    body = env.client.get("/api/form526").json()
    names = {c["name"] for c in body["contentions"]}
    assert names == {"Back strain"}
    assert "PTSD" not in names
    assert body["completeness"]["conditions"] == 1
    assert body["itf"] is None  # B has no ITF; A's is not visible
    assert body["veteran"]["name"] == "Blair Other"
