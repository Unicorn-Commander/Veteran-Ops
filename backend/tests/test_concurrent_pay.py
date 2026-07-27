"""Concurrent-pay engine — CRDP (§1414) / CRSC (§1413a) pure-logic unit tests.

Deterministic and DB-free, like the rating engine. The legal lane is asserted:
NO outcome-promise language, and `likely_fits` is only ever a read of the veteran's
own facts — never "you qualify" / "you will receive".
"""

from __future__ import annotations

import re

from app.strategy.concurrent_pay import (
    CRDP_MIN_RATING,
    CRSC_MIN_RATING,
    crdp_restoration_estimate,
    screen_concurrent_pay,
)

# Language that would cross the legal lane — must never appear in a read.
_PROMISE = re.compile(
    r"\b(you (?:qualify|will (?:get|receive|be granted|be paid)|are eligible|are entitled)|"
    r"guarantee|guaranteed|approved for|you'll get)\b",
    re.IGNORECASE,
)


def _no_promises(screen: dict) -> None:
    blob = str(screen)
    m = _PROMISE.search(blob)
    assert not m, f"promise language leaked: {m.group()!r}"


# ── CRDP read (§1414) ────────────────────────────────────────────────────────
def test_crdp_fits_retiree_at_50():
    """A retiree at exactly the 50% threshold → CRDP likely fits, automatic."""
    s = screen_concurrent_pay(50, receives_retired_pay=True, combat_related=False)
    assert s["crdp"]["likely_fits"] is True
    assert s["crdp"]["status"] == "likely_eligible"
    assert s["crdp"]["requires_application"] is False
    assert s["crdp"]["taxable"] is True
    assert s["crdp"]["statute"] == "10 U.S.C. §1414"
    _no_promises(s)


def test_crdp_below_threshold_at_40():
    """A retiree below 50% → CRDP does not currently fit (ratings can change)."""
    s = screen_concurrent_pay(40, receives_retired_pay=True, combat_related=False)
    assert s["crdp"]["likely_fits"] is False
    assert s["crdp"]["status"] == "below_rating_threshold"
    _no_promises(s)


def test_crdp_not_a_retiree():
    """No military retired pay → CRDP can't apply, regardless of rating."""
    s = screen_concurrent_pay(90, receives_retired_pay=False, combat_related=True)
    assert s["crdp"]["likely_fits"] is False
    assert s["crdp"]["status"] == "not_a_retiree"
    _no_promises(s)


def test_crdp_unknown_retired_status():
    """Retired-pay fact absent → we can't read it; prompt to fill the profile."""
    s = screen_concurrent_pay(80, receives_retired_pay=None, combat_related=True)
    assert s["retired_pay_known"] is False
    assert s["receives_retired_pay"] is None
    assert s["crdp"]["status"] == "unknown"
    assert s["crsc"]["status"] == "unknown"
    assert s["crdp"]["likely_fits"] is False
    assert s["crsc"]["likely_fits"] is False
    _no_promises(s)


# ── CRSC read (§1413a) ───────────────────────────────────────────────────────
def test_crsc_fits_combat_retiree():
    """Retiree + combat-related disability at 10%+ → CRSC likely, needs DD 2860, tax-free."""
    s = screen_concurrent_pay(30, receives_retired_pay=True, combat_related=True)
    assert s["crsc"]["likely_fits"] is True
    assert s["crsc"]["status"] == "likely_eligible"
    assert s["crsc"]["requires_application"] is True
    assert s["crsc"]["form"] == "DD Form 2860"
    assert s["crsc"]["taxable"] is False
    assert s["crsc"]["statute"] == "10 U.S.C. §1413a"
    _no_promises(s)


def test_crsc_needs_combat_related():
    """Retiree with no combat-related disability marked → CRSC doesn't fit yet."""
    s = screen_concurrent_pay(70, receives_retired_pay=True, combat_related=False)
    assert s["crsc"]["likely_fits"] is False
    assert s["crsc"]["status"] == "needs_combat_related"
    _no_promises(s)


def test_crsc_below_rating_threshold():
    """Combat-related but combined rating below 10% → below CRSC's rating floor."""
    s = screen_concurrent_pay(0, receives_retired_pay=True, combat_related=True)
    assert s["crsc"]["likely_fits"] is False
    assert s["crsc"]["status"] == "below_rating_threshold"
    _no_promises(s)


# ── The election point (can't hold both) ─────────────────────────────────────
def test_both_fit_forces_election():
    """Retiree + 70% + combat-related → both fit → must elect one, note present."""
    s = screen_concurrent_pay(70, receives_retired_pay=True, combat_related=True)
    assert s["crdp"]["likely_fits"] is True
    assert s["crsc"]["likely_fits"] is True
    assert s["must_elect"] is True
    assert s["election_note"]
    assert "open season" in s["election_note"].lower()
    _no_promises(s)


def test_only_one_fits_no_election():
    """CRDP fits but CRSC doesn't (no combat) → no election needed."""
    s = screen_concurrent_pay(60, receives_retired_pay=True, combat_related=False)
    assert s["crdp"]["likely_fits"] is True
    assert s["crsc"]["likely_fits"] is False
    assert s["must_elect"] is False
    assert s["election_note"] == ""
    _no_promises(s)


# ── input normalization ──────────────────────────────────────────────────────
def test_none_rating_normalizes_to_zero():
    s = screen_concurrent_pay(None, receives_retired_pay=True, combat_related=True)
    assert s["combined_rating"] == 0
    assert s["crdp"]["likely_fits"] is False  # 0 < 50
    _no_promises(s)


def test_out_of_range_rating_is_clamped():
    s = screen_concurrent_pay(150, receives_retired_pay=True, combat_related=False)
    assert s["combined_rating"] == 100
    assert s["crdp"]["likely_fits"] is True
    _no_promises(s)


def test_thresholds_are_the_documented_statutory_ones():
    assert CRDP_MIN_RATING == 50
    assert CRSC_MIN_RATING == 10


def test_what_to_do_present_for_eligible_retiree():
    s = screen_concurrent_pay(70, receives_retired_pay=True, combat_related=True)
    assert s["what_to_do"]
    joined = " ".join(s["what_to_do"]).lower()
    assert "dfas" in joined
    assert "dd form 2860" in joined


# ── CRDP restoration estimate (rough, bounded, deterministic) ────────────────
def test_estimate_returns_ceiling_when_crdp_fits():
    est = crdp_restoration_estimate(1500.0, crdp_fits=True)
    assert est is not None
    assert est["monthly_ceiling"] == 1500.0
    assert est["is_estimate"] is True
    assert "estimate" in est["basis"].lower()
    # Never promissory.
    assert not _PROMISE.search(str(est))


def test_estimate_none_when_crdp_does_not_fit():
    assert crdp_restoration_estimate(1500.0, crdp_fits=False) is None


def test_estimate_none_without_a_base_amount():
    assert crdp_restoration_estimate(None, crdp_fits=True) is None
    assert crdp_restoration_estimate(0.0, crdp_fits=True) is None


def test_estimate_is_deterministic():
    a = crdp_restoration_estimate(2311.04, crdp_fits=True)
    b = crdp_restoration_estimate(2311.04, crdp_fits=True)
    assert a == b
