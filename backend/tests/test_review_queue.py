"""Phase 3 review queue (end-to-end, in-memory SQLite; the LLM is never called).

Covers the extract-verify review surface: the flagged-document queue, the review
detail (which value the machine took vs. what the record shows), and reconcile
(the veteran writes the corrected tuple and clears the flag). Plus the pipeline
integration: with the extract-verify pass enabled and its model seam monkeypatched
to DISPUTE a percent, an uploaded document lands `ready` but `flagged` — the
disputed value is never silently persisted. RLS can't run on SQLite, so cross-user
isolation exercises the routers' explicit user_id defense-in-depth.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import deps, models, overrides as overrides_mod  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.intake import process as process_mod  # noqa: E402
from app.intake.classify import validate_extraction  # noqa: E402
from app.routers import documents as documents_mod  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover
    Vector = None


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


TABLES = [
    models.User.__table__,
    models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__,
    models.EvidenceItem.__table__,
    models.Document.__table__,
    models.DocumentChunk.__table__,
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
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
DOC_FLAGGED = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
DOC_CLEAN = uuid.UUID("00000000-0000-0000-0000-0000000000c1")

# A pre-flagged document (the shape intake writes when extract-verify disputes a
# value): PTSD's percent is disputed (record shows 70, machine took 50), and a
# missed condition (sleep apnea) is on the recall list.
FLAGGED_EXTRACTED = {
    "doc_type": "rating_decision",
    "conditions_mentioned": [
        {"name": "PTSD", "rating_percent": 50, "diagnostic_code": "9411", "decision": "granted"},
        {"name": "Tinnitus", "rating_percent": 10, "diagnostic_code": "6260", "decision": "granted"},
    ],
    "review": {
        "status": "flagged",
        "fields": [
            {
                "field_id": "0:rating_percent", "index": 0, "condition": "PTSD",
                "field": "rating_percent", "extracted_value": 50, "candidate_value": 70,
                "status": "disputed", "span": "PTSD is evaluated at 70 percent", "source": "verify",
            }
        ],
        "conditions": [],
        "missing_conditions": [{"name": "Sleep apnea", "span": "sleep apnea diagnosed on the 2020 study"}],
        "crossread": None,
    },
}

# For the pipeline test: classify returns PTSD@50, but the stored text says 70.
_PIPELINE_CANNED = {
    "doc_type": "rating_decision", "doc_date": "2019-03-14", "title": "Rating Decision",
    "summary": "PTSD.", "is_va_decision": True,
    "conditions_mentioned": [{"name": "PTSD", "rating_percent": 50, "diagnostic_code": "9411", "decision": "granted"}],
}


async def _canned_classify(text: str):
    return validate_extraction(_PIPELINE_CANNED)


async def _disputing_verify(text: str, extracted: dict, *, model: str):
    # The record actually says 70 percent; the extraction took 50 → a real dispute
    # (the span is a genuine substring of the uploaded text).
    return {"conditions": [{"name": "PTSD", "span": "PTSD granted at 70 percent"}]}


async def _fake_privacy_mode(db):
    return False


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'review_test.db'}", poolclass=NullPool
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

    monkeypatch.setattr(process_mod, "user_session", test_user_session)
    monkeypatch.setattr(documents_mod, "UPLOAD_DIR", tmp_path)
    current = {"uid": str(USER_A)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=TABLES)
        async with Session() as s:
            s.add_all(
                [
                    models.User(id=USER_A, email="alex@example.com", password_hash="x", full_name="Alex"),
                    models.User(id=USER_B, email="blair@example.com", password_hash="x", full_name="Blair"),
                    models.Document(
                        id=DOC_FLAGGED, user_id=USER_A, filename="decision.pdf",
                        content_type="application/pdf", size_bytes=10, sha256="f" * 64,
                        status="ready", review_status="flagged", doc_type="rating_decision",
                        title="VA Rating Decision", extracted=FLAGGED_EXTRACTED,
                    ),
                    models.Document(
                        id=DOC_CLEAN, user_id=USER_A, filename="clean.pdf",
                        content_type="application/pdf", size_bytes=10, sha256="c" * 64,
                        status="ready", review_status="clear", doc_type="treatment_record",
                        title="Treatment note", extracted={"conditions_mentioned": []},
                    ),
                ]
            )
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
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
    app.dependency_overrides[deps.current_workspace_id] = lambda: current["uid"]
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current)


# ── Queue + detail ───────────────────────────────────────────────────────────
def test_review_queue_lists_flagged_documents(env):
    rows = env.client.get("/api/documents/review-queue").json()
    assert len(rows) == 1
    item = rows[0]
    assert item["id"] == str(DOC_FLAGGED)
    assert item["review_status"] == "flagged"
    assert item["fields_pending"] == 1
    assert item["missing_conditions"] == 1
    # The clean document is NOT in the queue.
    assert str(DOC_CLEAN) not in [r["id"] for r in rows]


def test_review_detail_shows_the_disagreement(env):
    body = env.client.get(f"/api/documents/{DOC_FLAGGED}/review").json()
    assert body["review_status"] == "flagged"
    f = body["fields"][0]
    assert f["field"] == "rating_percent"
    assert f["extracted_value"] == 50 and f["candidate_value"] == 70
    assert f["status"] == "disputed"
    assert body["missing_conditions"][0]["name"] == "Sleep apnea"


# ── Reconcile ────────────────────────────────────────────────────────────────
def test_reconcile_clear_document_resolves_without_500(env):
    """Clear flag and continue — must not UnboundLocalError on audit `dismiss`."""
    resp = env.client.post(
        f"/api/documents/{DOC_FLAGGED}/reconcile",
        json={"resolutions": [], "dismiss_missing": [], "clear_document": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["review_status"] == "resolved"
    assert env.client.get("/api/documents/review-queue").json() == []


def test_reconcile_writes_the_corrected_tuple_and_clears_the_flag(env):
    resp = env.client.post(
        f"/api/documents/{DOC_FLAGGED}/reconcile",
        json={
            "resolutions": [{"field_id": "0:rating_percent", "value": 70}],
            "dismiss_missing": ["Sleep apnea"],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied"] == 1
    assert body["review_status"] == "resolved"
    # The corrected value is written onto the tuple.
    ptsd = next(c for c in body["conditions_mentioned"] if c["name"] == "PTSD")
    assert ptsd["rating_percent"] == 70

    # It's out of the queue, and the document reflects resolved.
    assert env.client.get("/api/documents/review-queue").json() == []
    detail = env.client.get(f"/api/documents/{DOC_FLAGGED}").json()
    assert detail["review_status"] == "resolved"
    assert detail["extracted"]["conditions_mentioned"][0]["rating_percent"] == 70


def test_reconcile_off_grid_value_is_rejected_by_the_reused_cleaner(env):
    # 55 isn't a multiple of 10 → the reused _clean_percent nulls it (never persisted).
    resp = env.client.post(
        f"/api/documents/{DOC_FLAGGED}/reconcile",
        json={"resolutions": [{"field_id": "0:rating_percent", "value": 55}]},
    )
    body = resp.json()
    ptsd = next(c for c in body["conditions_mentioned"] if c["name"] == "PTSD")
    assert ptsd["rating_percent"] is None


def test_partial_reconcile_stays_flagged(env):
    # Resolve the field but leave the missing-condition note → still pending.
    resp = env.client.post(
        f"/api/documents/{DOC_FLAGGED}/reconcile",
        json={"resolutions": [{"field_id": "0:rating_percent", "value": 70}]},
    )
    assert resp.json()["review_status"] == "flagged"
    # The remaining item is the missed condition.
    review = env.client.get(f"/api/documents/{DOC_FLAGGED}/review").json()
    assert review["fields"] == []
    assert len(review["missing_conditions"]) == 1


def test_reconcile_409_when_not_flagged(env):
    # A document that was never flagged has nothing to reconcile.
    resp = env.client.post(
        f"/api/documents/{DOC_CLEAN}/reconcile", json={"resolutions": []}
    )
    assert resp.status_code == 409
    assert "isn't flagged" in resp.json()["detail"]


def test_cross_user_cannot_see_or_reconcile(env):
    env.current["uid"] = str(USER_B)
    assert env.client.get("/api/documents/review-queue").json() == []
    assert env.client.get(f"/api/documents/{DOC_FLAGGED}/review").status_code == 404
    assert env.client.post(
        f"/api/documents/{DOC_FLAGGED}/reconcile",
        json={"resolutions": [{"field_id": "0:rating_percent", "value": 70}]},
    ).status_code == 404


# ── Pipeline integration: extract-verify flags a disputed extraction ──────────
def test_pipeline_extract_verify_flags_disputed_extraction(env, monkeypatch):
    monkeypatch.setattr(settings, "intake_verify_default", True)
    monkeypatch.setattr(process_mod, "classify_text", _canned_classify)
    monkeypatch.setattr(process_mod, "verify_extraction", _disputing_verify)
    monkeypatch.setattr(overrides_mod, "workspace_privacy_mode", _fake_privacy_mode)

    resp = env.client.post(
        "/api/documents",
        files=[("files", ("misread.txt", b"RATING DECISION\nPTSD granted at 70 percent.", "text/plain"))],
    )
    assert resp.status_code == 201, resp.text
    doc_id = resp.json()["items"][0]["document"]["id"]

    detail = env.client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "ready"            # still readable + classified…
    assert detail["review_status"] == "flagged"   # …but the disputed value is flagged
    review = detail["extracted"]["review"]
    f = review["fields"][0]
    assert f["field"] == "rating_percent"
    assert f["extracted_value"] == 50 and f["candidate_value"] == 70
    # The (wrong) extracted value is kept as the best guess, NOT silently corrected.
    assert detail["extracted"]["conditions_mentioned"][0]["rating_percent"] == 50

    # And it shows up in the queue for the veteran to fix.
    queue = env.client.get("/api/documents/review-queue").json()
    assert doc_id in [r["id"] for r in queue]
