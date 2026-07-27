"""Condition→diagnostic-code mapping helpers with the HARD grounding rule.

The LLM's only job here is to (a) pick the best-matching retrieved KB card and
(b) point at which authored tier's criteria the veteran's own notes suggest —
selected FROM the retrieved cards, never invented. Validation is enforced in
`validate_selection`: any diagnostic code or percent the model emits that does
not exist in the retrieved cards' structured data is dropped and logged.

`extract_tiers`, `tier_percents`, `parse_llm_json`, and `validate_selection`
are pure functions (unit-testable without a DB or gateway).
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("veteran_ops.analysis")

MAPPING_CAVEAT = (
    "Educational information only — the criteria come from the cited regulation; "
    "which tier applies is decided by VA based on the whole record. Verify current "
    "criteria at eCFR / VA.gov and discuss with your provider or an accredited VSO."
)


def extract_tiers(card_data: dict | None) -> list[dict]:
    """Normalized tiers [{percent, criteria, evidence_needed}] from a card's data."""
    tiers = (card_data or {}).get("tiers") or []
    out: list[dict] = []
    for t in tiers:
        if not isinstance(t, dict) or "percent" not in t:
            continue
        try:
            pct = int(t["percent"])
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "percent": pct,
                "criteria": str(t.get("criteria") or ""),
                "evidence_needed": list(t.get("evidence_needed") or []),
            }
        )
    return out


def tier_percents(card_data: dict | None) -> set[int]:
    return {t["percent"] for t in extract_tiers(card_data)}


def build_mapping_prompt(
    condition_name: str,
    notes: str | None,
    current_rating: int | None,
    cards: list[dict],
) -> list[dict]:
    """Chat messages asking the model to select a card + tier from the retrieved set.

    cards: [{index, title, diagnostic_code, source, tiers: [{percent, criteria}]}]
    """
    catalog = json.dumps(cards, indent=1)
    user = (
        f"Condition: {condition_name}\n"
        f"Veteran's current rating for it: "
        f"{current_rating if current_rating is not None else 'none/unknown'}\n"
        f"Veteran's notes about symptoms/impact: {notes or '(none provided)'}\n\n"
        f"Candidate rating-criteria cards (the ONLY permitted sources):\n{catalog}\n\n"
        "Task: pick the single best-matching card for this condition, and — ONLY if "
        "the notes clearly describe criteria of a specific tier — identify that "
        "tier's percent for educational discussion. Use ONLY percents that appear in "
        "the chosen card's tiers; never invent codes or percentages. If the notes "
        "don't support a tier, use null.\n\n"
        'Reply with STRICT JSON only: {"card_index": <int>, '
        '"suggested_tier_percent": <int or null>, '
        '"rationale": "<one or two educational sentences citing which criteria the '
        "notes appear to describe; phrase as 'the criteria describe', never promise "
        "an outcome>\"}"
    )
    return [
        {
            "role": "system",
            "content": (
                "You are an educational assistant for veterans organizing their own VA "
                "disability claims. You only ground answers in the provided regulation "
                "cards. You never predict or promise ratings, never say 'you will "
                "receive X%'. Reply with strict JSON only."
            ),
        },
        {"role": "user", "content": user},
    ]


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_llm_json(text: str) -> dict | None:
    """Extract the first JSON object from model output; None when unparseable."""
    if not text:
        return None
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def validate_selection(
    answer: dict | None,
    cards: list[dict],
) -> tuple[int | None, int | None, str | None]:
    """Enforce the grounding rule on an LLM answer.

    cards: the retrieved card dicts [{diagnostic_code, data, ...}] in prompt order.
    Returns (card_index, suggested_tier_percent, rationale) with every ungrounded
    element dropped (and logged).
    """
    if not answer:
        return None, None, None

    idx = answer.get("card_index")
    if not isinstance(idx, int) or not (0 <= idx < len(cards)):
        if idx is not None:
            log.warning("LLM mapping: card_index %r not in retrieved set — dropped.", idx)
        return None, None, None

    card = cards[idx]
    allowed = tier_percents(card.get("data"))

    pct = answer.get("suggested_tier_percent")
    if pct is not None:
        try:
            pct = int(pct)
        except (TypeError, ValueError):
            log.warning("LLM mapping: non-integer tier %r — dropped.", pct)
            pct = None
    if pct is not None and pct not in allowed:
        log.warning(
            "LLM mapping: suggested tier %s%% not in card '%s' tiers %s — dropped.",
            pct,
            card.get("title"),
            sorted(allowed),
        )
        pct = None

    rationale = answer.get("rationale")
    rationale = str(rationale).strip() if rationale else None

    # Belt-and-suspenders: drop a rationale that cites a diagnostic code absent
    # from the retrieved cards (the model inventing DCs is exactly the failure
    # mode this layer exists to stop).
    if rationale:
        known_dcs = {
            str(c.get("diagnostic_code"))
            for c in cards
            if c.get("diagnostic_code")
        }
        cited = set(re.findall(r"\bDC\s*(\d{4})\b", rationale, flags=re.IGNORECASE))
        unknown = cited - known_dcs
        if unknown:
            log.warning(
                "LLM mapping: rationale cites unknown diagnostic code(s) %s — rationale dropped.",
                sorted(unknown),
            )
            rationale = None

    # Same rule for percentages: every "NN%" the rationale mentions must be a
    # tier that actually exists in the retrieved cards — an invented percentage
    # in a benefits context is exactly as harmful as an invented DC.
    if rationale:
        known_pcts: set[int] = set()
        for c in cards:
            known_pcts |= tier_percents(c.get("data"))
        cited_pcts = {
            int(m) for m in re.findall(r"\b(\d{1,3})\s*(?:%|percent\b)", rationale)
        }
        unknown_pcts = cited_pcts - known_pcts
        if unknown_pcts:
            log.warning(
                "LLM mapping: rationale cites percentage(s) %s not present in any "
                "retrieved card's tiers — rationale dropped.",
                sorted(unknown_pcts),
            )
            rationale = None

    return idx, pct, rationale
