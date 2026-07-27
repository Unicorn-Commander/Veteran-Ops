"""VA Lighthouse integration + C-CDA intake tests — no Postgres, no network.

Same harness as test_api_documents.py: the real routers run against in-memory
SQLite (Postgres column shims, client-side uuid4), deps are overridden, and
every VA HTTP touchpoint (`lighthouse.exchange_code` / `refresh_tokens` /
`revoke_token` / `api_request`) is monkeypatched with shape-accurate canned
payloads verified against the live sandbox OpenAPI specs. RLS itself can't run
on SQLite — cross-user tests exercise the routers' explicit user_id
defense-in-depth filters.

The OAuth tests verify the ACTUAL PKCE contract: the code_challenge in the
authorize redirect must equal S256(code_verifier that reaches the token
exchange).

CCD tests: the synthetic C-CDA fixture runs the REAL intake pipeline
end-to-end with the LLM rigged to explode — proving classification is fully
bypassed for structured clinical XML.
"""

from __future__ import annotations

import base64
import hashlib
import urllib.parse
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
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

from app import deps, models  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base, personal_workspace_id  # noqa: E402
from app.intake import ccd  # noqa: E402
from app.intake import process as process_mod  # noqa: E402
from app.routers import documents as documents_mod  # noqa: E402
from app.routers import va as va_mod  # noqa: E402
from app.va import lighthouse, normalize, service  # noqa: E402
from app.va.lighthouse import VaAuthError  # noqa: E402
from app.va.token_crypto import decrypt_token, encrypt_token  # noqa: E402

# ── SQLite shims (test-only; the app itself always runs on Postgres) ─────────


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
    models.EvidenceItem.__table__,
    models.Document.__table__,
    models.DocumentChunk.__table__,
    models.VaConnection.__table__,
    models.VaConnectState.__table__,
    models.AuditLog.__table__,
]

for _t in TABLES:  # gen_random_uuid() → client-side uuid4 (idempotent)
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())

# ── Seed identities ──────────────────────────────────────────────────────────
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
COND_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")
COND_TINNITUS = uuid.UUID("00000000-0000-0000-0000-000000000012")
COND_B = uuid.UUID("00000000-0000-0000-0000-000000000021")

# ── Canned VA payloads (shape-verified against the sandbox OpenAPI specs) ────

VA_SERVICE_HISTORY = {
    "data": [
        {
            "id": "ep-1",
            "type": "service-history-episodes",
            "attributes": {
                "first_name": "Alex",
                "last_name": "Veteran",
                "branch_of_service": "Army",
                "service_type": "Military Service",
                "component_of_service": "Active",
                "start_date": "2004-01-15",
                "end_date": "2008-06-30",
                "pay_grade": "E05",
                "discharge_status": "Honorable",
                "separation_reason": "COMPLETION OF REQUIRED ACTIVE SERVICE",
                "deployments": [
                    {"start_date": "2005-02-01", "end_date": "2006-01-15", "location": "IRQ"}
                ],
            },
        }
    ]
}

VA_RATING = {
    "data": {
        "id": "0",
        "type": "disability-ratings",
        "attributes": {
            "combined_disability_rating": 70,
            "combined_effective_date": "2019-04-01",
            "legal_effective_date": "2019-03-14",
            "individual_ratings": [
                {
                    "decision": "Service Connected",
                    "effective_date": "2019-04-01",
                    "rating_end_date": None,
                    "rating_percentage": 50,
                    "diagnostic_type_code": "9411",
                    "diagnostic_type_name": "Post traumatic stress disorder",
                    "diagnostic_text": "PTSD",
                    "static_ind": True,
                },
                {
                    "decision": "Service Connected",
                    "effective_date": "2010-01-01",
                    "rating_percentage": 10,
                    "diagnostic_type_code": "6260",
                    "diagnostic_type_name": "Tinnitus",
                    "diagnostic_text": "Tinnitus",
                    "static_ind": True,
                },
                {
                    "decision": "Service Connected",
                    "effective_date": "2019-04-01",
                    "rating_percentage": 20,
                    "diagnostic_type_code": "5237",
                    "diagnostic_type_name": "Lumbosacral or cervical strain",
                    "diagnostic_text": "Lumbosacral strain",
                    "static_ind": False,
                },
            ],
        },
    }
}

VA_PT = {
    "data": {
        "permanent_and_total": {
            "service_connected_status": False,
            "pension_award_status": False,
        },
        "total_disability": {"status": False, "effective_date": None},
    }
}

VA_VET_STATUS = {
    "data": {"id": "x", "type": "veteran_status",
             "attributes": {"veteran_status": "confirmed"}}
}

