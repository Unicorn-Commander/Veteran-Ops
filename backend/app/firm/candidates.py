"""Shared contract for the data-driven rating-candidate enumerator.

The enumerator is deliberately deterministic: every candidate carries the
literal signal that caused a rule or a piece of veteran-owned data to put the
rating into consideration.  A per-rating expert may add a grounded explanation,
but it may not manufacture this object (or a Finding) on its own.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateRating:
    """One deterministically-seeded rating lane to investigate.

    ``diagnostic_code`` is empty only for a non-DC candidate such as concurrent
    pay.  Those candidates can be counted by the enumerator, but the rating
    expert's separate graduation gate still requires a matching rating-criteria
    card before it can produce a Finding.
    """

    diagnostic_code: str
    title: str
    body_system: str | None
    origin: str
    seed_signal: str
    source_ref: str | None
    primary_dc: str | None

