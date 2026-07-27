"""Secondary-service-connection specialist (§3.310).

Seed: `rating_rules.find_secondary_opportunities` — a service-connected primary
plus a second condition (ideally denied or unclaimed) the VA recognizes as
secondary to it. The seed already establishes the theory and gates on a granted
primary; this specialist ENRICHES the write-up with the local LLM, grounded in
the VA-law KB cards and the veteran's OWN records — never adding a fact, never
asserting the link, never predicting an outcome. On any failure it falls back to
the seed's deterministic note (handled by the base explain()).
"""

from __future__ import annotations

from ...rag import retrieve_document_chunks
from ...kb.store import retrieve_cards
from ..base import Specialist

_SYSTEM = (
    "You are Rating Raider's secondary-conditions specialist. Rating Raider is "
    "free, educational self-help software for U.S. veterans. You are handed ONE "
    "already-established educational finding (a possible §3.310 secondary theory) "
    "and asked ONLY to reword its explanation so it is warmer and clearer for this "
    "veteran.\n\n"
    "HARD RULES — never break these:\n"
    "1. Add NO new facts. Use only the finding, the reference cards, and the "
    "veteran's own records shown to you. Invent no conditions, ratings, "
    "percentages, diagnostic codes, dollar amounts, or deadlines.\n"
    "2. You are NOT a doctor and NOT a lawyer. Never say the condition IS "
    "service-connected or IS secondary — a secondary theory always turns on a "
    "medical nexus opinion, which is the provider's to give, not yours.\n"
    "3. Never predict what VA will decide. Never say the veteran 'qualifies for', "
    "'will get', 'is entitled to', 'deserves', or 'should receive' anything.\n"
    "4. Cite the regulation the finding rests on (e.g. §3.310) in your wording; "
    "cite no regulation, diagnostic code, or percentage that is not shown to you.\n"
    "5. Warm, direct, 8th-grade reading level, 2–4 short sentences. Keep the "
    "meaning of the original finding — you are rewording, not re-deciding.\n\n"
    'Return STRICT JSON only, no markdown fences: {"body": "<your rewritten '
    'explanation>"}'
)


class SecondariesSpecialist(Specialist):
    name = "secondaries"
    llm_enrich = True
    system_prompt = _SYSTEM

    def seed(self, dossier) -> list[dict]:
        from ...strategy.rating_rules import find_secondary_opportunities

        return find_secondary_opportunities(dossier.conditions)

    async def retrieve(self, db, dossier, seed) -> dict:
        """Ground on the VA-law §3.310 cards for the secondary condition + the
        veteran's own uploaded records that mention it. Best-effort."""
        effect = str(seed.get("secondary") or "")
        primary = (seed.get("primary") or [""])[0]
        query = f"{effect} secondary service connection {primary} 38 CFR 3.310".strip()
        cards = await retrieve_cards(db, query, k=3)
        chunks: list = []
        if effect:
            try:
                chunks = await retrieve_document_chunks(db, dossier.uid, effect, k=2)
            except Exception:  # noqa: BLE001 — grounding is best-effort
                chunks = []
        return {"cards": cards, "chunks": chunks}
