"""Whole-C-file MAP pass — structured facts per segment, with provenance.

The classifier answers "what IS this document"; the map pass answers "what does
every part of it SAY." It reads the file segment by segment (reusing the pure
overlapping-window segmenter in intake/segment.py, so EVERY page is read, not just
the head) and pulls the facts a case turns on — conditions, C&P exams, nexus
statements, decisions, dates, and internal contradictions — each stamped with WHERE
it came from (segment index + char span + page). The analysis/comprehension.py
REDUCE later folds these per-segment facts into one durable case picture.

The model proposes; PURE validators dispose — the SAME contract as
classify.validate_extraction. Per-segment conditions run through the exact
classifier cleaners (invented codes nulled, off-grid percents dropped); exams /
nexus / decisions / dates / contradictions are whitelisted and capped. A
per-segment failure is tolerated and recorded in read_coverage so the picture can
be honest about how much of the file was actually read.
"""

from __future__ import annotations

import json

from .classify import (
    _DECISIONS,
    _clean_date,
    _clean_str,
    parse_llm_json,
    validate_extraction,
)
from .segment import map_segments

MAP_SYSTEM = (
    "You are a meticulous records analyst reading ONE section of a veteran's VA "
    "claims file (C-file). Extract the facts this section states — do NOT summarize "
    "or infer beyond the text. Return STRICT JSON ONLY (no prose, no code fences):\n"
    "{\n"
    '  "claim_relevant": true|false,   // does this section bear on a disability claim?\n'
    '  "salience": 0.0-1.0,            // how important to the claim (0 trivial, 1 decisive)\n'
    '  "conditions": [{"name": "...", "rating_percent": 0-100 multiple of 10 or null,\n'
    '                  "diagnostic_code": "4-digit or null", "decision": "granted|denied|deferred|null"}],\n'
    '  "exams": [{"type": "C&P exam|DBQ|treatment|imaging|other", "date": "YYYY-MM-DD or null", "provider": "... or null"}],\n'
    '  "nexus_statements": [{"text": "the nexus/opinion sentence verbatim", "meets_standard": true|false}],\n'
    '  "decisions": [{"condition": "...", "decision": "granted|denied|deferred", "date": "YYYY-MM-DD or null"}],\n'
    '  "dates": ["YYYY-MM-DD", ...],   // claim-significant dates only (see rules)\n'
    '  "contradictions": ["a plain-language note where this section conflicts with itself"]\n'
    "}\n"
    "meets_standard is true only when the opinion uses the VA nexus standard "
    "('at least as likely as not' / 'more likely than not'). Null anything not in "
    "the text.\n"
    "DATES rules: include service entry/separation, injury/onset, exam/treatment, "
    "and decision effective dates. Do NOT include spouse, child, or other dependent "
    "birth dates, marriage ceremony dates unless they are the claim issue, or "
    "unrelated family dates. If a date is only a family member's birthday, omit it.\n"
    "Output valid JSON only."
)

_MAX_LIST = 40  # per-fact-type cap per segment (a runaway model can't flood a row)
# Deterministic detection of the VA nexus standard in an opinion sentence.
_NEXUS_STANDARD_PHRASES = (
    "at least as likely as not",
    "more likely than not",
    "as likely as not",
)


def _page_for_offset(page_offsets, char_start: int) -> int | None:
    """0-based page index containing `char_start`, from the page start-offsets the
    OCR/text-layer step recorded. None when offsets are unavailable."""
    if not isinstance(page_offsets, list) or not page_offsets:
        return None
    page = 0
    for i, off in enumerate(page_offsets):
        try:
            if int(off) <= char_start:
                page = i
            else:
                break
        except (TypeError, ValueError):
            break
    return page


def _clean_salience(value) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 0.0 <= x <= 1.0:
        return round(x, 3)
    if 1.0 < x <= 100.0:  # tolerate a 0–100 scale
        return round(x / 100.0, 3)
    return 0.0


def _clean_exams(value) -> list[dict]:
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value[:_MAX_LIST]:
        if not isinstance(item, dict):
            continue
        etype = _clean_str(item.get("type"), 64)
        if not etype:
            continue
        out.append(
            {
                "type": etype,
                "date": _clean_date(item.get("date")),
                "provider": _clean_str(item.get("provider"), 255),
            }
        )
    return out


