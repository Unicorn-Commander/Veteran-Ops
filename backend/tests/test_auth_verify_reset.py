"""WAVE12 — email verification + password reset endpoints (app/routers/auth.py) on the
SQLite harness. These handlers use the ORM (db.get/select) + purpose tokens, which run
fine on SQLite. We mint the purpose tokens ourselves (simplest, most direct) and drive
register → verify → forgot → reset, asserting: verification flips email_verified; wrong-
purpose / garbage / unknown-user tokens 400; forgot never enumerates; reset is single-use
(fingerprint changes with the hash) and also marks the email verified.
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
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import db as db_mod, models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.routers import auth as auth_mod  # noqa: E402
from app.security import make_purpose_token, password_fingerprint  # noqa: E402

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


_TABLES = [models.User.__table__]
for _t in _TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())

_STRONG = "z" * 40


@pytest.fixture()
def env(tmp_path, monkeypatch):
    # Same live secret for our minting and the endpoint's verifying.
    monkeypatch.setattr(settings, "jwt_secret", _STRONG, raising=False)
    # Keep tests hermetic — never touch the email backend.
    async def _noop_verify(user):  # noqa: ANN001
        return None

    async def _noop_reset(to, link):  # noqa: ANN001
        return None

    monkeypatch.setattr(auth_mod, "_send_verify_link", _noop_verify)
    monkeypatch.setattr(auth_mod, "send_password_reset_email", _noop_reset)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'auth.db'}", poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(auth_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[db_mod.get_session] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, Session=Session)


async def _get_user_by_email(Session, email):  # noqa: ANN001
    async with Session() as s:
        return (await s.execute(select(models.User).where(models.User.email == email))).scalar_one()


def _register(client, email="vet@example.com", password="hunter2pass"):
    return client.post(
        "/api/auth/register",
        json={"email": email, "password": password, "full_name": "Vet Eran"},
    )


def test_register_creates_unverified_user(env):
    r = _register(env.client)
    assert r.status_code == 201
    assert r.json()["user"]["email_verified"] is False

    import asyncio

    user = asyncio.run(_get_user_by_email(env.Session, "vet@example.com"))
    assert user.email_verified is False


def test_auth_config_never_advertises_dead_actions(env, monkeypatch):
    monkeypatch.setattr(settings, "allow_registration", False)
    monkeypatch.setattr(settings, "keycloak_url", "")
    monkeypatch.setattr(settings, "email_provider", "")

    # A closed fresh install still exposes its one bootstrap account.
    before = env.client.get("/api/auth/config")
    assert before.status_code == 200
    assert before.json() == {
        "sso_enabled": False,
        "sso_label": "Unicorn Commander",
        "password_login_enabled": True,
        "registration_open": True,
        "registration_mode": "bootstrap",
        "email_enabled": False,
        "password_reset_enabled": False,
    }

    assert _register(env.client).status_code == 201
    after = env.client.get("/api/auth/config").json()
    assert after["registration_open"] is False
    assert after["registration_mode"] == "closed"


def test_auth_config_enables_reset_only_with_delivery_and_public_base(env, monkeypatch):
    monkeypatch.setattr(settings, "email_provider", "postmark")
    monkeypatch.setattr(settings, "postmark_server_token", "test-token")
    monkeypatch.setattr(settings, "email_from", "support@example.test")
    monkeypatch.setattr(settings, "sso_redirect_base", "https://valor.example.test")
    body = env.client.get("/api/auth/config").json()
    assert body["email_enabled"] is True
    assert body["password_reset_enabled"] is True


def test_password_endpoints_fail_closed_when_instance_is_sso_only(env, monkeypatch):
    monkeypatch.setattr(settings, "password_login_enabled", False)
    config = env.client.get("/api/auth/config").json()
    assert config["password_login_enabled"] is False
    assert config["registration_mode"] == "closed"

    assert _register(env.client).status_code == 503
    assert env.client.post(
        "/api/auth/login", json={"email": "vet@example.com", "password": "hunter2pass"}
    ).status_code == 503
    assert env.client.post(
        "/api/auth/password/forgot", json={"email": "vet@example.com"}
    ).status_code == 503


def test_verify_email_confirm_flips_flag(env):
    import asyncio

    _register(env.client)
    user = asyncio.run(_get_user_by_email(env.Session, "vet@example.com"))
    token = make_purpose_token("verify-email", str(user.id), 60, email=user.email)
    r = env.client.post("/api/auth/verify-email/confirm", json={"token": token})
    assert r.status_code == 200

    user2 = asyncio.run(_get_user_by_email(env.Session, "vet@example.com"))
    assert user2.email_verified is True


def test_verify_email_rejects_wrong_purpose_garbage_and_unknown_user(env):
    import asyncio

    _register(env.client)
    user = asyncio.run(_get_user_by_email(env.Session, "vet@example.com"))

    # Right shape, wrong purpose.
    wrong_purpose = make_purpose_token("pw-reset", str(user.id), 60)
    assert env.client.post(
        "/api/auth/verify-email/confirm", json={"token": wrong_purpose}
    ).status_code == 400

    # Garbage token (satisfies min-length schema but not a JWT).
    assert env.client.post(
        "/api/auth/verify-email/confirm", json={"token": "garbage-token-value"}
    ).status_code == 400

    # Valid verify-email token for a user that does not exist.
    ghost = make_purpose_token("verify-email", str(uuid.uuid4()), 60)
    assert env.client.post(
        "/api/auth/verify-email/confirm", json={"token": ghost}
    ).status_code == 400


def test_forgot_password_does_not_enumerate(env, monkeypatch):
    monkeypatch.setattr(settings, "email_provider", "postmark")
    monkeypatch.setattr(settings, "postmark_server_token", "test-token")
    monkeypatch.setattr(settings, "email_from", "support@example.test")
    monkeypatch.setattr(settings, "sso_redirect_base", "https://valor.example.test")
    _register(env.client)
    r_exists = env.client.post("/api/auth/password/forgot", json={"email": "vet@example.com"})
    r_absent = env.client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})
    assert r_exists.status_code == 200 and r_absent.status_code == 200
    assert r_exists.json()["message"] == r_absent.json()["message"]


def test_password_reset_completes_verifies_and_is_single_use(env):
    import asyncio

    _register(env.client, password="oldpassword1")
    user = asyncio.run(_get_user_by_email(env.Session, "vet@example.com"))
    old_hash = user.password_hash

    token = make_purpose_token(
        "pw-reset", str(user.id), 60, fp=password_fingerprint(old_hash)
    )
    r = env.client.post(
        "/api/auth/password/reset", json={"token": token, "password": "brandnewpass1"}
    )
    assert r.status_code == 200

    user2 = asyncio.run(_get_user_by_email(env.Session, "vet@example.com"))
    assert user2.password_hash != old_hash
    assert user2.email_verified is True

    # Re-using the same token now fails: the hash (and thus fingerprint) changed.
    r2 = env.client.post(
        "/api/auth/password/reset", json={"token": token, "password": "another1pass"}
    )
    assert r2.status_code == 400


def test_password_reset_rejects_mismatched_fingerprint(env):
    import asyncio

    _register(env.client)
    user = asyncio.run(_get_user_by_email(env.Session, "vet@example.com"))
    bad = make_purpose_token("pw-reset", str(user.id), 60, fp="not-the-real-fp")
    r = env.client.post(
        "/api/auth/password/reset", json={"token": bad, "password": "whateverpass1"}
    )
    assert r.status_code == 400
