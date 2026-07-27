"""Wave-2 intake + records tests — no Postgres required.

Pure-function tests exercise the validation layer directly (invented doc types,
off-grid percents, unknown fields all dropped). The API tests run the real
routers + the real background pipeline end-to-end against in-memory SQLite:
Postgres-only column types get SQLite compile shims, gen_random_uuid() server
defaults become client-side uuid4, and the intake task's RLS session factory is
monkeypatched (SQLite has no set_config). RLS itself can't run on SQLite — the
cross-user 404 tests exercise the routers' explicit user_id defense-in-depth
filters that back the Postgres policies.

The LLM is never called: `classify_text` is monkeypatched to run the REAL
validator over a canned raw-model payload (so validation is exercised e2e), or
to return None for the "LLM down" degradation path.
"""

from __future__ import annotations

import asyncio
import io
import uuid
import zipfile
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
from app.config import settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.intake import ocr as ocr_mod  # noqa: E402
from app.intake import process as process_mod  # noqa: E402
from app.intake.classify import (  # noqa: E402
    build_rating_summary,
    parse_llm_json,
    suggest_links,
    validate_extraction,
)
from app.routers import documents as documents_mod  # noqa: E402
from app.routers import records as records_mod  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover
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

# ── Seed identities ──────────────────────────────────────────────────────────
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
COND_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")
COND_TINNITUS = uuid.UUID("00000000-0000-0000-0000-000000000012")
COND_B = uuid.UUID("00000000-0000-0000-0000-000000000021")

CANNED_RAW = {
    "doc_type": "rating_decision",
    "doc_date": "2019-03-14",
    "title": "VA Rating Decision — March 2019",
    "summary": "Rating decision granting PTSD at 50 percent. Tinnitus was also addressed.",
    "conditions_mentioned": [
        {"name": "PTSD", "rating_percent": 50, "diagnostic_code": "9411", "decision": "granted"},
        # 55 is not a multiple of 10 → must be DROPPED by validation.
        {"name": "Tinnitus", "rating_percent": 55, "decision": "granted"},
        # invented decision + invented percent + unknown key → all dropped.
        {"name": "Back pain", "rating_percent": 110, "decision": "maybe", "made_up": True},
    ],
    "is_va_decision": True,
    "invented_top_level_field": "should be discarded",
}


async def _canned_classify(text: str):
    """Stands in for the gateway call; runs the REAL validator on canned output."""
    return validate_extraction(CANNED_RAW)


async def _llm_down_classify(text: str):
    return None


# ── Environment fixture ──────────────────────────────────────────────────────
@pytest.fixture()
def env(tmp_path, monkeypatch):
    # FILE-backed SQLite + NullPool (the test_api_va.py pattern): every session
    # gets its OWN connection over the same data, so the intake queue's
    # concurrent workers (bounded by the semaphore) behave like they do on
    # Postgres instead of interleaving on one shared connection.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'docs_test.db'}",
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

    monkeypatch.setattr(process_mod, "user_session", test_user_session)
    monkeypatch.setattr(process_mod, "classify_text", _canned_classify)
    monkeypatch.setattr(documents_mod, "UPLOAD_DIR", tmp_path)

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
                    models.VeteranProfile(
                        user_id=USER_A,
                        service_periods=[
                            {"branch": "Army", "component": "Active",
                             "start_date": "2004-01-15", "end_date": "2008-06-30",
                             "discharge_character": "Honorable"},
                        ],
                        combat_service=True,
                        exposures={"burn_pits": True},
                        state="SC",
                    ),
                    models.ClaimedCondition(id=COND_PTSD, user_id=USER_A,
                                            name="PTSD", claim_type="direct"),
                    models.ClaimedCondition(id=COND_TINNITUS, user_id=USER_A,
                                            name="Tinnitus", claim_type="direct"),
                    # Named to fuzzy-match "PTSD" — must NEVER surface for user A.
                    models.ClaimedCondition(id=COND_B, user_id=USER_B,
                                            name="PTSD (other veteran)",
                                            claim_type="direct"),
                ]
            )
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(documents_mod.router, prefix="/api")
    app.include_router(records_mod.router, prefix="/api")

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


