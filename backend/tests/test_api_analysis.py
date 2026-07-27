"""Unit tests for the deterministic analysis cores — pure functions, no DB/LLM.

Covers the presumptive matcher (profile × KB lists), the evidence-gap analyzer
(three-element rules), the secondary-map keyword matcher, and the LLM-output
grounding validator.
"""

from __future__ import annotations

from datetime import date

from app.analysis.gaps import analyze_gaps
from app.analysis.mapping import (
    extract_tiers,
    parse_llm_json,
    tier_percents,
    validate_selection,
)
from app.analysis.presumptives import match_presumptives
from app.analysis.secondaries import match_secondaries
from app.kb.store import load_cards, load_secondary_map

TODAY = date(2026, 7, 5)


def _presumptive_cards() -> list[dict]:
    return [c for c in load_cards() if c["card_type"] == "presumptive"]


# ── Presumptive matcher ──────────────────────────────────────────────────────
def test_presumptive_exposure_flag_match():
    profile = {"service_periods": [], "exposures": {"burn_pits": True}}
    matches = match_presumptives(profile, _presumptive_cards(), TODAY)
    programs = {m["program"] for m in matches}
    assert "pact_burn_pits" in programs
    m = next(m for m in matches if m["program"] == "pact_burn_pits")
    assert "burn pits" in m["matched_reason"]
    assert m["conditions"]
    assert m["source"]


def test_presumptive_service_window_match():
    """A 2004–2008 service period overlaps the post-9/11 PACT window and the
    Gulf War window — WITHOUT any exposure flags set."""
    profile = {
        "service_periods": [{"start_date": "2004-01-15", "end_date": "2008-06-30"}],
        "exposures": {},
    }
    matches = match_presumptives(profile, _presumptive_cards(), TODAY)
    programs = {m["program"] for m in matches}
    assert "pact_burn_pits" in programs
    assert "gulf_war" in programs
    # Vietnam-era-only windows must NOT match a 2004 period.
    assert "agent_orange" not in programs


def test_presumptive_vietnam_window_match():
    profile = {
        "service_periods": [{"start_date": "1968-01-01", "end_date": "1970-12-31"}],
        "exposures": {},
    }
    matches = match_presumptives(profile, _presumptive_cards(), TODAY)
    assert "agent_orange" in {m["program"] for m in matches}


def test_presumptive_open_ended_period_treated_as_ongoing():
    profile = {
        "service_periods": [{"start_date": "2020-01-01", "end_date": None}],
        "exposures": {},
    }
    matches = match_presumptives(profile, _presumptive_cards(), TODAY)
    assert "pact_burn_pits" in {m["program"] for m in matches}


def test_presumptive_chronic_one_year_rule():
    recent = {
        "service_periods": [{"start_date": "2020-01-01", "end_date": "2025-12-01"}],
        "exposures": {},
    }
    matches = match_presumptives(recent, _presumptive_cards(), TODAY)
    assert "chronic_one_year" in {m["program"] for m in matches}

    old = {
        "service_periods": [{"start_date": "2010-01-01", "end_date": "2014-01-01"}],
        "exposures": {},
    }
    matches = match_presumptives(old, _presumptive_cards(), TODAY)
    assert "chronic_one_year" not in {m["program"] for m in matches}


def test_presumptive_empty_profile_no_matches():
    assert match_presumptives({}, _presumptive_cards(), TODAY) == []
    assert match_presumptives(None, _presumptive_cards(), TODAY) == []


def test_pow_presumptive_flag_match():
    """POW card surfaces when pow flag is set (flag_only)."""
    profile = {"service_periods": [], "exposures": {"pow": True}}
    matches = match_presumptives(profile, _presumptive_cards(), TODAY)
    programs = {m["program"] for m in matches}
    assert "pow" in programs
    m = next(m for m in matches if m["program"] == "pow")
    assert m["conditions"]


def test_pow_presumptive_no_flag_no_match():
    """POW card does NOT surface when pow flag is not set."""
    profile = {"service_periods": [], "exposures": {}}
    matches = match_presumptives(profile, _presumptive_cards(), TODAY)
    assert "pow" not in {m["program"] for m in matches}


