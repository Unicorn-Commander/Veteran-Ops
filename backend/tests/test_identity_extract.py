"""Identity auto-extraction (intake/identity_extract.py) + the aggregation endpoint.

Pure-function tests exercise the validator and the merge directly. The extractor is
tested against a monkeypatched gateway SEAM (`_gateway_complete`) so the success path
runs WITHOUT the OpenAI SDK installed — and the same seam proves the degrade-to-empty
contract. The endpoint test runs the real profile router end-to-end over in-memory
SQLite (the test_api_documents pattern), seeding documents whose intake stashed an
`identity_suggestion`.

⚖️ The SSN guarantee is asserted at every layer: the validator never emits an `ssn`
key even when the model returns one, SSN-shaped values are scrubbed, and the endpoint
response never carries one.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from app.intake import identity_extract as ie
from app.intake.identity_extract import (
    authority_rank,
    extract_identity,
    merge_identity_suggestions,
    should_extract_identity,
    validate_identity,
)

# A realistic LOCAL-model payload for a VA decision letter — including an SSN and a
# VA file number the model should never have emitted (we prove they're dropped).
DECISION_LETTER_RAW = {
    "full_name": "Alexander P. Veteran",
    "date_of_birth": "1985-06-02",
    "phone": "843-555-0102",
    "address": {
        "street": "100 Palm Blvd",
        "city": "Charleston",
        "state": "SC",
        "zip": "29401",
    },
    "ssn": "123-45-6789",
    "va_file_number": "987654321",
    "dependents": [
        {"relationship": "spouse", "full_name": "Jamie Veteran", "date_of_birth": "1986-01-01"},
        {"relationship": "child", "full_name": "Sam Veteran"},
    ],
}


# ═══ Pure validator ═══════════════════════════════════════════════════════════
def test_validate_pulls_name_address_dob_from_decision_letter():
    out = validate_identity(DECISION_LETTER_RAW)
    assert out["full_name"] == "Alexander P. Veteran"
    assert out["date_of_birth"] == "1985-06-02"
    assert out["phone"] == "(843) 555-0102"  # normalized to 10-digit format
    assert out["address"] == {
        "street": "100 Palm Blvd",
        "city": "Charleston",
        "state": "SC",
        "zip": "29401",
    }
    deps = out["dependents"]
    assert deps[0] == {
        "relationship": "spouse",
        "full_name": "Jamie Veteran",
        "date_of_birth": "1986-01-01",
    }
    assert deps[1] == {"relationship": "child", "full_name": "Sam Veteran"}


def test_validate_never_emits_ssn_or_file_number():
    """The whitelist is the guarantee: an ssn / va_file_number key is structurally
    dropped, and an SSN-shaped VALUE inside a whitelisted field guts that field."""
    out = validate_identity(DECISION_LETTER_RAW)
    assert "ssn" not in out
    assert "va_file_number" not in out
    # No value anywhere in the result is an SSN-shaped token.
    assert "123-45-6789" not in json.dumps(out)

    # An SSN smuggled into the name field → the whole field is dropped.
    smuggled = validate_identity({"full_name": "John 123-45-6789 Doe"})
    assert "full_name" not in smuggled
    # A bare SSN string offered as the phone is not a 10-digit phone → dropped.
    assert validate_identity({"phone": "123-45-6789"}) == {}


def test_validate_empty_and_garbage_return_empty():
    assert validate_identity({}) == {}
    assert validate_identity(None) == {}
    assert validate_identity("garbage") == {}
    assert validate_identity({"unknown_key": "x", "full_name": "   "}) == {}


def test_validate_phone_state_zip_and_dependent_rules():
    # Phone: exactly 10 digits (so a 9-digit SSN can never masquerade as one).
    assert validate_identity({"phone": "18435550102"})["phone"] == "(843) 555-0102"
    assert validate_identity({"phone": "555-0102"}) == {}          # too short
    assert validate_identity({"phone": "123456789"}) == {}         # 9 digits → not a phone
    # State: real 2-letter code only.
    assert validate_identity({"address": {"state": "sc"}})["address"] == {"state": "SC"}
    assert validate_identity({"address": {"state": "XX"}}) == {}   # not a real state → address empty
    # ZIP: 5 or 9 digits.
    assert validate_identity({"address": {"zip": "294011234"}})["address"] == {"zip": "29401-1234"}
    assert validate_identity({"address": {"zip": "2940"}}) == {}
    # Dependents: valid relationship AND (name or dob), else dropped.
    assert validate_identity({"dependents": [{"relationship": "friend", "full_name": "Pat"}]}) == {}
    assert validate_identity({"dependents": [{"relationship": "spouse"}]}) == {}  # no name/dob


def test_validate_drops_veteran_dob_when_it_matches_spouse_dob():
    """Dependency forms often list both people — model must not promote spouse DOB."""
    out = validate_identity(
        {
            "full_name": "Alexander P. Veteran",
            "date_of_birth": "1986-01-01",  # same as spouse below
            "dependents": [
                {
                    "relationship": "spouse",
                    "full_name": "Jamie Veteran",
                    "date_of_birth": "1986-01-01",
                }
            ],
        }
    )
    assert out["full_name"] == "Alexander P. Veteran"
    assert "date_of_birth" not in out
    assert out["dependents"][0]["date_of_birth"] == "1986-01-01"


def test_merge_drops_dob_when_any_document_lists_it_as_dependent():
    letter = {
        "document_id": "a",
        "title": "Decision",
        "doc_type": "decision_letter",
        "doc_date": "2024-01-01",
        "created_at": "2024-01-02",
        "suggestion": {
            "full_name": "Alex Veteran",
            "date_of_birth": "1990-05-05",  # wrongly spouse
        },
    }
    dep_form = {
        "document_id": "b",
        "title": "686c",
        "doc_type": "other",
        "doc_date": "2023-01-01",
        "created_at": "2023-01-02",
        "suggestion": {
            "dependents": [
                {
                    "relationship": "spouse",
                    "full_name": "Jamie",
                    "date_of_birth": "1990-05-05",
                }
            ],
        },
    }
    # decision letter ranks higher for DOB, but merge must still reject spouse DOB
    merged = merge_identity_suggestions([letter, dep_form])
    assert merged["identity"].get("full_name") == "Alex Veteran"
    assert "date_of_birth" not in merged["identity"]
    assert merged["dependents"][0]["date_of_birth"] == "1990-05-05"


# ═══ Gate + authority ═════════════════════════════════════════════════════════
def test_should_extract_identity_gate():
    assert should_extract_identity("decision_letter") is True
    assert should_extract_identity("service_record") is True  # DD-214
    assert should_extract_identity("lay_statement") is False
    assert should_extract_identity("other") is False
    assert should_extract_identity(None) is False


def test_authority_ranking_orders_decision_over_treatment():
    assert authority_rank("decision_letter") > authority_rank("treatment_record")
    assert authority_rank("rating_decision") > authority_rank("dbq")
    assert authority_rank("service_record") > authority_rank("str")
    assert authority_rank(None) == 0


# ═══ extract_identity (gateway seam monkeypatched — no OpenAI SDK needed) ══════
async def test_extract_identity_from_decision_letter_text(monkeypatch):
    async def fake_complete(messages):
        # A code-fenced payload also proves parse_llm_json tolerance.
        return "```json\n" + json.dumps(DECISION_LETTER_RAW) + "\n```"

    monkeypatch.setattr(ie, "_gateway_complete", fake_complete)
    out = await extract_identity(
        "DEPARTMENT OF VETERANS AFFAIRS\nRating Decision for Alexander P. Veteran...",
        "decision_letter",
    )
    assert out["full_name"] == "Alexander P. Veteran"
    assert out["date_of_birth"] == "1985-06-02"
    assert out["address"]["city"] == "Charleston"
    assert "ssn" not in out and "123-45-6789" not in json.dumps(out)


async def test_extract_identity_empty_text_skips_gateway(monkeypatch):
    calls = {"n": 0}

    async def counting(messages):
        calls["n"] += 1
        return "{}"

    monkeypatch.setattr(ie, "_gateway_complete", counting)
    assert await extract_identity("", "decision_letter") == {}
    assert await extract_identity("   \n\t ", "decision_letter") == {}
    # Non-authoritative type is gated out too.
    assert await extract_identity("real text", "lay_statement") == {}
    assert calls["n"] == 0  # gateway never touched in any of these


async def test_extract_identity_degrades_on_gateway_failure(monkeypatch):
    async def boom(messages):
        raise RuntimeError("gateway down / SDK missing")

    monkeypatch.setattr(ie, "_gateway_complete", boom)
    assert await extract_identity("a decision letter body", "decision_letter") == {}

    async def junk(messages):
        return "I couldn't read this document."

    monkeypatch.setattr(ie, "_gateway_complete", junk)
    assert await extract_identity("a decision letter body", "decision_letter") == {}


# ═══ merge_identity_suggestions (pure aggregation) ════════════════════════════
def _entry(doc_id, doc_type, doc_date, suggestion, created_at="2020-01-01T00:00:00"):
    return {
        "document_id": doc_id,
        "title": f"{doc_type} {doc_date}",
        "doc_type": doc_type,
        "doc_date": doc_date,
        "created_at": created_at,
        "suggestion": suggestion,
    }


def test_merge_most_authoritative_wins_per_field():
    letter = _entry(
        "d1", "decision_letter", "2019-03-14",
        {"full_name": "Alexander P Veteran", "date_of_birth": "1985-06-02",
         "address": {"street": "100 Palm Blvd", "city": "Charleston", "state": "SC", "zip": "29401"}},
    )
    treat = _entry(
        "d2", "treatment_record", "2021-08-01",  # MORE RECENT but LOWER authority
        {"full_name": "Alex Veteran", "phone": "(843) 555-0102",
         "address": {"street": "55 Clinic Way", "city": "Mount Pleasant", "state": "SC", "zip": "29464"}},
    )
    merged = merge_identity_suggestions([treat, letter])  # order shouldn't matter
    assert merged["has_suggestions"] is True
    ident = merged["identity"]
    # Authority beats recency: name + address come from the decision letter.
    assert ident["full_name"] == "Alexander P Veteran"
    assert ident["address"]["street"] == "100 Palm Blvd"
    # Fields only the treatment record had still fill in.
    assert ident["phone"] == "(843) 555-0102"
    assert ident["date_of_birth"] == "1985-06-02"
    # Sources point at the winning document per field.
    assert merged["sources"]["full_name"]["document_id"] == "d1"
    assert merged["sources"]["address"]["document_id"] == "d1"
    assert merged["sources"]["phone"]["document_id"] == "d2"


def test_merge_recency_breaks_authority_ties():
    older = _entry("old", "decision_letter", "2018-01-01", {"full_name": "Old Name"})
    newer = _entry("new", "decision_letter", "2020-01-01", {"full_name": "New Name"})
    merged = merge_identity_suggestions([older, newer])
    assert merged["identity"]["full_name"] == "New Name"
    assert merged["sources"]["full_name"]["document_id"] == "new"


def test_merge_empty_and_dependents_taken_as_unit():
    assert merge_identity_suggestions([]) == {
        "identity": {}, "dependents": [], "sources": {}, "has_suggestions": False,
    }
    with_deps = _entry(
        "d1", "decision_letter", "2019-01-01",
        {"dependents": [{"relationship": "spouse", "full_name": "Jamie Veteran"}]},
    )
    merged = merge_identity_suggestions([with_deps])
    assert merged["dependents"] == [{"relationship": "spouse", "full_name": "Jamie Veteran"}]
    assert merged["sources"]["dependents"]["document_id"] == "d1"
    assert merged["has_suggestions"] is True


# ═══ GET /profile/identity-suggestions (end-to-end over SQLite) ═══════════════
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
from app.intake import process as process_mod  # noqa: E402
from app.routers import profile as profile_mod  # noqa: E402

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
    models.Document.__table__,
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
DOC_LETTER = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
DOC_TREAT = uuid.UUID("00000000-0000-0000-0000-0000000000d2")


def _doc(doc_id, user_id, doc_type, doc_date, created_at, status, extracted, title):
    return models.Document(
        id=doc_id, user_id=user_id, filename=f"{doc_type}.pdf",
        sha256=uuid.uuid4().hex, status=status, doc_type=doc_type,
        doc_date=doc_date, title=title, created_at=created_at, extracted=extracted,
    )


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'ident_test.db'}", poolclass=NullPool
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(USER_A)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=USER_A, email="alex@example.com", password_hash="x", full_name="Alex"),
                models.User(id=USER_B, email="blair@example.com", password_hash="x", full_name="Blair"),
                # A's authoritative decision letter (older) — name/DOB/address.
                _doc(
                    DOC_LETTER, USER_A, "decision_letter", date(2019, 3, 14),
                    datetime(2019, 3, 20, tzinfo=timezone.utc), "ready",
                    {"doc_type": "decision_letter", "identity_suggestion": {
                        "full_name": "Alexander P Veteran", "date_of_birth": "1985-06-02",
                        "address": {"street": "100 Palm Blvd", "city": "Charleston",
                                    "state": "SC", "zip": "29401"}}},
                    "Rating Decision — March 2019",
                ),
                # A's newer treatment record (lower authority) — phone + a different address.
                _doc(
                    DOC_TREAT, USER_A, "treatment_record", date(2021, 8, 1),
                    datetime(2021, 8, 2, tzinfo=timezone.utc), "ready",
                    {"identity_suggestion": {
                        "full_name": "Alex Veteran", "phone": "(843) 555-0102",
                        "address": {"street": "55 Clinic Way", "city": "Mount Pleasant",
                                    "state": "SC", "zip": "29464"}}},
                    "Clinic visit",
                ),
                # Ready but NO suggestion → excluded.
                _doc(
                    uuid.uuid4(), USER_A, "rating_decision", date(2020, 1, 1),
                    datetime(2020, 1, 2, tzinfo=timezone.utc), "ready",
                    {"doc_type": "rating_decision"}, "No identity here",
                ),
                # Has a suggestion but NOT ready → excluded.
                _doc(
                    uuid.uuid4(), USER_A, "decision_letter", date(2022, 1, 1),
                    datetime(2022, 1, 2, tzinfo=timezone.utc), "uploaded",
                    {"identity_suggestion": {"full_name": "Should Not Appear"}}, "Queued",
                ),
                # B's document with a suggestion → must NEVER surface for A.
                _doc(
                    uuid.uuid4(), USER_B, "decision_letter", date(2019, 1, 1),
                    datetime(2019, 1, 2, tzinfo=timezone.utc), "ready",
                    {"identity_suggestion": {"full_name": "Blair Other Veteran"}}, "B letter",
                ),
            ])
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(profile_mod.router, prefix="/api")

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


def test_identity_suggestions_merges_documents(env):
    body = env.client.get("/api/profile/identity-suggestions").json()
    assert body["has_suggestions"] is True
    ident = body["identity"]
    # Authority wins: name/DOB/address from the decision letter, phone from the newer
    # treatment record.
    assert ident["full_name"] == "Alexander P Veteran"
    assert ident["date_of_birth"] == "1985-06-02"
    assert ident["phone"] == "(843) 555-0102"
    assert ident["address"]["street"] == "100 Palm Blvd"
    assert ident["address"]["city"] == "Charleston"
    # Source attribution per field.
    assert body["sources"]["full_name"]["document_id"] == str(DOC_LETTER)
    assert body["sources"]["address"]["document_id"] == str(DOC_LETTER)
    assert body["sources"]["phone"]["document_id"] == str(DOC_TREAT)
    assert body["disclaimer"]
    # SSN is never present in the response (structural — VeteranIdentity has no field).
    assert "ssn" not in ident
    assert "Should Not Appear" not in json.dumps(body)  # the queued doc was excluded


def test_identity_suggestions_are_user_isolated(env):
    """B never sees A's records (and vice versa) — RLS-shaped user_id fence."""
    env.current["uid"] = str(USER_B)
    body = env.client.get("/api/profile/identity-suggestions").json()
    assert body["identity"]["full_name"] == "Blair Other Veteran"
    assert "Alexander" not in json.dumps(body)