VA_CLAIMS = {
    "data": [
        {
            "id": "600118851",
            "type": "evss_claims",
            "attributes": {
                "evss_id": 600118851,
                "date_filed": "2018-06-04",
                "min_est_date": "2019-06-04",
                "max_est_date": "2019-09-04",
                "open": True,
                "waiver_submitted": False,
                "documents_needed": True,
                "development_letter_sent": True,
                "decision_letter_sent": False,
                "status": "Evidence gathering, review, and decision",
                "requested_decision": False,
                "claim_type": "Compensation",
                "events_timeline": [{"type": "filed", "date": "2018-06-04"}],
            },
        }
    ]
}

VA_ITF = {
    "data": {
        "id": "183042",
        "type": "intent_to_file",
        "attributes": {
            "creation_date": "2026-06-30",
            "expiration_date": "2027-06-30",
            "type": "compensation",
            "status": "active",
        },
    }
}


def _canned_api(responses: dict | None = None, calls: list | None = None):
    """An api_request stand-in dispatching on path; records calls."""
    table = {
        "service_history": VA_SERVICE_HISTORY,
        "disability_rating": VA_RATING,
        "permanent_and_total_disability": VA_PT,
        "status": VA_VET_STATUS,
        "claims": VA_CLAIMS,
        "forms/0966/active": VA_ITF,
        "forms/0966": VA_ITF,
        **(responses or {}),
    }

    async def fake_api_request(api, method, path, *, access_token, json_body=None):
        if calls is not None:
            calls.append(
                {"api": api.key, "method": method, "path": path,
                 "token": access_token, "json": json_body}
            )
        result = table[path]
        if isinstance(result, Exception):
            raise result
        return result

    return fake_api_request


# ── Environment fixture ──────────────────────────────────────────────────────
@pytest.fixture()
def env(tmp_path, monkeypatch):
    # FILE-backed SQLite (not :memory:/StaticPool): the VA tests seed and
    # inspect rows from their own event loops (see _run), and an aiosqlite
    # connection must never be reused across loops — NullPool + a shared file
    # gives every loop its own connection over the same data.
    db_path = tmp_path / "va_test.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        poolclass=NullPool,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def test_user_session(user_id: str):
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # The callback + intake task re-establish their own sessions.
    monkeypatch.setattr(service, "user_session", test_user_session)
    monkeypatch.setattr(process_mod, "user_session", test_user_session)
    monkeypatch.setattr(va_mod, "SessionLocal", Session)
    monkeypatch.setattr(documents_mod, "UPLOAD_DIR", tmp_path)

    # VA feature ON (default settings keep it off).
    monkeypatch.setattr(settings, "va_client_id", "test-client-id")
    monkeypatch.setattr(settings, "va_client_secret", "")
    monkeypatch.setattr(settings, "va_token_encryption_key", "test-only-va-token-key-32-chars-minimum")
    monkeypatch.setattr(settings, "va_base_url", "https://sandbox-api.va.gov")
    monkeypatch.setattr(settings, "va_redirect_base", "https://valor.test")

    current = {"uid": str(USER_A)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=TABLES)
        async with Session() as s:
            s.add_all(
                [
                    models.User(id=USER_A, email="alex@example.com",
                                password_hash="x", full_name="Alex Veteran"),
                    models.User(id=USER_B, email="blair@example.com",
                                password_hash="x", full_name="Blair Other"),
                    # Profile periods keyed identically to the VA payload → the
                    # differ must NOT suggest replacing them.
                    models.VeteranProfile(
                        user_id=USER_A,
                        service_periods=[
                            {"branch": "Army", "component": "Active",
                             "start_date": "2004-01-15", "end_date": "2008-06-30",
                             "discharge_character": "Honorable"},
                        ],
                        combat_service=True,
                        current_combined_rating=None,
                        state="SC",
                    ),
                    models.ClaimedCondition(id=COND_PTSD, user_id=USER_A,
                                            name="PTSD", claim_type="direct"),
                    models.ClaimedCondition(id=COND_TINNITUS, user_id=USER_A,
                                            name="Tinnitus", claim_type="increase",
                                            diagnostic_code="6260",
                                            current_rating=10),
                    models.ClaimedCondition(id=COND_B, user_id=USER_B,
                                            name="PTSD (other veteran)",
                                            claim_type="direct"),
                ]
            )
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(va_mod.router, prefix="/api")
    app.include_router(documents_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.current_workspace_id] = (
        lambda: personal_workspace_id(current["uid"])
    )
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current, Session=Session,
                              monkeypatch=monkeypatch)


