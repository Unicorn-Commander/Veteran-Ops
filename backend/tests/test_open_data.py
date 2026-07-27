"""VA open-data integrations: vendored loaders, at-max gap rule, contention
classification attach, eCFR freshness compare, and the new /kb endpoints.

Loader + rule tests are pure (no DB, no network). Endpoint tests mount the real
kb router on a bare FastAPI app with the auth dependency overridden; the
freshness endpoint's eCFR fetch is monkeypatched (no network in tests).
"""

from __future__ import annotations

from datetime import date

import pytest

from app.analysis.gaps import analyze_gaps
from app.kb.freshness import KB_VERIFIED_AS_OF, is_stale
from app.kb.store import (
    classify_contention,
    load_contention_map,
    load_max_ratings,
    validate_kb_max_ratings,
)

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deps  # noqa: E402
from app.routers import kb as kb_router_mod  # noqa: E402


# ── Loaders (vendored CSVs) ──────────────────────────────────────────────────
def test_load_max_ratings_parses_and_spot_checks():
    ratings = load_max_ratings()
    assert len(ratings) > 500
    tinnitus = ratings["6260"]
    assert tinnitus["max_rating"] == 10
    assert tinnitus["body_system"] == "The Organs of Special Sense"
    assert tinnitus["cfr_reference"] == "38 CFR 4.87"
    assert "tinnitus" in tinnitus["rated_issue_name"].lower()
    # every row carries the contract keys with a sane percent
    for row in ratings.values():
        assert 0 <= row["max_rating"] <= 100
        assert set(row) >= {"max_rating", "body_system", "category", "cfr_reference"}


def test_load_contention_map_parses_and_spot_checks():
    cmap = load_contention_map()
    assert len(cmap["by_dc"]) > 500
    assert len(cmap["by_text"]) > 500
    assert cmap["by_dc"]["6260"]["classification_name"] == "Hearing Loss"
    assert cmap["by_text"]["tinnitus"]["classification_name"] == "Hearing Loss"


def test_loaders_degrade_to_empty_when_vendor_dir_missing(monkeypatch, tmp_path):
    from app.kb import store

    monkeypatch.setattr(store, "VENDOR_DIR", tmp_path / "nope")
    assert store.load_max_ratings() == {}
    cmap = store.load_contention_map()
    assert cmap == {"by_dc": {}, "by_text": {}}
    # matcher over an empty map: no hit, no crash
    assert store.classify_contention(text="tinnitus", cmap=cmap) is None
    # gap rule with no dataset: no info gap, no crash
    gaps = analyze_gaps(
        {"name": "Tinnitus", "claim_type": "increase",
         "diagnostic_code": "6260", "current_rating": 10},
        [{"kind": "treatment_record", "status": "have"},
         {"kind": "diagnosis", "status": "have"}],
        max_ratings={},
    )
    assert gaps == []


# ── Contention classification matcher ────────────────────────────────────────
def test_classify_contention_text_matches():
    cmap = load_contention_map()
    hit = classify_contention(text="Tinnitus", cmap=cmap)
    assert hit and hit["classification_name"] == "Hearing Loss"
    assert hit["match"] == "text"
    # synonym + filler-word stripping both resolve deterministically
    assert classify_contention(text="ringing in ears", cmap=cmap)["classification_name"] == "Hearing Loss"
    assert classify_contention(text="chronic tinnitus", cmap=cmap)["classification_name"] == "Hearing Loss"
    assert classify_contention(text="totally made up nonsense", cmap=cmap) is None


def test_classify_contention_dc_beats_text():
    cmap = load_contention_map()
    hit = classify_contention(text="no such words", diagnostic_code="6260", cmap=cmap)
    assert hit and hit["classification_name"] == "Hearing Loss"
    assert hit["match"] == "diagnostic_code"


