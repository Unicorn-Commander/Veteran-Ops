"""Deadline Guardian — the veteran's time-sensitive clocks, computed from their
OWN data. PURE: no DB, no LLM, no clock. Every function takes `today` so it stays
testable and can never disagree with the ITF / decoder math it reuses.

The 1-year clock is the spine of a VA claim (veteran-workflows research, cross-
cutting requirement #2: "the 1-year clock is the product's spine — build one
'deadline guardian' that tracks every clock and reminds"). Three clocks can cost a
veteran back pay or an appeal if missed, and each is sourced from data the veteran
already gave us:

  • Intent-to-File expiry   — an active ITF locks the effective date for 365 days
                              (filed_date + 1yr); reuses the ITF/decoder math.
  • Decision-review window  — a VA decision opens a one-year review window
                              (decision_date + 1yr; Document.extracted['decode']).
  • Dependency retroactivity — reporting a new dependent within one year of the
                              marriage/birth is retroactive (38 CFR 3.401).

Legal lane: this INFORMS about the deadline + what the veteran can do — it never
predicts an outcome and never files. We never invent a deadline: if the source date
is absent, that clock simply contributes nothing (degrade gracefully).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .decoder.deadline import add_one_year, appeal_window

# A still-open deadline within this many days is "soon" (amber); past due is
# "overdue" (red); further out is "ok" (green). 90 days ≈ one quarter of the
# 365-day clock — enough runway to gather evidence or reach a free VSO.
SOON_THRESHOLD_DAYS = 90

# How far PAST a dependency-retroactivity window we still surface it (as overdue):
# a just-missed window is still actionable (file now — benefits go forward), but an
# ancient one is noise. Only the retro window goes overdue in practice; the ITF and
# appeal clocks are filtered to still-open by their sources.
RETRO_OVERDUE_GRACE_DAYS = 60


@dataclass
class Deadline:
    """One time-sensitive clock, ready for the panel. `due_date`/`days_left` are
    None only when the source date is unknown (the UI shows 'date not detected')."""

    kind: str  # "itf" | "appeal" | "dependent"
    title: str
    due_date: str | None
    days_left: int | None
    urgency: str  # "overdue" | "soon" | "ok" — SEMANTIC, not a brand color
    what_to_do: str
    related_route: str


def urgency_for(days_left: int | None) -> str:
    """Bucket a SIGNED days-remaining into a semantic urgency. Unknown (None) →
    'soon' so an undated-but-real clock still nudges rather than reading as safe."""
    if days_left is None:
        return "soon"
    if days_left < 0:
        return "overdue"
    if days_left <= SOON_THRESHOLD_DAYS:
        return "soon"
    return "ok"


def _parse_date(value: object) -> date | None:
    """Accept a date or an ISO string (JSONB round-trips dates as strings)."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def itf_deadline(itf_records: list[dict], today: date) -> Deadline | None:
    """Soonest un-expired ITF → its 1-year expiry. `itf_records`: [{type, filed_date}]
    (filed_date a date or ISO string). Mirrors firm/context._active_itf: expired
    ITFs are moot (no effective date left to protect) and are skipped."""
    best: Deadline | None = None
    for rec in itf_records:
        filed = _parse_date(rec.get("filed_date"))
        if filed is None:
            continue
        w = appeal_window(filed, today)  # {deadline, days_remaining, expired}
        if w["expired"]:
            continue
        dr = w["days_remaining"]
        if best is not None and best.days_left is not None and dr >= best.days_left:
            continue
        itf_type = (rec.get("type") or "compensation").strip() or "compensation"
        best = Deadline(
            kind="itf",
            title=f"Complete your {itf_type} claim before your Intent to File expires",
            due_date=w["deadline"],
            days_left=dr,
            urgency=urgency_for(dr),
            what_to_do=(
                "Your Intent to File locks in this effective date for one year. File "
                "the actual claim (VA Form 21-526EZ) — or ask a free VSO to help — "
                "before this date so you don't lose the earlier effective date and any "
                "back pay it protects."
            ),
            related_route="/itf",
        )
    return best


