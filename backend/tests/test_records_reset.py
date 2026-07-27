"""POST /documents/reset — the veteran's right-to-erasure of their C-file and the
clean slate for a cold-run benchmark.

Verifies: confirm is mandatory (no accidental wipe); every C-file-derived table is
cleared and the counts returned are exact; a SECOND user's rows and the caller's own
PRESERVED account state (profile, ITF deadlines) are untouched.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import deps, models  # noqa: E402
from app.db import Base  # noqa: E402
from app.routers import documents as documents_mod  # noqa: E402

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
    models.User.__table__, models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__, models.EvidenceItem.__table__,
    models.EvidenceCitation.__table__, models.RatingScenario.__table__,
    models.ChecklistItem.__table__, models.ItfRecord.__table__,
    models.Document.__table__, models.DocumentFact.__table__,
    models.DocumentChunk.__table__, models.KBCard.__table__,
    models.GamePlanFirmCache.__table__, models.GamePlanBriefingCache.__table__,
    models.CFilePictureCache.__table__, models.AuditLog.__table__,
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
WS = uuid.UUID("00000000-0000-0000-0000-0000000000c3")


def _count(Session, model, user_id) -> int:
    async def _go():
        async with Session() as s:
            return int(
                (await s.execute(
                    select(func.count()).select_from(model).where(model.user_id == user_id)
                )).scalar() or 0
            )
    return asyncio.run(_go())


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}", poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(UA)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=UA, email="a@e.test", password_hash="x", full_name="Alex V"),
                models.User(id=UB, email="b@e.test", password_hash="x", full_name="Blair O"),
                models.VeteranProfile(user_id=UA, current_combined_rating=50,
                                      service_periods=[{"branch": "Army"}], exposures={},
                                      identity={"full_name": "Alex V", "file_number": "9"},
                                      dependents={"spouse": True}),
                # An ITF deadline is PRESERVED account state, not a C-file record.
                models.ItfRecord(user_id=UA, filed_date=date(2026, 1, 1)),
            ])
            await s.commit()
            # UA's C-file + everything derived from it.
            cond = models.ClaimedCondition(user_id=UA, name="PTSD", claim_type="direct")
            doc = models.Document(user_id=UA, filename="rd.pdf", sha256="h1",
                                  size_bytes=10, status="ready")
            s.add_all([cond, doc])
            await s.commit()
            ev = models.EvidenceItem(user_id=UA, condition_id=cond.id, kind="diagnosis",
                                     title="Dx", status="have")
            s.add(ev)
            await s.commit()
            s.add_all([
                models.EvidenceCitation(evidence_id=ev.id, user_id=UA, document_id=doc.id,
                                        quote="q", char_start=0, char_end=1),
                models.DocumentFact(user_id=UA, document_id=doc.id, segment_index=0,
                                    facts={"conditions": []}),
                models.DocumentChunk(user_id=UA, document_id=doc.id, chunk_index=0, content="c"),
                models.RatingScenario(user_id=UA, name="what-if", entries=[]),
                models.ChecklistItem(user_id=UA, condition_id=cond.id, text="do a thing"),
                models.GamePlanBriefingCache(user_id=UA, facts_hash="f", payload={}),
                models.GamePlanFirmCache(user_id=UA, facts_hash="f", payload={}),
                models.CFilePictureCache(user_id=UA, facts_hash="f", payload={}),
                # UB's condition — must survive UA's reset.
                models.ClaimedCondition(user_id=UB, name="Back strain", claim_type="direct"),
            ])
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(documents_mod.router, prefix="/api")
    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.current_workspace_id] = lambda: str(WS)

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current, Session=Session)


def test_reset_requires_confirmation(env):
    # No confirm → 400 and NOTHING deleted.
    assert env.client.post("/api/documents/reset", json={}).status_code == 400
    assert env.client.post("/api/documents/reset", json={"confirm": False}).status_code == 400
    assert _count(env.Session, models.Document, UA) == 1
    assert _count(env.Session, models.ClaimedCondition, UA) == 1


def test_reset_clears_every_derived_table_with_exact_counts(env):
    r = env.client.post("/api/documents/reset", json={"confirm": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {
        "documents": 1, "facts": 1, "chunks": 1, "conditions": 1, "evidence": 1,
        "citations": 1, "scenarios": 1, "checklist": 1, "caches": 3,
    }
    # Every derived table for UA is now empty.
    for model in (models.Document, models.DocumentFact, models.DocumentChunk,
                  models.ClaimedCondition, models.EvidenceItem, models.EvidenceCitation,
                  models.RatingScenario, models.ChecklistItem,
                  models.GamePlanBriefingCache, models.GamePlanFirmCache,
                  models.CFilePictureCache):
        assert _count(env.Session, model, UA) == 0, model.__name__


def test_reset_preserves_account_state_and_other_users(env):
    env.client.post("/api/documents/reset", json={"confirm": True})
    # PRESERVED: the caller's profile ROW + ITF deadline are account state, not records.
    assert _count(env.Session, models.VeteranProfile, UA) == 1
    assert _count(env.Session, models.ItfRecord, UA) == 1
    # UB's condition is untouched — reset is strictly the caller's own rows.
    assert _count(env.Session, models.ClaimedCondition, UB) == 1


def test_reset_clears_document_extracted_profile_pii_but_keeps_onboarding(env):
    env.client.post("/api/documents/reset", json={"confirm": True})

    async def _profile():
        async with env.Session() as s:
            return (
                await s.execute(select(models.VeteranProfile).where(models.VeteranProfile.user_id == UA))
            ).scalar_one()

    p = asyncio.run(_profile())
    # Document-EXTRACTED PII is wiped (it came from the erased C-file).
    assert p.identity is None
    assert p.dependents is None
    # Onboarding inputs the veteran entered themselves survive.
    assert p.current_combined_rating == 50
    assert p.service_periods == [{"branch": "Army"}]