def test_presumptive_gap_pow_exposure_counts_as_qualifying_service():
    """POW / mustard gas flags must satisfy presumptive 'qualifying service' gap."""
    from app.analysis.gaps import analyze_gaps

    cond = {
        "name": "Psychosis",
        "claim_type": "presumptive",
        "in_service_event": None,
        "nexus_notes": None,
    }
    gaps_no = analyze_gaps(cond, [], {"service_periods": [], "exposures": {}})
    assert any(g.get("kind") == "service_record" for g in gaps_no)

    gaps_pow = analyze_gaps(
        cond, [], {"service_periods": [], "exposures": {"pow": True}}
    )
    assert not any(g.get("kind") == "service_record" for g in gaps_pow)


def test_pow_internment_duration_branches_condition_lists():
    """§3.309(c): any-period vs 30+ day lists branch on pow_internment_days."""
    from app.analysis.presumptives import match_presumptives as match

    any_only = {
        "card_type": "presumptive",
        "title": "Former POW",
        "source": "38 CFR §3.309(c)",
        "data": {
            "program": "pow",
            "exposure_flags": ["pow"],
            "match": "flag_only",
            "conditions_any_period": ["psychosis", "anxiety state"],
            "conditions_thirty_days": ["beriberi", "avitaminosis", "psychosis"],
            "conditions": ["psychosis", "anxiety state", "beriberi", "avitaminosis"],
        },
    }
    # No duration → any-period floor only (not the full bag).
    m0 = match(
        {"exposures": {"pow": True}},
        [any_only],
        TODAY,
    )
    assert m0 and set(m0[0]["conditions"]) == {"psychosis", "anxiety state"}
    assert "any period" in m0[0]["matched_reason"].lower() or "internment" in m0[0]["matched_reason"].lower()

    # Under 30 days → still any-period only.
    m_short = match(
        {"exposures": {"pow": True, "pow_internment_days": 10}},
        [any_only],
        TODAY,
    )
    assert set(m_short[0]["conditions"]) == {"psychosis", "anxiety state"}
    assert "under 30" in m_short[0]["matched_reason"].lower()

    # 30+ days → merge both lists (deduped).
    m_long = match(
        {"exposures": {"pow": True, "pow_internment_days": 45}},
        [any_only],
        TODAY,
    )
    assert set(m_long[0]["conditions"]) == {
        "psychosis",
        "anxiety state",
        "beriberi",
        "avitaminosis",
    }
    assert "30+" in m_long[0]["matched_reason"] or "30" in m_long[0]["matched_reason"]


def test_cumulative_service_days():
    from app.analysis.presumptives import cumulative_service_days

    assert cumulative_service_days(None) == 0
    assert cumulative_service_days([]) == 0
    assert cumulative_service_days([{"start_date": "2000-01-01", "end_date": "2000-01-10"}]) == 9
    # No end date → period contributes 0 days
    assert cumulative_service_days([{"start_date": "2000-01-01", "end_date": None}]) == 0
    # Invalid dates are skipped
    assert cumulative_service_days([{"start_date": None, "end_date": None}]) == 0
    # 90+ days
    assert cumulative_service_days([{"start_date": "2000-01-01", "end_date": "2000-04-01"}]) >= 90


def test_als_keyword_detection():
    """The ALS keyword patterns used in _suggestions match expected strings."""
    als_keywords = {"als", "amyotrophic", "lou gehrig", "motor neuron"}
    assert any(kw in "als" for kw in als_keywords)
    assert any(kw in "amyotrophic lateral sclerosis" for kw in als_keywords)
    assert any(kw in "motor neuron disease" for kw in als_keywords)
    assert any(kw in "Lou Gehrig's disease".lower() for kw in als_keywords)
    assert not any(kw in "back strain" for kw in als_keywords)
    assert not any(kw in "PTSD" for kw in als_keywords)


def test_als_presumptive_requires_condition_and_90_days():
    """ALS (§3.318): 90+ service days alone must NOT match; condition gate required."""
    profile = {
        "service_periods": [{"start_date": "2000-01-01", "end_date": "2004-01-01"}],
        "exposures": {},
    }
    # No condition_names → no ALS spam for every long-service veteran.
    matches = match_presumptives(profile, _presumptive_cards(), TODAY)
    assert "als" not in {m["program"] for m in matches}

    # ALS condition + 90+ days → program fires with §3.318 source.
    matches = match_presumptives(
        profile,
        _presumptive_cards(),
        TODAY,
        condition_names=["Amyotrophic lateral sclerosis"],
    )
    programs = {m["program"] for m in matches}
    assert "als" in programs
    m = next(m for m in matches if m["program"] == "als")
    assert "3.318" in (m.get("source") or "")
    assert m["conditions"]


