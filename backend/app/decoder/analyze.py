"""Assemble the final decode payload — PURE (no DB, no LLM, no clock).

Takes the validated decode dict (decode.py), the stored classify extraction (for
the VA contention-taxonomy chips + is_va_decision), a decision date, and `today`,
and produces the locked `DecodeOut` shape (docs/WAVE4-DECODER-SPEC.md).

The AMA decision-review lanes are constant, educational, and faithful to the KB
`process` card ("Decision review lanes under the AMA"); the source string is
stamped from that card when the caller passes it. Nothing here files or advises —
every denial routes to a free VSO.
"""

from __future__ import annotations

from datetime import date

from ..intake.classify import attach_va_classifications
from .combined_check import cross_check_combined
from .deadline import appeal_window

# Educational next-step per decision (keys the UI maps to copy/links).
_NEXT_STEP = {"denied": "supplemental_claim", "deferred": "awaiting", "granted": None}

_DEFAULT_REVIEW_SOURCE = (
    "Appeals Modernization Act (Pub. L. 115-55); 38 CFR Part 3 subpart D "
    "(§3.2500 et seq.); Forms 20-0995, 20-0996, 10182"
)


def _lanes(source: str) -> list[dict]:
    """The three AMA decision-review lanes — always shown, educational only."""
    return [
        {
            "key": "supplemental_claim",
            "title": "Supplemental Claim (VA Form 20-0995)",
            "form": "20-0995",
            "when": "You have NEW and relevant evidence to add.",
            "detail": (
                "The workhorse lane after a denial: submit new and relevant "
                "evidence a reviewer hasn't seen (a nexus opinion, a current "
                "diagnosis, buddy statements). Filing within one year of the "
                "decision preserves your original effective date; you can also "
                "file later (with a potentially later effective date)."
            ),
            "source": source,
        },
        {
            "key": "higher_level_review",
            "title": "Higher-Level Review (VA Form 20-0996)",
            "form": "20-0996",
            "when": "You believe VA misapplied the rules to evidence already on file.",
            "detail": (
                "A senior reviewer re-examines the SAME record for errors — no new "
                "evidence allowed. You may request an informal conference to point "
                "out where VA went wrong. Best when the facts were right but the "
                "criteria were applied incorrectly."
            ),
            "source": source,
        },
        {
            "key": "board_appeal",
            "title": "Board Appeal (VA Form 10182)",
            "form": "10182",
            "when": "You want a Veterans Law Judge to review the decision.",
            "detail": (
                "Appeal to the Board of Veterans' Appeals — three dockets: direct "
                "review (no new evidence, fastest), evidence submission, or a "
                "hearing with a judge. Filing within one year preserves your "
                "effective date."
            ),
            "source": source,
        },
    ]


_VSO_REFERRAL = (
    "For free, expert help deciding whether and how to respond to this decision, "
    "talk to a VA-accredited Veterans Service Officer (VSO) — VFW, DAV, The "
    "American Legion, or your state/county veterans office. Accredited VSOs help "
    "veterans for free; you never have to pay to appeal a VA decision."
)

_DISCLAIMER = (
    "This is our plain-language reading of what your letter says — it is not legal "
    "advice and it is not a substitute for reading the decision itself. Rating "
    "Raider is not a VA-accredited representative and does not file or appeal "
    "anything for you. Deadlines and effective-date rules have exceptions; confirm "
    "them with a VSO."
)

_SOURCE_NOTE = (
    "Decoded from the text of the letter you uploaded. VA's official decision and "
    "the combined evaluation printed on the letter are what control — the "
    "cross-check below is an educational estimate."
)


def build_decode(
    *,
    decode: dict | None,
    extracted: dict | None,
    doc_date: date | None,
    today: date,
    decoded_at: str,
    document_id: str,
    review_source: str | None = None,
    contention_map: dict | None = None,
) -> dict:
    """Compose the DecodeOut payload.

    decode:     validated decode.py output (may be None → fall back to the stored
                classify extraction's conditions_mentioned).
    extracted:  the document's stored classify extraction (is_va_decision, and the
                conditions_mentioned fallback).
    doc_date:   the veteran-confirmed / classified document date; used for the
                appeal window when the decode didn't surface a decision_date.
    today:      passed in (pure) — the reference date for days-remaining.
    decoded_at: caller-stamped ISO timestamp (pure functions can't read the clock).
    """
    extracted = extracted or {}

    # Decision rows: prefer the richer decode pass; fall back to the classify
    # extraction so a decode with the LLM down still shows the grant/deny grid.
    if decode and decode.get("decisions"):
        rows = [dict(r) for r in decode["decisions"]]
    else:
        rows = [
            {
                "name": m.get("name"),
                "diagnostic_code": m.get("diagnostic_code"),
                "decision": m.get("decision"),
                "rating_percent": m.get("rating_percent"),
                "effective_date": None,
                "plain": None,
                "missing_elements": [],
            }
            for m in extracted.get("conditions_mentioned", [])
            if m.get("name")
        ]

    # Stamp the official VA contention taxonomy (deterministic, no LLM) so the UI
    # can show the same classification chips it shows in Documents.
    attach_va_classifications(rows, cmap=contention_map)

    decisions: list[dict] = []
    for r in rows:
        decision = r.get("decision")
        decisions.append(
            {
                "name": r.get("name"),
                "diagnostic_code": r.get("diagnostic_code"),
                "decision": decision,
                "rating_percent": r.get("rating_percent"),
                "effective_date": r.get("effective_date"),
                "va_classification": r.get("va_classification"),
                "va_classification_code": r.get("va_classification_code"),
                "plain": r.get("plain"),
                "missing_elements": r.get("missing_elements") or [],
                "next_step": _NEXT_STEP.get(decision),
            }
        )

    granted = [d for d in decisions if d["decision"] == "granted"]
    has_denials = any(d["decision"] == "denied" for d in decisions)
    has_grants = bool(granted)

    va_stated = (decode or {}).get("combined_evaluation")
    combined_check = cross_check_combined(granted, va_stated)

    # Decision date: the decode's parsed date wins; else the document's date.
    dd = None
    if decode and decode.get("decision_date"):
        try:
            dd = date.fromisoformat(decode["decision_date"])
        except (ValueError, TypeError):
            dd = None
    if dd is None:
        dd = doc_date

    return {
        "document_id": document_id,
        "decoded_at": decoded_at,
        "decision_date": dd.isoformat() if dd else None,
        "decisions": decisions,
        "combined_check": combined_check,
        "appeal_window": appeal_window(dd, today),
        "options": _lanes(review_source or _DEFAULT_REVIEW_SOURCE),
        "has_denials": has_denials,
        "has_grants": has_grants,
        "vso_referral": _VSO_REFERRAL,
        "disclaimer": _DISCLAIMER,
        "source_note": _SOURCE_NOTE,
    }
