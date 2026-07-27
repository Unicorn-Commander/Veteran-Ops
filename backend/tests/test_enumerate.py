from __future__ import annotations

import uuid

import pytest

from app.firm.candidates import CandidateRating
from app.firm.context import VeteranDossier
from app.firm.enumerate import enumerate_candidates


def _cond(**kw):
    base = {
        "id": str(uuid.uuid4()),
        "name": "X",
        "claim_type": "direct",
        "status": "considering",
        "va_status": "unknown",
        "diagnostic_code": None,
        "current_rating": None,
        "target_rating": None,
        "band": "early",
        "missing": [],
        "has_have_evidence": False,
    }
    base.update(kw)
    return base


def _dossier(conditions=None, *, current_combined=None, profile=None):
    return VeteranDossier(
        uid=str(uuid.uuid4()),
        conditions=conditions or [],
        current_combined=current_combined,
        profile=profile,
        generated_at="2026-07-09T00:00:00+00:00",
    )


# ── direct ────────────────────────────────────────────────────────────────────


def test_direct_emits_known_dc_from_condition():
    c = _cond(name="PTSD", diagnostic_code="9411")
    result = enumerate_candidates(_dossier([c]))
    direct = [r for r in result if r.origin == "direct"]
    assert len(direct) >= 1
    cr = direct[0]
    assert cr.diagnostic_code == "9411"
    assert cr.origin == "direct"
    assert "claimed/known condition" in cr.seed_signal.lower()
    assert cr.source_ref == c["id"]
    assert cr.primary_dc is None


def test_direct_emits_multiple_conditions():
    c1 = _cond(name="PTSD", diagnostic_code="9411")
    c2 = _cond(name="Chronic fatigue syndrome", diagnostic_code="6354")
    result = enumerate_candidates(_dossier([c1, c2]))
    direct = [r for r in result if r.origin == "direct"]
    codes = {r.diagnostic_code for r in direct}
    assert "9411" in codes
    assert "6354" in codes


def test_direct_emits_only_the_conditions_own_dc_not_siblings():
    # A condition maps to ITS code only. We must NOT fan out to every DC in the
    # same schedule group: knee bursitis is not bone cancer + every muscle group,
    # anxiety is not schizophrenia + Alzheimer's. That expansion produced 100+
    # trust-destroying candidates on real records.
    c = _cond(name="Right knee instability", diagnostic_code="5257")
    result = enumerate_candidates(_dossier([c]))
    direct = [r for r in result if r.origin == "direct" and r.source_ref == c["id"]]
    assert [r.diagnostic_code for r in direct] == ["5257"]  # exactly one, its own code
    assert "sibling" not in direct[0].seed_signal.lower()


# ── increase ──────────────────────────────────────────────────────────────────


def test_increase_emitted_when_rated_with_evidence():
    c = _cond(
        name="PTSD",
        diagnostic_code="9411",
        va_status="service_connected",
        current_rating=30,
        target_rating=50,
        band="complete",
        has_have_evidence=True,
    )
    result = enumerate_candidates(_dossier([c]))
    increase = [r for r in result if r.origin == "increase"]
    assert len(increase) >= 1
    cr = increase[0]
    assert cr.diagnostic_code == "9411"
    assert "rated at 30%" in cr.seed_signal
    assert "target 50% is higher" in cr.seed_signal
    assert cr.source_ref == c["id"]


def test_increase_skipped_when_not_rated():
    c = _cond(name="PTSD", diagnostic_code="9411", va_status="not_service_connected")
    result = enumerate_candidates(_dossier([c]))
    increase = [r for r in result if r.origin == "increase"]
    assert increase == []


def test_increase_skipped_when_no_evidence():
    c = _cond(
        name="PTSD",
        diagnostic_code="9411",
        va_status="service_connected",
        current_rating=30,
        target_rating=50,
        band="early",
        has_have_evidence=False,
    )
    result = enumerate_candidates(_dossier([c]))
    increase = [r for r in result if r.origin == "increase"]
    assert increase == []


