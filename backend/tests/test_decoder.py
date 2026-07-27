"""Wave-4 decision-letter decoder tests — no Postgres, no network.

Pure-function tests exercise the decoder's four pure modules directly:
  * deadline.py    — one-year appeal-window math (incl. the Feb-29 leap case)
  * combined_check — the §4.25 educational cross-check (real rating engine)
  * decode.py      — validate_decode (propose/dispose) + decode_text (LLM pass)
  * analyze.py     — build_decode end-to-end payload assembly

The endpoint tests mount the real `documents` router on a bare FastAPI app
against in-memory-ish (file-backed) SQLite — the exact harness test_api_documents
uses: Postgres-only column types get SQLite compile shims (UUID→CHAR(36),
JSONB→JSON, pgvector Vector→TEXT), gen_random_uuid() server defaults become
client-side uuid4, and the RLS session is never exercised (SQLite has no
set_config) — the cross-user 404s ride the routers' explicit user_id
defense-in-depth filters that back the Postgres policies.

The LLM is never called: the decode LLM pass is driven by monkeypatching the
gateway's `complete` so the REAL validator runs over a canned raw-model payload
(no network), or by making it raise for the "gateway down" degradation path.
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace

import pytest

# ── The pure decoder modules under test ──────────────────────────────────────
from app.decoder.analyze import (
    _DEFAULT_REVIEW_SOURCE,
    _DISCLAIMER,
    _SOURCE_NOTE,
    _VSO_REFERRAL,
    build_decode,
)
from app.decoder.combined_check import (
    _MATCH_NOTE,
    _MISMATCH_NOTE,
    _UNKNOWN_NOTE,
    cross_check_combined,
)
from app.decoder.deadline import add_one_year, appeal_window
from app.decoder.decode import decode_text, validate_decode
from app.rating.engine import RatingEntry, combined_rating

TODAY = date(2026, 7, 6)


# ═══════════════════════════════════════════════════════════════════════════
# 1. deadline.py — pure appeal-window math
# ═══════════════════════════════════════════════════════════════════════════
def test_add_one_year_normal_dates():
    assert add_one_year(date(2021, 3, 14)) == date(2022, 3, 14)
    assert add_one_year(date(2020, 1, 31)) == date(2021, 1, 31)
    assert add_one_year(date(2019, 12, 31)) == date(2020, 12, 31)


def test_add_one_year_leap_feb29_lands_on_feb28():
    # 2020-02-29 → 2021 has no Feb 29; the deadline lands on Feb 28, never rolls
    # into March (a deadline must never quietly gain a day).
    assert add_one_year(date(2020, 2, 29)) == date(2021, 2, 28)
    # Feb 28 in a leap year still maps to Feb 28 (no ValueError path taken).
    assert add_one_year(date(2020, 2, 28)) == date(2021, 2, 28)
    # A leap-to-leap Feb 28 stays Feb 28.
    assert add_one_year(date(2019, 2, 28)) == date(2020, 2, 28)


def test_appeal_window_future_deadline_not_expired():
    w = appeal_window(date(2026, 3, 1), TODAY)
    assert w["deadline"] == "2027-03-01"
    assert w["days_remaining"] > 0
    assert w["expired"] is False


def test_appeal_window_past_deadline_expired():
    w = appeal_window(date(2024, 1, 1), TODAY)
    assert w["deadline"] == "2025-01-01"
    assert w["days_remaining"] < 0
    assert w["expired"] is True


def test_appeal_window_same_day_boundary_not_expired():
    # decision_date + 1yr == today → 0 days left, and 0 is NOT past (0 < 0 False).
    w = appeal_window(date(2025, 7, 6), TODAY)
    assert w["deadline"] == "2026-07-06"
    assert w["days_remaining"] == 0
    assert w["expired"] is False


def test_appeal_window_none_decision_date_all_none():
    assert appeal_window(None, TODAY) == {
        "deadline": None,
        "days_remaining": None,
        "expired": None,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. combined_check.py — §4.25 educational cross-check
# ═══════════════════════════════════════════════════════════════════════════
def test_cross_check_exact_match():
    granted = [{"name": "PTSD", "rating_percent": 50}, {"name": "Knee", "rating_percent": 40}]
    out = cross_check_combined(granted, va_stated=70)
    assert out["computed"] == 70           # 50 & 40 combine to 70 per §4.25
    assert out["va_stated"] == 70
    assert out["matches"] is True
    assert out["note"] == _MATCH_NOTE


def test_cross_check_computed_comes_from_real_engine():
    granted = [{"rating_percent": 50}, {"rating_percent": 40}]
    engine_val = combined_rating(
        [RatingEntry(label="a", percent=50), RatingEntry(label="b", percent=40)]
    ).combined
    assert cross_check_combined(granted, va_stated=70)["computed"] == engine_val


def test_cross_check_mismatch():
    granted = [{"rating_percent": 50}, {"rating_percent": 40}]
    out = cross_check_combined(granted, va_stated=50)
    assert out["computed"] == 70
    assert out["matches"] is False
    assert out["note"] == _MISMATCH_NOTE


def test_cross_check_unknown_when_nothing_granted():
    out = cross_check_combined([], va_stated=70)
    assert out["computed"] is None
    assert out["matches"] is None
    assert out["note"] == _UNKNOWN_NOTE


def test_cross_check_unknown_when_va_stated_none():
    out = cross_check_combined([{"rating_percent": 50}], va_stated=None)
    assert out["computed"] == 50          # our recompute still runs
    assert out["matches"] is None         # …but there's nothing to compare against
    assert out["note"] == _UNKNOWN_NOTE


def test_cross_check_ignores_bool_and_non_int_percents():
    # True is a bool (not a percent), "50" is a string on the wire (not an int) —
    # both are ignored; only the real int 40 is combined.
    granted = [
        {"rating_percent": True},
        {"rating_percent": "50"},
        {"rating_percent": None},
        {"rating_percent": 40},
    ]
    out = cross_check_combined(granted, va_stated=40)
    assert out["computed"] == 40
    assert out["matches"] is True


def test_cross_check_handles_none_granted():
    out = cross_check_combined(None, va_stated=None)
    assert out["computed"] is None and out["matches"] is None
    assert out["note"] == _UNKNOWN_NOTE


# ═══════════════════════════════════════════════════════════════════════════
# 3. decode.py — validate_decode (pure propose/dispose)
# ═══════════════════════════════════════════════════════════════════════════
_EMPTY_SHAPE = {"decision_date": None, "combined_evaluation": None, "decisions": []}


def test_validate_decode_non_dict_inputs_return_empty_shape():
    assert validate_decode(None) == _EMPTY_SHAPE
    assert validate_decode("notadict") == _EMPTY_SHAPE
    assert validate_decode(12345) == _EMPTY_SHAPE
    assert validate_decode([{"name": "X"}]) == _EMPTY_SHAPE


def test_validate_decode_always_returns_full_shape():
    out = validate_decode({})
    assert set(out) == {"decision_date", "combined_evaluation", "decisions"}
    assert out["decisions"] == []


def test_validate_decode_drops_bad_decision_and_nameless_and_non_dict_rows():
    raw = {
        "decisions": [
            {"name": "PTSD", "decision": "granted"},          # kept
            {"name": "Back", "decision": "maybe"},            # bad decision → DROP
            {"name": "Knee", "decision": None},               # no decision → DROP
            {"name": "", "decision": "granted"},              # no name → DROP
            {"decision": "granted"},                          # no name → DROP
            "not-a-dict",                                     # skipped
            42,                                               # skipped
        ]
    }
    out = validate_decode(raw)
    assert [d["name"] for d in out["decisions"]] == ["PTSD"]


def test_validate_decode_percent_and_combined_off_grid_to_none():
    raw = {
        "combined_evaluation": 55,   # not a multiple of 10 → None
        "decisions": [
            {"name": "A", "decision": "granted", "rating_percent": 55},
            {"name": "B", "decision": "granted", "rating_percent": "77"},
            {"name": "C", "decision": "granted", "rating_percent": 105},
            {"name": "D", "decision": "granted", "rating_percent": True},
            {"name": "E", "decision": "granted", "rating_percent": 50},   # valid
            {"name": "F", "decision": "granted", "rating_percent": "70"},  # digit-str ok
        ],
    }
    out = validate_decode(raw)
    assert out["combined_evaluation"] is None
    pct = {d["name"]: d["rating_percent"] for d in out["decisions"]}
    assert pct == {"A": None, "B": None, "C": None, "D": None, "E": 50, "F": 70}


@pytest.mark.parametrize("bad", [55, "77", 105, True, "nope", -10])
def test_validate_decode_combined_off_grid(bad):
    assert validate_decode({"combined_evaluation": bad})["combined_evaluation"] is None


def test_validate_decode_combined_on_grid():
    assert validate_decode({"combined_evaluation": 70})["combined_evaluation"] == 70
    assert validate_decode({"combined_evaluation": 0})["combined_evaluation"] == 0
    assert validate_decode({"combined_evaluation": "80"})["combined_evaluation"] == 80


def test_validate_decode_missing_elements_denied_whitelist_only():
    raw = {
        "decisions": [
            {
                "name": "Denied one",
                "decision": "denied",
                "missing_elements": ["nexus", "current_disability", "made_up", "NEXUS"],
            }
        ]
    }
    out = validate_decode(raw)
    # whitelisted tokens survive (dedup, order-preserving); garbage + wrong-case dropped
    assert out["decisions"][0]["missing_elements"] == ["nexus", "current_disability"]


def test_validate_decode_missing_elements_cleared_for_grants_and_deferrals():
    raw = {
        "decisions": [
            {"name": "G", "decision": "granted", "missing_elements": ["nexus"]},
            {"name": "D", "decision": "deferred", "missing_elements": ["nexus", "in_service_event"]},
        ]
    }
    out = validate_decode(raw)
    assert out["decisions"][0]["missing_elements"] == []
    assert out["decisions"][1]["missing_elements"] == []


def test_validate_decode_missing_elements_garbage_cleared_to_empty():
    raw = {
        "decisions": [
            {"name": "D", "decision": "denied", "missing_elements": ["garbage", 1, None, "foo"]},
            {"name": "E", "decision": "denied", "missing_elements": "nexus"},  # not a list
        ]
    }
    out = validate_decode(raw)
    assert out["decisions"][0]["missing_elements"] == []
    assert out["decisions"][1]["missing_elements"] == []


def test_validate_decode_bad_dates_to_none_good_dates_kept():
    raw = {
        "decision_date": "not-a-date",
        "decisions": [
            {"name": "A", "decision": "granted", "effective_date": "2018-11-02"},
            {"name": "B", "decision": "granted", "effective_date": "garbage"},
            {"name": "C", "decision": "granted", "effective_date": 20181102},  # not a str
        ],
    }
    out = validate_decode(raw)
    assert out["decision_date"] is None
    eff = {d["name"]: d["effective_date"] for d in out["decisions"]}
    assert eff == {"A": "2018-11-02", "B": None, "C": None}
    # a good top-level decision_date is preserved (ISO string)
    assert validate_decode({"decision_date": "2019-03-14"})["decision_date"] == "2019-03-14"


def test_validate_decode_diagnostic_code_shape():
    raw = {
        "decisions": [
            {"name": "A", "decision": "granted", "diagnostic_code": "9411"},
            {"name": "B", "decision": "granted", "diagnostic_code": "941"},   # too short → None
            {"name": "C", "decision": "granted", "diagnostic_code": 9411},    # not a str → None
        ]
    }
    out = validate_decode(raw)
    dc = {d["name"]: d["diagnostic_code"] for d in out["decisions"]}
    assert dc == {"A": "9411", "B": None, "C": None}


def test_validate_decode_full_row_shape():
    raw = {
        "decision_date": "2019-03-14",
        "combined_evaluation": 70,
        "decisions": [
            {
                "name": "PTSD",
                "diagnostic_code": "9411",
                "decision": "granted",
                "rating_percent": 50,
                "effective_date": "2018-11-02",
                "plain": "VA granted service connection for PTSD at 50 percent.",
                "missing_elements": ["nexus"],   # cleared for a grant
                "made_up_field": "discarded",
            }
        ],
    }
    out = validate_decode(raw)
    row = out["decisions"][0]
    assert set(row) == {
        "name", "diagnostic_code", "decision", "rating_percent",
        "effective_date", "plain", "missing_elements",
    }
    assert "made_up_field" not in row
    assert row["missing_elements"] == []


# ═══════════════════════════════════════════════════════════════════════════
# 4. decode.py — decode_text (async LLM pass, gateway monkeypatched)
# ═══════════════════════════════════════════════════════════════════════════
_CANNED_RAW = {
    "decision_date": "2019-03-14",
    "combined_evaluation": 70,
    "decisions": [
        {"name": "PTSD", "diagnostic_code": "9411", "decision": "granted",
         "rating_percent": 50, "effective_date": "2018-11-02",
         "plain": "VA granted PTSD at 50 percent.", "missing_elements": []},
        # 55 off-grid + "maybe" decision + garbage element → validator must dispose.
        {"name": "Tinnitus", "diagnostic_code": "6260", "decision": "denied",
         "rating_percent": 55, "plain": "Denied — no link shown.",
         "missing_elements": ["nexus", "made_up"]},
        {"name": "Nothing", "decision": "maybe"},           # dropped
    ],
}


async def test_decode_text_runs_the_real_validator(monkeypatch):
    from app.llm.gateway import gateway as _gw

    async def fake_complete(messages, **kwargs):
        # wrapped in a code fence + prose to prove parse_llm_json tolerance too
        return "```json\n" + json.dumps(_CANNED_RAW) + "\n```"

    monkeypatch.setattr(_gw, "complete", fake_complete)
    out = await decode_text("A real VA decision letter body.")

    # The REAL validator ran end-to-end over the canned model output.
    assert out == validate_decode(_CANNED_RAW)
    assert out["decision_date"] == "2019-03-14"
    assert out["combined_evaluation"] == 70
    names = [d["name"] for d in out["decisions"]]
    assert names == ["PTSD", "Tinnitus"]        # "Nothing"/maybe dropped
    tin = out["decisions"][1]
    assert tin["rating_percent"] is None        # 55 disposed
    assert tin["missing_elements"] == ["nexus"]  # garbage disposed, denial kept


async def test_decode_text_gateway_error_returns_none(monkeypatch):
    from app.llm.gateway import gateway as _gw

    async def boom(messages, **kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(_gw, "complete", boom)
    assert await decode_text("some text") is None


async def test_decode_text_non_json_returns_none(monkeypatch):
    from app.llm.gateway import gateway as _gw

    async def junk(messages, **kwargs):
        return "I could not read this letter, sorry."

    monkeypatch.setattr(_gw, "complete", junk)
    assert await decode_text("some text") is None


async def test_decode_text_empty_text_skips_gateway(monkeypatch):
    from app.llm.gateway import gateway as _gw

    calls = {"n": 0}

    async def counting(messages, **kwargs):
        calls["n"] += 1
        return "{}"

    monkeypatch.setattr(_gw, "complete", counting)
    assert await decode_text("") is None
    assert await decode_text("   \n\t ") is None
    assert calls["n"] == 0                       # never even reached the gateway


# ═══════════════════════════════════════════════════════════════════════════
# 5. analyze.py — build_decode (pure end-to-end assembly)
# ═══════════════════════════════════════════════════════════════════════════
def _decode_fixture():
    return {
        "decision_date": "2019-03-14",
        "combined_evaluation": 70,
        "decisions": [
            {"name": "PTSD", "diagnostic_code": "9411", "decision": "granted",
             "rating_percent": 50, "effective_date": "2018-11-02",
             "plain": "Granted PTSD at 50%.", "missing_elements": []},
            {"name": "Right knee strain", "diagnostic_code": "5257", "decision": "granted",
             "rating_percent": 40, "effective_date": None,
             "plain": "Granted knee at 40%.", "missing_elements": []},
            {"name": "Tinnitus", "diagnostic_code": "6260", "decision": "denied",
             "rating_percent": None, "effective_date": None,
             "plain": "Denied — no nexus.", "missing_elements": ["nexus"]},
            {"name": "Sleep apnea", "diagnostic_code": None, "decision": "deferred",
             "rating_percent": None, "effective_date": None,
             "plain": "Deferred pending exam.", "missing_elements": []},
        ],
    }


def _build(decode, **over):
    kwargs = dict(
        decode=decode,
        extracted={"is_va_decision": True, "conditions_mentioned": []},
        doc_date=date(2019, 3, 14),
        today=TODAY,
        decoded_at="2026-07-06T00:00:00+00:00",
        document_id="doc-123",
    )
    kwargs.update(over)
    return build_decode(**kwargs)


def test_build_decode_next_steps_per_decision():
    out = _build(_decode_fixture())
    by_name = {d["name"]: d for d in out["decisions"]}
    assert by_name["PTSD"]["next_step"] is None                 # granted
    assert by_name["Right knee strain"]["next_step"] is None    # granted
    assert by_name["Tinnitus"]["next_step"] == "supplemental_claim"  # denied
    assert by_name["Sleep apnea"]["next_step"] == "awaiting"    # deferred


def test_build_decode_has_grants_and_denials():
    out = _build(_decode_fixture())
    assert out["has_grants"] is True
    assert out["has_denials"] is True


def test_build_decode_options_are_the_three_ama_lanes():
    out = _build(_decode_fixture())
    assert [o["key"] for o in out["options"]] == [
        "supplemental_claim", "higher_level_review", "board_appeal"
    ]
    # options are ALWAYS present regardless of outcome (pure grants, no denials)
    grants_only = {
        "decision_date": "2019-03-14", "combined_evaluation": 50,
        "decisions": [{"name": "PTSD", "diagnostic_code": "9411",
                       "decision": "granted", "rating_percent": 50,
                       "effective_date": None, "plain": "x", "missing_elements": []}],
    }
    out2 = _build(grants_only)
    assert [o["key"] for o in out2["options"]] == [
        "supplemental_claim", "higher_level_review", "board_appeal"
    ]
    assert out2["has_denials"] is False


def test_build_decode_combined_check_matches():
    out = _build(_decode_fixture())
    # granted 50 & 40 → 70, va_stated 70 → match
    assert out["combined_check"] == {
        "va_stated": 70, "computed": 70, "matches": True, "note": _MATCH_NOTE
    }


def test_build_decode_va_classification_chips_attached():
    out = _build(_decode_fixture())
    tin = next(d for d in out["decisions"] if d["name"] == "Tinnitus")
    # DC 6260 / "tinnitus" → the official VA contention taxonomy chip
    assert tin["va_classification"] == "Hearing Loss"
    assert tin["va_classification_code"] == 3140


def test_build_decode_decision_date_prefers_decode_over_doc_date():
    out = _build(_decode_fixture(), doc_date=date(2001, 1, 1))
    assert out["decision_date"] == "2019-03-14"        # decode's date wins
    assert out["appeal_window"]["deadline"] == "2020-03-14"


def test_build_decode_decision_date_falls_back_to_doc_date():
    d = _decode_fixture()
    d["decision_date"] = None
    out = _build(d, doc_date=date(2020, 6, 1))
    assert out["decision_date"] == "2020-06-01"
    # a BAD decode date also falls back (build_decode try/except)
    d["decision_date"] = "not-a-date"
    out2 = _build(d, doc_date=date(2020, 6, 1))
    assert out2["decision_date"] == "2020-06-01"


def test_build_decode_decision_date_none_when_no_source():
    d = _decode_fixture()
    d["decision_date"] = None
    out = _build(d, doc_date=None)
    assert out["decision_date"] is None
    assert out["appeal_window"] == {"deadline": None, "days_remaining": None, "expired": None}


def test_build_decode_fallback_from_extracted_when_decode_none():
    extracted = {
        "is_va_decision": True,
        "conditions_mentioned": [
            {"name": "PTSD", "diagnostic_code": "9411",
             "rating_percent": 50, "decision": "granted"},
            {"name": "Tinnitus", "diagnostic_code": "6260",
             "rating_percent": None, "decision": "denied"},
            {"rating_percent": 10, "decision": "granted"},   # no name → dropped
        ],
    }
    out = _build(None, extracted=extracted)
    names = [d["name"] for d in out["decisions"]]
    assert names == ["PTSD", "Tinnitus"]
    assert out["has_grants"] is True and out["has_denials"] is True
    # fallback rows still get the taxonomy chips + next_step
    tin = next(d for d in out["decisions"] if d["name"] == "Tinnitus")
    assert tin["va_classification"] == "Hearing Loss"
    assert tin["next_step"] == "supplemental_claim"
    # no decode → no VA-stated combined to compare
    assert out["combined_check"]["va_stated"] is None
    assert out["combined_check"]["matches"] is None


def test_build_decode_legal_lane_strings_present():
    out = _build(_decode_fixture())
    for key, expected in (
        ("vso_referral", _VSO_REFERRAL),
        ("disclaimer", _DISCLAIMER),
        ("source_note", _SOURCE_NOTE),
    ):
        assert out[key] == expected
        assert out[key].strip()
    # default review source stamped into every lane when caller passes none
    assert all(o["source"] == _DEFAULT_REVIEW_SOURCE for o in out["options"])
    # a passed-in KB source grounds the lanes instead
    grounded = _build(_decode_fixture(), review_source="KB CITE 123")
    assert all(o["source"] == "KB CITE 123" for o in grounded["options"])


def test_build_decode_payload_is_json_serializable():
    out = _build(_decode_fixture())
    dumped = json.dumps(out)          # no date/datetime objects leak
    round_tripped = json.loads(dumped)
    assert round_tripped["decision_date"] == "2019-03-14"
    assert round_tripped["appeal_window"]["deadline"] == "2020-03-14"
    assert isinstance(round_tripped["decisions"], list)


def test_build_decode_empty_when_no_decode_and_no_extracted():
    out = _build(None, extracted=None, doc_date=None)
    assert out["decisions"] == []
    assert out["has_grants"] is False and out["has_denials"] is False
    assert out["combined_check"]["computed"] is None
    json.dumps(out)  # still serializable


# ═══════════════════════════════════════════════════════════════════════════
# 6. Endpoint tests — real documents router, SQLite harness, LLM monkeypatched
# ═══════════════════════════════════════════════════════════════════════════
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
from app.db import Base, personal_workspace_id  # noqa: E402
from app.routers import documents as documents_mod  # noqa: E402

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
    models.Document.__table__,
    models.KBCard.__table__,       # _review_source queries it (returns None when empty)
    models.AuditLog.__table__,
]

for _t in _TABLES:  # gen_random_uuid() → client-side uuid4 (idempotent)
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())


# ── Seed identities + documents ──────────────────────────────────────────────
USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")

DOC_DECISION = uuid.UUID("00000000-0000-0000-0000-0000000d0001")  # A, rating_decision, decodable
DOC_LETTER = uuid.UUID("00000000-0000-0000-0000-0000000d0002")    # A, decision_letter, decodable
DOC_FLAG = uuid.UUID("00000000-0000-0000-0000-0000000d0003")      # A, is_va_decision flag, decodable
DOC_NOTVA = uuid.UUID("00000000-0000-0000-0000-0000000d0004")     # A, treatment_record, NOT decodable
DOC_FAILED = uuid.UUID("00000000-0000-0000-0000-0000000d0005")    # A, not ready
DOC_EMPTY = uuid.UUID("00000000-0000-0000-0000-0000000d0006")     # A, ready but no text
DOC_B = uuid.UUID("00000000-0000-0000-0000-0000000d00b1")         # B, rating_decision

_DECISION_TEXT = "DEPARTMENT OF VETERANS AFFAIRS RATING DECISION\nPTSD granted at 50 percent."

_DECISION_EXTRACTED = {
    "is_va_decision": True,
    "conditions_mentioned": [
        {"name": "PTSD", "diagnostic_code": "9411", "rating_percent": 50, "decision": "granted"},
        {"name": "Tinnitus", "diagnostic_code": "6260", "rating_percent": None, "decision": "denied"},
    ],
}

# The canned raw model output the gateway "returns" for the decode LLM pass.
_ENDPOINT_RAW = {
    "decision_date": "2019-03-14",
    "combined_evaluation": 70,
    "decisions": [
        {"name": "PTSD", "diagnostic_code": "9411", "decision": "granted",
         "rating_percent": 50, "effective_date": "2018-11-02",
         "plain": "VA granted PTSD at 50 percent.", "missing_elements": []},
        {"name": "Right knee strain", "diagnostic_code": "5257", "decision": "granted",
         "rating_percent": 40, "effective_date": None,
         "plain": "VA granted the knee at 40 percent.", "missing_elements": []},
        {"name": "Tinnitus", "diagnostic_code": "6260", "decision": "denied",
         "rating_percent": None, "effective_date": None,
         "plain": "Denied — the letter shows no medical link.",
         "missing_elements": ["nexus", "made_up_token"]},
    ],
}


def _doc(**kw):
    base = dict(
        user_id=USER_A,
        filename="decision.txt",
        content_type="text/plain",
        size_bytes=len(_DECISION_TEXT),
        status="ready",
        doc_type="rating_decision",
        doc_date=date(2019, 3, 14),
        text_content=_DECISION_TEXT,
        extracted=_DECISION_EXTRACTED,
    )
    base.update(kw)
    # unique sha256 per doc id (dedupe key, non-null)
    base.setdefault("sha256", str(base["id"]).replace("-", "").ljust(64, "0")[:64])
    return models.Document(**base)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'decoder_test.db'}", poolclass=NullPool
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
                _doc(id=DOC_DECISION),
                _doc(id=DOC_LETTER, doc_type="decision_letter"),
                _doc(id=DOC_FLAG, doc_type="other",
                     extracted={"is_va_decision": True, "conditions_mentioned": []}),
                _doc(id=DOC_NOTVA, doc_type="treatment_record",
                     extracted={"is_va_decision": False, "conditions_mentioned": []}),
                _doc(id=DOC_FAILED, status="failed", error="LLM unavailable"),
                _doc(id=DOC_EMPTY, text_content="   "),
                _doc(id=DOC_B, user_id=USER_B),
            ])
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
    app.dependency_overrides[deps.current_workspace_id] = (
        lambda: personal_workspace_id(current["uid"])
    )
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current)


def _patch_gateway(monkeypatch, raw=_ENDPOINT_RAW, error=False):
    """Drive the decode LLM pass through the REAL validator over canned JSON."""
    from app.llm.gateway import gateway as _gw

    async def fake_complete(messages, **kwargs):
        if error:
            raise RuntimeError("gateway down")
        return json.dumps(raw)

    monkeypatch.setattr(_gw, "complete", fake_complete)


# ── GET /documents/decodable ─────────────────────────────────────────────────
def test_decodable_lists_only_ready_va_decisions(env):
    ids = {d["id"] for d in env.client.get("/api/documents/decodable").json()}
    # ready VA decisions — by type and by is_va_decision flag — are included
    assert str(DOC_DECISION) in ids
    assert str(DOC_LETTER) in ids
    assert str(DOC_FLAG) in ids
    # non-VA doc and not-ready doc are excluded
    assert str(DOC_NOTVA) not in ids
    assert str(DOC_FAILED) not in ids
    # never another user's document
    assert str(DOC_B) not in ids
    # the list view is slim (no text body)
    body = env.client.get("/api/documents/decodable").json()
    assert body and "text_content" not in body[0]


# ── POST /documents/{id}/decode ──────────────────────────────────────────────
def test_decode_returns_valid_payload_and_caches(env, monkeypatch):
    _patch_gateway(monkeypatch)
    resp = env.client.post(f"/api/documents/{DOC_DECISION}/decode")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["document_id"] == str(DOC_DECISION)
    assert body["decision_date"] == "2019-03-14"
    assert body["has_grants"] is True and body["has_denials"] is True
    # granted 50 & 40 → 70, matches the letter's stated 70
    assert body["combined_check"] == {
        "va_stated": 70, "computed": 70, "matches": True, "note": _MATCH_NOTE
    }
    assert body["appeal_window"]["deadline"] == "2020-03-14"
    assert [o["key"] for o in body["options"]] == [
        "supplemental_claim", "higher_level_review", "board_appeal"
    ]
    by_name = {d["name"]: d for d in body["decisions"]}
    assert by_name["Tinnitus"]["decision"] == "denied"
    assert by_name["Tinnitus"]["next_step"] == "supplemental_claim"
    assert by_name["Tinnitus"]["missing_elements"] == ["nexus"]  # garbage disposed
    assert by_name["Tinnitus"]["va_classification"] == "Hearing Loss"
    assert by_name["PTSD"]["next_step"] is None
    for s in ("vso_referral", "disclaimer", "source_note"):
        assert body[s].strip()

    # Cached into extracted['decode'] — a subsequent GET returns it verbatim.
    got = env.client.get(f"/api/documents/{DOC_DECISION}/decode")
    assert got.status_code == 200
    assert got.json() == body


def test_decode_gateway_down_falls_back_to_grid(env, monkeypatch):
    _patch_gateway(monkeypatch, error=True)
    resp = env.client.post(f"/api/documents/{DOC_DECISION}/decode")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # decode LLM produced nothing → the grant/deny grid comes from the stored
    # classify extraction (PTSD granted, Tinnitus denied), still educational.
    by_name = {d["name"]: d for d in body["decisions"]}
    assert set(by_name) == {"PTSD", "Tinnitus"}
    assert by_name["PTSD"]["decision"] == "granted"
    assert by_name["Tinnitus"]["decision"] == "denied"
    assert body["has_grants"] is True and body["has_denials"] is True
    # no LLM-parsed combined → nothing to cross-check against
    assert body["combined_check"]["va_stated"] is None
    assert body["combined_check"]["matches"] is None


def test_decode_409_when_not_ready(env, monkeypatch):
    _patch_gateway(monkeypatch)
    assert env.client.post(f"/api/documents/{DOC_FAILED}/decode").status_code == 409


def test_decode_409_when_no_text(env, monkeypatch):
    _patch_gateway(monkeypatch)
    assert env.client.post(f"/api/documents/{DOC_EMPTY}/decode").status_code == 409


def test_decode_409_when_not_va_decision(env, monkeypatch):
    _patch_gateway(monkeypatch)
    assert env.client.post(f"/api/documents/{DOC_NOTVA}/decode").status_code == 409


# ── GET /documents/{id}/decode ───────────────────────────────────────────────
def test_get_decode_404_before_any_decode(env):
    assert env.client.get(f"/api/documents/{DOC_DECISION}/decode").status_code == 404


# ── Cross-user isolation (RLS-shaped 404 defense-in-depth) ───────────────────
def test_cross_user_cannot_decode_or_read_or_list(env, monkeypatch):
    _patch_gateway(monkeypatch)
    # A decodes their own document and caches it.
    assert env.client.post(f"/api/documents/{DOC_DECISION}/decode").status_code == 200

    # B cannot see it in decodable, cannot POST-decode it, cannot GET the decode.
    env.current["uid"] = str(USER_B)
    b_ids = {d["id"] for d in env.client.get("/api/documents/decodable").json()}
    assert str(DOC_DECISION) not in b_ids and str(DOC_LETTER) not in b_ids
    assert env.client.post(f"/api/documents/{DOC_DECISION}/decode").status_code == 404
    assert env.client.get(f"/api/documents/{DOC_DECISION}/decode").status_code == 404

    # A still can.
    env.current["uid"] = str(USER_A)
    assert env.client.get(f"/api/documents/{DOC_DECISION}/decode").status_code == 200
