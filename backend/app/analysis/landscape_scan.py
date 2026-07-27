"""Deep landscape scan — the ONE agent that reaches beyond curated data.

Every other agent is grounded in supplied facts/cards (generic knowledge = cited DB).
This one is different by necessity: it asks the model to use its OWN broad medical
knowledge to surface plausible secondary-connection LEADS that are NOT in the curated
secondary map and that the deterministic rules didn't catch — the "scan the whole
landscape" pass.

Because these are the model's medical knowledge (not a cited source), they are framed
as EMERGING LEADS to research with a provider/VSO — never as established facts, never
as "you qualify." That framing is the safety boundary: we're honest that this is a
hypothesis-generator to investigate, not an assertion. The curated, cited pathways stay
the source of truth; this only widens the net for the veteran + their doctor to examine.

Runtime model is configurable (opts.model) because THIS is the task whose quality tracks
the model's medical breadth — the one place a bigger model may earn its cost. The tier
is chosen by the bake-off in the eval, not hard-coded here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.gateway import gateway
from ..models import ClaimedCondition

_SYSTEM = (
    "You are Rating Raider's landscape scout — a careful, well-read medical researcher "
    "helping a veteran and their doctor find connections worth investigating. You are "
    "given the veteran's service-connected / claimed conditions and a list of "
    "secondary connections ALREADY KNOWN to the system. Using your own medical "
    "knowledge, surface OTHER conditions that could plausibly be SECONDARY to (caused "
    "or aggravated by) the veteran's conditions and that are NOT already in the known "
    "list.\n\n"
    "HARD RULES — these are LEADS to research, not claims:\n"
    "1. NEVER say the veteran qualifies, is entitled, will be granted, or will receive "
    "anything. These are possibilities to discuss with a doctor or VSO, nothing more.\n"
    "2. Do NOT repeat anything already in the known-connections list.\n"
    "3. For EACH lead give the biological mechanism in plain language, and an HONEST "
    "strength tag — 'well_documented' (strong medical literature), 'plausible' "
    "(reasonable mechanism, less established), or 'emerging' (early/limited evidence).\n"
    "4. Invent no diagnostic codes, percentages, or dollar amounts.\n"
    "5. Propose at most 6, strongest/most-documented first. If nothing beyond the known "
    "list is well-founded, return an empty list — do NOT pad.\n\n"
    "Return STRICT JSON only, no markdown fences: {\"leads\": [{"
    "\"secondary\": \"<the condition that may be secondary>\", "
    "\"primary\": \"<which of the veteran's conditions it stems from>\", "
    "\"mechanism\": \"<1-2 sentence plain-language biological link>\", "
    "\"strength\": \"well_documented\"|\"plausible\"|\"emerging\", "
    "\"discuss\": \"<what to ask a provider / what evidence would help>\"}]}"
)

_STRENGTHS = {"well_documented", "plausible", "emerging"}


@dataclass
class Lead:
    secondary: str
    primary: str
    mechanism: str
    strength: str
    discuss: str


def _parse(raw: str, known: set[str]) -> list[Lead]:
    """Parse strict-JSON leads; drop malformed rows, dedupe vs the known set + each
    other, clamp strength to the allowed tags. Never raises."""
    try:
        start, end = raw.find("{"), raw.rfind("}")
        obj = json.loads(raw[start : end + 1]) if start >= 0 else {}
    except Exception:  # noqa: BLE001
        return []
    out: list[Lead] = []
    seen = set(known)
    for row in (obj.get("leads") or [])[:12]:
        if not isinstance(row, dict):
            continue
        sec = str(row.get("secondary") or "").strip()
        key = sec.lower()
        if not sec or key in seen:
            continue
        strength = str(row.get("strength") or "plausible").strip().lower()
        if strength not in _STRENGTHS:
            strength = "plausible"
        seen.add(key)
        out.append(
            Lead(
                secondary=sec,
                primary=str(row.get("primary") or "").strip(),
                mechanism=str(row.get("mechanism") or "").strip(),
                strength=strength,
                discuss=str(row.get("discuss") or "").strip(),
            )
        )
    return out[:6]


async def scan_landscape(
    db: AsyncSession,
    uid: str,
    known_secondaries: list[str] | None = None,
    *,
    model: str | None = None,
) -> list[Lead]:
    """Surface novel secondary-connection LEADS beyond the curated map. `model=None`
    uses the gateway default (local); pass a larger allowlisted id to escalate. Returns
    [] if the veteran has no conditions or the model is unavailable."""
    conds = list(
        (
            await db.execute(
                select(ClaimedCondition).where(ClaimedCondition.user_id == uuid.UUID(uid))
            )
        ).scalars()
    )
    if not conds:
        return []
    cond_lines = "; ".join(
        f"{c.name}" + (f" (DC {c.diagnostic_code})" if c.diagnostic_code else "") for c in conds
    )
    known = known_secondaries or []
    known_set = {k.strip().lower() for k in known if k.strip()}
    user = (
        f"VETERAN'S CONDITIONS: {cond_lines}\n"
        f"ALREADY-KNOWN SECONDARY CONNECTIONS (do not repeat): "
        f"{', '.join(known) if known else '(none on file)'}\n\n"
        "Surface OTHER plausible secondary conditions worth investigating, strongest first."
    )
    try:
        raw = await gateway.complete(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
            model=model,
            temperature=0.3,
            max_tokens=900,
            touches_pii=True,
        )
    except Exception:  # noqa: BLE001 — additive; a miss just yields no extra leads
        return []
    return _parse(raw, known_set)
