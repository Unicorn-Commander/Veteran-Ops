"""Deterministic-core tests for the 'what's changed since you were rated' workflow.

The AI judgment (assess_actionability) is not tested here — it's additive and
network-bound; these cover the pure matching/date logic that decides what a veteran
sees, which must be exactly right (a false 'you may now qualify' is a real harm)."""

from types import SimpleNamespace as NS

from app.analysis import regulatory_changes as rc
from app.analysis import whats_changed as wc


def _cond(name, dc=None):
    return NS(name=name, diagnostic_code=dc)


def test_changes_after_filters_strictly_by_date():
    after = {c.id for c in rc.changes_after("2024-01-16")}
    # Digestive rule took effect 2024-05-19 (after) — included.
    assert "digestive-2024" in after
    # PACT Act burn-pit presumptives (2022-08-10) predate this rating — excluded.
    assert "pact-act-burn-pit-2022" not in after


def test_changes_after_none_returns_all():
    assert len(rc.changes_after(None)) == len(rc.REGULATORY_CHANGES)


def test_match_by_diagnostic_code_changed_rule_signals_review():
    change = next(c for c in rc.REGULATORY_CHANGES if c.id == "digestive-2024")
    m = wc._match_change(change, [_cond("GERD", "7206")], {})
    assert m is not None
    assert m.matched_by == "condition"
    assert m.action_signal == "review"  # a FINAL rule → act
    assert "GERD" in m.matched_detail and "7206" in m.matched_detail


def test_proposed_rule_signals_watch_not_review():
    change = next(c for c in rc.REGULATORY_CHANGES if c.id == "tinnitus-proposed")
    m = wc._match_change(change, [_cond("Tinnitus", "6260")], {})
    assert m is not None and m.action_signal == "watch"  # proposed → never "act now"


def test_match_by_exposure_for_presumptive_addition():
    change = next(c for c in rc.REGULATORY_CHANGES if c.id == "pact-act-burn-pit-2022")
    m = wc._match_change(change, [], {"burn_pits": True})
    assert m is not None
    assert m.matched_by == "exposure" and m.action_signal == "check_eligibility"


def test_no_match_when_neither_condition_nor_exposure_applies():
    change = next(c for c in rc.REGULATORY_CHANGES if c.id == "digestive-2024")
    # A knee condition + no relevant exposure → the digestive change doesn't apply.
    assert wc._match_change(change, [_cond("Knee strain", "5257")], {"agent_orange": True}) is None


def test_exposure_does_not_match_a_pure_rule_change():
    # A rule change with no exposure tags must not match on exposures alone.
    change = next(c for c in rc.REGULATORY_CHANGES if c.id == "digestive-2024")
    assert change.exposure_tags == ()
    assert wc._match_change(change, [], {"burn_pits": True, "agent_orange": True}) is None


def test_every_change_has_a_source_and_iso_date():
    for c in rc.REGULATORY_CHANGES:
        assert c.source_url.startswith("http")
        assert len(c.effective_date) == 10 and c.effective_date[4] == "-"
        assert c.status in {"changed", "proposed"}
