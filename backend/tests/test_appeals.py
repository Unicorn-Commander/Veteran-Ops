"""WAVE7 Track A — Appeals draft-assist tests. No Postgres, no network.

Endpoint tests mount the real appeals router on the same SQLite harness the other
DB-reading routers use (PG types shimmed, gen_random_uuid()→uuid4, pgvector
Vector→TEXT so create_all can compile the models module; RLS not exercised —
cross-user isolation rides the router's explicit user_id filter that backs the
Postgres policy). Appeal-window expectations are computed from date.today() so the
test stays hermetic across calendar time.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
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
from app.routers import appeals as appeals_mod  # noqa: E402

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


_TABLES = [
    models.User.__table__,
    models.ClaimedCondition.__table__,
    models.EvidenceItem.__table__,
    models.Document.__table__,
]

for _t in _TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())


USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
COND_PTSD = uuid.UUID("00000000-0000-0000-0000-000000000011")   # A, name "PTSD", has evidence
COND_SLEEP = uuid.UUID("00000000-0000-0000-0000-000000000012")  # A, name "Sleep apnea", no evidence
COND_B = uuid.UUID("00000000-0000-0000-0000-000000000021")      # B — must never surface for A
DOC_DECISION = uuid.UUID("00000000-0000-0000-0000-0000000000d1")  # A, decoded VA decision

# The rare token that must survive VERBATIM through the draft.
RARE_STATEMENT = (
    "ZZQ-VERBATIM-9173: the IED blast at FOB Zeebrugge on 14 Mar 2007 is when the "
    "nightmares started, and they have never let up since."
)

# A cached decode dict, in the exact shape decoder/analyze.build_decode caches in
# Document.extracted['decode']: one DENIED row (PTSD, missing nexus) + one GRANTED
# row (tinnitus) that must NOT become a candidate.
DECODE = {
    "document_id": str(DOC_DECISION),
    "decoded_at": "2024-05-02T00:00:00Z",
    "decision_date": "2024-05-01",
    "decisions": [
        {
            "name": "PTSD",
            "diagnostic_code": "9411",
            "decision": "denied",
            "rating_percent": None,
            "effective_date": None,
            "missing_elements": ["nexus"],
            "next_step": "supplemental_claim",
        },
        {
            "name": "Tinnitus",
            "diagnostic_code": "6260",
            "decision": "granted",
            "rating_percent": 10,
            "missing_elements": [],
            "next_step": None,
        },
    ],
    "has_denials": True,
    "has_grants": True,
}


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'appeals.db'}", poolclass=NullPool
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(USER_A)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=USER_A, email="alex@example.com",
                            password_hash="x", full_name="Alex Veteran"),
                models.User(id=USER_B, email="blair@example.com",
                            password_hash="x", full_name="Blair Other"),
                models.ClaimedCondition(
                    id=COND_PTSD, user_id=USER_A, name="PTSD", claim_type="direct",
                    diagnostic_code="9411",
                ),
                models.ClaimedCondition(
                    id=COND_SLEEP, user_id=USER_A, name="Sleep apnea",
                    claim_type="secondary",
                ),
                models.ClaimedCondition(
                    id=COND_B, user_id=USER_B, name="Back strain", claim_type="direct",
                ),
            ])
            # A 'have' evidence item on the PTSD condition — the "new and relevant"
            # material that should match BOTH the decoded-letter PTSD row (by name)
            # and the PTSD condition candidate (by condition_id).
            s.add(models.EvidenceItem(
                user_id=USER_A, condition_id=COND_PTSD, kind="nexus_letter",
                title="New nexus opinion (2026)", status="have",
            ))
            # A 'need' item must never surface as new evidence.
            s.add(models.EvidenceItem(
                user_id=USER_A, condition_id=COND_PTSD, kind="dbq",
                title="DBQ still requested", status="need",
            ))
            # The decoded VA decision letter, with the cached decode payload.
            s.add(models.Document(
                id=DOC_DECISION, user_id=USER_A, filename="rating-decision.pdf",
                sha256="a" * 64, status="ready", doc_type="rating_decision",
                extracted={"is_va_decision": True, "decode": DECODE},
            ))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(appeals_mod.router, prefix="/api")

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
        yield SimpleNamespace(client=client, current=current)


# ── GET /appeals/candidates ──────────────────────────────────────────────────
def test_candidates_surfaces_denial_and_conditions_and_matches_evidence(env):
    body = env.client.get("/api/appeals/candidates").json()
    cands = body["candidates"]

    by_key = {(c["source"], c["name"]): c for c in cands}

    # 1) The DENIED decoded-letter row surfaces (the GRANTED tinnitus does NOT).
    assert ("decoded_letter", "PTSD") in by_key
    assert ("decoded_letter", "Tinnitus") not in by_key
    letter = by_key[("decoded_letter", "PTSD")]
    assert letter["decision"] == "denied"
    assert letter["missing_elements"] == ["nexus"]
    assert letter["document_id"] == str(DOC_DECISION)
    assert letter["diagnostic_code"] == "9411"
    # appeal_window recomputed from the decision date (2024-05-01) with today.
    assert letter["appeal_window"]["deadline"] == "2025-05-01"
    assert letter["appeal_window"]["expired"] is True  # a 2024 window is long past
    # have-evidence matched by condition NAME (no condition_id on a letter row).
    assert [e["title"] for e in letter["new_evidence"]] == ["New nexus opinion (2026)"]
    assert "DBQ still requested" not in [e["title"] for e in letter["new_evidence"]]

    # 2) Each claimed condition surfaces as its own candidate.
    assert ("condition", "PTSD") in by_key
    assert ("condition", "Sleep apnea") in by_key
    cond_ptsd = by_key[("condition", "PTSD")]
    assert cond_ptsd["condition_id"] == str(COND_PTSD)
    assert cond_ptsd["decision"] is None
    assert cond_ptsd["missing_elements"] == []
    # matched by condition_id.
    assert [e["title"] for e in cond_ptsd["new_evidence"]] == ["New nexus opinion (2026)"]
    # A condition with no have-evidence carries an empty list.
    assert by_key[("condition", "Sleep apnea")]["new_evidence"] == []

    # 3) The three AMA lanes + legal-lane strings are always present.
    assert len(body["lanes"]) == 3
    assert {lane["key"] for lane in body["lanes"]} == {
        "supplemental_claim", "higher_level_review", "board_appeal"
    }
    assert body["vso_referral"] and "VSO" in body["vso_referral"]
    assert body["disclaimer"]
    assert "medical opinion" in body["disclaimer"].lower()


def test_candidates_cross_user_isolation(env):
    # User B sees only their own condition, never A's PTSD/Sleep apnea/decoded letter.
    env.current["uid"] = str(USER_B)
    body = env.client.get("/api/appeals/candidates").json()
    names = {c["name"] for c in body["candidates"]}
    sources = {c["source"] for c in body["candidates"]}
    assert names == {"Back strain"}
    assert "decoded_letter" not in sources  # B has no decoded letter


# ── POST /appeals/draft ──────────────────────────────────────────────────────
def _draft_body(lane: str = "supplemental_claim") -> dict:
    return {
        "lane": lane,
        "decision_date": "2024-05-01",
        "contentions": [
            {
                "name": "PTSD",
                "diagnostic_code": "9411",
                "missing_elements": ["nexus"],
                "new_evidence_titles": ["New nexus opinion (2026)"],
                "veteran_statement": RARE_STATEMENT,
            }
        ],
    }


def test_draft_preserves_verbatim_statement(env):
    body = env.client.post("/api/appeals/draft", json=_draft_body()).json()
    cont = body["contentions"][0]
    # The veteran's own words survive EXACTLY — never rewritten or paraphrased.
    assert cont["veteran_statement"] == RARE_STATEMENT
    assert "ZZQ-VERBATIM-9173" in cont["veteran_statement"]
    # The missing element is rendered in plain English.
    assert any("nexus" in m.lower() for m in cont["missing_element_plain"])
    # New-and-relevant evidence echoes exactly what the veteran chose.
    assert cont["new_and_relevant_evidence"] == ["New nexus opinion (2026)"]
    # what_this_addresses ties the lane to the missing element.
    assert cont["what_this_addresses"]
    assert "Supplemental Claim" in cont["what_this_addresses"]


def test_draft_lane_form_per_lane(env):
    expected = {
        "supplemental_claim": ("20-0995", "Supplemental Claim"),
        "higher_level_review": ("20-0996", "Higher-Level Review"),
        "board_appeal": ("10182", "Board Appeal"),
    }
    for lane, (form, title_frag) in expected.items():
        body = env.client.post("/api/appeals/draft", json=_draft_body(lane)).json()
        assert body["lane_key"] == lane
        assert body["lane_form"] == form
        assert title_frag in body["lane_title"]
        # The three educational lanes always ride along.
        assert len(body["lane_guidance"]) == 3


def test_draft_includes_attestation_deadline_and_signature(env):
    body = env.client.post("/api/appeals/draft", json=_draft_body()).json()
    assert body["veteran_attestation"]
    assert "true and correct" in body["veteran_attestation"].lower()
    assert body["signature_block"]
    assert "signature" in body["signature_block"].lower()
    # The router stamps prepared_on in UTC (datetime.now(timezone.utc)); compare
    # against the SAME clock so the assertion doesn't flake at the local/UTC
    # midnight boundary (e.g. evening US time, when UTC has already rolled over).
    assert body["prepared_on"] == datetime.now(timezone.utc).date().isoformat()
    # Deadline computed from the decision date (2024-05-01 + 1yr).
    assert body["deadline"]["deadline"] == "2025-05-01"
    assert body["vso_referral"] and body["source_note"]


def test_draft_missing_decision_date_gives_all_none_deadline(env):
    payload = _draft_body()
    payload["decision_date"] = None
    body = env.client.post("/api/appeals/draft", json=payload).json()
    assert body["deadline"] == {
        "deadline": None, "days_remaining": None, "expired": None
    }


def test_draft_renders_no_medical_opinion(env):
    """The draft must never assert a medical link on the veteran's behalf — no
    opinion language anywhere in the produced paper."""
    body = env.client.post("/api/appeals/draft", json=_draft_body()).json()
    blob = json.dumps(body).lower()
    for forbidden in (
        "it is more likely than not",
        "at least as likely as not",
        "in my medical opinion",
        "i opine",
        "to a reasonable degree of medical certainty",
    ):
        assert forbidden not in blob, f"draft rendered a medical opinion: {forbidden!r}"
    # And the disclaimer explicitly disclaims rendering one.
    assert "never renders a medical opinion" in blob


def test_draft_requires_at_least_one_contention(env):
    resp = env.client.post(
        "/api/appeals/draft",
        json={"lane": "supplemental_claim", "contentions": []},
    )
    assert resp.status_code == 422  # AppealDraftIn.contentions min_length=1