def test_attach_va_classifications():
    from app.intake.classify import attach_va_classifications

    cmap = load_contention_map()
    mentioned = [
        {"name": "tinnitus", "rating_percent": 10, "diagnostic_code": None, "decision": "granted"},
        {"name": "mystery ailment", "rating_percent": None, "diagnostic_code": "5000", "decision": None},
        {"name": "utterly unknown thing", "rating_percent": None, "diagnostic_code": None, "decision": None},
    ]
    out = attach_va_classifications(mentioned, cmap=cmap)
    assert out[0]["va_classification"] == "Hearing Loss"
    assert out[0]["va_classification_code"] == 3140
    # DC hit even when the text misses
    assert out[1]["va_classification"] == "Musculoskeletal - Osteomyelitis"
    # miss stamps None (UI can rely on the keys)
    assert out[2]["va_classification"] is None
    assert out[2]["va_classification_code"] is None


# ── At-schedular-maximum gap rule ────────────────────────────────────────────
_MAX = {"6260": {"diagnostic_code": "6260", "rated_issue_name": "Tinnitus, recurrent",
                 "max_rating": 10, "body_system": "The Organs of Special Sense",
                 "category": "Ear", "cfr_reference": "38 CFR 4.87"}}
_TREATMENT = [{"kind": "treatment_record", "status": "have"},
              {"kind": "diagnosis", "status": "have"}]


def test_increase_at_max_emits_info_gap():
    gaps = analyze_gaps(
        {"name": "Tinnitus", "claim_type": "increase",
         "diagnostic_code": "6260", "current_rating": 10},
        _TREATMENT,
        max_ratings=_MAX,
    )
    info = [g for g in gaps if "schedular maximum" in g["label"]]
    assert len(info) == 1
    assert info[0]["kind"] == "other"
    assert "§4.16" in info[0]["source"] and "§3.350" in info[0]["source"]
    assert "TDIU" in info[0]["detail"]
    assert "can't go higher" in info[0]["detail"]


def test_increase_at_max_does_not_remove_existing_gaps():
    gaps = analyze_gaps(
        {"name": "Tinnitus", "claim_type": "increase",
         "diagnostic_code": "6260", "current_rating": 10},
        [],  # no evidence at all → diagnosis + treatment gaps still emitted
        max_ratings=_MAX,
    )
    kinds = [g["kind"] for g in gaps]
    assert "diagnosis" in kinds
    assert "treatment_record" in kinds
    assert "other" in kinds  # plus the info item


@pytest.mark.parametrize(
    "condition",
    [
        # below the ceiling → no info gap
        {"name": "PTSD", "claim_type": "increase", "diagnostic_code": "9411", "current_rating": 70},
        # at max but not an increase claim → rule doesn't apply
        {"name": "Tinnitus", "claim_type": "direct", "diagnostic_code": "6260", "current_rating": 10},
        # unknown DC → no info gap
        {"name": "Tinnitus", "claim_type": "increase", "diagnostic_code": "0000", "current_rating": 10},
        # no current rating recorded → no info gap
        {"name": "Tinnitus", "claim_type": "increase", "diagnostic_code": "6260", "current_rating": None},
    ],
)
def test_no_info_gap_when_rule_does_not_apply(condition):
    max_map = {**_MAX, "9411": {"diagnostic_code": "9411", "rated_issue_name": "PTSD",
                                "max_rating": 100, "body_system": "Mental",
                                "category": None, "cfr_reference": "38 CFR 4.130"}}
    gaps = analyze_gaps(condition, _TREATMENT, max_ratings=max_map)
    assert not any("schedular maximum" in g["label"] for g in gaps)


def test_at_max_rule_with_real_dataset():
    gaps = analyze_gaps(
        {"name": "Tinnitus", "claim_type": "increase",
         "diagnostic_code": "6260", "current_rating": 10},
        _TREATMENT,
        max_ratings=load_max_ratings(),
    )
    assert any("schedular maximum" in g["label"] for g in gaps)