def test_increase_skipped_without_explicit_higher_target():
    c = _cond(
        name="PTSD",
        diagnostic_code="9411",
        va_status="service_connected",
        current_rating=30,
        target_rating=30,
        band="complete",
        has_have_evidence=True,
    )
    assert [r for r in enumerate_candidates(_dossier([c])) if r.origin == "increase"] == []


# ── secondary ─────────────────────────────────────────────────────────────────


def test_secondary_emitted_for_known_primary():
    c = _cond(name="PTSD", diagnostic_code="9411", va_status="service_connected")
    result = enumerate_candidates(_dossier([c]))
    secondaries = [r for r in result if r.origin == "secondary"]
    assert len(secondaries) >= 1
    for s in secondaries:
        assert s.origin == "secondary"
        assert "§3.310" in s.seed_signal
        assert s.primary_dc == "9411"
        assert s.source_ref is None


def test_secondary_primary_dc_matches_origin():
    c = _cond(name="PTSD", diagnostic_code="9411", va_status="service_connected")
    result = enumerate_candidates(_dossier([c]))
    secondaries = [r for r in result if r.origin == "secondary"]
    assert all(s.primary_dc == "9411" for s in secondaries)


# ── presumptive ───────────────────────────────────────────────────────────────


def test_presumptive_emitted_on_exposure_flag():
    profile = {
        "service_periods": [
            {
                "branch": "Army",
                "start_date": "2003-01-15",
                "end_date": "2007-11-20",
            }
        ],
        "exposures": {"burn_pits": True},
    }
    result = enumerate_candidates(_dossier(current_combined=0, profile=profile))
    presumptives = [r for r in result if r.origin == "presumptive"]
    assert len(presumptives) >= 1
    for p in presumptives:
        assert p.origin == "presumptive"
        assert p.seed_signal


def test_presumptive_emitted_on_service_period_overlap():
    profile = {
        "service_periods": [
            {
                "branch": "Marines",
                "start_date": "2005-06-01",
                "end_date": "2009-08-15",
            }
        ],
        "exposures": {},
    }
    result = enumerate_candidates(_dossier(current_combined=0, profile=profile))
    presumptives = [r for r in result if r.origin == "presumptive"]
    assert len(presumptives) >= 1


def test_presumptive_not_emitted_without_service_facts():
    result = enumerate_candidates(_dossier(current_combined=0, profile=None))
    presumptives = [r for r in result if r.origin == "presumptive"]
    assert presumptives == []


# ── concurrent ────────────────────────────────────────────────────────────────


def test_concurrent_emitted_when_combined_rating_high_enough():
    profile = {
        "service_periods": [
            {
                "branch": "Army",
                "start_date": "1995-06-01",
                "end_date": "2018-08-15",
            }
        ],
        "exposures": {"military_retired": True},
    }
    result = enumerate_candidates(_dossier(current_combined=70, profile=profile))
    concurrent = [r for r in result if r.origin == "concurrent"]
    assert len(concurrent) == 1
    cr = concurrent[0]
    assert cr.diagnostic_code == ""
    assert cr.title == "Concurrent receipt (CRDP/CRSC)"
    assert "CRDP" in cr.seed_signal
    assert cr.body_system is None


def test_concurrent_skipped_when_no_combined_rating():
    profile = {
        "service_periods": [{"branch": "Army", "start_date": "2000-01-01", "end_date": "2004-01-01"}],
        "exposures": {"military_retired": True},
    }
    result = enumerate_candidates(_dossier(current_combined=None, profile=profile))
    concurrent = [r for r in result if r.origin == "concurrent"]
    assert concurrent == []


def test_concurrent_skipped_when_no_periods():
    result = enumerate_candidates(_dossier(current_combined=60, profile={"service_periods": [], "exposures": {}}))
    concurrent = [r for r in result if r.origin == "concurrent"]
    assert concurrent == []


