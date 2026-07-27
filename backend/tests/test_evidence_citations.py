"""Evidence rationale/citation tests — deterministic helpers plus router smoke.

The pure tests pin the kind→element mapping, the chunk ranking, and the
char-offset→page lookup. The API test exercises the actual evidence read,
citation pinning, and packet index assembly end-to-end on SQLite.
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
from pgvector.sqlalchemy import Vector  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import models  # noqa: E402
from app.db import Base  # noqa: E402
from app.evidence_rationale import evidence_rationale, page_for_char_offset, rank_chunk_rows  # noqa: E402
from app.models import DocumentChunk  # noqa: E402
from app.routers import evidence as evidence_router  # noqa: E402
from app.routers import packet as packet_router  # noqa: E402


@compiles(PGUUID, "sqlite")
def _pg_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


@compiles(Vector, "sqlite")
def _vector_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "TEXT"


TABLES = [
    models.User.__table__,
    models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__,
    models.EvidenceItem.__table__,
    models.EvidenceCitation.__table__,
    models.Document.__table__,
    models.DocumentChunk.__table__,
    models.AuditLog.__table__,
    models.KBCard.__table__,
]

for _t in TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())

USER = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
COND = uuid.UUID("00000000-0000-0000-0000-000000000011")
DOC = uuid.UUID("00000000-0000-0000-0000-000000000101")
EVIDENCE = uuid.UUID("00000000-0000-0000-0000-000000000201")


def test_rationale_mapping_and_helpers():
    diagnosis = evidence_rationale("diagnosis")
    assert diagnosis["elements"] == ["current_disability"]
    assert "current, diagnosed disability" in diagnosis["why"]

    chunks = [
        type("Chunk", (), {"content": "Service record: unrelated visit", "chunk_index": 0, "char_start": 0})(),
        type("Chunk", (), {"content": "PTSD diagnosis recorded in treatment notes", "chunk_index": 1, "char_start": 120})(),
        type("Chunk", (), {"content": "A later continuity note", "chunk_index": 2, "char_start": 240})(),
    ]
    ranked = rank_chunk_rows(chunks, ["ptsd", "current_disability"], k=2)
    assert [c.chunk_index for c in ranked] == [1]
    assert page_for_char_offset([0, 120, 240], 121) == 2
    assert page_for_char_offset(None, 50) is None


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'evidence_test.db'}",
        poolclass=NullPool,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async def test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=TABLES)
        async with Session() as session:
            session.add_all(
                [
                    models.User(id=USER, email="test@example.com", password_hash="x", full_name="Tester"),
                    models.ClaimedCondition(id=COND, user_id=USER, name="PTSD", claim_type="direct"),
                    models.Document(
                        id=DOC,
                        user_id=USER,
                        filename="record.txt",
                        content_type="text/plain",
                        size_bytes=128,
                        sha256="abc123",
                        status="ready",
                        title="Treatment Record",
                        text_content="Service record: unrelated visit.\n\nPTSD diagnosis recorded in treatment notes.",
                        page_offsets=[0, 33],
                        file_ref="/tmp/record.txt",
                    ),
                    models.DocumentChunk(
                        user_id=USER,
                        document_id=DOC,
                        chunk_index=0,
                        content="Service record: unrelated visit.",
                        char_start=0,
                        char_end=33,
                    ),
                    models.DocumentChunk(
                        user_id=USER,
                        document_id=DOC,
                        chunk_index=1,
                        content="PTSD diagnosis recorded in treatment notes.",
                        char_start=35,
                        char_end=78,
                    ),
                    models.EvidenceItem(
                        id=EVIDENCE,
                        user_id=USER,
                        condition_id=COND,
                        kind="diagnosis",
                        title="Diagnosis note",
                        status="have",
                        file_ref="/tmp/record.txt",
                    ),
                ]
            )
            await session.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(evidence_router.router, prefix="/api")
    app.include_router(packet_router.router, prefix="/api")
    app.dependency_overrides[evidence_router.current_user_id] = lambda: str(USER)
    app.dependency_overrides[evidence_router.get_db] = test_db
    app.dependency_overrides[packet_router.current_user_id] = lambda: str(USER)
    app.dependency_overrides[packet_router.get_db] = test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client)


def test_evidence_read_includes_rationale_and_citation(env):
    body = env.client.get(f"/api/conditions/{COND}/evidence").json()
    assert len(body) == 1
    item = body[0]
    assert item["rationale"]["elements"] == ["current_disability"]
    assert item["citations"][0]["selected"] is True
    assert item["citations"][0]["page"] == 2
    assert "PTSD diagnosis recorded" in item["citations"][0]["quote"]


def test_pin_citation_and_packet_index(env):
    evidence = env.client.get(f"/api/conditions/{COND}/evidence").json()[0]
    chosen = evidence["citations"][0]
    pin = env.client.post(
        f"/api/evidence/{evidence['id']}/citation",
        json={
            "quote": chosen["quote"],
            "char_start": chosen["char_start"],
            "char_end": chosen["char_end"],
            "page": chosen["page"],
            "chunk_index": chosen["chunk_index"],
            "note": "Use this quote",
        },
    )
    assert pin.status_code == 200
    pinned = pin.json()
    assert pinned["citations"][0]["selected"] is True
    assert pinned["citations"][0]["note"] == "Use this quote"

    packet = env.client.get(f"/api/packet/{COND}").json()
    assert len(packet["evidence_index"]) == 1
    idx = packet["evidence_index"][0]
    selected = next(c for c in idx["citations"] if c["selected"])
    assert selected["page"] == 2
    assert selected["note"] == "Use this quote"