def _upload(client, content: bytes = b"RATING DECISION\nPTSD granted at 50 percent.",
            name: str = "decision.txt", content_type: str = "text/plain"):
    return client.post("/api/documents", files=[("files", (name, content, content_type))])


# ═══ Pure validation layer ═══════════════════════════════════════════════════
def test_validate_drops_invented_doc_type():
    out = validate_extraction({"doc_type": "medical_bill", "title": "x"})
    assert out["doc_type"] is None
    out = validate_extraction({"doc_type": "dbq"})
    assert out["doc_type"] == "dbq"


def test_validate_percent_rules():
    def pct(v):
        return validate_extraction(
            {"conditions_mentioned": [{"name": "X", "rating_percent": v}]}
        )["conditions_mentioned"][0]["rating_percent"]

    assert pct(50) == 50
    assert pct(0) == 0
    assert pct(100) == 100
    assert pct("70") == 70          # digit-string coerced
    assert pct(55) is None          # not a multiple of 10 → dropped
    assert pct(110) is None         # out of range → dropped
    assert pct(-10) is None
    assert pct(True) is None        # bool is not a percent
    assert pct("a lot") is None


def test_validate_drops_unknown_fields_and_bad_values():
    out = validate_extraction(CANNED_RAW)
    assert "invented_top_level_field" not in out
    back = next(m for m in out["conditions_mentioned"] if m["name"] == "Back pain")
    assert "made_up" not in back
    assert back["decision"] is None          # "maybe" is not granted/denied/deferred
    assert back["rating_percent"] is None
    assert out["doc_date"] == "2019-03-14"
    assert validate_extraction({"doc_date": "not-a-date"})["doc_date"] is None
    assert validate_extraction("garbage")["conditions_mentioned"] == []
    assert validate_extraction(None)["doc_type"] is None


def test_validate_diagnostic_code_shape():
    def dc(v):
        return validate_extraction(
            {"conditions_mentioned": [{"name": "X", "diagnostic_code": v}]}
        )["conditions_mentioned"][0]["diagnostic_code"]

    assert dc("9411") == "9411"
    assert dc("941") is None
    assert dc("ABCD") is None
    assert dc(9411) is None  # must be a string on the wire


def test_suggest_links_casefold_substring():
    mentioned = [{"name": "ptsd"}, {"name": "Left knee strain"}, {"name": "Zqxwv"}]
    conditions = [
        {"id": "c1", "name": "PTSD"},
        {"id": "c2", "name": "Knee strain"},
        {"id": "c3", "name": "Migraines"},
    ]
    links = suggest_links(mentioned, conditions)
    by_cond = {link["condition_id"]: link for link in links}
    assert set(by_cond) == {"c1", "c2"}
    assert by_cond["c1"]["match"] == "ptsd"
    assert by_cond["c2"]["name"] == "Knee strain"
    assert suggest_links([], conditions) == []
    assert suggest_links(mentioned, []) == []


def test_build_rating_summary_only_for_va_decisions_with_percents():
    validated = validate_extraction(CANNED_RAW)
    summary = build_rating_summary(validated)
    assert summary == [{"name": "PTSD", "rating_percent": 50, "decision": "granted"}]
    not_decision = dict(validated, is_va_decision=False)
    assert build_rating_summary(not_decision) == []


def test_parse_llm_json_tolerates_wrapping():
    assert parse_llm_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_llm_json('noise before {"a": 1} noise after') == {"a": 1}
    assert parse_llm_json("no json at all") is None
    assert parse_llm_json("") is None
    assert parse_llm_json("[1, 2]") is None  # must be an object


