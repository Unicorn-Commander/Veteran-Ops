"""Canonical VA reconciliation — pure matching engine (no DB) + the
POST /va/reconcile endpoint on the in-memory-ish SQLite harness.

The pure tests pin the normalizer + matching rules; the endpoint tests prove
dry-run writes NOTHING and apply persists current_rating / va_status / combined
rating (and, with create_new, creates the unmatched). Legal lane: reconcile only
sets what the VA data says.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.va.reconcile import (
    ClaimedRef,
    VaCondition,
    _norm,
    reconcile,
)

# ═══ Pure engine (no DB, no network) ═════════════════════════════════════════


def test_norm_strips_parenthetical_history_and_whitespace():
    assert _norm("  Chronic   Fatigue  Syndrome ") == "chronic fatigue syndrome"
    assert _norm("GERD (claimed as acid reflux)") == "gerd"
    assert _norm("History of hypertension") == "hypertension"
    assert _norm("history of  Lumbar Strain (claimed as back pain)") == "lumbar strain"
    assert _norm(None) == ""
    assert _norm("PTSD.") == "ptsd"


def test_exact_match_sets_status_and_rating():
    claimed = [ClaimedRef(id="c1", name="PTSD", current_rating=None, va_status="unknown")]
    plan = reconcile(
        70,
        [VaCondition(name="ptsd", percent=50, disposition="service_connected")],
        claimed,
    )
    assert plan.combined_rating == 70
    assert not plan.unmatched
    m = plan.matched[0]
    assert (m.condition_id, m.set_current_rating, m.set_va_status, m.changed) == (
        "c1", 50, "service_connected", True,
    )


def test_containment_match_but_short_tokens_do_not_over_match():
    claimed = [
        ClaimedRef(id="c1", name="Chronic Fatigue Syndrome"),
        ClaimedRef(id="knee", name="Knee"),
    ]
    # "chronic fatigue" is contained in the claimed name and is >= 6 chars → match.
    plan = reconcile(
        None,
        [
            VaCondition(name="Chronic Fatigue", percent=40, disposition="service_connected"),
            VaCondition(name="Left knee strain", percent=10, disposition="service_connected"),
        ],
        claimed,
    )
    matched = {m.condition_id for m in plan.matched}
    assert "c1" in matched                       # containment hit
    assert "knee" not in matched                 # "knee" (4 chars) must NOT over-match
    assert any(u.name == "Left knee strain" for u in plan.unmatched)


def test_exact_wins_over_containment_and_one_claimed_per_va():
    # Two claimed: exact "diabetes" and a longer "diabetes mellitus type 2".
    claimed = [
        ClaimedRef(id="long", name="Diabetes Mellitus Type 2"),
        ClaimedRef(id="exact", name="Diabetes"),
    ]
    plan = reconcile(
        None,
        [VaCondition(name="Diabetes", percent=20, disposition="service_connected")],
        claimed,
    )
    assert len(plan.matched) == 1
    assert plan.matched[0].condition_id == "exact"  # exact beats containment


def test_denied_and_pending_leave_rating_unchanged():
    claimed = [
        ClaimedRef(id="d", name="Sleep Apnea", current_rating=50, va_status="unknown"),
        ClaimedRef(id="p", name="Migraines", current_rating=None, va_status="unknown"),
    ]
    plan = reconcile(
        None,
        [
            VaCondition(name="Sleep Apnea", percent=None, disposition="denied"),
            VaCondition(name="Migraines", percent=30, disposition="pending"),
        ],
        claimed,
    )
    by_id = {m.condition_id: m for m in plan.matched}
    # denial never rewrites a rating
    assert by_id["d"].set_current_rating is None
    assert by_id["d"].set_va_status == "denied" and by_id["d"].changed is True
    # pending with a percent still does NOT set a rating (only service_connected does)
    assert by_id["p"].set_current_rating is None
    assert by_id["p"].set_va_status == "pending" and by_id["p"].changed is True


def test_no_change_when_values_already_match():
    claimed = [ClaimedRef(id="c1", name="Tinnitus", current_rating=10,
                          va_status="service_connected")]
    plan = reconcile(
        None,
        [VaCondition(name="Tinnitus", percent=10, disposition="service_connected")],
        claimed,
    )
    assert plan.matched[0].changed is False


# ═══ Endpoint (SQLite harness) ═══════════════════════════════════════════════

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import deps, models  # noqa: E402
from app.db import Base  # noqa: E402
from app.routers import va as va_mod  # noqa: E402


@compiles(PGUUID, "sqlite")
def _pg_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


TABLES = [
    models.User.__table__,
    models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__,
    models.AuditLog.__table__,
]

for _t in TABLES:  # gen_random_uuid() → client-side uuid4 (idempotent)
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())

USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
COND_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")
COND_TINNITUS = uuid.UUID("00000000-0000-0000-0000-000000000012")


@pytest.fixture()
def env(tmp_path):
    db_path = tmp_path / "reconcile_test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=TABLES)
        async with Session() as s:
            s.add_all(
                [
                    models.User(id=USER_A, email="alex@example.com",
                                password_hash="x", full_name="Alex Veteran"),
                    models.ClaimedCondition(id=COND_PTSD, user_id=USER_A, name="PTSD",
                                            claim_type="direct"),
                    models.ClaimedCondition(id=COND_TINNITUS, user_id=USER_A,
                                            name="Tinnitus", claim_type="increase",
                                            current_rating=10),
                ]
            )
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(va_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps.current_user_id] = lambda: str(USER_A)
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, Session=Session)


def _run(coro):
    import asyncio

    return asyncio.run(coro)


async def _snapshot(env) -> dict:
    async with env.Session() as s:
        rows = (
            await s.execute(
                select(models.ClaimedCondition).where(
                    models.ClaimedCondition.user_id == USER_A)
            )
        ).scalars().all()
        conds = {r.name: (r.current_rating, r.va_status) for r in rows}
        prof = (
            await s.execute(
                select(models.VeteranProfile).where(
                    models.VeteranProfile.user_id == USER_A)
            )
        ).scalar_one_or_none()
        return {"conds": conds, "combined": prof.current_combined_rating if prof else None}


def _body(**kw):
    base = {
        "combined_rating": 80,
        "conditions": [
            {"name": "ptsd", "percent": 70, "disposition": "service_connected"},
            {"name": "Chronic fatigue syndrome", "percent": None, "disposition": "denied"},
        ],
        "create_new": False,
        "apply": False,
    }
    base.update(kw)
    return base


def test_dry_run_writes_nothing(env):
    before = _run(_snapshot(env))
    resp = env.client.post("/api/va/reconcile", json=_body(apply=False, create_new=True))
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["applied"] is False
    assert data["combined_rating"] == 80
    m = {x["va_name"]: x for x in data["matched"]}
    assert m["ptsd"]["condition_id"] == str(COND_PTSD)
    assert m["ptsd"]["set_current_rating"] == 70
    assert m["ptsd"]["set_va_status"] == "service_connected"
    assert m["ptsd"]["changed"] is True
    # Chronic fatigue syndrome has no claimed condition → unmatched, created=false
    # even though create_new=true, because apply=false.
    unm = data["unmatched"]
    assert unm[0]["name"] == "Chronic fatigue syndrome"
    assert unm[0]["created"] is False

    # NOTHING changed on disk.
    assert _run(_snapshot(env)) == before


def test_apply_sets_ratings_status_combined_and_creates(env):
    resp = env.client.post("/api/va/reconcile", json=_body(apply=True, create_new=True))
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["applied"] is True
    assert data["unmatched"][0]["created"] is True

    after = _run(_snapshot(env))
    assert after["combined"] == 80
    assert after["conds"]["PTSD"] == (70, "service_connected")
    # denial does not rewrite a rating, but a new condition was created from the
    # unmatched VA condition with its disposition.
    assert after["conds"]["Chronic fatigue syndrome"] == (None, "denied")

    audits = _run(_fetch_audit(env, "va.reconcile"))
    assert audits and audits[0]["created"] == 1 and audits[0]["matched"] == 1


def test_apply_without_create_new_leaves_unmatched_uncreated(env):
    resp = env.client.post("/api/va/reconcile", json=_body(apply=True, create_new=False))
    assert resp.status_code == 200, resp.text
    assert resp.json()["unmatched"][0]["created"] is False
    after = _run(_snapshot(env))
    assert "Chronic fatigue syndrome" not in after["conds"]
    assert after["conds"]["PTSD"] == (70, "service_connected")


def test_null_combined_leaves_profile_unchanged(env):
    resp = env.client.post(
        "/api/va/reconcile",
        json={"combined_rating": None, "conditions": [], "apply": True},
    )
    assert resp.status_code == 200
    assert resp.json()["combined_rating"] is None
    assert _run(_snapshot(env))["combined"] is None


def test_requires_auth():
    app = FastAPI()
    app.include_router(va_mod.router, prefix="/api")
    client = TestClient(app)
    assert client.post("/api/va/reconcile", json=_body()).status_code in (401, 403)


async def _fetch_audit(env, action: str) -> list[dict]:
    async with env.Session() as s:
        rows = (
            await s.execute(
                select(models.AuditLog).where(models.AuditLog.action == action)
            )
        ).scalars().all()
        return [r.meta or {} for r in rows]
