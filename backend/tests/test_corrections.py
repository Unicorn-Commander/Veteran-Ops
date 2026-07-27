"""WAVE10 — military records corrections routing + packet. Pure-engine tests (the
routing is legally consequential — the wrong board wastes months) + the endpoints.
"""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace

import pytest

from app.corrections.draft import build_correction_packet
from app.corrections.route import route_correction

# No promise/guarantee language may appear (educational lane).
_PROMISE = re.compile(
    r"\b(you will (?:get|receive|win|be upgraded)|we will file|guarantee|guaranteed|"
    r"definitely|is certain to)\b",
    re.IGNORECASE,
)


def _no_promises(obj):
    m = _PROMISE.search(str(obj))
    assert not m, f"promise language leaked: {m.group()!r}"


def test_in_window_discharge_upgrade_routes_to_drb():
    r = route_correction({"goals": ["discharge_upgrade"], "years_since_separation": 5})
    assert r["routed"] and r["board"] == "DRB" and r["form"] == "DD Form 293"
    # BCMR is offered as the fallback.
    assert any(a["board"] == "BCMR" for a in r["also_consider"])
    _no_promises(r)


def test_over_15_years_routes_to_bcmr():
    r = route_correction({"goals": ["discharge_upgrade"], "years_since_separation": 20})
    assert r["board"] == "BCMR" and r["form"] == "DD Form 149"


def test_general_court_martial_forces_bcmr_with_warning():
    r = route_correction({
        "goals": ["discharge_upgrade"], "years_since_separation": 2,
        "general_court_martial": True,
    })
    assert r["board"] == "BCMR"
    assert any("court-martial" in w.lower() for w in r["warnings"])


def test_drb_denied_forces_bcmr():
    r = route_correction({
        "goals": ["narrative_reason"], "years_since_separation": 3, "drb_denied": True,
    })
    assert r["board"] == "BCMR"


def test_unknown_separation_date_routes_to_bcmr():
    r = route_correction({"goals": ["re_code"], "years_since_separation": None})
    assert r["board"] == "BCMR"


def test_records_error_routes_to_bcmr():
    r = route_correction({"goals": ["records_error"]})
    assert r["board"] == "BCMR"


def test_pdbr_for_2001_2009_low_rating_medical_separation():
    r = route_correction({
        "goals": ["medical_rating"],
        "medically_separated_2001_2009": True, "dod_rating_20_or_less": True,
    })
    assert r["board"] == "PDBR" and r["form"] == "DD Form 294"


def test_medical_rating_without_pdbr_window_falls_through():
    # Not a 2001-2009 low-rating separation → not PDBR; with no discharge goal it's a
    # records-style correction → BCMR (medical rating correction via the catch-all).
    r = route_correction({"goals": ["medical_rating"]})
    assert r["board"] == "BCMR"


def test_re_code_only_routes_to_bcmr_not_drb():
    # RE-code corrections are a BCMR matter even within 15 years (review M1).
    r = route_correction({"goals": ["re_code"], "years_since_separation": 3})
    assert r["board"] == "BCMR"
    assert "RE" in r["why"] and "reenlistment" in r["why"].lower()


def test_re_code_rides_along_with_discharge_upgrade_at_drb():
    # When it accompanies a real discharge goal, the RE code follows at the DRB.
    r = route_correction({"goals": ["discharge_upgrade", "re_code"], "years_since_separation": 3})
    assert r["board"] == "DRB"
    assert "RE" in r["why"]


def test_discharge_plus_nonpdbr_medical_surfaces_bcmr_for_the_rating():
    # Review M2: the medical need must not be silently dropped on a DRB route.
    r = route_correction({"goals": ["discharge_upgrade", "medical_rating"],
                          "years_since_separation": 5})
    assert r["board"] == "DRB"
    assert any(a["board"] == "BCMR" and "rating" in a["when"].lower()
               for a in r["also_consider"])


def test_medical_rating_only_bcmr_uses_medical_copy_not_clerical():
    # Review M3: BCMR medical route explains rating/retirement, not "typos".
    r = route_correction({"goals": ["medical_rating"]})
    assert r["board"] == "BCMR"
    assert "retire" in r["why"].lower() and "rating" in r["why"].lower()