# ═══ Documents API (end-to-end, LLM canned) ══════════════════════════════════
def test_upload_txt_end_to_end(env):
    resp = _upload(env.client)
    assert resp.status_code == 201, resp.text
    item = resp.json()["items"][0]
    assert item["accepted"] is True and item["duplicate"] is False
    doc = item["document"]
    assert doc["status"] == "uploaded"

    # Background processing ran inside the request cycle (TestClient waits).
    detail = env.client.get(f"/api/documents/{doc['id']}").json()
    assert detail["status"] == "ready"
    assert detail["doc_type"] == "rating_decision"
    assert detail["doc_date"] == "2019-03-14"
    assert detail["title"] == "VA Rating Decision — March 2019"
    assert "PTSD granted" in detail["text_content"]
    assert detail["error"] is None

    extracted = detail["extracted"]
    assert extracted["is_va_decision"] is True
    assert "invented_top_level_field" not in extracted
    # Validation e2e: Tinnitus's 55% was dropped, PTSD's 50% kept.
    percents = {m["name"]: m["rating_percent"] for m in extracted["conditions_mentioned"]}
    assert percents == {"PTSD": 50, "Tinnitus": None, "Back pain": None}
    # Deterministic suggestions: A's PTSD + Tinnitus only — NEVER user B's,
    # and nothing was auto-linked.
    linked_ids = {link["condition_id"] for link in extracted["suggested_links"]}
    assert linked_ids == {str(COND_PTSD), str(COND_TINNITUS)}
    assert detail["condition_id"] is None
    assert extracted["rating_summary"] == [
        {"name": "PTSD", "rating_percent": 50, "decision": "granted"}
    ]


def test_list_documents_filters(env):
    doc_id = _upload(env.client).json()["items"][0]["document"]["id"]
    listed = env.client.get("/api/documents").json()
    assert [d["id"] for d in listed] == [doc_id]
    assert env.client.get("/api/documents?status=ready").json()[0]["id"] == doc_id
    assert env.client.get("/api/documents?status=failed").json() == []
    assert env.client.get("/api/documents?doc_type=rating_decision").json()[0]["id"] == doc_id
    assert env.client.get("/api/documents?doc_type=dbq").json() == []
    assert env.client.get("/api/documents?status=bogus").status_code == 422
    assert env.client.get("/api/documents?doc_type=bogus").status_code == 422
    # The list view is slim — no text body.
    assert "text_content" not in listed[0]


def test_upload_dedupe_same_sha256(env):
    content = b"the very same bytes"
    first = _upload(env.client, content=content).json()["items"][0]
    assert first["accepted"] is True
    doc_id = first["document"]["id"]

    second = _upload(env.client, content=content, name="renamed-copy.txt").json()["items"][0]
    assert second["accepted"] is False
    assert second["duplicate"] is True
    assert second["existing_document_id"] == doc_id
    # No second row.
    assert len(env.client.get("/api/documents").json()) == 1


def test_upload_rejects_unsupported_and_oversized(env, monkeypatch):
    bad = _upload(env.client, name="virus.exe",
                  content_type="application/octet-stream").json()["items"][0]
    assert bad["accepted"] is False and bad["duplicate"] is False
    assert "Unsupported file type" in bad["detail"]

    monkeypatch.setattr(documents_mod, "MAX_BYTES", 8)
    monkeypatch.setattr(documents_mod, "MAX_TEXT_BYTES", 8)
    big = _upload(env.client, content=b"way more than eight bytes").json()["items"][0]
    assert big["accepted"] is False
    assert "95 MB" in big["detail"]
    assert env.client.get("/api/documents").json() == []


