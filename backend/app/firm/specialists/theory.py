"""Theory-origination specialist (Phase 2b) — the one roster member that
ORIGINATES reasoned service-connection theories ABOVE the deterministic floor.

Unlike the four floor specialists it has NO deterministic seed (``seed()`` is
empty); it produces nothing but theories, and only when
``settings.theory_origination_enabled`` is on. Each theory it emits is grounded in
retrieved VA-law cards + the veteran's OWN record chunks, cited (card_id + chunk_id
per claim), confidence-tagged in the VA register, and then passed through the
reviewer's well-foundedness gates before it can reach a veteran. A floor-only
install (the default) never sees it fire, so the deterministic floor is unchanged.
"""

from __future__ import annotations

from ...kb.store import retrieve_cards
from ...rag import retrieve_document_chunks
from ..base import Specialist


class TheorySpecialist(Specialist):
    name = "theory"
    llm_enrich = True  # theory origination is inherently a model pass
    can_theorize = True  # ...and this is the specialist that opts in
    # theory_system_prompt="" → theorize() uses the module default (_THEORY_SYSTEM).

    def seed(self, dossier) -> list[dict]:
        """No deterministic floor — this specialist is theory-only. It adds nothing
        to the seed layer, so the floor is byte-identical with or without it."""
        return []

    async def retrieve_for_theory(self, db, dossier) -> dict:
        """Dossier-level grounding: §3.303/§3.310 + condition-relevant VA-law cards
        and the veteran's own record chunks. Best-effort — a retrieval failure (or a
        None db in a pure-fn test) yields no grounding, and theorize() then originates
        nothing (a theory with no law/record to cite is not well-founded)."""
        names = [
            str(c.get("name") or "")
            for c in (dossier.conditions or [])
            if isinstance(c, dict) and c.get("name")
        ]
        card_query = (
            " ".join(names[:6])
            + " secondary service connection nexus aggravation 38 CFR 3.310 3.303"
        ).strip()
        chunk_query = " ".join(names[:6]).strip() or card_query
        cards: list = []
        chunks: list = []
        if db is not None:
            try:
                cards = await retrieve_cards(db, card_query, k=6)
            except Exception:  # noqa: BLE001 — grounding is best-effort
                cards = []
            try:
                chunks = await retrieve_document_chunks(db, dossier.uid, chunk_query, k=6)
            except Exception:  # noqa: BLE001 — grounding is best-effort
                chunks = []
        return {"cards": cards, "chunks": chunks}
