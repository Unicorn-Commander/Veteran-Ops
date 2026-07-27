"""Classify + extract structure from a veteran document via the LOCAL LLM.

The LLM proposes; PURE validators dispose (mirrors Glitter Mane's
medical/extraction.py separation): `validate_extraction` is deterministic and
unit-tested — invented doc types are nulled, percents that aren't 0–100
multiples of 10 are dropped, unknown fields are discarded. Link suggestions
(`suggest_links`) are deterministic casefold substring matches; the LLM never
picks a condition id, and NOTHING is linked without the veteran's explicit
confirmation via POST /documents/{id}/link.
"""

from __future__ import annotations

import json
import re
from datetime import date

from .segment import map_segments

DOC_TYPES = (
    "rating_decision",
    "decision_letter",
    "str",
    "dbq",
    "treatment_record",
    "private_medical_opinion",
    "lay_statement",
    "service_record",
    "other",
)
_DECISIONS = ("granted", "denied", "deferred")

CLASSIFY_SYSTEM = (
    "You are a meticulous document-classification agent for a veteran's self-help "
    "VA disability claim organizer. Read the document text and return STRICT JSON "
    "ONLY (no prose, no code fences) matching exactly this shape:\n"
    "{\n"
    '  "doc_type": "rating_decision|decision_letter|str|dbq|treatment_record|private_medical_opinion|lay_statement|service_record|other",\n'
    '  "doc_date": "YYYY-MM-DD or null (the date ON the document, not today)",\n'
    '  "title": "short human title, e.g. \'VA Rating Decision — March 2019\'",\n'
    '  "summary": "exactly two sentences describing what this document is and what it covers",\n'
    '  "conditions_mentioned": [{"name": "condition name", "rating_percent": 0-100 multiple of 10 or null,\n'
    '                            "diagnostic_code": "4-digit code or null", "decision": "granted|denied|deferred|null"}],\n'
    '  "is_va_decision": true|false,\n'
    '  "relevance": "relevant|unclear|off_topic",\n'
    '  "relevance_reason": "one short phrase, e.g. \'utility bill — not claim evidence\' or null"\n'
    "}\n"
    "Notes: 'str' means Service Treatment Record. rating_percent only when the "
    "document itself states an evaluation percentage for that condition. "
    "private_medical_opinion means a signed letter or opinion from a private "
    "(non-VA) physician stating a diagnosis or a nexus/'at least as likely as not' opinion. "
    "is_va_decision is true only for VA rating decisions / decision letters that "
    "grant, deny, or defer claims. "
    "relevance: is this document plausibly part of a VA DISABILITY-COMPENSATION claim "
    "(any medical record, service record, VA correspondence, nexus/DBQ, lay/buddy "
    "statement, or supporting evidence)? Use 'relevant' for anything a veteran would "
    "reasonably submit or reference in a claim. Use 'off_topic' ONLY when the document "
    "clearly has nothing to do with a VA claim or the veteran's health/service (e.g. a "
    "utility bill, a store receipt, a recipe, an unrelated tax form, a random photo). "
    "When you are not sure, use 'unclear' — never 'off_topic'. "
    "Do NOT invent data — null anything you cannot see in the text. Output valid JSON only."
)

# Doc types that ARE claim evidence — these are NEVER flagged off-topic, no matter
# what the model says. An off-topic flag can only ever land on an 'other'/unclassified
# document, so real evidence is never put at risk of being suggested for deletion.
_EVIDENTIARY_DOC_TYPES = frozenset(DOC_TYPES) - {"other"}
_RELEVANCE_VALUES = ("relevant", "unclear", "off_topic")


