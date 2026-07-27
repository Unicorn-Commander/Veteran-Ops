"""Presumptive-eligibility specialist (§3.307 / §3.309 / §3.317 / PACT Act).

Seed: `analysis.presumptives.match_presumptives` — a PURE rules screen of the
veteran's profile (service periods + exposures) against the presumptive KB cards.

DETERMINISTIC-ONLY (like the underlying matcher, which "never uses the LLM,
ever"). It surfaces a presumptive PROGRAM the veteran's profile plausibly fits;
membership is the matcher's decision, not the model's. The seed uses the authored
card corpus (pure file load) so it stays DB-free and deterministic.
"""

from __future__ import annotations

from ...analysis.presumptives import match_presumptives
from ...kb.store import load_cards
from ..base import Specialist

# Program → the regulation the presumption rests on (for the finding's reg line).
_PROGRAM_REG = {
    "pact_burn_pits": "38 CFR §3.320 (PACT Act — burn pits / airborne hazards)",
    "agent_orange": "38 CFR §3.309(e) (Agent Orange / herbicides)",
    "gulf_war": "38 CFR §3.317 (Gulf War undiagnosed illness)",
    "gulf_war_infectious": "38 CFR §3.317(c) (Gulf War infectious diseases)",
    "camp_lejeune": "38 CFR §3.309(f) (Camp Lejeune)",
    "radiation": "38 CFR §3.309(d) (radiation-exposed veterans)",
    "chronic_one_year": "38 CFR §3.307 / §3.309(a) (chronic diseases within a year)",
    "pow": "38 CFR §3.309(c) (former prisoners of war)",
    "mustard_gas": "38 CFR §3.316 (mustard gas, Lewisite, and vesicating agents)",
    "als": "38 CFR §3.318 (amyotrophic lateral sclerosis)",
}


class PresumptivesSpecialist(Specialist):
    name = "presumptives"
    llm_enrich = False  # deterministic-only — the matcher never uses the LLM

    def seed(self, dossier) -> list[dict]:
        if not dossier.profile:
            return []
        cards = [c for c in load_cards() if c.get("card_type") == "presumptive"]
        # Pass claimed condition names so ALS (§3.318) can condition-gate on
        # 90+ service days + an ALS / motor-neuron claim (never spam-only).
        condition_names = [
            str(c.get("name") or "")
            for c in (dossier.conditions or [])
            if isinstance(c, dict)
        ]
        matches = match_presumptives(
            dossier.profile, cards, condition_names=condition_names
        )
        claimed = {(c.get("name") or "").strip().lower() for c in dossier.conditions}
        out: list[dict] = []
        for m in matches:
            title = (m.get("title") or "").strip()
            if not title or title.lower() in claimed:
                continue
            program = m.get("program") or "presumptive"
            out.append({
                "key": f"presumptive:{program}:{title.lower()}",
                "kind": "presumptive",
                "title": f"{title} may be presumptive for you",
                "body": (
                    m.get("matched_reason") or ""
                ) + (
                    " A presumptive claim does not need a nexus opinion — VA presumes "
                    "the service connection when the program's exposure and service "
                    "criteria are met. Confirm the specifics with a VSO."
                ),
                "reg": _PROGRAM_REG.get(program, "38 CFR §3.307 / §3.309"),
                "primary": [],
                "secondary": title,
                "needs_nexus": False,
                "severity": "medium",
            })
        return out
