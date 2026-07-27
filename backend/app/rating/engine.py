"""VA combined-rating engine — exact 38 CFR §4.25 / §4.26 arithmetic.

This module is deterministic, pure Python, and is the ONLY place rating math may
live. The LLM never does this arithmetic; it calls this engine and explains the
returned step log.

Regulation semantics implemented here:

§4.25 (combined ratings table)
  * Ratings are arranged in the exact order of severity, greatest first.
  * Values are combined pairwise: the table value for A and B is
    A + B(100−A)/100 rounded to the nearest whole number (.5 rounds up) — this
    reproduces the printed table exactly (e.g. 19&10→27, 72&10→75, 45&50→73).
  * The running combined value is an integer at every step (the table has only
    integer entries), so intermediate rounding is applied at each combination.
  * The FINAL combined value is converted once to the nearest degree divisible
    by 10; values ending in 5 are adjusted upward (65→70, 74→70, 75→80).

§4.26 (bilateral factor)
  * When compensable disabilities affect both arms, both legs, or paired
    skeletal muscles, ALL such extremity disabilities (upper and lower together,
    per §4.26(b)) are combined first, in order of severity; 10 percent of that
    combined value is ADDED (not combined), and the result is rounded to the
    nearest whole number (60&20 arms → 68 + 6.8 = 74.8 → 75; 30&20 legs →
    44 + 4.4 = 48.4 → 48).
  * That value is then treated as ONE disability and ranked/combined with the
    remaining ratings per §4.25(c)/§4.26(c).

The engine also emits *educational* flags (never determinations):
  * SMC-S (38 CFR §3.350(i) statutory housebound): a single 100% disability plus
    additional disability independently combinable to 60% or more.
  * TDIU thresholds (38 CFR §4.16(a)): one disability ratable at 60%+, or a
    combined 70%+ with at least one disability at 40%+.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Optional

Side = Optional[Literal["left", "right"]]


@dataclass(frozen=True)
class RatingEntry:
    """One disability rating as entered by the veteran.

    side marks an extremity (or paired-muscle) disability as left/right; the
    bilateral factor applies when at least one compensable entry exists on each
    side. group is a free-form label carried through to the step log.
    """

    label: str
    percent: int
    side: Side = None
    group: Optional[str] = None

    def __post_init__(self) -> None:
        if not (0 <= int(self.percent) <= 100):
            raise ValueError(f"percent must be 0–100, got {self.percent}")


@dataclass
class CombinedResult:
    combined: int                      # final §4.25 value, rounded to nearest 10
    raw: int                           # pre-final-rounding combined value
    steps: list[dict] = field(default_factory=list)
    bilateral_factor_applied: bool = False
    bilateral_value: Optional[int] = None
    smc_flags: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "combined": self.combined,
            "raw": self.raw,
            "steps": self.steps,
            "bilateral_factor_applied": self.bilateral_factor_applied,
            "bilateral_value": self.bilateral_value,
            "smc_flags": self.smc_flags,
        }


def _round_half_up(x: float) -> int:
    """The rounding the printed §4.25 table uses (.5 rounds up, never banker's)."""
    return int(math.floor(x + 0.5))


def combine_pair(a: int, b: int) -> int:
    """§4.25 table lookup for two values: A + B(100−A)/100, nearest whole number."""
    if not (0 <= a <= 100 and 0 <= b <= 100):
        raise ValueError("ratings must be 0–100")
    return _round_half_up(a + b * (100 - a) / 100.0)


def combine(percents: list[int]) -> int:
    """Combine values per §4.25: descending order, pairwise with intermediate
    integer rounding. Returns the raw combined value (NOT final-rounded).
    Zero ratings contribute nothing."""
    vals = sorted((int(p) for p in percents if int(p) > 0), reverse=True)
    if not vals:
        return 0
    c = vals[0]
    for v in vals[1:]:
        c = combine_pair(c, v)
    return c


def final_round(raw: int) -> int:
    """§4.25(a) final conversion: nearest degree divisible by 10, ending-in-5
    adjusted upward. 64→60, 65→70, 74→70, 75→80."""
    if raw <= 0:
        return 0
    base = (raw // 10) * 10
    return base + 10 if raw % 10 >= 5 else base


def bilateral_value(percents: list[int]) -> tuple[int, int, float]:
    """§4.26: combine the bilateral disabilities, add 10% of that value, round to
    the nearest whole number. Returns (value, combined_before_factor, factor)."""
    c = combine(percents)
    factor = c * 0.10
    return _round_half_up(c + factor), c, round(factor, 1)


def combined_rating(entries: list[RatingEntry]) -> CombinedResult:
    """Full §4.25 + §4.26 combination with a human-readable step log."""
    steps: list[dict] = []
    compensable = [e for e in entries if e.percent > 0]
    zeros = [e for e in entries if e.percent == 0]
    if zeros:
        steps.append({
            "kind": "note",
            "text": "0% (noncompensable) ratings do not change the combined value: "
                    + ", ".join(e.label for e in zeros),
        })
    if not compensable:
        return CombinedResult(combined=0, raw=0, steps=steps)

    # ── §4.26 bilateral grouping: sided entries qualify when both sides present ──
    sided = [e for e in compensable if e.side in ("left", "right")]
    sides_present = {e.side for e in sided}
    bilateral = sided if {"left", "right"} <= sides_present else []
    others = [e for e in compensable if e not in bilateral]

    working: list[tuple[str, int]] = [(e.label, e.percent) for e in others]
    bilat_val: Optional[int] = None
    if bilateral:
        ordered = sorted(bilateral, key=lambda e: e.percent, reverse=True)
        pcts = [e.percent for e in ordered]
        val, before, factor = bilateral_value(pcts)
        bilat_val = val
        steps.append({
            "kind": "bilateral",
            "text": (
                "Bilateral factor (38 CFR §4.26): "
                + " + ".join(f"{e.label} {e.percent}%" for e in ordered)
                + f" combine to {before}%; adding 10% of that value ({factor}) "
                  f"gives {before + factor:.1f}, rounded to {val}%. This is now "
                  "treated as one disability."
            ),
            "inputs": pcts,
            "combined_before_factor": before,
            "factor": factor,
            "value": val,
        })
        working.append(("Bilateral group (incl. factor)", val))

    # ── §4.25: exact order of severity, greatest first ──
    working.sort(key=lambda t: t[1], reverse=True)
    steps.append({
        "kind": "order",
        "text": "Ordered by severity (38 CFR §4.25(b)): "
                + ", ".join(f"{lbl} {pct}%" for lbl, pct in working),
    })

    label0, c = working[0]
    for lbl, pct in working[1:]:
        nxt = combine_pair(c, pct)
        steps.append({
            "kind": "combine",
            "text": f"{c} combined with {pct} ({lbl}) → {nxt} "
                    f"(table value: {c} + {pct}×{(100 - c)}% = "
                    f"{c + pct * (100 - c) / 100:.1f})",
            "a": c, "b": pct, "value": nxt,
        })
        c = nxt

    final = final_round(c)
    steps.append({
        "kind": "round",
        "text": f"Final conversion (38 CFR §4.25(a)): {c} → {final} "
                "(nearest degree divisible by 10; values ending in 5 round up).",
        "raw": c, "value": final,
    })

    result = CombinedResult(
        combined=final,
        raw=c,
        steps=steps,
        bilateral_factor_applied=bilat_val is not None,
        bilateral_value=bilat_val,
    )
    result.smc_flags = screening_flags(compensable, c)
    return result


def _raw_with_bilateral(entries: list[RatingEntry]) -> int:
    """Raw §4.25 combined value of a set of entries WITH the §4.26 bilateral
    factor applied when both sides are present — the same combination
    combined_rating performs, minus the step log. Used by the SMC-S screen,
    where the 'additional disability independently ratable at 60%' remainder
    is combined under the full §4.25/§4.26 rules."""
    compensable = [e for e in entries if e.percent > 0]
    sided = [e for e in compensable if e.side in ("left", "right")]
    bilateral = sided if {"left", "right"} <= {e.side for e in sided} else []
    values = [e.percent for e in compensable if e not in bilateral]
    if bilateral:
        values.append(bilateral_value([e.percent for e in bilateral])[0])
    return combine(values)


def screening_flags(entries: list[RatingEntry], raw_combined: int) -> list[dict]:
    """Educational pointers only — never eligibility determinations."""
    flags: list[dict] = []
    pcts = sorted((e.percent for e in entries), reverse=True)

    if pcts and pcts[0] == 100:
        hundred = next(e for e in entries if e.percent == 100)
        remaining = [e for e in entries if e is not hundred]
        rest = _raw_with_bilateral(remaining)
        if rest >= 60:
            flags.append({
                "key": "smc_s",
                "title": "Possible SMC-S (statutory housebound)",
                "text": (
                    "One disability is rated 100% and your remaining disabilities "
                    f"independently combine to {rest}%. 38 CFR §3.350(i) provides "
                    "special monthly compensation at the (s) rate when a veteran has "
                    "a single 100% disability plus additional disability independently "
                    "ratable at 60% or more (separate and distinct from the 100% "
                    "condition). Worth reviewing with an accredited VSO."
                ),
                "source": "38 CFR §3.350(i)",
            })

    if final_round(raw_combined) < 100 and (
        pcts and (pcts[0] >= 60 or (final_round(raw_combined) >= 70 and pcts[0] >= 40))
    ):
        flags.append({
            "key": "tdiu",
            "title": "TDIU schedular threshold met",
            "text": (
                "Your ratings meet the 38 CFR §4.16(a) schedular threshold for Total "
                "Disability based on Individual Unemployability (one disability at 60%+, "
                "or combined 70%+ with one disability at 40%+). If service-connected "
                "conditions prevent you from keeping substantially gainful employment, "
                "TDIU pays at the 100% rate. This is education, not a determination — "
                "discuss with an accredited VSO."
            ),
            "source": "38 CFR §4.16(a)",
        })

    if any(e.percent == 100 for e in entries) or len(entries) >= 3:
        flags.append({
            "key": "smc_k_note",
            "title": "SMC can't be inferred from percentages alone",
            "text": (
                "Special monthly compensation levels such as SMC-K (e.g., loss or loss "
                "of use of a hand, foot, or creative organ) depend on the specific "
                "nature of a disability, not its percentage. If any condition involves "
                "loss of use, review 38 CFR §3.350 with an accredited VSO."
            ),
            "source": "38 CFR §3.350",
        })
    return flags