def parse_llm_json(raw: str) -> dict | None:
    """Tolerant JSON extraction — strips code fences, finds the outer object."""
    if not raw or not isinstance(raw, str):
        return None
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            try:
                out = json.loads(raw[start : end + 1])
                return out if isinstance(out, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _clean_str(value, max_len: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:max_len] if value else None


def _clean_percent(value) -> int | None:
    """0–100 multiple of 10, else DROPPED (None). Accepts int or digit-string;
    bools and anything off-grid are rejected — the VA schedule has no 55%."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().rstrip("%").isdigit():
        value = int(value.strip().rstrip("%"))
    if not isinstance(value, int):
        return None
    if 0 <= value <= 100 and value % 10 == 0:
        return value
    return None


def _clean_date(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10]).isoformat()
    except ValueError:
        return None


def _clean_dc(value) -> str | None:
    v = _clean_str(value, 8)
    if v and re.fullmatch(r"[0-9]{4}(-[0-9]{4})?", v):
        return v[:8]
    return None


def validate_extraction(raw) -> dict:
    """PURE: validated, whitelisted extraction dict from arbitrary LLM output.

    Rules (WAVE2-SPEC §4): doc_type must be in the enum else None; percents must
    be 0–100 multiples of 10 else dropped; decisions outside granted/denied/
    deferred dropped; unknown fields (top-level and per-condition) discarded.
    Always returns the full shape so the UI can rely on the keys.
    """
    if not isinstance(raw, dict):
        raw = {}
    doc_type = raw.get("doc_type")
    relevance = raw.get("relevance")
    out: dict = {
        "doc_type": doc_type if doc_type in DOC_TYPES else None,
        "doc_date": _clean_date(raw.get("doc_date")),
        "title": _clean_str(raw.get("title"), 255),
        "summary": _clean_str(raw.get("summary"), 2000),
        "is_va_decision": raw.get("is_va_decision") is True,
        # Whitelisted to the enum; anything off-list (incl. missing) defaults to the
        # SAFE 'unclear' — a hallucinated 'off_topic' never survives, and 'unclear'
        # never flags. relevance_reason is advisory free text.
        "relevance": relevance if relevance in _RELEVANCE_VALUES else "unclear",
        "relevance_reason": _clean_str(raw.get("relevance_reason"), 160),
        "conditions_mentioned": [],
    }
    mentioned = raw.get("conditions_mentioned")
    if isinstance(mentioned, list):
        for item in mentioned:
            if not isinstance(item, dict):
                continue
            name = _clean_str(item.get("name"), 255)
            if not name:
                continue
            decision = item.get("decision")
            out["conditions_mentioned"].append(
                {
                    "name": name,
                    "rating_percent": _clean_percent(item.get("rating_percent")),
                    "diagnostic_code": _clean_dc(item.get("diagnostic_code")),
                    "decision": decision if decision in _DECISIONS else None,
                }
            )
    return out


def attach_va_classifications(
    mentioned: list[dict], cmap: dict | None = None
) -> list[dict]:
    """Deterministic (NO LLM): stamp each extracted condition with VA's official
    contention-classification taxonomy — `va_classification` (name) and
    `va_classification_code` — when its diagnostic code or normalized name hits
    the vendored CC0 dataset (kb.store.classify_contention). Misses stamp None
    so the UI can rely on the keys. Pure given cmap; the vendored map is used
    when cmap is None (empty map when the vendor files are absent → all None)."""
    from ..kb.store import classify_contention  # lazy: keep import surface small

    for m in mentioned or []:
        if not isinstance(m, dict):
            continue
        hit = classify_contention(
            text=m.get("name"), diagnostic_code=m.get("diagnostic_code"), cmap=cmap
        )
        m["va_classification"] = (hit or {}).get("classification_name")
        m["va_classification_code"] = (hit or {}).get("classification_code")
    return mentioned


def suggest_links(mentioned: list[dict], conditions: list[dict]) -> list[dict]:
    """PURE, deterministic fuzzy match: casefold substring either way between an
    extracted condition name and the veteran's claimed conditions. Returns
    [{condition_id, name, match}] — SUGGESTIONS only; the veteran confirms in
    the UI (link endpoint). Never auto-links."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for m in mentioned or []:
        m_name = (m.get("name") or "").strip().casefold()
        if not m_name:
            continue
        for cond in conditions or []:
            c_id = str(cond.get("id") or "")
            c_name = (cond.get("name") or "").strip()
            c_fold = c_name.casefold()
            if not c_id or not c_fold:
                continue
            if m_name in c_fold or c_fold in m_name:
                key = (c_id, m_name)
                if key in seen:
                    continue
                seen.add(key)
                out.append(
                    {"condition_id": c_id, "name": c_name, "match": m.get("name")}
                )
    return out


def build_rating_summary(extracted: dict) -> list[dict]:
    """PURE: the rating-decision special case — when the document is a VA decision
    and carries evaluated percents, list them so the UI can offer a
    veteran-CONFIRMED 'update my current ratings' flow (never automatic)."""
    if not extracted.get("is_va_decision"):
        return []
    return [
        {
            "name": m["name"],
            "rating_percent": m["rating_percent"],
            "decision": m.get("decision"),
        }
        for m in extracted.get("conditions_mentioned", [])
        if m.get("rating_percent") is not None
    ]


def relevance_flag(extracted: dict | None, doc_type: str | None = None) -> dict:
    """PURE, deterministic: should this document be softly flagged as possibly
    not related to a VA claim (so the veteran can review and delete it)?

    SAFETY (evidence is never at risk):
      * Only an 'other'/unclassified document is ever eligible — any evidentiary
        doc_type (rating decision, STR, DBQ, treatment record, medical opinion,
        lay/service record) can NEVER be flagged, even if the model said off_topic.
      * A document that is a VA decision or mentions any condition is treated as
        relevant regardless of the model's label (medical/claim content present).
      * The flag only ever SUGGESTS deletion; nothing is auto-removed. Mirrors the
        near-duplicate posture — flag, the veteran decides.

    Returns {flagged: bool, relevance: str, reason: str|None}. Always the full shape.
    """
    ex = extracted or {}
    dt = doc_type if doc_type is not None else ex.get("doc_type")
    relevance = ex.get("relevance") if ex.get("relevance") in _RELEVANCE_VALUES else "unclear"
    reason = ex.get("relevance_reason")
    has_claim_content = bool(ex.get("is_va_decision")) or bool(ex.get("conditions_mentioned"))
    flagged = (
        relevance == "off_topic"
        and dt not in _EVIDENTIARY_DOC_TYPES  # only 'other'/None eligible
        and not has_claim_content
    )
    return {"flagged": flagged, "relevance": relevance, "reason": reason if flagged else None}


_CLASSIFY_MAX_CHARS = 24_000  # per-segment safety cap (matched to the read window)


async def _classify_segment(text: str) -> dict | None:
    """LLM pass over ONE bounded window (DEFAULT LOCAL model via the allowlisted
    gateway — PII stays on the fleet). Returns a VALIDATED extraction dict, or None
    when the gateway is down / returns garbage."""
    if not text or not text.strip():
        return None
    from ..llm.gateway import gateway  # lazy — keeps pure validators importable sans SDK

    try:
        raw = await gateway.complete(
            [
                {"role": "system", "content": CLASSIFY_SYSTEM},
                {"role": "user", "content": text[:_CLASSIFY_MAX_CHARS]},
            ],
            temperature=0.0,
            max_tokens=1500,
        )
    except Exception:  # noqa: BLE001 — gateway down → retryable
        return None
    parsed = parse_llm_json(raw)
    if parsed is None:
        return None
    return validate_extraction(parsed)


def _condition_key(c: dict) -> tuple[str, str]:
    """Dedup key for a mentioned condition: normalized name + diagnostic code."""
    return ((c.get("name") or "").strip().casefold(), (c.get("diagnostic_code") or "").strip())


def select_classify_segments(segments: list, max_segments: int) -> tuple[list, bool]:
    """Pick a bounded subset of segments for classify: always head + tail, plus
    evenly spaced middle samples. Returns (chosen, was_sampled).

    Pure helper so unit tests can assert a 27-window Blue Button becomes ≤N
    LLM calls without spinning the gateway.
    """
    if not segments:
        return [], False
    limit = max(1, int(max_segments))
    if len(segments) <= limit:
        return list(segments), False
    if limit == 1:
        return [segments[0]], True
    # Evenly spaced indices including 0 and last.
    last = len(segments) - 1
    idxs: set[int] = {0, last}
    for i in range(1, limit - 1):
        idxs.add(round(i * last / (limit - 1)))
    chosen = [segments[i] for i in sorted(idxs)]
    # Cap length if rounding collided (rare on small N).
    if len(chosen) > limit:
        chosen = chosen[: limit - 1] + [segments[last]]
    return chosen, True


async def classify_text(text: str) -> dict | None:
    """Whole-document classification. A large record is split into overlapping
    segments so conditions deep in a C-file / Blue Button are not dropped.

    Doc-type / is_va_decision / summary / dates come from the HEAD segment;
    conditions_mentioned is the DEDUPED UNION across segments that ran.
    Returns None only when the HEAD can't be classified (gateway down →
    retryable). Per-segment failures deeper in are tolerated.

    Production guards (customer-safe):
      * sample at most `intake_classify_max_segments` windows (default 9) so a
        600k Blue Button cannot enqueue ~27 multi-minute LLM jobs;
      * run tail windows concurrently (capped) to match batch P40 slots.
    """
    if not text or not text.strip():
        return None
    from ..config import settings

    all_segments = map_segments(text)
    max_segs = getattr(settings, "intake_classify_max_segments", 9) or 9
    segments, sampled = select_classify_segments(all_segments, max_segs)

    base = await _classify_segment(segments[0].text) if segments else None
    if base is None:
        return None
    if len(segments) == 1:
        base.setdefault(
            "read_coverage",
            {
                "segments_total": len(all_segments),
                "segments_read": 1,
                "segments_failed": 0,
                "segments_sampled": sampled,
            },
        )
        return base

    import asyncio

    conc = max(1, int(getattr(settings, "intake_classify_concurrency", 3) or 3))
    sem = asyncio.Semaphore(conc)

    async def _one(seg_text: str) -> dict | None:
        async with sem:
            return await _classify_segment(seg_text)

    parts = await asyncio.gather(
        *(_one(seg.text) for seg in segments[1:]),
        return_exceptions=True,
    )

    merged = list(base.get("conditions_mentioned", []))
    seen = {_condition_key(c) for c in merged}
    read, failed = 1, 0
    for part in parts:
        if part is None or isinstance(part, BaseException):
            failed += 1
            continue
        read += 1
        for c in part.get("conditions_mentioned", []) or []:
            k = _condition_key(c)
            if k not in seen:
                seen.add(k)
                merged.append(c)
    base["conditions_mentioned"] = merged
    base["read_coverage"] = {
        "segments_total": len(all_segments),
        "segments_considered": len(segments),
        "segments_read": read,
        "segments_failed": failed,
        "segments_sampled": sampled,
    }
    if sampled:
        note = (
            f"Large record: classified {len(segments)} of {len(all_segments)} sections "
            "(head, tail, and samples through the middle) so intake stays responsive."
        )
        summary = (base.get("summary") or "").strip()
        base["summary"] = f"{summary} {note}".strip() if summary else note
    return base
