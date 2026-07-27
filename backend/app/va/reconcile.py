"""PURE reconciliation logic — turn structured VA rating/claim data into a plan
that maps each VA condition onto the veteran's existing claimed conditions.

No DB, no network, no ORM: everything here operates on plain values so it can be
unit-tested in isolation and reused by ANY source of VA data (the browser
extension, a manual paste, or the future Lighthouse pull). The router
(`app/routers/va.py`) loads rows, calls `reconcile()`, and — only on APPLY —
writes the resulting plan back through the ORM.

Legal lane: this is factual organizing of the veteran's OWN VA record. It sets
ONLY what the VA data says (disposition → va_status; service-connected percent →
current_rating). No outcome language, no predictions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Match case.py `_norm` / routers/analysis.py `_norm_name`, plus two VA-specific
# strips: a trailing parenthetical ("… (claimed as acid reflux)") and a leading
# "history of ".
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")
_LEADING_HISTORY = re.compile(r"^history of\s+")

# Below this length a contained token (e.g. "knee") over-matches — require the
# shorter, contained side to be at least this many chars for a containment hit.
_MIN_CONTAINMENT_LEN = 6


def _norm(name: str | None) -> str:
    """Lowercase, drop a trailing parenthetical + a leading 'history of ',
    collapse internal whitespace, and trim surrounding punctuation."""
    s = (name or "").lower()
    s = _TRAILING_PAREN.sub("", s)
    s = _LEADING_HISTORY.sub("", s)
    return " ".join(s.split()).strip(" .,:;")


def _is_containment(a: str, b: str) -> bool:
    """True when one normalized name fully contains the other AND the contained
    (shorter) side is long enough not to over-match. Equal-length handled by the
    exact pass, so here the shorter side is the contained one."""
    if not a or not b or a == b:
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) < _MIN_CONTAINMENT_LEN:
        return False
    return shorter in longer


@dataclass
class ClaimedRef:
    """A minimal, DB-free view of an existing claimed condition."""

    id: str
    name: str
    current_rating: int | None = None
    va_status: str = "unknown"


@dataclass
class VaCondition:
    """A single VA condition to reconcile (from any source)."""

    name: str
    percent: int | None = None
    effective_date: str | None = None
    disposition: str = "pending"  # service_connected | denied | pending


@dataclass
class MatchPlan:
    va_name: str
    condition_id: str
    condition_name: str
    set_current_rating: int | None
    set_va_status: str
    changed: bool


@dataclass
class UnmatchedPlan:
    name: str
    disposition: str
    percent: int | None


@dataclass
class ReconcilePlan:
    combined_rating: int | None
    matched: list[MatchPlan] = field(default_factory=list)
    unmatched: list[UnmatchedPlan] = field(default_factory=list)


def _planned_values(va: VaCondition, claimed: ClaimedRef) -> tuple[int | None, str, bool]:
    """(set_current_rating, set_va_status, changed) for a matched pair.

    `set_current_rating` is the percent ONLY for a service-connected rating with a
    known percent — otherwise None, meaning 'leave the existing rating unchanged'
    (a denial/pending disposition never rewrites a rating). `changed` reflects
    whether va_status or a to-be-written current_rating actually differs.
    """
    set_va_status = va.disposition
    if va.disposition == "service_connected" and va.percent is not None:
        set_current_rating = va.percent
    else:
        set_current_rating = None
    changed = set_va_status != claimed.va_status or (
        set_current_rating is not None and set_current_rating != claimed.current_rating
    )
    return set_current_rating, set_va_status, changed


def reconcile(
    combined_rating: int | None,
    va_conditions: list[VaCondition],
    claimed: list[ClaimedRef],
) -> ReconcilePlan:
    """Map each VA condition onto at most one existing claimed condition.

    Two passes so an EXACT normalized-name match always wins over a containment
    match, and each claimed condition is consumed by at most one VA condition
    (first VA condition, in input order, claims it)."""
    norm_claimed = [(c, _norm(c.name)) for c in claimed]
    used: set[str] = set()  # claimed ids already consumed
    match_for: dict[int, ClaimedRef] = {}  # va index → claimed

    # Pass 1 — exact normalized-name matches.
    for idx, va in enumerate(va_conditions):
        va_norm = _norm(va.name)
        if not va_norm:
            continue
        for c, c_norm in norm_claimed:
            if c.id in used or not c_norm:
                continue
            if c_norm == va_norm:
                match_for[idx] = c
                used.add(c.id)
                break

    # Pass 2 — containment matches for whatever is still unmatched.
    for idx, va in enumerate(va_conditions):
        if idx in match_for:
            continue
        va_norm = _norm(va.name)
        if not va_norm:
            continue
        for c, c_norm in norm_claimed:
            if c.id in used or not c_norm:
                continue
            if _is_containment(va_norm, c_norm):
                match_for[idx] = c
                used.add(c.id)
                break

    plan = ReconcilePlan(combined_rating=combined_rating)
    for idx, va in enumerate(va_conditions):
        c = match_for.get(idx)
        if c is None:
            plan.unmatched.append(
                UnmatchedPlan(name=va.name, disposition=va.disposition, percent=va.percent)
            )
            continue
        set_rating, set_status, changed = _planned_values(va, c)
        plan.matched.append(
            MatchPlan(
                va_name=va.name,
                condition_id=c.id,
                condition_name=c.name,
                set_current_rating=set_rating,
                set_va_status=set_status,
                changed=changed,
            )
        )
    return plan
