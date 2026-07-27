"""C&P exam companion tests (WAVE5 F5) — no Postgres, no network, no LLM.

Runs the real cp router against in-memory SQLite: Postgres-only column types get
compile shims (UUID→CHAR(36), JSONB→JSON, pgvector Vector→TEXT), gen_random_uuid()
server defaults become client-side uuid4, and auth/db are dependency-overridden.
RLS can't run on SQLite — cross-user 404s exercise the router's explicit user_id
defense-in-depth filter that backs the Postgres policy. Retrieval degrades to the
KB keyword path (the gateway/embeddings are never reachable), so the seeded
rating_criteria card is matched deterministically by name + diagnostic code.
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
from app.routers import cp as cp_mod  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover — pgvector always present with the app
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
    models.ClaimedCondition.__table__,
    models.KBCard.__table__,
    models.AuditLog.__table__,
]

for _t in _TABLES:  # gen_random_uuid() → client-side uuid4 (idempotent)
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())


# ── Seed identities + conditions ─────────────────────────────────────────────
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")

COND_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")      # A, DC 9411 (seeded card)
COND_SLEEP = uuid.UUID("00000000-0000-0000-0000-000000000012")     # A, no DC / no card
COND_B = uuid.UUID("00000000-0000-0000-0000-000000000021")         # B — must be invisible to A

# A minimal rating_criteria card for DC 9411 (mirrors the real KB card shape).
_PTSD_CARD_TIERS = [
    {"percent": 0, "criteria": "Diagnosis established but symptoms not severe enough to interfere with functioning."},
    {"percent": 30, "criteria": "Occupational and social impairment with occasional decrease in work efficiency."},
    {"percent": 70, "criteria": "Occupational and social impairment with deficiencies in most areas."},
    {"percent": 100, "criteria": "Total occupational and social impairment."},
]


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'cp_test.db'}",
        poolclass=NullPool,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(USER_A)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all(
                [
                    models.User(id=USER_A, email="alex@example.com",
                                password_hash="x", full_name="Alex Veteran"),
                    models.User(id=USER_B, email="blair@example.com",
                                password_hash="x", full_name="Blair Other"),
                    models.ClaimedCondition(
                        id=COND_PTSD, user_id=USER_A, name="PTSD",
                        diagnostic_code="9411", claim_type="direct",
                        body_system="mental",
                    ),
                    models.ClaimedCondition(
                        id=COND_SLEEP, user_id=USER_A, name="Sleep apnea",
                        claim_type="secondary",
                    ),
                    # Named to fuzzy-match "PTSD" — must NEVER surface for user A.
                    models.ClaimedCondition(
                        id=COND_B, user_id=USER_B, name="PTSD (other veteran)",
                        diagnostic_code="9411", claim_type="direct",
                    ),
                    models.KBCard(
                        card_type="rating_criteria",
                        title="PTSD (mental disorders) — General Rating Formula",
                        body_system="mental",
                        diagnostic_code="9411",
                        source="38 CFR §4.130, DC 9411",
                        content="PTSD rating criteria under the general rating formula for mental disorders.",
                        data={"tiers": _PTSD_CARD_TIERS},
                    ),
                ]
            )
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(cp_mod.router, prefix="/api")

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


# ═══ GET /cp/conditions ══════════════════════════════════════════════════════
def test_conditions_lists_only_callers_conditions(env):
    rows = env.client.get("/api/cp/conditions").json()
    assert isinstance(rows, list)
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {str(COND_PTSD), str(COND_SLEEP)}       # A's two only
    assert str(COND_B) not in by_id                              # never B's
    ptsd = by_id[str(COND_PTSD)]
    assert ptsd["name"] == "PTSD"
    assert ptsd["diagnostic_code"] == "9411"
    assert ptsd["claim_type"] == "direct"

    # User B sees only their own condition.
    env.current["uid"] = str(USER_B)
    rows_b = env.client.get("/api/cp/conditions").json()
    assert {r["id"] for r in rows_b} == {str(COND_B)}


# ═══ GET /cp/{id} — cross-user isolation ═════════════════════════════════════
def test_companion_404_for_another_users_condition(env):
    env.current["uid"] = str(USER_B)
    assert env.client.get(f"/api/cp/{COND_PTSD}").status_code == 404  # A's cond, B asks

    env.current["uid"] = str(USER_A)
    assert env.client.get(f"/api/cp/{COND_B}").status_code == 404      # B's cond, A asks
    assert env.client.get(f"/api/cp/{uuid.uuid4()}").status_code == 404


# ═══ GET /cp/{id} — grounded assembly ════════════════════════════════════════
def test_companion_assembles_criteria_dbq_and_guidance(env):
    body = env.client.get(f"/api/cp/{COND_PTSD}").json()

    assert body["condition"]["id"] == str(COND_PTSD)
    assert body["condition"]["diagnostic_code"] == "9411"

    # Rating criteria grounded in the seeded KB card for DC 9411.
    tiers = body["rating_criteria"]
    assert [t["percent"] for t in tiers] == [0, 30, 70, 100]
    for t in tiers:
        assert isinstance(t["criteria"], list) and t["criteria"] and t["criteria"][0]
    assert "Total occupational and social impairment." in tiers[-1]["criteria"]

    # DBQ mapped from the authored catalog (mental → a mental-disorders DBQ).
    assert body["dbq"]  # a form was mapped
    assert isinstance(body["dbq"], str)

    # The fixed educational content is always present and non-empty.
    for key in ("what_to_expect", "how_to_describe", "dos", "donts"):
        assert isinstance(body[key], list) and len(body[key]) >= 3
    assert body["disclaimer"]

    # Legal-lane guarantees: honest framing + the "never exaggerate" rule.
    assert any("worst" in s.lower() for s in body["how_to_describe"])
    assert any("exaggerat" in s.lower() for s in body["donts"])


def test_companion_unknown_dc_returns_valid_payload_with_empty_criteria(env):
    body = env.client.get(f"/api/cp/{COND_SLEEP}").json()
    assert body["condition"]["id"] == str(COND_SLEEP)
    assert body["condition"]["diagnostic_code"] is None
    # No DC and no matching rating_criteria card → empty tiers, but still valid.
    assert body["rating_criteria"] == []
    # Everything else still assembles.
    assert len(body["what_to_expect"]) >= 3
    assert len(body["dos"]) >= 3
    assert len(body["donts"]) >= 3
    assert body["disclaimer"]


# ═══ Auth posture ════════════════════════════════════════════════════════════
def test_requires_auth():
    """Without overrides, every endpoint 401/403s (bearer required)."""
    app = FastAPI()
    app.include_router(cp_mod.router, prefix="/api")
    client = TestClient(app)
    assert client.get("/api/cp/conditions").status_code in (401, 403)
    assert client.get(f"/api/cp/{COND_PTSD}").status_code in (401, 403)