def test_rls_shaped_404_on_cross_user_access(env):
    doc_id = _upload(env.client).json()["items"][0]["document"]["id"]

    env.current["uid"] = str(USER_B)
    assert env.client.get(f"/api/documents/{doc_id}").status_code == 404
    assert env.client.patch(f"/api/documents/{doc_id}", json={"title": "mine now"}).status_code == 404
    assert env.client.delete(f"/api/documents/{doc_id}").status_code == 404
    assert env.client.post(f"/api/documents/{doc_id}/reprocess").status_code == 404
    assert env.client.post(
        f"/api/documents/{doc_id}/link",
        json={"condition_id": str(COND_B), "kind": "treatment_record"},
    ).status_code == 404
    assert env.client.get("/api/documents").json() == []  # B sees nothing

    env.current["uid"] = str(USER_A)
    assert env.client.get(f"/api/documents/{doc_id}").status_code == 200
    # A cannot link their document to B's condition either.
    assert env.client.post(
        f"/api/documents/{doc_id}/link",
        json={"condition_id": str(COND_B)},
    ).status_code == 404


def test_patch_document_corrections(env):
    doc_id = _upload(env.client).json()["items"][0]["document"]["id"]
    resp = env.client.patch(
        f"/api/documents/{doc_id}",
        json={"doc_type": "treatment_record", "title": "Dr. Smith visit notes",
              "condition_id": str(COND_TINNITUS)},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["doc_type"] == "treatment_record"
    assert body["title"] == "Dr. Smith visit notes"
    assert body["condition_id"] == str(COND_TINNITUS)
    # Invented doc_type is a schema-level 422 (Literal enum).
    assert env.client.patch(
        f"/api/documents/{doc_id}", json={"doc_type": "carfax_report"}
    ).status_code == 422
    # Explicit null clears the link.
    cleared = env.client.patch(f"/api/documents/{doc_id}", json={"condition_id": None})
    assert cleared.json()["condition_id"] is None


def test_link_creates_evidence_on_confirmation(env):
    doc_id = _upload(env.client).json()["items"][0]["document"]["id"]
    resp = env.client.post(
        f"/api/documents/{doc_id}/link",
        json={"condition_id": str(COND_PTSD), "kind": "treatment_record"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["document"]["condition_id"] == str(COND_PTSD)
    ev = body["evidence"]
    assert ev["condition_id"] == str(COND_PTSD)
    assert ev["kind"] == "treatment_record"
    assert ev["status"] == "have"
    assert ev["file_ref"]  # points at the stored upload
    assert ev["title"] == "VA Rating Decision — March 2019"


def test_llm_down_stores_text_then_reprocess_recovers(env, monkeypatch):
    monkeypatch.setattr(process_mod, "classify_text", _llm_down_classify)
    doc_id = _upload(env.client).json()["items"][0]["document"]["id"]

    detail = env.client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "failed"
    assert "Reprocess" in detail["error"]          # human-readable, retry-worded
    assert "PTSD granted" in detail["text_content"]  # the text WAS stored
    assert detail["doc_type"] is None

    # Gateway is back — the veteran retries.
    monkeypatch.setattr(process_mod, "classify_text", _canned_classify)
    resp = env.client.post(f"/api/documents/{doc_id}/reprocess")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "processing"
    after = env.client.get(f"/api/documents/{doc_id}").json()
    assert after["status"] == "ready"
    assert after["doc_type"] == "rating_decision"
    assert after["error"] is None


def test_unreadable_file_fails_with_human_error(env, monkeypatch):
    doc_id = _upload(env.client, content=b"   \n  \t ").json()["items"][0]["document"]["id"]
    detail = env.client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "failed"
    assert "couldn't read any text" in detail["error"]


def test_delete_document_removes_file(env, tmp_path):
    doc_id = _upload(env.client).json()["items"][0]["document"]["id"]
    stored = list((tmp_path / str(USER_A)).iterdir())
    assert len(stored) == 1
    assert env.client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert env.client.get(f"/api/documents/{doc_id}").status_code == 404
    assert list((tmp_path / str(USER_A)).iterdir()) == []


# ═══ Massive-dump hardening: queue, ZIP expansion, batch endpoints ═══════════
def _make_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _upload_zip(client, name: str, zbytes: bytes):
    return client.post(
        "/api/documents", files=[("files", (name, zbytes, "application/zip"))]
    )


def _tracking_classify(active: dict):
    async def tracked(text):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.05)  # long enough that a stampede would overlap
        active["now"] -= 1
        return validate_extraction(CANNED_RAW)

    return tracked


def test_intake_semaphore_bounds_concurrency(env, monkeypatch):
    """A 6-file dump drains through at most INTAKE_CONCURRENCY (3) workers —
    and actually in parallel (not serialized one by one)."""
    active = {"now": 0, "max": 0}
    monkeypatch.setattr(process_mod, "classify_text", _tracking_classify(active))

    files = [
        ("files", (f"dump-{i}.txt", f"RATING DECISION {i}\nPTSD.".encode(), "text/plain"))
        for i in range(6)
    ]
    resp = env.client.post("/api/documents", files=files)
    assert resp.status_code == 201, resp.text
    assert all(item["accepted"] for item in resp.json()["items"])

    assert active["max"] <= 3          # the hard bound
    assert active["max"] >= 2          # and genuinely concurrent
    docs = env.client.get("/api/documents").json()
    assert len(docs) == 6
    assert all(d["status"] == "ready" for d in docs)


def test_intake_concurrency_knob(env, monkeypatch):
    """INTAKE_CONCURRENCY=1 (via settings) serializes the queue."""
    active = {"now": 0, "max": 0}
    monkeypatch.setattr(process_mod, "classify_text", _tracking_classify(active))
    monkeypatch.setattr(settings, "intake_concurrency", 1)

    files = [
        ("files", (f"one-{i}.txt", f"DECISION {i}".encode(), "text/plain"))
        for i in range(3)
    ]
    resp = env.client.post("/api/documents", files=files)
    assert resp.status_code == 201, resp.text
    assert active["max"] == 1


def test_zip_expands_members_like_individual_uploads(env):
    zbytes = _make_zip({
        "records/exam.txt": b"RATING DECISION\nPTSD granted at 50 percent.",
        "records/tool.exe": b"MZ not a document",
        "../../evil.txt": b"path traversal attempt",
    })
    resp = _upload_zip(env.client, "cfile.zip", zbytes)
    assert resp.status_code == 201, resp.text
    items = {i["filename"]: i for i in resp.json()["items"]}
    assert set(items) == {
        "cfile.zip/records/exam.txt",
        "cfile.zip/records/tool.exe",
        "cfile.zip/../../evil.txt",
    }

    good = items["cfile.zip/records/exam.txt"]
    assert good["accepted"] is True
    assert good["document"]["filename"] == "cfile.zip/records/exam.txt"

    assert items["cfile.zip/records/tool.exe"]["accepted"] is False
    assert "Unsupported file type" in items["cfile.zip/records/tool.exe"]["detail"]
    assert items["cfile.zip/../../evil.txt"]["accepted"] is False
    assert "unsafe path" in items["cfile.zip/../../evil.txt"]["detail"]

    # Exactly ONE document row — the member. The zip itself was never stored,
    # and the member went through the real pipeline.
    docs = env.client.get("/api/documents").json()
    assert len(docs) == 1
    assert docs[0]["status"] == "ready"
    assert docs[0]["doc_type"] == "rating_decision"


def test_zip_member_dedupes_against_existing_upload(env):
    content = b"RATING DECISION\nPTSD granted at 50 percent."
    first = _upload(env.client, content=content).json()["items"][0]
    assert first["accepted"] is True

    resp = _upload_zip(env.client, "again.zip", _make_zip({"copy.txt": content}))
    item = resp.json()["items"][0]
    assert item["accepted"] is False and item["duplicate"] is True
    assert item["existing_document_id"] == first["document"]["id"]
    assert len(env.client.get("/api/documents").json()) == 1


def test_zip_bomb_rejected_by_compression_ratio(env):
    # 12 MB of zeros deflates to ~12 KB — a classic bomb signature.
    zbytes = _make_zip({"zeros.txt": b"\0" * (12 * 1024 * 1024)})
    resp = _upload_zip(env.client, "bomb.zip", zbytes)
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["accepted"] is False
    assert "compression ratio" in items[0]["detail"]
    assert env.client.get("/api/documents").json() == []


def test_zip_guards_member_count_total_size_and_nesting(env, monkeypatch):
    # Member-count cap.
    monkeypatch.setattr(documents_mod, "MAX_ZIP_MEMBERS", 2)
    many = _make_zip({f"f{i}.txt": f"doc {i}".encode() for i in range(3)})
    item = _upload_zip(env.client, "many.zip", many).json()["items"][0]
    assert item["accepted"] is False and "limit is 2" in item["detail"]
    monkeypatch.setattr(documents_mod, "MAX_ZIP_MEMBERS", 400)

    # Total-uncompressed cap.
    monkeypatch.setattr(documents_mod, "MAX_ZIP_TOTAL_UNCOMPRESSED", 10)
    item = _upload_zip(
        env.client, "big.zip", _make_zip({"a.txt": b"x" * 100})
    ).json()["items"][0]
    assert item["accepted"] is False and "expands to more than" in item["detail"]
    monkeypatch.setattr(
        documents_mod, "MAX_ZIP_TOTAL_UNCOMPRESSED", 400 * 1024 * 1024
    )

    # The .zip itself over its cap.
    monkeypatch.setattr(documents_mod, "MAX_ZIP_BYTES", 10)
    item = _upload_zip(
        env.client, "fat.zip", _make_zip({"a.txt": b"hello"})
    ).json()["items"][0]
    assert item["accepted"] is False and "split it into smaller archives" in item["detail"]
    monkeypatch.setattr(documents_mod, "MAX_ZIP_BYTES", 200 * 1024 * 1024)

    # Nested zips are skipped (never recursed into); siblings still land.
    nested = _make_zip({
        "inner.zip": _make_zip({"deep.txt": b"nested"}),
        "ok.txt": b"RATING DECISION PTSD.",
    })
    items = {i["filename"]: i for i in _upload_zip(
        env.client, "outer.zip", nested
    ).json()["items"]}
    assert items["outer.zip/inner.zip"]["accepted"] is False
    assert "Nested ZIP" in items["outer.zip/inner.zip"]["detail"]
    assert items["outer.zip/ok.txt"]["accepted"] is True

    # Garbage bytes with a .zip name.
    item = _upload_zip(env.client, "junk.zip", b"not a zip at all").json()["items"][0]
    assert item["accepted"] is False and "not a ZIP" in item["detail"]


def test_documents_summary_counts(env, monkeypatch):
    _upload(env.client, content=b"decision one")
    _upload(env.client, content=b"decision two")
    monkeypatch.setattr(process_mod, "classify_text", _llm_down_classify)
    _upload(env.client, content=b"this one fails")

    summary = env.client.get("/api/documents/summary").json()
    assert summary["total"] == 3
    assert summary["by_status"] == {"ready": 2, "failed": 1}
    assert summary["processing"] == 0
    assert summary["queued"] == 0
    assert summary["by_type"]["rating_decision"] == 2
    assert summary["by_type"]["unclassified"] == 1  # the failed doc, never typed

    # Cross-user isolation: B sees an empty board.
    env.current["uid"] = str(USER_B)
    summary_b = env.client.get("/api/documents/summary").json()
    assert summary_b["total"] == 0
    assert summary_b["by_status"] == {} and summary_b["by_type"] == {}


def test_reprocess_failed_requeues_all_failed(env, monkeypatch):
    monkeypatch.setattr(process_mod, "classify_text", _llm_down_classify)
    _upload(env.client, content=b"failed doc one")
    _upload(env.client, content=b"failed doc two")
    assert env.client.get("/api/documents/summary").json()["by_status"] == {"failed": 2}

    # Gateway is back — one click retries the whole dump (bounded by the queue).
    monkeypatch.setattr(process_mod, "classify_text", _canned_classify)
    resp = env.client.post("/api/documents/reprocess-failed")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"requeued": 2}

    docs = env.client.get("/api/documents").json()
    assert all(d["status"] == "ready" and d["error"] is None for d in docs)

    # Nothing failed anymore — a second click is a no-op.
    assert env.client.post("/api/documents/reprocess-failed").json() == {"requeued": 0}


def test_force_ocr_reextracts_but_plain_reprocess_reuses_text(env, monkeypatch):
    """force_ocr=true CLEARS the stored text so the file is re-read (how an OCR
    improvement reaches an already-parsed doc); a plain reprocess reuses the cached
    text and never re-extracts."""
    doc_id = _upload(env.client).json()["items"][0]["document"]["id"]

    real_extract = process_mod.extract_text
    calls = {"n": 0}

    async def spy(path, content_type, *, full_read=False):
        calls["n"] += 1
        return await real_extract(path, content_type, full_read=full_read)

    monkeypatch.setattr(process_mod, "extract_text", spy)

    # Plain reprocess → cached text reused, no re-extract.
    assert env.client.post(f"/api/documents/{doc_id}/reprocess").status_code == 200
    assert calls["n"] == 0

    # force_ocr → text cleared, file re-read exactly once.
    assert env.client.post(f"/api/documents/{doc_id}/reprocess?force_ocr=true").status_code == 200
    assert calls["n"] == 1


def test_reprocess_ocr_requeues_every_ready_doc_with_a_file(env):
    """The 're-OCR my records' action re-reads every ready document that still has
    its stored file, so existing records pick up the current OCR pipeline."""
    _upload(env.client, content=b"RATING DECISION\nPTSD granted at 50 percent.", name="a.txt")
    _upload(env.client, content=b"RATING DECISION\nTinnitus granted at 10 percent.", name="b.txt")
    resp = env.client.post("/api/documents/reprocess-ocr")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"requeued": 2}
    docs = env.client.get("/api/documents").json()
    assert all(d["status"] == "ready" and d["error"] is None for d in docs)


