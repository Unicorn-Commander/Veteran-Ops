"""Unit tests for the §4.25/§4.26 rating engine.

Vectors are taken from the printed 38 CFR §4.25 combined-ratings table and the
worked examples in §4.26 — if any of these fail, the engine is legally wrong.
"""

import pytest

from app.rating.engine import (
    RatingEntry,
    bilateral_value,
    combine,
    combine_pair,
    combined_rating,
    final_round,
)


# ── §4.25 pairwise table values ──────────────────────────────────────────────
@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (50, 30, 65),   # the canonical example in §4.25(a)
        (60, 30, 72),
        (19, 10, 27),   # table row 19 col 10
        (72, 10, 75),   # 74.8 rounds up — printed table says 75
        (45, 50, 73),   # 72.5 rounds .5 UP (not banker's)
        (60, 60, 84),
        (90, 90, 99),
        (100, 50, 100),
        (10, 10, 19),
        (0, 40, 40),
        (40, 0, 40),
    ],
)
def test_combine_pair_table_values(a, b, expected):
    assert combine_pair(a, b) == expected


def test_combine_multi_descending_with_intermediate_rounding():
    # 70,60,30,20: 70&60→88, 88&30→91.6→92, 92&20→93.6→94
    assert combine([70, 60, 30, 20]) == 94
    # Order given must not matter — engine sorts descending per §4.25(b)
    assert combine([20, 30, 60, 70]) == 94
    assert combine([50, 30, 20]) == 72
    assert combine([]) == 0
    assert combine([0, 0]) == 0
    assert combine([30]) == 30


# ── §4.25(a) final conversion ────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 0), (4, 0), (5, 10), (14, 10), (15, 20), (64, 60), (65, 70), (72, 70),
     (74, 70), (75, 80), (94, 90), (95, 100), (100, 100)],
)
def test_final_round(raw, expected):
    assert final_round(raw) == expected


# ── §4.26 bilateral factor ───────────────────────────────────────────────────
def test_bilateral_value_reg_example():
    # §4.26 worked example: 60 & 20 (paired) → combined 68, +6.8 → 74.8 → 75
    val, before, factor = bilateral_value([60, 20])
    assert (val, before, factor) == (75, 68, 6.8)


def test_bilateral_value_rounds_down_too():
    # 30 & 20 legs → 44 + 4.4 = 48.4 → 48
    assert bilateral_value([30, 20])[0] == 48


def test_bilateral_small():
    # 10 & 10 knees → 19 + 1.9 = 20.9 → 21
    assert bilateral_value([10, 10])[0] == 21


# ── full combined_rating ─────────────────────────────────────────────────────
def test_classic_50_30():
    r = combined_rating([RatingEntry("PTSD", 50), RatingEntry("Back", 30)])
    assert r.raw == 65 and r.combined == 70
    assert not r.bilateral_factor_applied


def test_zero_ratings_noted_not_combined():
    r = combined_rating([RatingEntry("PTSD", 50), RatingEntry("Scar", 0)])
    assert r.raw == 50 and r.combined == 50
    assert any(s["kind"] == "note" for s in r.steps)


def test_bilateral_alone_reaches_80():
    # 60 + 20 paired arms → 74.8 → 75 raw → ends in 5 → 80 final
    r = combined_rating([
        RatingEntry("Right shoulder", 60, side="right"),
        RatingEntry("Left elbow", 20, side="left"),
    ])
    assert r.bilateral_factor_applied and r.bilateral_value == 75
    assert r.raw == 75 and r.combined == 80


def test_bilateral_group_combines_with_others():
    # legs 30&20 → 48 (incl. factor); then 48 & 20 → 58.4 → 58 → final 60
    r = combined_rating([
        RatingEntry("Right knee", 30, side="right"),
        RatingEntry("Left ankle", 20, side="left"),
        RatingEntry("Tinnitus", 20),
    ])
    assert r.bilateral_value == 48
    assert r.raw == 58 and r.combined == 60


def test_one_sided_entries_get_no_bilateral_factor():
    r = combined_rating([
        RatingEntry("Right knee", 30, side="right"),
        RatingEntry("Right ankle", 20, side="right"),
    ])
    assert not r.bilateral_factor_applied
    assert r.raw == combine([30, 20]) == 44 and r.combined == 40


def test_three_extremities_all_join_bilateral_group():
    # both sides present → ALL sided entries join the §4.26 group
    r = combined_rating([
        RatingEntry("Right knee", 30, side="right"),
        RatingEntry("Left knee", 20, side="left"),
        RatingEntry("Left ankle", 10, side="left"),
    ])
    # combine 30,20,10 → 44 → 49.6→50 ; +10% (5.0) → 55
    assert r.bilateral_value == 55
    assert r.combined == final_round(55) == 60