def test_general_discharge_without_upgrade_gets_no_oth_note():
    # Review N1: a General (under honorable) discharge doesn't trigger the OTH bar.
    r = route_correction({"goals": ["narrative_reason"], "years_since_separation": 5,
                          "discharge_char": "general"})
    assert r["character_of_discharge_note"] is None


def test_liberal_consideration_applies_only_to_discharge_goals():
    yes = route_correction({"goals": ["discharge_upgrade"], "years_since_separation": 4,
                            "related_to": ["mst"]})
    assert yes["liberal_consideration"]["applies"] is True
    assert "liberal consideration" in yes["liberal_consideration"]["note"].lower()
    # PTSD but only a records-error goal → liberal consideration doesn't apply.
    no = route_correction({"goals": ["records_error"], "related_to": ["ptsd"]})
    assert no["liberal_consideration"]["applies"] is False


def test_character_of_discharge_note_on_oth_upgrade():
    r = route_correction({"goals": ["discharge_upgrade"], "years_since_separation": 5,
                          "discharge_char": "oth"})
    assert r["character_of_discharge_note"] and "character-of-discharge" in r["character_of_discharge_note"].lower()


def test_no_goal_selected_guides_without_routing():
    r = route_correction({"goals": []})
    assert r["routed"] is False and r["board"] is None
    assert r["vso_referral"] and r["legal_aid_referral"] and r["disclaimer"]


def test_every_route_carries_legal_aid_and_disclaimer():
    for goals in (["discharge_upgrade"], ["records_error"], ["medical_rating"], []):
        r = route_correction({"goals": goals, "years_since_separation": 5})
        assert r["vso_referral"] and r["legal_aid_referral"] and r["disclaimer"]
        _no_promises(r)


def test_packet_preserves_verbatim_statement_and_liberal_language():
    rare = "QVX-VERBATIM-4471"
    p = build_correction_packet(payload={
        "situation": {"goals": ["discharge_upgrade"], "years_since_separation": 4,
                      "related_to": ["ptsd"]},
        "applicant_name": "Riley Example",
        "corrections_requested": [
            {"field": "Character of service", "current": "Other Than Honorable",
             "requested": "Honorable"},
        ],
        "veteran_statement": f"Here is what happened. {rare}",
    }, prepared_on="2026-07-06")
    assert p["route"]["board"] == "DRB"
    # verbatim statement survives byte-for-byte
    assert rare in p["statement_of_error_or_injustice"]
    assert rare in (p["veteran_statement"] or "")
    # structured request rendered
    assert "Character of service" in p["statement_of_error_or_injustice"]
    # liberal consideration language present (PTSD-connected discharge)
    assert "liberal consideration" in p["statement_of_error_or_injustice"].lower()
    # tailored evidence + attestation + referrals
    assert any("DD-214" in e["item"] for e in p["evidence_checklist"])
    assert any("diagnosis" in e["item"].lower() for e in p["evidence_checklist"])
    assert p["attestation"] and p["signature_block"]
    assert p["legal_aid_referral"] and p["disclaimer"]
    _no_promises(p)


def test_packet_without_statement_leaves_a_prompt_not_a_fabrication():
    p = build_correction_packet(payload={
        "situation": {"goals": ["records_error"]},
        "veteran_statement": None,
    })
    # No fabricated narrative — a bracketed prompt for the veteran to fill.
    assert "[Write" in p["statement_of_error_or_injustice"]


# ── Endpoint smoke (auth only; stateless — no DB) ────────────────────────────

fastapi = pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import deps  # noqa: E402
from app.routers import corrections as corrections_mod  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(corrections_mod.router, prefix="/api")
    app.dependency_overrides[deps.current_user_id] = lambda: str(uuid.uuid4())
    with TestClient(app) as c:
        yield c


def test_route_endpoint(client):
    r = client.post("/api/corrections/route",
                    json={"goals": ["discharge_upgrade"], "years_since_separation": 5,
                          "related_to": ["ptsd"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["board"] == "DRB" and body["liberal_consideration"]["applies"] is True


def test_draft_endpoint(client):
    r = client.post("/api/corrections/draft", json={
        "situation": {"goals": ["records_error"]},
        "corrections_requested": [{"field": "Middle name", "requested": "Quentin"}],
        "veteran_statement": "My name is misspelled.",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["route"]["board"] == "BCMR"
    assert body["prepared_on"]  # router stamped it
    assert "My name is misspelled." in body["statement_of_error_or_injustice"]
