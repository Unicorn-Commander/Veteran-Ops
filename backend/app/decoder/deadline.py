"""Appeal-window math — PURE, no dependencies (no dateutil in requirements).

Under the AMA (38 CFR §3.2500 et seq.), filing any decision-review lane within
ONE YEAR of the decision date preserves the original effective date. We compute
that deadline and the days remaining so the UI can show an urgency countdown.

This is an educational deadline aid, not legal advice: the date ON the letter is
authoritative and some situations (e.g. an earlier-still-open review) change the
math. The decoder always says so.
"""

from __future__ import annotations

from datetime import date


def add_one_year(d: date) -> date:
    """One calendar year later. Feb 29 has no counterpart in a common year → the
    conventional VA/legal treatment lands the anniversary on Feb 28 rather than
    rolling into March, so a deadline never quietly gains a day."""
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # only Feb 29 → target year has no Feb 29
        return d.replace(year=d.year + 1, month=2, day=28)


def appeal_window(decision_date: date | None, today: date) -> dict:
    """{deadline, days_remaining, expired} for the 1-year AMA review window.

    days_remaining is SIGNED (negative once past). `today` is passed in (never
    read from the clock here) so the function stays pure and testable. Unknown
    decision date → all-None (the UI shows 'date not detected — check the letter').
    """
    if decision_date is None:
        return {"deadline": None, "days_remaining": None, "expired": None}
    deadline = add_one_year(decision_date)
    days_remaining = (deadline - today).days
    return {
        "deadline": deadline.isoformat(),
        "days_remaining": days_remaining,
        "expired": days_remaining < 0,
    }