def test_huge_pdf_truncation_is_disclosed(env, monkeypatch):
    """When the page budget capped extraction, the veteran is told — in the
    summary AND the structured extraction."""
    async def fake_extract(path, content_type, *, full_read=False):
        # A scanned C-file past the OCR ceiling still truncates even under full-read.
        return "C-FILE TEXT head and tail pages only.", None, {"truncated": True}

    monkeypatch.setattr(process_mod, "extract_text", fake_extract)
    doc_id = _upload(
        env.client, content=b"%PDF-1.4 pretend 900-page c-file",
        name="cfile.pdf", content_type="application/pdf",
    ).json()["items"][0]["document"]["id"]

    detail = env.client.get(f"/api/documents/{doc_id}").json()
    assert detail["status"] == "ready"
    assert "key sections read" in detail["summary"]
    assert detail["extracted"]["truncated"] is True
    assert "key sections read" in detail["extracted"]["truncation_note"]


def test_pdf_page_budget_indices_pure():
    idx, truncated = ocr_mod._pdf_page_indices(200)
    assert truncated is False and idx == list(range(200))

    idx, truncated = ocr_mod._pdf_page_indices(1000)
    assert truncated is True
    assert len(idx) == 170
    assert idx[:150] == list(range(150))       # first 150 pages
    assert idx[-20:] == list(range(980, 1000))  # last 20 pages