# ── KB QA: card tiers vs dataset ceilings ────────────────────────────────────
def test_validate_kb_max_ratings_runs_and_reports_dicts():
    issues = validate_kb_max_ratings()
    for issue in issues:
        assert issue["card_max"] > issue["dataset_max"]
        assert issue["diagnostic_code"]
    # The knee card was un-bound from DC 5257 (multi-code card, tiers name their
    # own DCs) after the validator caught the contradiction — the KB must now be
    # contradiction-free against VA's max-ratings dataset.
    assert issues == []


# ── eCFR freshness (pure compare) ────────────────────────────────────────────
def test_is_stale_pure_compare():
    v = date(2026, 7, 5)
    assert is_stale("2026-08-01", v) is True
    assert is_stale("2026-06-15", v) is False
    assert is_stale("2026-07-05", v) is False  # same day = verified
    assert is_stale(date(2026, 7, 6), v) is True
    assert is_stale(None, v) is False  # unknown → no false alarm
    assert is_stale("not-a-date", v) is False
    assert KB_VERIFIED_AS_OF == date(2026, 7, 25)


# ── New /kb endpoints (real router, auth overridden, no network) ─────────────
@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(kb_router_mod.router, prefix="/api")
    app.dependency_overrides[deps.current_user_id] = lambda: "00000000-0000-0000-0000-000000000001"
    with TestClient(app) as c:
        yield c


def test_kb_max_rating_endpoint(client):
    r = client.get("/api/kb/max-rating/6260")
    assert r.status_code == 200
    body = r.json()
    assert body["max_rating"] == 10
    assert body["body_system"] == "The Organs of Special Sense"
    assert body["cfr_reference"] == "38 CFR 4.87"
    assert "source" in body

    assert client.get("/api/kb/max-rating/0000").status_code == 404


def test_kb_classify_contention_endpoint(client):
    r = client.get("/api/kb/classify-contention", params={"text": "tinnitus"})
    assert r.status_code == 200
    body = r.json()
    assert body["matched"] is True
    assert body["classification_name"] == "Hearing Loss"
    assert body["classification_code"] == 3140

    r = client.get("/api/kb/classify-contention", params={"text": "zz unknown zz"})
    assert r.status_code == 200
    assert r.json()["matched"] is False
    assert r.json()["classification_name"] is None


def test_kb_freshness_endpoint_stale_and_current(client, monkeypatch):
    from app.kb import freshness as fr

    async def _amended_after(timeout: float = 10.0):
        return "2099-01-01"

    monkeypatch.setattr(fr, "fetch_title38_latest_amended", _amended_after)
    body = client.get("/api/kb/freshness").json()
    assert body["stale"] is True
    assert body["title38_latest_amended_on"] == "2099-01-01"
    assert body["kb_verified_as_of"] == KB_VERIFIED_AS_OF.isoformat()

    async def _amended_before(timeout: float = 10.0):
        return "2020-01-01"

    monkeypatch.setattr(fr, "fetch_title38_latest_amended", _amended_before)
    assert client.get("/api/kb/freshness").json()["stale"] is False


def test_kb_freshness_endpoint_degrades_without_network(client, monkeypatch):
    from app.kb import freshness as fr

    async def _boom(timeout: float = 10.0):
        raise RuntimeError("ecfr down")

    monkeypatch.setattr(fr, "fetch_title38_latest_amended", _boom)
    monkeypatch.setattr(fr, "_last_result", None)
    body = client.get("/api/kb/freshness").json()
    assert body["stale"] is False
    assert body["error"] == "ecfr_unreachable"

    # with a cached prior success, the cache is served instead
    cached = {"title38_latest_amended_on": "2026-06-15",
              "kb_verified_as_of": KB_VERIFIED_AS_OF.isoformat(), "stale": False}
    monkeypatch.setattr(fr, "_last_result", cached)
    body = client.get("/api/kb/freshness").json()
    assert body["cached"] is True
    assert body["title38_latest_amended_on"] == "2026-06-15"
