"""Credit ledger, Stripe webhook, and grant-pool tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
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
from app.crediting import CreditConfig, adjust_credits  # noqa: E402
from app.db import Base  # noqa: E402
from app.routers import credits as credits_mod  # noqa: E402
from app.routers import analysis as analysis_mod  # noqa: E402
from app.routers import billing as billing_mod  # noqa: E402
from app import rbac  # noqa: E402


@compiles(PGUUID, "sqlite")
def _pg_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


TABLES = [
    models.User.__table__,
    models.AuditLog.__table__,
    models.ClaimedCondition.__table__,
    models.CreditBalance.__table__,
    models.CreditTransaction.__table__,
    models.GrantApplication.__table__,
    models.GrantPool.__table__,
    models.Sponsorship.__table__,
]

for _t in TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())

USER = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
WS = uuid.UUID("00000000-0000-0000-0000-0000000000c2")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'credits.db'}", poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(USER), "ws": str(WS), "role": "owner"}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=TABLES)
        async with Session() as s:
            s.add(models.User(id=USER, email="alex@example.com", password_hash="x", full_name="Alex"))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(credits_mod.router, prefix="/api")
    app.include_router(analysis_mod.router, prefix="/api")
    app.include_router(billing_mod.router, prefix="/api")

    async def _db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def _session_for_user(user_id: str, workspace_id: str | None = None):
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.current_workspace_id] = lambda: current["ws"]
    app.dependency_overrides[rbac.current_role] = lambda: current["role"]
    app.dependency_overrides[deps.get_db] = _db

    monkeypatch.setattr(billing_mod, "session_for_user", _session_for_user)
    monkeypatch.setattr(billing_mod.settings, "billing_self_serve", True)
    monkeypatch.setattr(billing_mod.settings, "stripe_secret_key", "sk_test_secret")
    monkeypatch.setattr(billing_mod.settings, "stripe_webhook_secret", "whsec_test_secret")
    # These tests exercise the ENFORCED metering path; the app default is off (dormant).
    monkeypatch.setattr(billing_mod.settings, "credits_enabled", True)

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current, Session=Session)


def _stripe_sig(secret: str, payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ts = str(int(time.time()))
    signed = f"{ts}.{body.decode()}".encode()
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return body.decode(), f"t={ts},v1={sig}"


def test_credit_ledger_math_and_recent_ledger(env):
    async def seed():
        async with env.Session() as s:
            await adjust_credits(
                s,
                USER,
                25,
                operation="test.credit",
                reference_type="test",
                reference_id="seed",
            )
            await s.commit()
    import asyncio

    asyncio.run(seed())

    resp = env.client.get("/api/credits")
    assert resp.status_code == 200
    body = resp.json()
    assert body["balance"] == 25
    assert body["recent"][0]["delta"] == 25
    assert body["recent"][0]["balance_after"] == 25


def test_insufficient_credits_returns_402(env):
    resp = env.client.post("/api/analysis/map-conditions", json={"names": ["PTSD"]})
    assert resp.status_code == 402
    assert "credits" in resp.json()["detail"].lower()


def test_stripe_webhook_is_signed_and_idempotent(env):
    event = {
        "id": "evt_full_claim",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_full_claim",
                "client_reference_id": str(USER),
                "amount_total": CreditConfig.full_claim_amount_cents,
                "payment_intent": "pi_full_claim",
                "metadata": {
                    "user_id": str(USER),
                    "workspace_id": str(WS),
                    "product": "full_claim",
                },
            }
        },
    }
    body, sig = _stripe_sig("whsec_test_secret", event)
    headers = {"Stripe-Signature": sig, "Content-Type": "application/json"}
    r1 = env.client.post("/api/billing/stripe/webhook", data=body, headers=headers)
    r2 = env.client.post("/api/billing/stripe/webhook", data=body, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200

    resp = env.client.get("/api/credits")
    assert resp.json()["balance"] == CreditConfig.full_claim_credits

    async def count_rows():
        async with env.Session() as s:
            txs = (await s.execute(select(models.CreditTransaction))).scalars().all()
            return len(txs)

    from sqlalchemy import select
    import asyncio

    assert asyncio.run(count_rows()) == 1


def test_grant_pool_accounting(env):
    sponsor_event = {
        "id": "evt_sponsor",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_sponsor",
                "client_reference_id": str(USER),
                "amount_total": CreditConfig.sponsor_amount_cents,
                "payment_intent": "pi_sponsor",
                "metadata": {
                    "user_id": str(USER),
                    "workspace_id": str(WS),
                    "product": "sponsor",
                },
            }
        },
    }
    body, sig = _stripe_sig("whsec_test_secret", sponsor_event)
    headers = {"Stripe-Signature": sig, "Content-Type": "application/json"}
    assert env.client.post("/api/billing/stripe/webhook", data=body, headers=headers).status_code == 200

    app_payload = {
        "monthly_income_band": "under $2,000/mo",
        "household_size": 1,
        "employment_status": "unemployed",
        "hardship_summary": "I need help covering the one-time claim cost right now.",
        "contact_email": "alex@example.com",
    }
    app_resp = env.client.post("/api/credits/grant-applications", json=app_payload)
    assert app_resp.status_code == 201
    app_id = app_resp.json()["id"]

    admin_before = env.client.get("/api/credits/admin/grant-applications").json()
    assert admin_before["pool"]["available_claims"] == 1
    assert len(admin_before["applications"]) == 1

    review = env.client.patch(
        f"/api/credits/admin/grant-applications/{app_id}",
        json={"status": "approved", "review_note": "Approved in test."},
    )
    assert review.status_code == 200
    assert review.json()["status"] == "approved"

    credits = env.client.get("/api/credits").json()
    assert credits["balance"] == CreditConfig.full_claim_credits

    admin_after = env.client.get("/api/credits/admin/grant-applications").json()
    assert admin_after["pool"]["available_claims"] == 0
    assert admin_after["applications"][0]["funded_sponsorship_id"] is not None