def _meets_standard(text: str, claimed) -> bool:
    """Trust the deterministic phrase, not the model's boolean: the standard is met
    only when the quote actually uses the VA nexus language."""
    low = (text or "").lower()
    return any(p in low for p in _NEXUS_STANDARD_PHRASES)


def _clean_nexus(value) -> list[dict]:
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value[:_MAX_LIST]:
        if not isinstance(item, dict):
            continue
        text = _clean_str(item.get("text"), 1000)
        if not text:
            continue
        out.append({"text": text, "meets_standard": _meets_standard(text, item.get("meets_standard"))})
    return out


def _clean_decisions(value) -> list[dict]:
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for item in value[:_MAX_LIST]:
        if not isinstance(item, dict):
            continue
        decision = item.get("decision")
        decision = decision if decision in _DECISIONS else None
        condition = _clean_str(item.get("condition"), 255)
        if not condition and decision is None:
            continue
        out.append({"condition": condition, "decision": decision, "date": _clean_date(item.get("date"))})
    return out


def _clean_dates(value) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for item in value[:_MAX_LIST]:
        iso = _clean_date(item)
        if iso and iso not in seen:
            seen.append(iso)
    return seen


def _clean_notes(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:_MAX_LIST]:
        note = _clean_str(item, 500)
        if note:
            out.append(note)
    return out


def validate_map_facts(
    raw,
    *,
    segment_index: int = 0,
    char_start: int = 0,
    char_end: int = 0,
    page_offsets=None,
) -> dict:
    """PURE: a validated, whitelisted facts dict for ONE segment (mirrors
    classify.validate_extraction). Conditions run through the classifier's exact
    per-condition cleaners; every fact carries its provenance so the reduce can
    cite the source. Always returns the full shape so callers can rely on the keys.
    """
    if not isinstance(raw, dict):
        raw = {}
    conditions = validate_extraction({"conditions_mentioned": raw.get("conditions")})[
        "conditions_mentioned"
    ]
    return {
        "segment": int(segment_index),
        "char_start": int(char_start),
        "char_end": int(char_end),
        "page": _page_for_offset(page_offsets, int(char_start)),
        "claim_relevant": raw.get("claim_relevant") is True,
        "salience": _clean_salience(raw.get("salience")),
        "conditions": conditions,
        "exams": _clean_exams(raw.get("exams")),
        "nexus_statements": _clean_nexus(raw.get("nexus_statements")),
        "decisions": _clean_decisions(raw.get("decisions")),
        "dates": _clean_dates(raw.get("dates")),
        "contradictions": _clean_notes(raw.get("contradictions")),
    }


_MAP_MAX_CHARS = 24_000  # per-segment cap (matched to the read window)


async def _map_segment(text: str, *, model: str = "") -> dict | None:
    """Model seam over ONE segment (module-level so tests monkeypatch it, exactly
    like classify._classify_segment). Returns RAW parsed JSON, or None when the
    gateway is down / returns garbage. Never raises."""
    if not text or not text.strip():
        return None
    from ..llm.gateway import gateway  # lazy — keep the pure validators importable

    try:
        raw = await gateway.complete(
            [
                {"role": "system", "content": MAP_SYSTEM},
                {"role": "user", "content": text[:_MAP_MAX_CHARS]},
            ],
            model=model,
            temperature=0.0,
            max_tokens=2000,
            touches_pii=True,
        )
    except Exception:  # noqa: BLE001 — a per-segment miss is tolerated + recorded
        return None
    return parse_llm_json(raw)


async def run_map_pass(text: str, page_offsets=None, *, model: str = "") -> dict:
    """MAP over the whole document: read every segment, validate its facts, and
    record how much was actually read.

    Returns {segments: [validated facts, ...], read_coverage: {...}}. A per-segment
    failure (transient gateway hiccup deep in a huge file) is counted, not fatal —
    the reduce stays honest about partial reads. `model` is resolved by the caller
    (overrides.effective_model_for(tier="extraction", touches_pii=True, ...)).
    """
    segments = map_segments(text or "")
    facts: list[dict] = []
    read = failed = 0
    for seg in segments:
        raw = await _map_segment(seg.text, model=model)
        if raw is None:
            failed += 1
            continue
        read += 1
        facts.append(
            validate_map_facts(
                raw,
                segment_index=seg.index,
                char_start=seg.start,
                char_end=seg.end,
                page_offsets=page_offsets,
            )
        )
    return {
        "segments": facts,
        "read_coverage": {
            "segments_total": len(segments),
            "segments_read": read,
            "segments_failed": failed,
        },
    }