def test_concurrent_requires_explicit_retired_pay_fact():
    profile = {
        "service_periods": [
            {"branch": "Army", "start_date": "1995-01-01", "end_date": "2020-01-01"}
        ],
        "exposures": {},
    }
    assert [
        r for r in enumerate_candidates(_dossier(current_combined=70, profile=profile))
        if r.origin == "concurrent"
    ] == []


# ── dedupe ────────────────────────────────────────────────────────────────────


def test_dedupe_collapses_same_origin_dc():
    c1 = _cond(name="PTSD", diagnostic_code="9411")
    c2 = _cond(name="Posttraumatic stress disorder", diagnostic_code="9411")
    result = enumerate_candidates(_dossier([c1, c2]))
    direct = [r for r in result if r.origin == "direct" and r.diagnostic_code == "9411"]
    assert len(direct) == 1


def test_dedupe_preserves_different_origins():
    c = _cond(
        name="PTSD",
        diagnostic_code="9411",
        va_status="service_connected",
        current_rating=30,
        target_rating=50,
        band="complete",
        has_have_evidence=True,
    )
    result = enumerate_candidates(_dossier([c]))
    codes = {(r.diagnostic_code, r.origin) for r in result}
    assert ("9411", "direct") in codes
    assert ("9411", "increase") in codes


# ── unresolvable ──────────────────────────────────────────────────────────────


def test_unresolvable_condition_does_not_fabricate_dc():
    c = _cond(name="Some rare disease XKCD-42", diagnostic_code=None)
    result = enumerate_candidates(_dossier([c]))
    direct = [r for r in result if r.origin == "direct"]
    assert len(direct) == 1
    cr = direct[0]
    assert cr.diagnostic_code == ""
    assert "unresolved" in cr.seed_signal.lower()


# ── empty dossier ─────────────────────────────────────────────────────────────


def test_empty_dossier_returns_empty_list():
    result = enumerate_candidates(_dossier([]))
    assert result == []


def test_no_conditions_still_yields_presumptive_and_concurrent():
    profile = {
        "service_periods": [
            {
                "branch": "Army",
                "start_date": "1995-06-01",
                "end_date": "2018-08-15",
            }
        ],
        "exposures": {"burn_pits": True, "military_retired": True},
    }
    result = enumerate_candidates(_dossier([], current_combined=70, profile=profile))
    origins = {r.origin for r in result}
    assert "presumptive" in origins
    assert "concurrent" in origins
    assert "direct" not in origins
    assert "increase" not in origins
    assert "secondary" not in origins


# ── CandidateRating value object ──────────────────────────────────────────────


def test_candidate_rating_is_frozen():
    cr = CandidateRating(
        diagnostic_code="9411",
        title="Posttraumatic stress disorder",
        body_system="Mental Disorders",
        origin="direct",
        seed_signal="claimed condition 'PTSD'",
        source_ref=None,
        primary_dc=None,
    )
    with pytest.raises(AttributeError):
        cr.diagnostic_code = "0000"


def test_candidate_rating_all_origins_have_nonempty_seed():
    profile = {
        "service_periods": [
            {"branch": "Army", "start_date": "2003-01-15", "end_date": "2007-11-20"}
        ],
        "exposures": {"burn_pits": True},
    }
    c = _cond(
        name="PTSD",
        diagnostic_code="9411",
        va_status="service_connected",
        current_rating=30,
        band="complete",
        has_have_evidence=True,
    )
    result = enumerate_candidates(_dossier([c], current_combined=70, profile=profile))
    for r in result:
        assert r.seed_signal, f"candidate {r.origin}/{r.diagnostic_code} has empty seed_signal"


# ── body_system from max_ratings ──────────────────────────────────────────────


def test_body_system_populated_from_max_ratings():
    c = _cond(name="PTSD", diagnostic_code="9411")
    result = enumerate_candidates(_dossier([c]))
    direct = [r for r in result if r.origin == "direct" and r.diagnostic_code == "9411"]
    assert len(direct) == 1
    assert direct[0].body_system == "Mental Disorders"