def appeal_deadline(decodes: list[dict], today: date) -> Deadline | None:
    """Soonest STILL-OPEN 1-year decision-review window across the veteran's decoded
    decision letters. `decodes`: the Document.extracted['decode'] dicts. Days-left is
    recomputed from the stored decision_date so the countdown is never stale."""
    best: Deadline | None = None
    for decode in decodes:
        if not isinstance(decode, dict):
            continue
        dd = _parse_date(decode.get("decision_date"))
        if dd is None:
            continue
        w = appeal_window(dd, today)
        if w["expired"] or w["days_remaining"] is None:
            continue
        dr = w["days_remaining"]
        if best is not None and best.days_left is not None and dr >= best.days_left:
            continue
        best = Deadline(
            kind="appeal",
            title="Decision-review deadline on your VA decision",
            due_date=w["deadline"],
            days_left=dr,
            urgency=urgency_for(dr),
            what_to_do=(
                "A VA decision starts a one-year clock. If you disagree with any part, "
                "filing a review within one year — a Supplemental Claim (new evidence), "
                "a Higher-Level Review, or a Board Appeal — protects your original "
                "effective date. A free VSO can help you choose the right lane."
            ),
            related_route="/appeals",
        )
    return best


# Which dependent field opens the 1-year retro window, by relationship.
_DEPENDENT_EVENT = {
    "spouse": ("marriage_date", "marriage"),
    "child": ("date_of_birth", "child's birth"),
    "stepchild": ("date_of_birth", "child's birth"),
    # 'parent' has no clean 1-year event in the profile → best-effort skip.
}


def dependent_deadline(dependents: list[dict], today: date) -> Deadline | None:
    """Soonest 1-year dependency-retroactivity window (38 CFR 3.401) from a recent
    marriage or birth in `profile.dependents`. Best-effort: dependents without a
    usable event date are skipped, and windows more than RETRO_OVERDUE_GRACE_DAYS
    past due are dropped as noise (never ancient events)."""
    best: Deadline | None = None
    for dep in dependents:
        if not isinstance(dep, dict):
            continue
        rel = (dep.get("relationship") or "").strip().lower()
        field_label = _DEPENDENT_EVENT.get(rel)
        if field_label is None:
            continue
        field_name, event_label = field_label
        event_date = _parse_date(dep.get(field_name))
        if event_date is None:
            continue
        deadline = add_one_year(event_date)
        days_left = (deadline - today).days
        if days_left < -RETRO_OVERDUE_GRACE_DAYS:
            continue  # too old to be actionable
        if best is not None and best.days_left is not None and days_left >= best.days_left:
            continue
        name = (dep.get("full_name") or "").strip()
        who = name or ("your spouse" if event_label == "marriage" else "your child")
        best = Deadline(
            kind="dependent",
            title=f"Add {who} within one year of the {event_label}",
            due_date=deadline.isoformat(),
            days_left=days_left,
            urgency=urgency_for(days_left),
            what_to_do=(
                "Reporting a new dependent within one year of the marriage or birth "
                "makes the added compensation retroactive to the event (38 CFR 3.401), "
                "once your combined rating is 30% or higher. File VA Form 21-686c (or "
                "ask a free VSO) so you don't lose that back pay."
            ),
            related_route="/dependency",
        )
    return best


def compute_deadlines(
    *,
    itf_records: list[dict] | None,
    decodes: list[dict] | None,
    dependents: list[dict] | None,
    today: date,
) -> list[Deadline]:
    """Every clock the veteran has, SOONEST-FIRST. Each source is best-effort — a
    missing or undated source contributes nothing. An unknown due date (days_left
    None) sorts last (it can't be ranked against dated clocks)."""
    candidates = [
        itf_deadline(itf_records or [], today),
        appeal_deadline(decodes or [], today),
        dependent_deadline(dependents or [], today),
    ]
    out = [d for d in candidates if d is not None]
    out.sort(key=lambda d: (d.days_left is None, d.days_left if d.days_left is not None else 0))
    return out
