"""M1 — doc-type 'what to upload' guidance: pure data + the API endpoint.

Pure-function tests exercise `guidance_for` / `DOC_TYPE_GUIDANCE` directly (no
Postgres). The endpoint test follows the same in-memory-SQLite harness pattern
as test_api_documents.py — a minimal FastAPI app with the real documents
router and dependency overrides standing in for auth.
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

from app import deps  # noqa: E402
from app.intake.classify import DOC_TYPES  # noqa: E402
from app.intake.doc_guidance import DOC_TYPE_GUIDANCE, guidance_for  # noqa: E402
from app.routers import documents as documents_mod  # noqa: E402

# ── SQLite shims (test-only; the app itself always runs on Postgres) ─────────


@compiles(PGUUID, "sqlite")
def _pg_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


# ═══ Pure data ════════════════════════════════════════════════════════════
def test_every_doc_type_has_non_empty_guidance():
    assert set(DOC_TYPE_GUIDANCE) == set(DOC_TYPES)
    for doc_type in DOC_TYPES:
        entry = DOC_TYPE_GUIDANCE[doc_type]
        assert entry["label"].strip()
        assert entry["what_it_is"].strip()
        assert entry["why_it_helps"].strip()
        assert isinstance(entry["what_to_upload"], list)
        assert 2 <= len(entry["what_to_upload"]) <= 4
        for example in entry["what_to_upload"]:
            assert isinstance(example, str) and example.strip()


def test_guidance_for_known_type_matches_map():
    assert guidance_for("dbq") == DOC_TYPE_GUIDANCE["dbq"]
    assert guidance_for("rating_decision") == DOC_TYPE_GUIDANCE["rating_decision"]


def test_guidance_for_unknown_type_returns_safe_default():
    fallback = guidance_for("nonsense")
    assert fallback["label"].strip()
    assert fallback["what_it_is"].strip()
    assert fallback["why_it_helps"].strip()
    assert isinstance(fallback["what_to_upload"], list) and fallback["what_to_upload"]
    # None and non-string inputs degrade the same way — never raises.
    assert guidance_for(None) == fallback
    assert guidance_for(123) == fallback  # type: ignore[arg-type]


def test_guidance_content_avoids_outcome_promises():
    """Legal lane: educational content, never a promised rating/outcome."""
    banned_phrases = ("you will get", "guarantees", "guaranteed rating")
    for entry in DOC_TYPE_GUIDANCE.values():
        blob = " ".join(
            [entry["what_it_is"], entry["why_it_helps"], *entry["what_to_upload"]]
        ).lower()
        for phrase in banned_phrases:
            assert phrase not in blob


# ═══ API endpoint ═════════════════════════════════════════════════════════
@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'guidance_test.db'}",
        poolclass=NullPool,
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)

    app = FastAPI()
    app.include_router(documents_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            yield session

    app.dependency_overrides[deps.current_user_id] = lambda: str(USER_A)
    app.dependency_overrides[deps.current_workspace_id] = lambda: str(USER_A)
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client)


def test_upload_guidance_endpoint_returns_all_types(env):
    resp = env.client.get("/api/documents/upload-guidance")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    guidance = body["guidance"]
    assert set(guidance) == set(DOC_TYPES)
    for doc_type in DOC_TYPES:
        entry = guidance[doc_type]
        assert entry["label"] == DOC_TYPE_GUIDANCE[doc_type]["label"]
        assert entry["what_to_upload"]


def test_upload_guidance_requires_auth():
    app = FastAPI()
    app.include_router(documents_mod.router, prefix="/api")
    client = TestClient(app)
    assert client.get("/api/documents/upload-guidance").status_code in (401, 403)