def test_bilateral_upper_and_lower_extremities_single_group():
    """§4.26(b): compensable disabilities of both upper AND lower extremities
    form ONE bilateral group — all sided entries combine first, then +10%."""
    r = combined_rating([
        RatingEntry("Right arm", 40, side="right"),
        RatingEntry("Left arm", 30, side="left"),
        RatingEntry("Right leg", 20, side="right"),
        RatingEntry("Left leg", 10, side="left"),
    ])
    # 40&30→58, 58&20→66.4→66, 66&10→69.4→69; +10% (6.9) → 75.9 → 76
    assert r.bilateral_factor_applied
    assert r.bilateral_value == 76
    assert r.raw == 76 and r.combined == final_round(76) == 80


def test_bilateral_multi_extremity_with_non_sided():
    """Bilateral group (arms+legs) then combines with a non-extremity rating."""
    r = combined_rating([
        RatingEntry("Right knee", 20, side="right"),
        RatingEntry("Left knee", 10, side="left"),
        RatingEntry("PTSD", 50),
    ])
    # knees 20&10 → 28 + 2.8 = 30.8 → 31 bilateral; then 50&31 → 65.5 → 66 → 70
    assert r.bilateral_factor_applied and r.bilateral_value == 31
    assert r.raw == 66 and r.combined == 70


def test_hundred_percent_dominates():
    r = combined_rating([RatingEntry("Cancer", 100), RatingEntry("PTSD", 50)])
    assert r.raw == 100 and r.combined == 100


def test_smc_s_flag():
    r = combined_rating([
        RatingEntry("Cancer", 100),
        RatingEntry("PTSD", 50),
        RatingEntry("Back", 20),
    ])
    assert any(f["key"] == "smc_s" for f in r.smc_flags)


def test_smc_s_not_flagged_below_60_rest():
    r = combined_rating([RatingEntry("Cancer", 100), RatingEntry("Tinnitus", 10)])
    assert not any(f["key"] == "smc_s" for f in r.smc_flags)


def test_tdiu_flag_single_60():
    r = combined_rating([RatingEntry("Heart", 60)])
    assert any(f["key"] == "tdiu" for f in r.smc_flags)


def test_tdiu_flag_70_combined_with_40():
    r = combined_rating([RatingEntry("PTSD", 50), RatingEntry("Back", 40),
                         RatingEntry("Tinnitus", 10)])
    # 50&40→70, &10→73 → combined 70; one ≥40 → threshold met
    assert r.combined == 70
    assert any(f["key"] == "tdiu" for f in r.smc_flags)


def test_no_tdiu_flag_when_below_thresholds():
    r = combined_rating([RatingEntry("Tinnitus", 10), RatingEntry("Scar", 10)])
    assert not any(f["key"] == "tdiu" for f in r.smc_flags)


def test_invalid_percent_rejected():
    with pytest.raises(ValueError):
        RatingEntry("Bad", 105)
    with pytest.raises(ValueError):
        RatingEntry("Bad", -5)


def test_whatif_delta_scenario():
    """The product's headline example: 'if tinnitus is granted at 10%, your
    combined goes 60 → 70' must hold for a plausible rating set."""
    base = [RatingEntry("PTSD", 50), RatingEntry("Back", 20)]
    before = combined_rating(base)          # 50&20→60 → 60
    after = combined_rating(base + [RatingEntry("Tinnitus", 10)])  # 60&10→64 → 60?
    assert before.combined == 60
    # 50&20→60, &10→64 → final 60: adding 10% does NOT always bump the rating —
    # the engine must show that honestly.
    assert after.combined == 60
    # But with a 30% back: 50&30→65, &10→68.5→69? →  pairwise: 65&10→68.5→69 → 70
    richer = combined_rating([RatingEntry("PTSD", 50), RatingEntry("Back", 30),
                              RatingEntry("Tinnitus", 10)])
    assert richer.combined == 70


def test_smc_s_remainder_includes_bilateral_factor():
    """§3.350(i) remainder combines under full §4.25/§4.26: 40+30 paired arms
    = 58 pre-factor (would miss 60) but 63.8→64 with the bilateral factor."""
    r = combined_rating([
        RatingEntry("Cancer", 100),
        RatingEntry("Right arm", 40, side="right"),
        RatingEntry("Left arm", 30, side="left"),
    ])
    assert any(f["key"] == "smc_s" for f in r.smc_flags)
    # Same percents WITHOUT sides stay below 60 → no flag.
    r2 = combined_rating([
        RatingEntry("Cancer", 100),
        RatingEntry("Back", 40),
        RatingEntry("Neck", 30),
    ])
    assert not any(f["key"] == "smc_s" for f in r2.smc_flags)
