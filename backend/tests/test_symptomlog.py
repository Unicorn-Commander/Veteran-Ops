"""Symptom-log tests (WAVE5 F3) — no Postgres, no network.

Runs the real router end-to-end against in-memory (file-backed) SQLite: the
Postgres-only column types get compile shims (UUID→CHAR(36), JSONB→JSON, and the
KBCard pgvector Vector→TEXT, since the criteria endpoint queries KBCard),
gen_random_uuid() server defaults become client-side uuid4, and auth is overridden.

RLS itself can't run on SQLite — the cross-user 404 tests exercise the router's
explicit user_id defense-in-depth filters that back the Postgres policies.

The Glitter Mane bridge is never hit over the wire: `fetch_continuity` (and
`_user_email`) are monkeypatched to return canned check-ins for the happy path and
to raise for the degradation path (proving the endpoint never 500s when GM is off).
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
from app.routers import glitter as glitter_mod  # noqa: E402
from app.routers import symptomlog as symptomlog_mod  # noqa: E402

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
    models.SymptomLogEntry.__table__,
    models.AuditLog.__table__,
]

for _t in _TABLES:  # gen_random_uuid() → client-side uuid4 (idempotent)
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())


# ── Seed identities ──────────────────────────────────────────────────────────
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
COND_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")   # A, DC 9411 (has KB card)
COND_NODC = uuid.UUID("00000000-0000-0000-0000-000000000012")   # A, no diagnostic code
COND_UNKNOWN = uuid.UUID("00000000-0000-0000-0000-000000000013")  # A, DC with no KB card
COND_B = uuid.UUID("00000000-0000-0000-0000-000000000021")      # B's condition

_RATING_CARD_DATA = {
    "tiers": [
        {
            "percent": 70,
            "criteria": (
                "Occupational and social impairment with deficiencies in most areas; "
                "suicidal ideation; near-continuous panic; neglect of personal appearance"
            ),
        },
        {
            "percent": 50,
            "criteria": (
                "Reduced reliability and productivity due to flattened affect; "
                "panic attacks more than once a week, or difficulty understanding "
                "complex commands"
            ),
        },
    ]
}


# ── Environment fixture ──────────────────────────────────────────────────────
@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'symptomlog_test.db'}",
        poolclass=NullPool,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

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
                    models.ClaimedCondition(id=COND_PTSD, user_id=USER_A,
                                            name="PTSD", diagnostic_code="9411",
                                            claim_type="direct"),
                    models.ClaimedCondition(id=COND_NODC, user_id=USER_A,
                                            name="Tinnitus", claim_type="direct"),
                    models.ClaimedCondition(id=COND_UNKNOWN, user_id=USER_A,
                                            name="Mystery", diagnostic_code="0000",
                                            claim_type="direct"),
                    models.ClaimedCondition(id=COND_B, user_id=USER_B,
                                            name="PTSD (other veteran)",
                                            diagnostic_code="9411",
                                            claim_type="direct"),
                    models.KBCard(
                        card_type="rating_criteria",
                        title="Mental disorders — General Rating Formula",
                        diagnostic_code="9411",
                        source="38 CFR §4.130",
                        content="General rating formula for mental disorders.",
                        data=_RATING_CARD_DATA,
                    ),
                ]
            )
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(symptomlog_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    current = {"uid": str(USER_A)}
    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current)


def _create(client, **overrides):
    body = {
        "entry_date": "2026-01-10",
        "title": "Bad flare-up",
        "symptoms": "Severe panic attacks and insomnia all week.",
        "severity": 7,
        "functional_impact": "Could not go to work two days.",
    }
    body.update(overrides)
    return client.post("/api/symptomlog", json=body)


# ═══ CRUD ════════════════════════════════════════════════════════════════════
def test_create_list_patch_delete(env):
    resp = _create(env.client, condition_id=str(COND_PTSD))
    assert resp.status_code == 201, resp.text
    entry = resp.json()
    assert entry["source"] == "manual"
    assert entry["condition_id"] == str(COND_PTSD)
    assert entry["severity"] == 7
    eid = entry["id"]

    # Second entry, older date → newest-first ordering.
    _create(env.client, entry_date="2025-12-01", title="Earlier note")
    listed = env.client.get("/api/symptomlog").json()
    assert [e["title"] for e in listed] == ["Bad flare-up", "Earlier note"]

    # Condition filter.
    filtered = env.client.get(f"/api/symptomlog?condition_id={COND_PTSD}").json()
    assert [e["id"] for e in filtered] == [eid]

    # Partial patch.
    patched = env.client.patch(
        f"/api/symptomlog/{eid}", json={"severity": 9, "criteria_tags": ["panic attacks"]}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["severity"] == 9
    assert patched.json()["criteria_tags"] == ["panic attacks"]
    assert patched.json()["title"] == "Bad flare-up"  # unchanged

    # Delete → gone.
    assert env.client.delete(f"/api/symptomlog/{eid}").status_code == 204
    assert env.client.get(f"/api/symptomlog?condition_id={COND_PTSD}").json() == []


def test_create_rejects_foreign_condition(env):
    resp = _create(env.client, condition_id=str(COND_B))
    assert resp.status_code == 404


def test_cross_user_404_isolation(env):
    eid = _create(env.client).json()["id"]

    env.current["uid"] = str(USER_B)
    assert env.client.get("/api/symptomlog").json() == []  # B sees nothing
    assert env.client.patch(f"/api/symptomlog/{eid}", json={"severity": 1}).status_code == 404
    assert env.client.delete(f"/api/symptomlog/{eid}").status_code == 404

    env.current["uid"] = str(USER_A)
    assert len(env.client.get("/api/symptomlog").json()) == 1


def test_create_validation_422(env):
    # Empty title / empty symptoms / off-range severity all fail the schema.
    assert _create(env.client, title="").status_code == 422
    assert _create(env.client, symptoms="").status_code == 422
    assert _create(env.client, severity=11).status_code == 422


# ═══ §4 criteria chips ═══════════════════════════════════════════════════════
def test_criteria_returns_tier_phrases_for_known_dc(env):
    body = env.client.get(f"/api/symptomlog/criteria?condition_id={COND_PTSD}").json()
    assert body["diagnostic_code"] == "9411"
    assert body["condition_name"] == "PTSD"
    tiers = {t["percent"]: t["criteria"] for t in body["tiers"]}
    assert set(tiers) == {70, 50}
    # The single criteria sentence is split into concise chips on "; or" / ", or".
    assert "suicidal ideation" in tiers[70]
    assert any("panic" in c.lower() for c in tiers[70])
    # ", or difficulty understanding complex commands" becomes its own chip.
    assert any(c.lower().startswith("difficulty understanding") for c in tiers[50])
    # No chip carries a trailing separator.
    assert all(";" not in c for tier in tiers.values() for c in tier)


def test_criteria_empty_for_unknown_dc(env):
    body = env.client.get(f"/api/symptomlog/criteria?condition_id={COND_UNKNOWN}").json()
    assert body["diagnostic_code"] == "0000"
    assert body["tiers"] == []


def test_criteria_empty_when_no_dc_or_no_condition(env):
    no_dc = env.client.get(f"/api/symptomlog/criteria?condition_id={COND_NODC}").json()
    assert no_dc["tiers"] == [] and no_dc["diagnostic_code"] is None
    # No condition at all → empty, never an error.
    none = env.client.get("/api/symptomlog/criteria").json()
    assert none["tiers"] == [] and none["condition_name"] is None
    # Another veteran's condition id → treated as absent (no leak, no error).
    foreign = env.client.get(f"/api/symptomlog/criteria?condition_id={COND_B}").json()
    assert foreign["tiers"] == [] and foreign["condition_name"] is None


# ═══ Export lay statement ════════════════════════════════════════════════════
def test_export_markdown_contains_entries_and_signature(env):
    _create(env.client, condition_id=str(COND_PTSD), entry_date="2026-01-10",
            title="January flare", symptoms="Panic attacks daily.",
            functional_impact="Missed work.")
    _create(env.client, condition_id=str(COND_PTSD), entry_date="2025-11-02",
            title="November baseline", symptoms="Trouble sleeping.")

    body = env.client.get(f"/api/symptomlog/export?condition_id={COND_PTSD}").json()
    assert body["entries_count"] == 2
    assert body["condition_name"] == "PTSD"
    md = body["markdown"]
    assert "Statement in Support of Claim" in md
    assert "January flare" in md and "November baseline" in md
    assert "Panic attacks daily." in md
    assert "review and signature" in md.lower()
    assert "**Signature:**" in md
    # Chronological: the November entry precedes the January one.
    assert md.index("November baseline") < md.index("January flare")


def test_export_empty_log_still_returns_statement(env):
    body = env.client.get("/api/symptomlog/export").json()
    assert body["entries_count"] == 0
    assert "**Signature:**" in body["markdown"]


# ═══ Glitter Mane import ═════════════════════════════════════════════════════
_GM_CHECKINS = [
    {"id": 1, "pain": 8, "symptoms": "Migraine, light sensitivity",
     "note": "Missed a shift", "created_at": "2026-02-01T09:00:00Z"},
    {"id": 2, "pain": 3, "symptoms": "Ringing in ears", "note": "",
     "created_at": "2026-02-03T20:00:00Z"},
]


def test_import_from_glitter_persists_entries(env, monkeypatch):
    async def fake_email(db, uid):
        return "alex@example.com"

    async def fake_continuity(email, condition=None):
        assert email == "alex@example.com"
        return _GM_CHECKINS

    monkeypatch.setattr(glitter_mod, "_user_email", fake_email)
    monkeypatch.setattr(glitter_mod, "fetch_continuity", fake_continuity)

    resp = env.client.post("/api/symptomlog/import-from-glitter")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["imported"] == 2
    assert len(body["entries"]) == 2
    assert all(e["source"] == "glitter" for e in body["entries"])
    severities = {e["severity"] for e in body["entries"]}
    assert severities == {8, 3}

    # They landed in the log, tagged glitter.
    logged = env.client.get("/api/symptomlog").json()
    assert len(logged) == 2
    assert any("Glitter Mane check-in" in e["title"] for e in logged)

    # Idempotent: a re-pull imports nothing new (no duplicates).
    again = env.client.post("/api/symptomlog/import-from-glitter").json()
    assert again["imported"] == 0
    assert len(env.client.get("/api/symptomlog").json()) == 2


def test_import_from_glitter_degrades_when_bridge_off(env, monkeypatch):
    async def fake_email(db, uid):
        return "alex@example.com"

    async def boom(email, condition=None):
        raise RuntimeError("Glitter Mane bridge is not configured")

    monkeypatch.setattr(glitter_mod, "_user_email", fake_email)
    monkeypatch.setattr(glitter_mod, "fetch_continuity", boom)

    resp = env.client.post("/api/symptomlog/import-from-glitter")
    assert resp.status_code == 200  # never 500
    body = resp.json()
    assert body["imported"] == 0
    assert body["entries"] == []
    assert body["detail"]
    assert env.client.get("/api/symptomlog").json() == []


# ═══ Auth posture ════════════════════════════════════════════════════════════
def test_requires_auth():
    app = FastAPI()
    app.include_router(symptomlog_mod.router, prefix="/api")
    client = TestClient(app)
    assert client.get("/api/symptomlog").status_code in (401, 403)
    assert client.get("/api/symptomlog/export").status_code in (401, 403)