# ═══ Records API ═════════════════════════════════════════════════════════════
def test_sf180_prefill_from_seeded_profile(env):
    resp = env.client.get("/api/records/sf180")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["form"] == "SF-180"
    assert body["form_url"].endswith(".pdf")
    pre = body["prefill"]
    assert pre["full_name"] == "Alex Veteran"
    assert pre["email"] == "alex@example.com"
    assert pre["branches"] == ["Army"]
    assert pre["service_periods"][0]["start_date"] == "2004-01-15"
    assert pre["discharge_characters"] == ["Honorable"]
    assert any("DD Form 214" in r for r in pre["records_requested"])
    assert any("eVetRecs" in g for g in body["guidance"])
    # Legal lane: for-your-signature framing + VSO pointer.
    assert "YOUR signature" in body["note"] and "VSO" in body["note"]


def test_va_20_10206_prefill(env):
    body = env.client.get("/api/records/va-20-10206").json()
    assert body["form"] == "VA Form 20-10206"
    assert body["prefill"]["full_name"] == "Alex Veteran"
    assert any("C-file" in r for r in body["prefill"]["records_requested"])
    assert "VSO" in body["note"]


def test_records_prefill_empty_profile_still_200(env):
    """User B has no profile row — prefill degrades to identity-only."""
    env.current["uid"] = str(USER_B)
    body = env.client.get("/api/records/sf180").json()
    assert body["prefill"]["full_name"] == "Blair Other"
    assert body["prefill"]["service_periods"] == []
    assert body["prefill"]["branches"] == []


