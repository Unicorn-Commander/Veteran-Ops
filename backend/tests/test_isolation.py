"""WAVE9 security M1 — defense-in-depth tenant isolation. The SQLite harness has NO
RLS, so a cross-user 404 here proves the EXPLICIT user_id filter (not RLS) guards
conditions/evidence/checklist against IDOR. If these pass, isolation survives an RLS
misconfiguration in production.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
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
from app.routers import checklist as checklist_mod  # noqa: E402
from app.routers import conditions as conditions_mod  # noqa: E402
from app.routers import evidence as evidence_mod  # noqa: E402

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
    models.User.__table__, models.ClaimedCondition.__table__,
    models.EvidenceItem.__table__, models.ChecklistItem.__table__,
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
COND_B = uuid.UUID("00000000-0000-0000-0000-0000000000c1")   # owned by B
EV_B = uuid.UUID("00000000-0000-0000-0000-0000000000e1")     # owned by B
CHK_B = uuid.UUID("00000000-0000-0000-0000-0000000000f1")    # owned by B


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'iso.db'}", poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(UA)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=UA, email="a@e.test", password_hash="x", full_name="A"),
                models.User(id=UB, email="b@e.test", password_hash="x", full_name="B"),
            ])
            await s.commit()
            s.add(models.ClaimedCondition(id=COND_B, user_id=UB, name="B's PTSD",
                                          claim_type="direct"))
            await s.commit()
            s.add(models.EvidenceItem(id=EV_B, user_id=UB, condition_id=COND_B,
                                      kind="diagnosis", title="B's Dx", status="have"))
            s.add(models.ChecklistItem(id=CHK_B, user_id=UB, condition_id=COND_B,
                                       text="B's task", category="evidence"))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    # Each router carries its own prefix (/conditions, /checklist; evidence is flat)
    # — mount all at /api exactly like main.py.
    app.include_router(conditions_mod.router, prefix="/api")
    app.include_router(evidence_mod.router, prefix="/api")
    app.include_router(checklist_mod.router, prefix="/api")

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
        # Caller is A throughout; every target row belongs to B.
        yield SimpleNamespace(client=client, current=current)


def test_cannot_read_or_mutate_another_users_condition(env):
    c = env.client
    assert c.get(f"/api/conditions/{COND_B}").status_code == 404
    assert c.patch(f"/api/conditions/{COND_B}", json={"name": "hijacked"}).status_code == 404
    assert c.delete(f"/api/conditions/{COND_B}").status_code == 404
    assert c.get(f"/api/conditions/{COND_B}/gaps").status_code == 404
    # A's own list never shows B's condition.
    assert env.client.get("/api/conditions").json() == []


def test_cannot_read_or_mutate_another_users_evidence(env):
    c = env.client
    # List evidence under B's condition → 404 (condition not A's).
    assert c.get(f"/api/conditions/{COND_B}/evidence").status_code == 404
    assert c.patch(f"/api/evidence/{EV_B}", json={"status": "need"}).status_code == 404
    assert c.delete(f"/api/evidence/{EV_B}").status_code == 404


def test_cannot_mutate_another_users_checklist(env):
    c = env.client
    assert c.patch(f"/api/checklist/{CHK_B}", json={"done": True}).status_code == 404
    assert c.delete(f"/api/checklist/{CHK_B}").status_code == 404
    # A's checklist list is empty (B's item never leaks).
    assert env.client.get("/api/checklist").json() == []