def test_als_presumptive_no_match_under_90_days():
    """ALS does not fire when cumulative service is under 90 days."""
    profile = {
        "service_periods": [{"start_date": "2000-01-01", "end_date": "2000-02-01"}],
        "exposures": {},
    }
    matches = match_presumptives(
        profile,
        _presumptive_cards(),
        TODAY,
        condition_names=["ALS"],
    )
    assert "als" not in {m["program"] for m in matches}


def test_chronic_1yr_keyword_detection():
    """The §3.309(a) chronic-disease keywords used in _suggestions (surfaced for
    OLDER separations) match the common chronic conditions and not unrelated ones."""
    chronic_keywords = {
        "arthritis", "diabetes", "hypertension", "high blood pressure",
        "cardiovascular", "heart disease", "sensorineural hearing loss",
        "hearing loss", "tinnitus", "peptic ulcer", "epilepsy", "psychosis",
    }
    for name in ["Type 2 diabetes mellitus", "Essential hypertension",
                 "Bilateral hearing loss", "Tinnitus", "Degenerative arthritis"]:
        assert any(kw in name.lower() for kw in chronic_keywords), name
    for name in ["Left knee strain", "Erectile dysfunction", "Shrapnel wound"]:
        assert not any(kw in name.lower() for kw in chronic_keywords), name


# ── Gap analyzer ─────────────────────────────────────────────────────────────
def test_gaps_direct_all_missing():
    gaps = analyze_gaps({"name": "Lumbar strain", "claim_type": "direct"}, [], None)
    kinds = [g["kind"] for g in gaps]
    assert kinds == ["diagnosis", "service_record", "nexus_letter", "continuity"]
    assert all(g["source"] for g in gaps)


def test_gaps_direct_satisfied_by_evidence_and_fields():
    condition = {
        "name": "Lumbar strain",
        "claim_type": "direct",
        "in_service_event": "Fell off a truck at Ft. Bragg, 2006",
        "nexus_notes": "Dr. Smith letter, at least as likely as not",
    }
    evidence = [
        {"kind": "diagnosis", "status": "have"},
        {"kind": "treatment_record", "status": "have"},
    ]
    assert analyze_gaps(condition, evidence, None) == []


def test_gaps_need_status_does_not_satisfy():
    gaps = analyze_gaps(
        {"name": "X", "claim_type": "direct"},
        [{"kind": "diagnosis", "status": "need"}],
        None,
    )
    assert "diagnosis" in [g["kind"] for g in gaps]


def test_gaps_secondary_rules():
    gaps = analyze_gaps({"name": "Sleep apnea", "claim_type": "secondary"}, [], None)
    kinds = [g["kind"] for g in gaps]
    assert "diagnosis" in kinds
    assert "other" in kinds  # missing primary link
    assert "nexus_letter" in kinds
    assert "service_record" not in kinds  # secondary path doesn't need in-service event

    gaps = analyze_gaps(
        {"name": "Sleep apnea", "claim_type": "secondary", "secondary_to": "some-uuid"},
        [{"kind": "diagnosis", "status": "have"}, {"kind": "nexus_letter", "status": "have"}],
        None,
    )
    assert gaps == []


def test_gaps_presumptive_needs_qualifying_service():
    gaps = analyze_gaps(
        {"name": "Hypertension", "claim_type": "presumptive"},
        [{"kind": "diagnosis", "status": "have"}],
        {"service_periods": [], "exposures": {}},
    )
    assert [g["kind"] for g in gaps] == ["service_record"]

    gaps = analyze_gaps(
        {"name": "Hypertension", "claim_type": "presumptive"},
        [{"kind": "diagnosis", "status": "have"}],
        {"service_periods": [{"start_date": "1968-01-01"}], "exposures": {}},
    )
    assert gaps == []