def test_request_letter_creates_evidence(env):
    resp = env.client.post(
        "/api/records/request-letter",
        json={
            "provider_name": "Coastal Behavioral Health",
            "address": "123 Palm Blvd\nCharleston, SC 29401",
            "condition_ids": [str(COND_PTSD), str(COND_TINNITUS)],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    letter = body["letter"]
    assert "Coastal Behavioral Health" in letter
    assert "123 Palm Blvd" in letter
    assert "PTSD" in letter and "Tinnitus" in letter
    assert "Alex Veteran" in letter
    assert "45 CFR 164.524" in letter  # HIPAA access right — deterministic template
    assert sorted(body["conditions"]) == ["PTSD", "Tinnitus"]

    assert len(body["evidence"]) == 2
    for ev in body["evidence"]:
        assert ev["status"] == "requested"
        assert ev["kind"] == "treatment_record"
        assert ev["source"] == "Coastal Behavioral Health"
    assert {ev["condition_id"] for ev in body["evidence"]} == {
        str(COND_PTSD), str(COND_TINNITUS),
    }


def test_request_letter_rejects_foreign_condition(env):
    resp = env.client.post(
        "/api/records/request-letter",
        json={"provider_name": "Anywhere Clinic",
              "condition_ids": [str(COND_PTSD), str(COND_B)]},
    )
    assert resp.status_code == 404  # B's condition doesn't exist for A (RLS-shaped)


def test_request_letter_validation_422(env):
    assert env.client.post(
        "/api/records/request-letter",
        json={"provider_name": "X", "condition_ids": []},
    ).status_code == 422
    assert env.client.post(
        "/api/records/request-letter",
        json={"provider_name": "", "condition_ids": [str(COND_PTSD)]},
    ).status_code == 422


# ═══ Auth posture ════════════════════════════════════════════════════════════
def test_requires_auth():
    """Without overrides, every endpoint 401/403s (bearer required)."""
    app = FastAPI()
    app.include_router(documents_mod.router, prefix="/api")
    app.include_router(records_mod.router, prefix="/api")
    client = TestClient(app)
    assert client.get("/api/documents").status_code in (401, 403)
    assert client.get("/api/records/sf180").status_code in (401, 403)
    assert client.post(
        "/api/records/request-letter",
        json={"provider_name": "X", "condition_ids": [str(COND_PTSD)]},
    ).status_code in (401, 403)
