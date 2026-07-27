"""Retro/back-pay estimator — pure, deterministic; no LLM, no DB.

Given a timeline of rating periods (combined % + dependent status, each with an
effective date), build a month-by-month ledger of what VA's published rate
tables say each month pays, minus anything already received.

Legal lane: this is EDUCATION, not a benefits determination. Every response
carries assumptions + a not-modeled list, and the totals are framed as
estimates — VA's award letter and payment history are authoritative.

Key rules implemented (and cited in the output):
- 38 CFR §3.31: payment of monetary benefits based on an award or increase
  begins the first day of the calendar month FOLLOWING the month the award
  became effective. Whole months only — VA does not prorate.
- COLA: rate years are effective Dec 1 (of the prior calendar year), and the
  December month itself is paid at the new rate — §3.31's month-after rule
  applies to awards/increases, not to general COLA adjustments.
- Missing rate years: if a month falls in a rate year we do not have official
  VA.gov data for, that month is reported with rate=null and EXCLUDED from
  totals — the calculator never guesses a dollar amount.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .rates_data import (
    Dependents,
    available_rate_years,
    monthly_rate,
    rate_year_for,
    sources,
)

__all__ = ["Dependents", "RatingPeriod", "compute_backpay"]

CFR_331 = (
    "38 CFR §3.31: payment begins the first day of the month AFTER the "
    "effective date; whole months only (no proration)."
)

NOT_MODELED = [
    "Special Monthly Compensation (SMC) — any SMC level changes the amounts.",
    "Apportionment (part of the benefit paid to a spouse/child/other).",
    "Offsets: military disability severance pay recoupment, VA drill-pay "
    "offsets, and CRDP/CRSC coordination for military retirees.",
    "Incarceration reductions (38 CFR §3.665).",
    "Clothing allowance, and any state benefits.",
    "Withholdings (e.g., attorney fees, debts to VA).",
]


@dataclass(frozen=True)
class RatingPeriod:
    """One segment of the rating timeline. ``from_date`` is the EFFECTIVE date
    (per the award), not the first payment date — §3.31 is applied here."""

    from_date: date
    combined_percent: int
    to_date: date | None = None
    dependents: Dependents = field(default_factory=Dependents)


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _next_month(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def _prev_month(d: date) -> date:
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)


def _applicable(periods: list[RatingPeriod], month: date) -> RatingPeriod | None:
    """The period that pays calendar month ``month`` (a first-of-month date).

    §3.31 in whole-month form: a period governs a month only when its effective
    date is strictly before the 1st of that month (an effective date ON the 1st
    still waits for the next month). Among candidates, the latest effective
    date wins (an increase supersedes the prior period for later months).
    """
    best: RatingPeriod | None = None
    for p in periods:
        if p.from_date < month and (p.to_date is None or p.to_date >= month):
            if best is None or p.from_date > best.from_date:
                best = p
    return best


def _cents(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.01")))


def compute_backpay(
    periods: list[RatingPeriod],
    received: list[RatingPeriod] | None = None,
    end_date: date | None = None,
    today: date | None = None,
) -> dict:
    """Month-by-month back-pay ledger.

    ``periods``  — what the veteran is (or would be) entitled to.
    ``received`` — optional timeline of what VA actually paid (same shape);
                   the net per month is entitled − received.
    ``end_date`` — optional explicit ledger end; otherwise runs through the
                   last full calendar month before ``today``.
    """
    if not periods:
        raise ValueError("at least one rating period is required")
    for p in periods + (received or []):
        if p.to_date is not None and p.to_date < p.from_date:
            raise ValueError(f"period to_date {p.to_date} precedes from_date {p.from_date}")
        # trigger percent/dependents validation early, on a known-covered probe
        p.dependents.validate()
        if p.combined_percent not in range(0, 101, 10):
            raise ValueError(f"combined_percent must be a multiple of 10 in 0..100, got {p.combined_percent}")

    today = today or date.today()
    earliest = min(p.from_date for p in periods)
    # §3.31 — first potentially-payable month is the month AFTER the earliest
    # effective date.
    first_month = _next_month(_first_of_month(earliest))
    last_month = _first_of_month(end_date) if end_date else _prev_month(_first_of_month(today))

    received = received or []
    covered_years = available_rate_years()

    months: list[dict] = []
    excluded: list[str] = []
    entitled_total = Decimal("0")
    received_total = Decimal("0")
    net_total = Decimal("0")
    by_year: dict[str, dict[str, Decimal]] = {}
    prev_period: RatingPeriod | None = None

    m = first_month
    while m <= last_month:
        key = f"{m.year:04d}-{m.month:02d}"
        ry = rate_year_for(m)
        period = _applicable(periods, m)
        notes: list[str] = []

        if period is None:
            months.append({
                "month": key, "percent": None, "rate": None, "received": None,
                "net": None, "rate_year": ry,
                "note": "No rating period covers this month (see 38 CFR §3.31 for "
                        "the month-after start rule); excluded from totals.",
            })
            prev_period = None
            m = _next_month(m)
            continue

        if period is not prev_period:
            notes.append(
                f"Rating effective {period.from_date.isoformat()}; payment at this "
                f"rate begins {key}-01 per {CFR_331}"
            )
        if m.month == 12:
            notes.append(
                f"COLA: rate year {ry} rates effective {m.year}-12-01 apply to this "
                "month (general COLA increases are not delayed by §3.31)."
            )

        rate = monthly_rate(m, period.combined_percent, period.dependents)

        rec_amount: Decimal | None = Decimal("0")
        rec_period = _applicable(received, m) if received else None
        if rec_period is not None:
            rec_amount = monthly_rate(m, rec_period.combined_percent, rec_period.dependents)
            if rec_amount is not None:
                notes.append(
                    f"Already received at {rec_period.combined_percent}% "
                    f"({_cents(rec_amount)}/mo) — netted out."
                )

        if rate is None or rec_amount is None:
            notes.append(
                f"Rate year {ry} is not in the verified VA.gov table "
                f"(covered: {covered_years[0]}–{covered_years[-1]}); this month is "
                "excluded from totals — no amount is estimated for it."
            )
            excluded.append(key)
            months.append({
                "month": key, "percent": period.combined_percent, "rate": None,
                "received": None, "net": None, "rate_year": ry,
                "note": " ".join(notes),
            })
        else:
            net = rate - rec_amount
            entitled_total += rate
            received_total += rec_amount
            net_total += net
            yr = by_year.setdefault(
                str(m.year),
                {"entitled": Decimal("0"), "received": Decimal("0"), "net": Decimal("0")},
            )
            yr["entitled"] += rate
            yr["received"] += rec_amount
            yr["net"] += net
            months.append({
                "month": key, "percent": period.combined_percent, "rate": _cents(rate),
                "received": _cents(rec_amount), "net": _cents(net), "rate_year": ry,
                "note": " ".join(notes),
            })

        prev_period = period
        m = _next_month(m)

    src = sources()
    assumptions = [
        CFR_331,
        "COLA rate years are effective December 1 (of the prior calendar year); "
        "the December month itself is paid at the new COLA rate.",
        "Whole calendar months only; the ledger ends with the last full month "
        f"before {(end_date or today).isoformat()}.",
        "10% and 20% ratings pay a flat rate regardless of dependents.",
        "With children: the first child is priced from VA's 'with 1 child' table "
        "row; each additional child uses VA's published added amounts (under 18 "
        "vs. 18–23 in a qualifying school program).",
        "Monthly amounts are VA's published rate-table values (dollars and "
        "cents, unrounded); the total is their exact sum.",
        f"Rate tables fetched from official VA.gov pages; rate years covered: "
        f"{covered_years[0]}–{covered_years[-1]}. Months in any other rate year "
        "are excluded from totals, never estimated.",
        "Estimates only — VA's award letter and payment history are "
        "authoritative. Veteran-Ops is self-help educational software, not a "
        "benefits determination, not legal advice, and not a VA-accredited "
        "representative.",
    ]

    return {
        "total": _cents(net_total),
        "entitled_total": _cents(entitled_total),
        "received_total": _cents(received_total),
        "months": months,
        "by_year_subtotals": {
            y: {k: _cents(v) for k, v in vals.items()} for y, vals in sorted(by_year.items())
        },
        "excluded_months": excluded,
        "rate_years_covered": covered_years,
        "rate_sources": {str(y): s for y, s in sorted(src.items())},
        "assumptions": assumptions,
        "not_modeled": NOT_MODELED,
    }
