"""WAVE9 — account data portability (export) + erasure (delete). SQLite harness;
verifies export gathers the veteran's data (and excludes secrets), delete requires
a matching email and cascades to every user-owned table + isolates across users.
"""

from __future__ import annotations

import uuid
import io
import json
import zipfile
import asyncio
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event, select  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import deps, models  # noqa: E402
from app.db import Base  # noqa: E402
from app.routers import account as account_mod  # noqa: E402

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
    models.User.__table__, models.Organization.__table__,
    models.OrganizationMember.__table__, models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__, models.EvidenceItem.__table__,
    models.Document.__table__, models.EvidenceCitation.__table__,
    models.ChecklistItem.__table__, models.RatingScenario.__table__,
    models.SymptomLogEntry.__table__, models.ItfRecord.__table__,
    models.DocumentFact.__table__, models.DocumentChunk.__table__,
    models.GamePlanBriefingCache.__table__, models.GamePlanFirmCache.__table__,
    models.CFilePictureCache.__table__, models.AnalysisRun.__table__,
    models.CreditBalance.__table__, models.CreditTransaction.__table__,
    models.GrantApplication.__table__, models.Sponsorship.__table__,
    models.VaConnection.__table__, models.AuditLog.__table__,
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
C_A = uuid.UUID("00000000-0000-0000-0000-000000000011")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'acc.db'}", poolclass=NullPool)

    # SQLite ignores ON DELETE CASCADE unless FK enforcement is on — turn it on so
    # this test actually exercises the cascade the Postgres schema relies on.
    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(UA)}
    upload_dir = (tmp_path / "uploads").resolve()
    user_dir = upload_dir / str(UA)
    user_dir.mkdir(parents=True)
    original = user_dir / "claim-record.txt"
    original.write_bytes(b"de-identified claim record")
    monkeypatch.setattr(account_mod, "UPLOAD_DIR", upload_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            # FK enforcement is ON → commit parents before children.
            s.add_all([
                models.User(id=UA, email="Alex@Example.test", password_hash="secret-hash",
                            full_name="Alex V"),
                models.User(id=UB, email="blair@example.test", password_hash="x", full_name="Blair O"),
            ])
            await s.commit()
            s.add_all([
                models.VeteranProfile(user_id=UA, current_combined_rating=40,
                                      service_periods=[], exposures={}),
                models.ClaimedCondition(id=C_A, user_id=UA, name="PTSD", claim_type="direct"),
                models.ClaimedCondition(user_id=UB, name="Back strain", claim_type="direct"),
                models.Document(
                    user_id=UA,
                    filename="claim-record.txt",
                    content_type="text/plain",
                    size_bytes=original.stat().st_size,
                    sha256="archive-source",
                    status="ready",
                    text_content="de-identified claim record",
                    file_ref=str(original),
                ),
            ])
            await s.commit()
            s.add(models.EvidenceItem(user_id=UA, condition_id=C_A, kind="diagnosis",
                                      title="Dx", status="have"))
            s.add(models.ItfRecord(user_id=UA, type="compensation", filed_date=date.today()))
            s.add(models.VaConnection(
                user_id=UA,
                provider="lighthouse",
                api="verification",
                access_token="encrypted-access-secret",
                refresh_token="encrypted-refresh-secret",
            ))
            s.add(models.AuditLog(
                user_id=UA,
                actor_user_id=UB,
                actor_label="blair@example.test",
                action="case.reviewed",
            ))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(account_mod.router, prefix="/api")

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
        yield SimpleNamespace(
            client=client,
            current=current,
            Session=Session,
            original=original,
            upload_dir=upload_dir,
        )


def test_export_gathers_data_and_excludes_secrets(env):
    r = env.client.get("/api/account/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert "rating-raider-my-data" in r.headers["content-disposition"]
    body = r.json()
    assert body["account"]["email"] == "Alex@Example.test"
    assert body["profile"]["current_combined_rating"] == 40
    assert [c["name"] for c in body["conditions"]] == ["PTSD"]
    assert len(body["evidence"]) == 1
    assert len(body["intent_to_file"]) == 1
    assert body["export_version"] == 2
    assert len(body["va_connections"]) == 1
    assert "access_token" not in body["va_connections"][0]
    assert "refresh_token" not in body["va_connections"][0]
    assert len(body["activity_history"]) == 1
    assert "actor_label" not in body["activity_history"][0]
    assert "actor_user_id" not in body["activity_history"][0]
    assert body["document_chunks"] == []
    assert body["documents"] and "file_ref" not in body["documents"][0]
    assert str(env.upload_dir) not in r.text
    # No password hash / secrets anywhere in the export.
    assert "secret-hash" not in r.text
    assert "encrypted-access-secret" not in r.text
    assert "encrypted-refresh-secret" not in r.text
    assert "blair@example.test" not in r.text
    assert "password_hash" not in r.text


def test_archive_contains_portable_json_and_user_originals(env):
    response = env.client.get("/api/account/export/archive")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/zip")
    assert response.headers["cache-control"] == "private, no-store"

    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        names = bundle.namelist()
        assert "rating-raider-data.json" in names
        original_name = next(name for name in names if name.endswith("/claim-record.txt"))
        assert ".." not in original_name
        assert bundle.read(original_name) == b"de-identified claim record"
        payload = json.loads(bundle.read("rating-raider-data.json"))
        assert payload["conditions"][0]["name"] == "PTSD"
        assert "file_ref" not in payload["documents"][0]


def test_archive_rejects_over_limit_instead_of_truncating(env, monkeypatch):
    monkeypatch.setattr(account_mod.settings, "account_export_max_bytes", 1)
    response = env.client.get("/api/account/export/archive")
    assert response.status_code == 413
    assert "JSON-only" in response.json()["detail"]


def test_archive_rejects_unconfined_original(env, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"not this account's confined upload")

    async def _move_reference():
        async with env.Session() as session:
            document = (await session.execute(select(models.Document))).scalar_one()
            document.file_ref = str(outside)
            await session.commit()

    asyncio.run(_move_reference())
    response = env.client.get("/api/account/export/archive")
    assert response.status_code == 409
    assert "could not include" in response.json()["detail"]


def test_export_is_user_scoped(env):
    env.current["uid"] = str(UB)
    body = env.client.get("/api/account/export").json()
    assert [c["name"] for c in body["conditions"]] == ["Back strain"]
    import json
    assert "PTSD" not in json.dumps(body)


def test_delete_requires_matching_email(env):
    # Wrong email → 400, nothing deleted (A's data still exports).
    r = env.client.request("DELETE", "/api/account", json={"confirm_email": "nope@x.test"})
    assert r.status_code == 400
    assert env.client.get("/api/account/export").json()["conditions"]  # still there
    # Case-insensitive match on the real email → 204.
    r = env.client.request("DELETE", "/api/account", json={"confirm_email": "alex@example.test"})
    assert r.status_code == 204


def test_delete_cascades_and_isolates(env):
    # Delete A's account.
    r = env.client.request("DELETE", "/api/account", json={"confirm_email": "alex@example.test"})
    assert r.status_code == 204

    # A is fully erased — export now finds no user, no conditions, no evidence (the
    # cascade fired: children are gone, not orphaned).
    a = env.client.get("/api/account/export").json()
    assert a["account"]["email"] is None
    assert a["conditions"] == [] and a["evidence"] == [] and a["intent_to_file"] == []
    assert a["profile"] is None

    # B is untouched.
    env.current["uid"] = str(UB)
    b = env.client.get("/api/account/export").json()
    assert b["account"]["email"] == "blair@example.test"
    assert [c["name"] for c in b["conditions"]] == ["Back strain"]
