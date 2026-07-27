"""Officer rank/promotion-correction analyzer — time-in-grade reasoning + legal lane."""

from __future__ import annotations

import re

from app.corrections.rank import analyze_rank

# The analyzer must never assert entitlement or promise an outcome — it flags an
# opportunity the BOARD decides.
_OVERREACH = re.compile(
    r"you (?:will|are) (?:promoted|entitled|guaranteed)|we (?:will )?file|"
    r"guarantee|you qualify for|you deserve",
    re.IGNORECASE,
)


def _has(findings, frm, to):
    return next((f for f in findings if f["grade_from"].startswith(frm) and to in f["grade_to"]), None)


def test_long_2lt_no_promotion_is_strong():
    # Aaron's shape: commissioned, held 2LT for years, never promoted to 1LT, then retired.
    out = analyze_rank({
        "commission_date": "2006-05-15",
        "date_of_rank_2lt": "2006-05-15",
        "promoted_to_1lt": False,
        "separation_date": "2010-06-01",  # ~4 years as a 2LT
        "medically_retired": True,
        "branch": "Army",
    })
    f = _has(out["findings"], "2LT", "1LT")
    assert f and f["strength"] == "strong"
    assert "18 months" in f["reasoning"]
    # Retired-grade / pay linkage surfaces because medically retired.
    assert "retired" in out["retired_grade_note"].lower()
    assert out["form"] == "DD Form 149"
    assert not _OVERREACH.search(" ".join(str(v) for v in out.values()))


def test_short_2lt_is_weak_not_strong():
    out = analyze_rank({
        "date_of_rank_2lt": "2020-01-01",
        "promoted_to_1lt": False,
        "separation_date": "2020-10-01",  # 9 months, under 18
    })
    f = _has(out["findings"], "2LT", "1LT")
    assert f and f["strength"] == "weak"


def test_capt_lane_without_selection_is_weak():
    out = analyze_rank({
        "date_of_rank_2lt": "2015-01-01",
        "promoted_to_1lt": True,
        "date_of_rank_1lt": "2016-07-01",
        "promoted_to_capt": False,
        "separation_date": "2019-01-01",
        "completed_captains_career_course": False,
    })
    f = _has(out["findings"], "1LT", "CPT")
    assert f and f["strength"] == "weak"
    assert "board" in f["reasoning"].lower()  # competitive/board-selected framing
    # No strong 2LT finding since he WAS promoted to 1LT.
    assert _has(out["findings"], "2LT", "1LT") is None


def test_capt_lane_with_documented_selection_is_moderate():
    out = analyze_rank({
        "promoted_to_1lt": True,
        "date_of_rank_1lt": "2016-07-01",
        "promoted_to_capt": False,
        "separation_date": "2019-09-01",
        "selected_for_promotion": "capt",
    })
    f = _has(out["findings"], "1LT", "CPT")
    assert f and f["strength"] == "moderate"
    assert "select" in f["reasoning"].lower()


def test_no_dates_asks_for_them():
    out = analyze_rank({"promoted_to_1lt": False})
    f = _has(out["findings"], "2LT", "1LT")
    assert f and f["strength"] == "needs_dates"
    assert "date" in out["overall"].lower()


def test_non_army_branch_is_flagged():
    out = analyze_rank({
        "date_of_rank_2lt": "2010-01-01",
        "promoted_to_1lt": False,
        "separation_date": "2014-01-01",
        "branch": "Air Force",
    })
    assert out["non_army_note"] and "Air Force" in out["non_army_note"]