async def _seed_connection(env, api="verification", *, user_id=USER_A,
                           expires_in_s: int | None = None,
                           refresh_token: str | None = "rt-live",
                           meta: dict | None = None):
    async with env.Session() as s:
        conn = models.VaConnection(
            user_id=user_id,
            provider="lighthouse",
            api=api,
            scope_set=lighthouse.get_api(api).scopes,
            access_token=encrypt_token("at-live"),
            refresh_token=encrypt_token(refresh_token) if refresh_token else None,
            token_expires_at=(
                datetime.now(timezone.utc) + timedelta(seconds=expires_in_s)
                if expires_in_s is not None else None
            ),
            meta=meta,
        )
        s.add(conn)
        await s.commit()
        await s.refresh(conn)
        return conn.id


# ═══ Degradation: feature off ════════════════════════════════════════════════
def test_disabled_status_and_clean_503s(env, monkeypatch):
    monkeypatch.setattr(settings, "va_client_id", "")
    assert env.client.get("/api/va/status").json() == {
        "enabled": False, "connected": False, "scopes": [],
        "last_sync": None, "needs_reconnect": False, "connections": [],
    }
    assert env.client.get("/api/va/connect", follow_redirects=False).status_code == 503
    assert env.client.get("/api/va/callback?code=x&state=y").status_code == 503
    assert env.client.post("/api/va/sync").status_code == 503
    assert env.client.post("/api/va/apply", json={}).status_code == 503
    assert env.client.get("/api/va/claims").status_code == 503
    assert env.client.get("/api/va/itf/active").status_code == 503
    assert env.client.post("/api/va/itf", json={"confirm": True}).status_code == 503
    assert env.client.post("/api/va/disconnect", json={}).status_code == 503


# ═══ OAuth connect / callback ════════════════════════════════════════════════
def test_connect_redirects_to_va_with_pkce(env):
    resp = env.client.get("/api/va/connect", follow_redirects=False)
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith(
        "https://sandbox-api.va.gov/oauth2/veteran-verification/v1/authorization?"
    )
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))
    assert q["client_id"] == "test-client-id"
    assert q["response_type"] == "code"
    assert q["redirect_uri"] == "https://valor.test/api/va/callback"
    assert q["code_challenge_method"] == "S256"
    assert q["code_challenge"] and q["state"]
    assert "service_history.read" in q["scope"]
    assert "offline_access" in q["scope"]

    # Claims family goes to ITS authorization server with ITS scopes.
    loc2 = env.client.get(
        "/api/va/connect?api=claims", follow_redirects=False
    ).headers["location"]
    assert "/oauth2/claims/v1/authorization?" in loc2
    assert "claim.read" in loc2 and "claim.write" in loc2

    # JSON mode for SPA-driven navigation + bad api rejected.
    body = env.client.get("/api/va/connect?redirect=false").json()
    assert body["authorize_url"].startswith("https://sandbox-api.va.gov/oauth2/")
    assert env.client.get("/api/va/connect?api=bogus",
                          follow_redirects=False).status_code == 422


