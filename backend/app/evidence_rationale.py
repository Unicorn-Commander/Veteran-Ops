"""Deterministic evidence rationale + citation ranking helpers.

This module stays pure where possible so the backend and tests can reuse the
same mapping and scoring rules without any model calls.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
import re
from typing import Any

_NON_WORD = re.compile(r"[^a-z0-9]+")

EVIDENCE_RATIONALE: dict[str, dict[str, object]] = {
    "diagnosis": {
        "elements": ["current_disability"],
        "why": "A current, diagnosed disability - the first thing a claim needs.",
    },
    "dbq": {
        "elements": ["current_disability", "severity"],
        "why": "A DBQ records the condition and the level of symptoms or limitations.",
    },
    "service_record": {
        "elements": ["in_service_event"],
        "why": "A service record can place the event, duty, or injury during service.",
    },
    "nexus_letter": {
        "elements": ["nexus"],
        "why": "A medical link connecting your condition to your service.",
    },
    "treatment_record": {
        "elements": ["current_disability", "continuity"],
        "why": "Treatment records can show the condition and that it kept showing up over time.",
    },
    "continuity": {
        "elements": ["continuity"],
        "why": "A lay or treatment record can show symptoms continuing after service.",
    },
    "lay_statement": {
        "elements": ["in_service_event", "continuity"],
        "why": "A lay statement can describe what a person saw, heard, or lived through.",
    },
    "other": {
        "elements": ["general_support"],
        "why": "Helpful background material that organizes the record around the claim.",
    },
}


def evidence_rationale(kind: str) -> dict[str, object]:
    row = EVIDENCE_RATIONALE.get(kind, EVIDENCE_RATIONALE["other"])
    return {
        "elements": list(row["elements"]),  # type: ignore[index]
        "why": str(row["why"]),
    }


def evidence_query_terms(condition_name: str, kind: str) -> list[str]:
    rationale = evidence_rationale(kind)
    parts = [condition_name, *map(str, rationale["elements"])]
    terms: list[str] = []
    seen: set[str] = set()
    for part in parts:
        for token in _tokenize(part):
            if len(token) < 3 or token in seen:
                continue
            seen.add(token)
            terms.append(token)
    return terms


def _tokenize(text: str) -> Iterable[str]:
    for token in _NON_WORD.split((text or "").lower()):
        token = token.strip()
        if token:
            yield token


def score_chunk_text(text: str, terms: Iterable[str]) -> int:
    body = (text or "").lower()
    score = 0
    for term in terms:
        if term and term in body:
            score += 2 if len(term) >= 6 else 1
    return score


def rank_chunk_rows(rows: Iterable[Any], terms: Iterable[str], *, k: int = 3) -> list[Any]:
    """Rank chunk-like rows by simple term overlap.

    Rows may be ORM objects or dicts with `content`, `chunk_index`, `char_start`
    and `char_end`. Returns the top-k rows with a positive score, stable on
    chunk order when scores tie.
    """

    term_list = [t for t in terms if t]
    scored: list[tuple[int, int, int, Any]] = []
    for order, row in enumerate(rows):
        content = getattr(row, "content", None) if not isinstance(row, dict) else row.get("content")
        chunk_index = getattr(row, "chunk_index", None) if not isinstance(row, dict) else row.get("chunk_index")
        char_start = getattr(row, "char_start", None) if not isinstance(row, dict) else row.get("char_start")
        score = score_chunk_text(str(content or ""), term_list)
        if score > 0:
            scored.append((score, int(chunk_index or order), int(char_start or 0), row))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [row for _, _, _, row in scored[:k]]


def page_for_char_offset(page_offsets: list[int] | None, char_start: int) -> int | None:
    if not page_offsets:
        return None
    idx = bisect_right(page_offsets, max(0, int(char_start))) - 1
    return idx + 1 if idx >= 0 else None


def citation_quote_from_chunk(content: str) -> str:
    return (content or "").strip()
