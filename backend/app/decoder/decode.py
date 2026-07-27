"""The decode LLM pass — proposes structure, PURE validators dispose.

Mirrors intake/classify.py's separation exactly: the LOCAL model (PII stays on
the fleet) reads the decision-letter text and returns strict JSON; deterministic,
unit-tested validators whitelist it. The model may only surface what the letter
says — validators drop invented codes/percents/dates, and the analyze step never
asserts a value the extraction didn't carry.

Element vocabulary for denials mirrors the three §3.303 elements the rest of the
app already teaches (analysis/gaps.py): current_disability, in_service_event, nexus.
"""

from __future__ import annotations

# Reuse the exact cleaners the intake pipeline is tested against — one grammar
# for percents/codes/dates across the whole app.
from ..intake.classify import _clean_date, _clean_dc, _clean_percent, _clean_str, parse_llm_json

_DECISIONS = ("granted", "denied", "deferred")
_ELEMENTS = ("current_disability", "in_service_event", "nexus")

DECODE_SYSTEM = (
    "You are a meticulous VA rating-decision decoder for a veteran's self-help "
    "claim organizer. Read the decision letter text and return STRICT JSON ONLY "
    "(no prose, no code fences) matching EXACTLY this shape:\n"
    "{\n"
    '  "decision_date": "YYYY-MM-DD or null (the date the decision was issued)",\n'
    '  "combined_evaluation": 0-100 multiple of 10 or null (the overall combined '
    'evaluation percentage stated on the letter),\n'
    '  "decisions": [{\n'
    '     "name": "the contention/condition as written",\n'
    '     "diagnostic_code": "4-digit code or null",\n'
    '     "decision": "granted|denied|deferred",\n'
    '     "rating_percent": 0-100 multiple of 10 or null (the evaluation assigned),\n'
    '     "effective_date": "YYYY-MM-DD or null",\n'
    '     "plain": "ONE or TWO plain-English sentences: what VA decided for this '
    'condition and, if denied, the core reason IN PLAIN WORDS. No legalese, no '
    'invented facts.",\n'
    '     "missing_elements": ["current_disability" and/or "in_service_event" '
    'and/or "nexus" — ONLY for denials, ONLY elements the letter says are missing; '
    'else []]\n'
    "  }]\n"
    "}\n"
    "Rules: Decode ONLY what the letter states — null anything you cannot see. "
    "rating_percent only when an evaluation percentage is assigned to that "
    "condition. 'missing_elements' names WHY a denial happened using exactly those "
    "three tokens: current_disability (no current diagnosed disability), "
    "in_service_event (no in-service event/injury/disease or qualifying service), "
    "nexus (no link/medical connection between the two). Empty list for grants and "
    "deferrals. Output valid JSON only."
)


def _clean_elements(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for v in value:
        if v in _ELEMENTS and v not in out:
            out.append(v)
    return out


def validate_decode(raw) -> dict:
    """PURE: whitelist the decode LLM output. Always returns the full shape.

    decision must be in granted/denied/deferred (else the row is dropped — a
    decode row with no decision is meaningless). percents/codes/dates run through
    the same cleaners as intake. missing_elements only survives for denials.
    """
    if not isinstance(raw, dict):
        raw = {}
    out: dict = {
        "decision_date": _clean_date(raw.get("decision_date")),
        "combined_evaluation": _clean_percent(raw.get("combined_evaluation")),
        "decisions": [],
    }
    rows = raw.get("decisions")
    if isinstance(rows, list):
        for item in rows:
            if not isinstance(item, dict):
                continue
            name = _clean_str(item.get("name"), 255)
            decision = item.get("decision")
            if not name or decision not in _DECISIONS:
                continue
            missing = _clean_elements(item.get("missing_elements")) if decision == "denied" else []
            out["decisions"].append(
                {
                    "name": name,
                    "diagnostic_code": _clean_dc(item.get("diagnostic_code")),
                    "decision": decision,
                    "rating_percent": _clean_percent(item.get("rating_percent")),
                    "effective_date": _clean_date(item.get("effective_date")),
                    "plain": _clean_str(item.get("plain"), 600),
                    "missing_elements": missing,
                }
            )
    return out


async def decode_text(text: str) -> dict | None:
    """LLM pass (DEFAULT LOCAL model via the allowlisted gateway). Returns a
    VALIDATED decode dict, or None when the gateway is down / returns garbage —
    the caller can fall back to the already-stored classify extraction and leave
    the decode retryable."""
    if not text or not text.strip():
        return None
    from ..llm.gateway import gateway  # lazy — keep pure validators import-light

    try:
        raw = await gateway.complete(
            [
                {"role": "system", "content": DECODE_SYSTEM},
                {"role": "user", "content": text[:16000]},
            ],
            temperature=0.0,
            max_tokens=2000,
        )
    except Exception:  # noqa: BLE001 — gateway down → retryable
        return None
    parsed = parse_llm_json(raw)
    if parsed is None:
        return None
    return validate_decode(parsed)
