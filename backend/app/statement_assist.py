"""Assisted personal-statement drafting — PROPOSE + DRAFT, the veteran DISPOSES.

The deterministic 21-4138 builder (routers/statement.py) formats the veteran's own
typed words verbatim. THIS adds the assisted path Aaron asked for, drawn on the right
side of a bright line:

  * It drafts a first-person statement using ONLY facts already in the veteran's own
    record (their logged symptoms, the in-service event they entered, their condition
    notes). It invents no event, date, symptom, or detail.
  * It offers condition-specific PROMPTS — common effects to consider — phrased as
    questions ("you may want to describe whether…"), never as assertions that the
    veteran has them.
  * The output is a DRAFT the veteran edits line by line, adopts as their own words,
    and attests to before signing. The app never signs, never submits, never files.

This is assisted drafting the way a VSO helps — proposing and organizing, while the
veteran authors and attests. Runs on the local model; never raises (a miss just means
no draft, and the veteran writes it themselves as before).
"""

from __future__ import annotations

from .llm.gateway import gateway

_DRAFT_SYSTEM = (
    "You help a U.S. veteran organize a first-person VA Form 21-4138 (Statement in "
    "Support of Claim) DRAFT. This will be the veteran's OWN sworn statement, so accuracy "
    "is everything.\n\n"
    "ABSOLUTE RULES:\n"
    "1. Use ONLY the facts provided below. Invent NOTHING — no event, date, place, "
    "symptom, diagnosis, or detail that is not in the provided material. If a detail "
    "isn't given, leave a clearly-marked blank like [add the date] for the veteran.\n"
    "2. Write in the FIRST PERSON ('I'), in plain, honest, 8th-grade language — the way "
    "the veteran would speak, not legalese.\n"
    "3. NEVER predict or promise a VA outcome, a rating, or a dollar amount. State only "
    "what the veteran experienced and how it affects them.\n"
    "4. This is a DRAFT for the veteran to verify and edit. Do not fabricate certainty. "
    "Where the provided facts are thin, write less rather than filling gaps.\n\n"
    "Organize it naturally: the in-service event (what happened), what they personally "
    "experienced, and how the condition affects their work and daily life. Return ONLY "
    "the statement text — no preamble, no headings, no signature block."
)

_PROMPTS_SYSTEM = (
    "You help a veteran remember what to include in their own personal statement about a "
    "condition. List the kinds of day-to-day effects and experiences that veterans with "
    "this condition COMMONLY describe — as PROMPTS the veteran can consider, phrased as "
    "questions or 'you may want to describe whether…'. These are memory joggers, NOT "
    "assertions that the veteran has them, and NOT medical claims. No outcomes, no "
    "ratings. Return STRICT JSON only: {\"prompts\": [\"...\", ...]} with 5-8 short items."
)


def _facts_block(facts: dict) -> str:
    lines: list[str] = []
    name = (facts.get("condition_name") or "").strip()
    if name:
        lines.append(f"CONDITION: {name}")
    ev = (facts.get("in_service_event") or "").strip()
    if ev:
        lines.append(f"IN-SERVICE EVENT (the veteran's own words): {ev}")
    notes = (facts.get("notes") or "").strip()
    if notes:
        lines.append(f"CONDITION NOTES: {notes}")
    for e in facts.get("symptom_entries") or []:
        bits = []
        if e.get("entry_date"):
            bits.append(str(e["entry_date"]))
        if e.get("symptoms"):
            bits.append(f"symptoms: {e['symptoms']}")
        if e.get("severity") is not None:
            bits.append(f"severity {e['severity']}/10")
        if e.get("functional_impact"):
            bits.append(f"impact: {e['functional_impact']}")
        if bits:
            lines.append("LOGGED: " + " — ".join(bits))
    return "\n".join(lines) if lines else "(the veteran has not recorded facts yet)"


async def draft_from_facts(facts: dict, *, model: str | None = None) -> str:
    """A first-person 21-4138 DRAFT built ONLY from the veteran's recorded facts. Empty
    string on any failure or when there's nothing to draft from."""
    if not (facts.get("in_service_event") or facts.get("notes") or facts.get("symptom_entries")):
        return ""
    try:
        return (
            await gateway.complete(
                [
                    {"role": "system", "content": _DRAFT_SYSTEM},
                    {"role": "user", "content": _facts_block(facts)},
                ],
                model=model,
                temperature=0.3,
                max_tokens=900,
                touches_pii=True,
            )
        ).strip()
    except Exception:  # noqa: BLE001 — additive; the veteran can always write it themselves
        return ""


async def suggest_prompts(condition_name: str, *, model: str | None = None) -> list[str]:
    """Condition-specific memory-jogger prompts (questions, not assertions). [] on failure."""
    name = (condition_name or "").strip()
    if not name:
        return []
    import json

    try:
        raw = await gateway.complete(
            [
                {"role": "system", "content": _PROMPTS_SYSTEM},
                {"role": "user", "content": f"Condition: {name}"},
            ],
            model=model,
            temperature=0.4,
            max_tokens=400,
        )
        start, end = raw.find("{"), raw.rfind("}")
        obj = json.loads(raw[start : end + 1]) if start >= 0 else {}
        return [str(p).strip() for p in (obj.get("prompts") or []) if str(p).strip()][:8]
    except Exception:  # noqa: BLE001
        return []
