"""VA compensation rate tables — loader + monthly-rate lookup.

Data lives in ``data/rates.json``, transcribed programmatically from the
official VA.gov rate pages (source URL + fetch date recorded per rate year in
the JSON). Rate years are named the VA way: "rate year 2024" = rates effective
December 1, 2023 (COLA effective dates are always Dec 1 of the prior calendar
year). NEVER hand-edit dollar amounts here or in the JSON — re-fetch from
VA.gov instead. Excluded/missing years must stay missing (the calculator
reports a gap rather than guessing).

Table shape per rate year:
- ``flat``: 10% and 20% — a single amount, no dependent variation.
- ``base_no_children`` / ``base_with_1_child``: 30%–100% x six spouse/parent
  combos (alone, spouse, spouse_1_parent, spouse_2_parents, one_parent,
  two_parents).
- ``added``: 30%–100% add-ons — child_under_18 (each ADDITIONAL child),
  child_over_18_school (each additional child 18–23 in a qualifying school
  program), spouse_aa (spouse receiving Aid and Attendance).

All amounts are strings in the JSON and Decimals here — money never touches
binary floats.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "rates.json"

VALID_PERCENTS = tuple(range(0, 101, 10))

_COMBO_KEYS = {
    (False, 0): "alone",
    (False, 1): "one_parent",
    (False, 2): "two_parents",
    (True, 0): "spouse",
    (True, 1): "spouse_1_parent",
    (True, 2): "spouse_2_parents",
}


@dataclass(frozen=True)
class Dependents:
    """Dependent status for one rating period (VA table dimensions only)."""

    spouse: bool = False
    children_under_18: int = 0
    children_in_school: int = 0  # children 18-23 in a qualifying school program
    parents: int = 0  # dependent parents, 0-2
    spouse_aa: bool = False  # spouse receiving Aid and Attendance

    def validate(self) -> None:
        if self.children_under_18 < 0 or self.children_in_school < 0:
            raise ValueError("child counts must be >= 0")
        if self.parents not in (0, 1, 2):
            raise ValueError("parents must be 0, 1, or 2")
        if self.spouse_aa and not self.spouse:
            raise ValueError("spouse_aa requires spouse=True")


@lru_cache(maxsize=1)
def load_rates() -> dict:
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


def available_rate_years() -> list[int]:
    return sorted(int(y) for y in load_rates()["rate_years"])


def sources() -> dict[int, dict]:
    """rate year -> {source_url, fetched, effective_date} (for citations)."""
    return {
        int(y): {k: d[k] for k in ("source_url", "fetched", "effective_date")}
        for y, d in load_rates()["rate_years"].items()
    }


def rate_year_for(month: date) -> int:
    """The VA rate year in effect for a calendar month.

    Rate year Y is effective Dec 1 of Y-1, so December belongs to the NEXT
    rate year (Dec 2023 is paid at 2024 rates) and Jan–Nov belong to the
    current calendar year's rate year.
    """
    return month.year + 1 if month.month == 12 else month.year


def monthly_rate(month: date, percent: int, dependents: Dependents) -> Decimal | None:
    """Official monthly amount for (month, combined %, dependent status).

    Returns None when the applicable rate year is not in the table (caller
    must surface a gap — never estimate). Raises ValueError on invalid input.
    """
    if percent not in VALID_PERCENTS:
        raise ValueError(f"percent must be one of {VALID_PERCENTS}, got {percent}")
    dependents.validate()
    if percent == 0:
        return Decimal("0.00")

    year = load_rates()["rate_years"].get(str(rate_year_for(month)))
    if year is None:
        return None

    if percent in (10, 20):  # flat — no dependent variation by law
        return Decimal(year["flat"][str(percent)])

    pct = str(percent)
    combo = _COMBO_KEYS[(dependents.spouse, dependents.parents)]
    kids = dependents.children_under_18 + dependents.children_in_school
    added = year["added"][pct]

    if kids == 0:
        total = Decimal(year["base_no_children"][pct][combo])
    else:
        # First child is priced by VA's "with 1 child" base row; every further
        # child uses the "each additional child" added amounts by age bracket.
        total = Decimal(year["base_with_1_child"][pct][combo])
        extra_under_18 = dependents.children_under_18
        extra_school = dependents.children_in_school
        if extra_under_18 > 0:
            extra_under_18 -= 1  # an under-18 child fills the base-row slot
        else:
            extra_school -= 1  # only school-age children: one fills the slot
        total += extra_under_18 * Decimal(added["child_under_18"])
        total += extra_school * Decimal(added["child_over_18_school"])

    if dependents.spouse_aa:
        total += Decimal(added["spouse_aa"])
    return total