def test_gaps_increase_needs_current_treatment():
    gaps = analyze_gaps({"name": "PTSD", "claim_type": "increase"}, [], None)
    kinds = [g["kind"] for g in gaps]
    assert "treatment_record" in kinds

    gaps = analyze_gaps(
        {"name": "PTSD", "claim_type": "increase"},
        [{"kind": "diagnosis", "status": "have"}, {"kind": "treatment_record", "status": "have"}],
        None,
    )
    assert gaps == []


# ── Secondary matcher ────────────────────────────────────────────────────────
def test_secondaries_ptsd_suggests_osa():
    out = match_secondaries(["PTSD"], load_secondary_map())
    secondaries = {m["secondary"] for m in out}
    assert "Obstructive sleep apnea" in secondaries
    for m in out:
        assert m["primary"] == "PTSD"
        assert m["source"] == "38 CFR §3.310 (see rationale)"
        assert m["rationale"]
        assert m["dbq"]


def test_secondaries_skip_already_claimed():
    out = match_secondaries(["PTSD", "Obstructive sleep apnea"], load_secondary_map())
    ptsd_secondaries = {m["secondary"] for m in out if m["primary"] == "PTSD"}
    assert "Obstructive sleep apnea" not in ptsd_secondaries


def test_secondaries_no_match():
    assert match_secondaries(["Zqxwv nonsense"], load_secondary_map()) == []
    assert match_secondaries([], load_secondary_map()) == []


# ── LLM-output grounding validation ──────────────────────────────────────────
_CARDS = [
    {
        "title": "Mental disorders",
        "diagnostic_code": "9411",
        "source": "38 CFR §4.130",
        "data": {"tiers": [{"percent": 30, "criteria": "a"}, {"percent": 50, "criteria": "b"}]},
    },
    {
        "title": "Migraines",
        "diagnostic_code": "8100",
        "source": "38 CFR §4.124a",
        "data": {"tiers": [{"percent": 30, "criteria": "c"}]},
    },
]


def test_extract_tiers_and_percents():
    tiers = extract_tiers(_CARDS[0]["data"])
    assert [t["percent"] for t in tiers] == [30, 50]
    assert tier_percents(_CARDS[0]["data"]) == {30, 50}
    assert extract_tiers(None) == []


def test_validate_selection_accepts_grounded_answer():
    idx, pct, rationale = validate_selection(
        {"card_index": 0, "suggested_tier_percent": 50, "rationale": "criteria describe b"},
        _CARDS,
    )
    assert (idx, pct, rationale) == (0, 50, "criteria describe b")


def test_validate_selection_drops_invented_percent():
    """A percent not present in the chosen card's tiers MUST be dropped."""
    idx, pct, _ = validate_selection(
        {"card_index": 0, "suggested_tier_percent": 70, "rationale": "x"}, _CARDS
    )
    assert idx == 0
    assert pct is None  # 70 is not a tier of card 0 (even though DC 9411 has one IRL)


def test_validate_selection_drops_bad_card_index():
    assert validate_selection({"card_index": 9, "suggested_tier_percent": 30}, _CARDS) == (
        None, None, None,
    )
    assert validate_selection(None, _CARDS) == (None, None, None)


def test_validate_selection_drops_rationale_citing_unknown_dc():
    _, _, rationale = validate_selection(
        {"card_index": 0, "suggested_tier_percent": 30,
         "rationale": "This is really DC 5237 territory"},
        _CARDS,
    )
    assert rationale is None


def test_parse_llm_json_tolerates_wrapping():
    assert parse_llm_json('noise {"a": 1} trailing')["a"] == 1
    assert parse_llm_json("no json here") is None
    assert parse_llm_json("") is None


def test_flag_only_programs_never_match_on_dates_alone():
    """Radiation/Camp Lejeune/Mustard Gas windows span most of history — date overlap says
    nothing about the actual exposure, so match='flag_only' cards require the
    explicit profile flag (the false-positive found in live E2E)."""
    from datetime import date
    from app.analysis.presumptives import match_presumptives
    from app.kb.store import load_cards

    cards = [c for c in load_cards() if c["card_type"] == "presumptive"]
    profile = {
        "service_periods": [{"start_date": "2003-06-01", "end_date": "2016-03-01"}],
        "exposures": {"burn_pits": True, "gulf_war": True},
    }
    programs = {m["program"] for m in match_presumptives(profile, cards, today=date(2026, 7, 5))}
    assert "radiation" not in programs and "camp_lejeune" not in programs and "mustard_gas" not in programs
    assert {"pact_burn_pits", "gulf_war"} <= programs
    # The flag still matches when actually set.
    profile["exposures"]["radiation"] = True
    programs = {m["program"] for m in match_presumptives(profile, cards, today=date(2026, 7, 5))}
    assert "radiation" in programs