def test_identity_suggestions_empty_when_no_records(env):
    """A user with no ready+extracted documents gets an empty, no-op proposal."""
    # A brand-new user id with no seeded documents.
    env.current["uid"] = str(uuid.UUID("00000000-0000-0000-0000-0000000000c3"))
    body = env.client.get("/api/profile/identity-suggestions").json()
    assert body["has_suggestions"] is False
    assert body["identity"]["full_name"] is None
    assert body["dependents"] == []
    assert body["sources"] == {}
    assert body["disclaimer"] == ""


# ═══ Intake wiring: process_document stashes extracted['identity_suggestion'] ═══
# Driven DIRECTLY (no TestClient/BackgroundTask) so it exercises the real pipeline
# wiring without depending on background-task timing.
async def _seed_ready_doc(Session, uid, doc_id, text):
    async with Session() as s:
        s.add(models.Document(
            id=doc_id, user_id=uid, filename="letter.txt", sha256=uuid.uuid4().hex,
            status="uploaded", text_content=text,
        ))
        await s.commit()


async def test_intake_stashes_identity_suggestion(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'wire.db'}", poolclass=NullPool
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=TABLES)
    uid, doc_id = uuid.uuid4(), uuid.uuid4()
    async with Session() as s:
        s.add(models.User(id=uid, email="v@example.com", password_hash="x", full_name="V"))
        await s.commit()
    await _seed_ready_doc(Session, uid, doc_id, "DEPARTMENT OF VETERANS AFFAIRS decision letter")

    @asynccontextmanager
    async def test_session(user_id):
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def canned_classify(text):
        return {"doc_type": "decision_letter", "doc_date": None, "title": "Decision",
                "summary": "x", "is_va_decision": True, "conditions_mentioned": []}

    async def canned_identity(text, doc_type):
        assert doc_type == "decision_letter"  # gated to authoritative types
        return {"full_name": "Alex Veteran", "date_of_birth": "1985-06-02",
                "address": {"street": "100 Palm Blvd", "city": "Charleston", "state": "SC", "zip": "29401"}}

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(process_mod, "user_session", test_session)
    monkeypatch.setattr(process_mod, "classify_text", canned_classify)
    monkeypatch.setattr(process_mod, "extract_identity", canned_identity)
    monkeypatch.setattr(process_mod, "adjust_credits", noop)
    monkeypatch.setattr(process_mod, "build_chunk_rows", noop)  # → None → no chunk write
    monkeypatch.setattr(process_mod.audit, "log", noop)

    await process_mod.process_document(str(uid), str(doc_id), None)

    async with Session() as s:
        doc = await s.get(models.Document, doc_id)
        assert doc.status == "ready"
        sug = doc.extracted["identity_suggestion"]
        assert sug["full_name"] == "Alex Veteran"
        assert sug["address"]["city"] == "Charleston"
        assert doc.extracted["is_va_decision"] is True  # non-destructive stash

    # A crashing extractor must NEVER break processing a document.
    doc2 = uuid.uuid4()
    await _seed_ready_doc(Session, uid, doc2, "another decision letter body")

    async def boom(text, doc_type):
        raise RuntimeError("extractor exploded")

    monkeypatch.setattr(process_mod, "extract_identity", boom)
    await process_mod.process_document(str(uid), str(doc2), None)
    async with Session() as s:
        doc = await s.get(models.Document, doc2)
        assert doc.status == "ready"                       # intake survived
        assert "identity_suggestion" not in doc.extracted  # nothing stashed

    await engine.dispose()