def test_callback_exchanges_code_and_stores_connection(env, monkeypatch):
    loc = env.client.get("/api/va/connect", follow_redirects=False).headers["location"]
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))

    seen = {}

    async def fake_exchange(api, *, code, code_verifier):
        seen.update(api=api.key, code=code, verifier=code_verifier)
        return {"access_token": "at-1", "refresh_token": "rt-1",
                "expires_in": 3600, "token_type": "Bearer",
                "scope": "openid service_history.read disability_rating.read"}

    monkeypatch.setattr(lighthouse, "exchange_code", fake_exchange)
    resp = env.client.get(
        f"/api/va/callback?code=authcode-1&state={q['state']}",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://valor.test/settings?va=connected&api=verification"

    # PKCE really held: challenge in the authorize URL == S256(verifier used).
    digest = hashlib.sha256(seen["verifier"].encode()).digest()
    assert q["code_challenge"] == base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert seen["code"] == "authcode-1"

    body = env.client.get("/api/va/status").json()
    assert body["enabled"] and body["connected"]
    assert body["needs_reconnect"] is False
    assert body["connections"][0]["api"] == "verification"
    # scope_set reflects what VA GRANTED, not what we asked for.
    assert body["connections"][0]["scopes"] == [
        "openid", "service_history.read", "disability_rating.read"]

    # The one-time state row was consumed — replay fails cleanly.
    replay = env.client.get(
        f"/api/va/callback?code=authcode-2&state={q['state']}",
        follow_redirects=False,
    )
    assert "va=error" in replay.headers["location"]

    # A native session JWT must NOT pass as connect state (purpose claim).
    from app.security import create_access_token

    forged = env.client.get(
        f"/api/va/callback?code=x&state={create_access_token(str(USER_A), 'a@x.com')}",
        follow_redirects=False,
    )
    assert "invalid_or_expired" in forged.headers["location"]


def test_callback_provider_error_and_missing_params(env):
    resp = env.client.get("/api/va/callback?error=access_denied", follow_redirects=False)
    assert "va=error" in resp.headers["location"]
    resp = env.client.get("/api/va/callback", follow_redirects=False)
    assert "missing_parameters" in resp.headers["location"]


# ═══ Sync: read-only preview + suggestions ═══════════════════════════════════
def test_sync_returns_preview_and_never_applies(env, monkeypatch):
    conn_id = _run(env, _seed_connection(env))
    assert conn_id

    calls: list = []
    monkeypatch.setattr(lighthouse, "api_request", _canned_api(calls=calls))

    resp = env.client.post("/api/va/sync")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Normalized service periods.
    sp = body["service_periods"]
    assert sp[0]["branch"] == "Army"
    assert sp[0]["discharge_character"] == "Honorable"
    assert sp[0]["deployments"][0]["location"] == "IRQ"

    # Normalized ratings + combined + P&T + status.
    assert body["combined"] == 70
    assert body["combined_effective_date"] == "2019-04-01"
    by_dc = {r["diagnostic_code"]: r for r in body["ratings"]}
    assert by_dc["9411"]["percent"] == 50 and by_dc["9411"]["name"] == "PTSD"
    assert by_dc["6260"]["percent"] == 10
    assert body["pt_status"]["permanent_and_total"] is False
    assert body["veteran_status"] == "confirmed"
    assert "preview" in body["disclaimer"]

    # Suggestions: PTSD (name match, no rating yet) → update; Tinnitus already
    # 10% → NO suggestion; Lumbosacral strain untracked → create.
    sug = body["suggestions"]
    assert sug["profile_updates"] == {
        "current_combined_rating": {"from": None, "to": 70}
    }  # service periods matched the profile → not suggested
    ups = {u["action"]: u for u in sug["condition_updates"]}
    assert ups["update_rating"]["condition_id"] == str(COND_PTSD)
    assert ups["update_rating"]["percent"] == 50
    assert ups["create"]["name"] == "Lumbosacral strain"
    assert ups["create"]["condition_id"] is None
    assert len(sug["condition_updates"]) == 2

    # NOTHING was applied.
    detailed = _run(env, _fetch_conditions(env, USER_A))
    assert detailed["PTSD"] is None
    assert detailed["Tinnitus"] == 10
    assert "Lumbosacral strain" not in detailed

    # status reflects the sync + audit trail exists (token never in meta).
    st = env.client.get("/api/va/status").json()
    assert st["last_sync"] is not None
    audits = _run(env, _fetch_audit(env, "va.sync"))
    assert audits and "at-live" not in str(audits)


def test_sync_requires_connection(env):
    resp = env.client.post("/api/va/sync")
    assert resp.status_code == 409
    assert "connect" in resp.json()["detail"].lower()


# ═══ Apply: veteran-confirmed, snapshot-validated ════════════════════════════
def test_apply_selected_suggestions(env, monkeypatch):
    _run(env, _seed_connection(env))
    monkeypatch.setattr(lighthouse, "api_request", _canned_api())
    assert env.client.post("/api/va/sync").status_code == 200

    resp = env.client.post("/api/va/apply", json={
        "service_periods": True,
        "combined_rating": True,
        "condition_updates": [{"condition_id": str(COND_PTSD), "percent": 50}],
        "condition_creates": [{"name": "Lumbosacral strain",
                               "diagnostic_code": "5237", "percent": 20}],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["profile_updated"] is True
    assert body["updated"][0]["current_rating"] == 50
    created = body["created"][0]
    assert created["claim_type"] == "increase"
    assert created["current_rating"] == 20
    assert created["diagnostic_code"] == "5237"

    ratings = _run(env, _fetch_conditions(env, USER_A))
    assert ratings["PTSD"] == 50
    assert ratings["Lumbosacral strain"] == 20
    audits = _run(env, _fetch_audit(env, "va.apply"))
    assert audits[0]["profile_fields"] == ["service_periods", "current_combined_rating"]


def test_apply_guards(env, monkeypatch):
    _run(env, _seed_connection(env))
    # No sync yet → 409.
    resp = env.client.post("/api/va/apply", json={"combined_rating": True})
    assert resp.status_code == 409 and "sync" in resp.json()["detail"].lower()

    monkeypatch.setattr(lighthouse, "api_request", _canned_api())
    env.client.post("/api/va/sync")

    # Empty selection → 422.
    assert env.client.post("/api/va/apply", json={}).status_code == 422
    # A percent VA never returned for that condition → 409.
    resp = env.client.post("/api/va/apply", json={
        "condition_updates": [{"condition_id": str(COND_PTSD), "percent": 70}]})
    assert resp.status_code == 409
    # A create that isn't in the snapshot → 409.
    resp = env.client.post("/api/va/apply", json={
        "condition_creates": [{"name": "Made-up syndrome", "percent": 50}]})
    assert resp.status_code == 409
    # Another user's condition → RLS-shaped 404.
    resp = env.client.post("/api/va/apply", json={
        "condition_updates": [{"condition_id": str(COND_B), "percent": 50}]})
    assert resp.status_code == 404


# ═══ Token refresh + needs_reconnect ═════════════════════════════════════════
def test_expired_token_is_refreshed_and_persisted(env, monkeypatch):
    _run(env, _seed_connection(env, expires_in_s=-60))  # already expired

    async def fake_refresh(api, *, refresh_token):
        assert refresh_token == "rt-live"
        return {"access_token": "at-fresh", "refresh_token": "rt-rotated",
                "expires_in": 3600, "scope": "openid service_history.read"}

    calls: list = []
    monkeypatch.setattr(lighthouse, "refresh_tokens", fake_refresh)
    monkeypatch.setattr(lighthouse, "api_request", _canned_api(calls=calls))

    assert env.client.post("/api/va/sync").status_code == 200
    # Every data call used the refreshed token, never the stale one.
    assert calls and all(c["token"] == "at-fresh" for c in calls)
    conn = _run(env, _fetch_connection(env, "verification"))
    assert conn["access_token"] == "at-fresh"
    assert conn["refresh_token"] == "rt-rotated"  # encrypted rotation persisted


def test_refresh_failure_marks_needs_reconnect(env, monkeypatch):
    _run(env, _seed_connection(env, expires_in_s=-60))

    async def refused(api, *, refresh_token):
        raise VaAuthError("declined")

    monkeypatch.setattr(lighthouse, "refresh_tokens", refused)
    resp = env.client.post("/api/va/sync")
    assert resp.status_code == 409
    assert "reconnect" in resp.json()["detail"].lower()
    st = env.client.get("/api/va/status").json()
    assert st["needs_reconnect"] is True
    assert st["connections"][0]["needs_reconnect"] is True


def test_data_401_gets_one_forced_refresh_then_reconnect(env, monkeypatch):
    _run(env, _seed_connection(env))  # not expired by clock

    async def always_401(api, method, path, *, access_token, json_body=None):
        raise VaAuthError("revoked upstream")

    async def refresh_ok(api, *, refresh_token):
        return {"access_token": "at-2", "expires_in": 3600}

    monkeypatch.setattr(lighthouse, "api_request", always_401)
    monkeypatch.setattr(lighthouse, "refresh_tokens", refresh_ok)
    assert env.client.post("/api/va/sync").status_code == 409
    assert env.client.get("/api/va/status").json()["needs_reconnect"] is True


# ═══ Disconnect ══════════════════════════════════════════════════════════════
def test_disconnect_revokes_best_effort_and_deletes(env, monkeypatch):
    _run(env, _seed_connection(env))
    revoked: list = []

    async def fake_revoke(api, *, token, token_type_hint):
        revoked.append((api.key, token_type_hint))
        return True

    monkeypatch.setattr(lighthouse, "revoke_token", fake_revoke)
    resp = env.client.post("/api/va/disconnect", json={})
    assert resp.status_code == 200
    assert resp.json() == {"disconnected": ["verification"]}
    assert ("verification", "refresh_token") in revoked
    assert env.client.get("/api/va/status").json()["connected"] is False

    # Revocation endpoint down → row still deleted (best-effort contract).
    _run(env, _seed_connection(env))

    async def broken_revoke(api, *, token, token_type_hint):
        return False

    monkeypatch.setattr(lighthouse, "revoke_token", broken_revoke)
    assert env.client.post("/api/va/disconnect", json={}).status_code == 200
    assert env.client.get("/api/va/status").json()["connected"] is False


# ═══ Claims + Intent to File ═════════════════════════════════════════════════
def test_claims_normalized(env, monkeypatch):
    _run(env, _seed_connection(env, api="claims"))
    monkeypatch.setattr(lighthouse, "api_request", _canned_api())
    body = env.client.get("/api/va/claims").json()
    claim = body["claims"][0]
    assert claim["id"] == "600118851"
    assert claim["status"] == "Evidence gathering, review, and decision"
    assert claim["phase"] == 3
    assert claim["open"] is True
    assert claim["documents_needed"] is True
    assert claim["development_letter_sent"] is True
    assert claim["decision_letter_sent"] is False
    assert claim["date_filed"] == "2018-06-04"
    assert claim["events"] == [
        {"type": "filed", "date": "2018-06-04", "phase": None, "filename": None}]


def test_claims_requires_claims_connection(env, monkeypatch):
    _run(env, _seed_connection(env, api="verification"))  # wrong family
    assert env.client.get("/api/va/claims").status_code == 409


def test_itf_active_and_none(env, monkeypatch):
    _run(env, _seed_connection(env, api="claims"))
    monkeypatch.setattr(lighthouse, "api_request", _canned_api())
    body = env.client.get("/api/va/itf/active").json()
    assert body["active"] is True
    assert body["expiration_date"] == "2027-06-30"

    from app.va.lighthouse import VaNotFound

    monkeypatch.setattr(
        lighthouse, "api_request",
        _canned_api(responses={"forms/0966/active": VaNotFound("none")}),
    )
    assert env.client.get("/api/va/itf/active").json()["active"] is False


def test_itf_file_requires_explicit_confirm_and_audits(env, monkeypatch):
    _run(env, _seed_connection(env, api="claims"))
    calls: list = []
    monkeypatch.setattr(lighthouse, "api_request", _canned_api(calls=calls))

    # No confirm → 422 with the confirmation contract spelled out; NO VA call.
    resp = env.client.post("/api/va/itf", json={"type": "compensation"})
    assert resp.status_code == 422
    assert "confirm" in resp.text.lower()
    assert calls == []

    resp = env.client.post("/api/va/itf",
                           json={"type": "compensation", "confirm": True})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["active"] is True and body["id"] == "183042"
    sent = [c for c in calls if c["method"] == "POST"]
    assert sent[0]["path"] == "forms/0966"
    assert sent[0]["json"] == {"data": {"attributes": {"type": "compensation"}}}
    audits = _run(env, _fetch_audit(env, "va.itf_filed"))
    assert audits[0]["veteran_confirmed"] is True


# ═══ Auth posture ════════════════════════════════════════════════════════════
def test_requires_auth():
    app = FastAPI()
    app.include_router(va_mod.router, prefix="/api")
    client = TestClient(app)
    assert client.get("/api/va/status").status_code in (401, 403)
    assert client.post("/api/va/sync").status_code in (401, 403)
    assert client.post("/api/va/itf", json={"confirm": True}).status_code in (401, 403)


# ═══ C-CDA (CCD) parser ══════════════════════════════════════════════════════
CCD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!-- VA Health Summary (synthetic) -->
<ClinicalDocument xmlns="urn:hl7-org:v3"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <title>VA Health Summary</title>
  <effectiveTime value="20260615103000-0500"/>
  <recordTarget><patientRole><patient>
    <name><given>Alex</given><family>Veteran</family></name>
  </patient></patientRole></recordTarget>
  <component><structuredBody>
    <component><section>
      <code code="11450-4" codeSystem="2.16.840.1.113883.6.1" displayName="Problem List"/>
      <title>Problems</title>
      <entry><act><entryRelationship typeCode="SUBJ"><observation classCode="OBS">
        <statusCode code="active"/>
        <effectiveTime><low value="20050301"/></effectiveTime>
        <value xsi:type="CD" code="F43.10" codeSystemName="ICD-10-CM"
               displayName="Post-traumatic stress disorder"/>
      </observation></entryRelationship></act></entry>
      <entry><act><entryRelationship typeCode="SUBJ"><observation classCode="OBS">
        <statusCode code="active"/>
        <effectiveTime><low value="20100610"/></effectiveTime>
        <value xsi:type="CD" code="H93.19" codeSystemName="ICD-10-CM"
               displayName="Tinnitus"/>
      </observation></entryRelationship></act></entry>
    </section></component>
    <component><section>
      <code code="10160-0" codeSystem="2.16.840.1.113883.6.1"/>
      <title>Medications</title>
      <entry><substanceAdministration classCode="SBADM">
        <statusCode code="active"/>
        <effectiveTime><low value="20250101"/></effectiveTime>
        <doseQuantity value="50" unit="mg"/>
        <consumable><manufacturedProduct><manufacturedMaterial>
          <code code="312941" displayName="Sertraline 50 MG Oral Tablet"/>
        </manufacturedMaterial></manufacturedProduct></consumable>
      </substanceAdministration></entry>
    </section></component>
    <component><section>
      <code code="48765-2" codeSystem="2.16.840.1.113883.6.1"/>
      <title>Allergies</title>
      <entry><act><entryRelationship><observation>
        <participant><participantRole><playingEntity>
          <code code="7980" displayName="Penicillin"/>
        </playingEntity></participantRole></participant>
        <entryRelationship><observation>
          <code code="ASSERTION"/>
          <value xsi:type="CD" code="247472004" displayName="Hives"/>
        </observation></entryRelationship>
      </observation></entryRelationship></act></entry>
    </section></component>
    <component><section>
      <code code="11369-6" codeSystem="2.16.840.1.113883.6.1"/>
      <title>Immunizations</title>
      <entry><substanceAdministration>
        <effectiveTime value="20251015"/>
        <consumable><manufacturedProduct><manufacturedMaterial>
          <code code="140" displayName="Influenza vaccine"/>
        </manufacturedMaterial></manufacturedProduct></consumable>
      </substanceAdministration></entry>
    </section></component>
    <component><section>
      <code code="8716-3" codeSystem="2.16.840.1.113883.6.1"/>
      <title>Vital Signs</title>
      <entry><organizer><component><observation>
        <code code="8480-6" displayName="Systolic blood pressure"/>
        <effectiveTime value="20260601"/>
        <value xsi:type="PQ" value="128" unit="mm[Hg]"/>
      </observation></component></organizer></entry>
    </section></component>
    <component><section>
      <code code="30954-2" codeSystem="2.16.840.1.113883.6.1"/>
      <title>Results</title>
      <entry><organizer><component><observation>
        <code code="2093-3" displayName="Cholesterol"/>
        <effectiveTime value="20260520"/>
        <value xsi:type="PQ" value="182" unit="mg/dL"/>
      </observation></component></organizer></entry>
    </section></component>
    <component><section>
      <code code="46240-8" codeSystem="2.16.840.1.113883.6.1"/>
      <title>Encounters</title>
      <entry><encounter>
        <code code="99213" displayName="Office outpatient visit"/>
        <effectiveTime value="20260601"/>
        <participant><participantRole><playingEntity>
          <name>Ralph H. Johnson VA Medical Center</name>
        </playingEntity></participantRole></participant>
      </encounter></entry>
    </section></component>
  </structuredBody></component>
</ClinicalDocument>
"""


def test_sniff_ccd():
    assert ccd.sniff_ccd(CCD_XML) is True
    assert ccd.sniff_ccd("<?xml version='1.0'?><Bundle/>") is False
    assert ccd.sniff_ccd("just some text mentioning ClinicalDocument") is False
    assert ccd.sniff_ccd("") is False
    assert ccd.sniff_ccd(None) is False
    # Prefixed root + leading comment still sniffs.
    assert ccd.sniff_ccd(
        "<?xml version='1.0'?><!-- c --><h:ClinicalDocument xmlns:h='urn:hl7-org:v3'/>"
    ) is True


def test_parse_ccd_sections():
    parsed = ccd.parse_ccd(CCD_XML)
    assert parsed["title"] == "VA Health Summary"
    assert parsed["doc_date"] == "2026-06-15"

    probs = {p["name"]: p for p in parsed["problems"]}
    assert set(probs) == {"Post-traumatic stress disorder", "Tinnitus"}
    assert probs["Post-traumatic stress disorder"]["code"] == "F43.10"
    assert probs["Post-traumatic stress disorder"]["onset_date"] == "2005-03-01"
    assert probs["Tinnitus"]["status"] == "active"

    med = parsed["medications"][0]
    assert med["name"] == "Sertraline 50 MG Oral Tablet"
    assert med["dose"] == "50" and med["dose_unit"] == "mg"
    assert med["start_date"] == "2025-01-01"

    allergy = parsed["allergies"][0]
    assert allergy["substance"] == "Penicillin"
    assert allergy["reaction"] == "Hives"

    assert parsed["immunizations"] == [{"name": "Influenza vaccine", "date": "2025-10-15"}]
    vital = parsed["vitals"][0]
    assert (vital["name"], vital["value"], vital["unit"]) == (
        "Systolic blood pressure", "128", "mm[Hg]")
    assert parsed["labs"][0]["name"] == "Cholesterol"
    enc = parsed["encounters"][0]
    assert enc["description"] == "Office outpatient visit"
    assert enc["location"] == "Ralph H. Johnson VA Medical Center"


def test_ccd_rejects_dtd_and_garbage():
    bomb = "<?xml version='1.0'?><!DOCTYPE x [<!ENTITY a 'aaaa'>]><ClinicalDocument/>"
    assert ccd.parse_ccd(bomb) is None
    assert ccd.extract_ccd(bomb) is None
    assert ccd.parse_ccd("<ClinicalDocument") is None      # not well-formed
    assert ccd.parse_ccd("<NotACcd/>") is None             # wrong root
    assert ccd.extract_ccd("plain text") is None


def test_extract_ccd_pipeline_shape():
    extracted = ccd.extract_ccd(CCD_XML)
    assert extracted["doc_type"] == "treatment_record"
    assert extracted["doc_date"] == "2026-06-15"
    assert extracted["title"] == "VA Health Summary"
    assert extracted["is_va_decision"] is False
    names = [m["name"] for m in extracted["conditions_mentioned"]]
    assert names == ["Post-traumatic stress disorder", "Tinnitus"]
    for m in extracted["conditions_mentioned"]:
        assert m["rating_percent"] is None and m["decision"] is None
    assert extracted["ccd"]["medications"]
    assert "no AI was involved" in extracted["summary"]


def test_ccd_upload_end_to_end_bypasses_llm(env, monkeypatch):
    async def llm_must_not_run(text):
        raise AssertionError("classify_text must not be called for a CCD")

    monkeypatch.setattr(process_mod, "classify_text", llm_must_not_run)

    resp = env.client.post(
        "/api/documents",
        files=[("files", ("va_health_summary.xml", CCD_XML.encode(), "application/xml"))],
    )
    assert resp.status_code == 201, resp.text
    item = resp.json()["items"][0]
    assert item["accepted"] is True
    doc_id = item["document"]["id"]

    detail = env.client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "ready", detail.get("error")
    assert detail["doc_type"] == "treatment_record"
    assert detail["doc_date"] == "2026-06-15"
    assert detail["error"] is None
    extracted = detail["extracted"]
    assert extracted["ccd"]["problems"][0]["name"] == "Post-traumatic stress disorder"
    # Deterministic linking suggestions still ran: the CCD's Tinnitus problem
    # matches the veteran's claimed Tinnitus — suggestion only, nothing linked.
    linked = {link["condition_id"] for link in extracted["suggested_links"]}
    assert str(COND_TINNITUS) in linked
    assert str(COND_B) not in linked
    assert detail["condition_id"] is None


def test_non_ccd_xml_falls_back_to_llm(env, monkeypatch):
    ran = {"llm": False}

    async def canned(text):
        ran["llm"] = True
        return {
            "doc_type": "other", "doc_date": None, "title": "Some XML",
            "summary": "Not clinical. Unknown.", "conditions_mentioned": [],
            "is_va_decision": False,
        }

    monkeypatch.setattr(process_mod, "classify_text", canned)
    resp = env.client.post(
        "/api/documents",
        files=[("files", ("random.xml", b"<?xml version='1.0'?><Widget><a/></Widget>",
                          "application/xml"))],
    )
    doc_id = resp.json()["items"][0]["document"]["id"]
    detail = env.client.get(f"/api/documents/{doc_id}").json()
    assert ran["llm"] is True
    assert detail["status"] == "ready"


# ═══ Pure normalizer edge cases ═══════════════════════════════════════════════
def test_normalizers_tolerate_missing_shapes():
    assert normalize.normalize_service_history({}) == []
    assert normalize.normalize_disability_rating({})["ratings"] == []
    assert normalize.normalize_disability_rating({})["combined"] is None
    assert normalize.normalize_pt({})["permanent_and_total"] is None
    assert normalize.normalize_claims({}) == []
    assert normalize.normalize_veteran_status({}) is None
    itf = normalize.normalize_itf({})
    assert itf["id"] is None and itf["status"] is None


def test_build_suggestions_prefers_diagnostic_code_over_name():
    rating = {
        "combined": 30,
        "ratings": [{"name": "Completely different words", "diagnostic_code": "6260",
                     "percent": 30, "effective_date": "2024-01-01"}],
    }
    conditions = [{"id": "c1", "name": "Tinnitus", "diagnostic_code": "6260",
                   "current_rating": 10}]
    sug = normalize.build_suggestions(
        service_periods=[], rating=rating, profile=None, conditions=conditions)
    assert sug["condition_updates"][0]["action"] == "update_rating"
    assert sug["condition_updates"][0]["condition_id"] == "c1"


# ── tiny async runners ───────────────────────────────────────────────────────
# TestClient is sync (the app runs on its own portal loop); these helpers hop
# onto a fresh loop of their own. The fixture's engine is FILE-backed with
# NullPool precisely so connections are never shared across event loops.
def _run(env, coro):
    import asyncio

    return asyncio.run(coro)


async def _fetch_conditions(env, user_id) -> dict:
    async with env.Session() as s:
        rows = (
            await s.execute(
                select(models.ClaimedCondition).where(
                    models.ClaimedCondition.user_id == user_id)
            )
        ).scalars().all()
        return {r.name: r.current_rating for r in rows}


async def _fetch_connection(env, api: str) -> dict:
    async with env.Session() as s:
        conn = (
            await s.execute(
                select(models.VaConnection).where(models.VaConnection.api == api)
            )
        ).scalar_one()
        return {"access_token": decrypt_token(conn.access_token),
                "refresh_token": decrypt_token(conn.refresh_token),
                "meta": conn.meta}


async def _fetch_audit(env, action: str) -> list[dict]:
    async with env.Session() as s:
        rows = (
            await s.execute(
                select(models.AuditLog).where(models.AuditLog.action == action)
            )
        ).scalars().all()
        return [r.meta or {} for r in rows]