def test_mustard_gas_flag_only_match():
    """Mustard gas card surfaces only when mustard_gas flag is set (flag_only)."""
    profile = {"service_periods": [], "exposures": {"mustard_gas": True}}
    cards = [c for c in load_cards() if c["card_type"] == "presumptive"]
    matches = match_presumptives(profile, cards, TODAY)
    programs = {m["program"] for m in matches}
    assert "mustard_gas" in programs
    m = next(m for m in matches if m["program"] == "mustard_gas")
    assert m["conditions"]
    assert m["matched_reason"]
    assert "mustard gas" in m["matched_reason"].lower()


def test_mustard_gas_no_flag_no_match():
    """Mustard gas card does NOT surface when mustard_gas flag is not set."""
    profile = {"service_periods": [{"start_date": "1990-01-01", "end_date": "1991-06-01"}], "exposures": {}}
    cards = [c for c in load_cards() if c["card_type"] == "presumptive"]
    matches = match_presumptives(profile, cards, TODAY)
    programs = {m["program"] for m in matches}
    # A Gulf War service period matches gulf_war and pact_burn_pits, but NOT mustard_gas.
    assert "gulf_war" in programs
    assert "pact_burn_pits" in programs
    assert "mustard_gas" not in programs


def test_gulf_war_infectious_flag_match():
    """Gulf War infectious diseases card surfaces when gulf_war flag is set."""
    profile = {"service_periods": [], "exposures": {"gulf_war": True}}
    cards = [c for c in load_cards() if c["card_type"] == "presumptive"]
    matches = match_presumptives(profile, cards, TODAY)
    programs = {m["program"] for m in matches}
    assert "gulf_war_infectious" in programs
    assert "gulf_war" in programs
    infectious = next(m for m in matches if m["program"] == "gulf_war_infectious")
    assert "malaria" in infectious["conditions"]
    assert "brucellosis" in infectious["conditions"]
    assert "tuberculosis" in infectious["conditions"]
    assert len(infectious["conditions"]) == 9


def test_gulf_war_infectious_service_window_match():
    """Gulf War infectious diseases card surfaces when service period overlaps
    the Afghanistan window (2001-09-19 onward) or Southwest Asia window."""
    afghanistan = {
        "service_periods": [{"start_date": "2002-06-01", "end_date": "2003-06-01"}],
        "exposures": {},
    }
    matches = match_presumptives(afghanistan, _presumptive_cards(), TODAY)
    programs = {m["program"] for m in matches}
    assert "gulf_war_infectious" in programs

    southwest_asia = {
        "service_periods": [{"start_date": "1991-01-01", "end_date": "1991-12-31"}],
        "exposures": {},
    }
    matches = match_presumptives(southwest_asia, _presumptive_cards(), TODAY)
    programs = {m["program"] for m in matches}
    assert "gulf_war_infectious" in programs

    # Pre-1990 service — no match.
    korea = {
        "service_periods": [{"start_date": "1980-01-01", "end_date": "1989-12-31"}],
        "exposures": {},
    }
    matches = match_presumptives(korea, _presumptive_cards(), TODAY)
    programs = {m["program"] for m in matches}
    assert "gulf_war_infectious" not in programs


def test_dbq_body_system_fallback_prefers_generic_entry():
    """Sinusitis has no name-keyword hit pre-expansion; the respiratory fallback
    must pick the generic Respiratory DBQ, never Sleep Apnea (order-of-catalog
    bug found by the harden swarm)."""
    from app.analysis.gaps import map_dbq
    from app.kb.store import load_dbq_catalog

    catalog = load_dbq_catalog()
    dbq = map_dbq("Chronic sinusitis", "respiratory", catalog)
    assert dbq and "Respiratory Conditions DBQ" in dbq
    # Sleep apnea itself still maps to its own DBQ via the phrase match.
    assert "Sleep Apnea DBQ" in map_dbq("Obstructive sleep apnea", "respiratory", catalog)
