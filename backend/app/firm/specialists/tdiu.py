"""TDIU specialist (§4.16 — Total Disability based on Individual Unemployability).

Seed: `rating_rules.screen_tdiu` — an educational screen (never an eligibility
determination) when the veteran plausibly meets, or is near, the schedular door.

DETERMINISTIC-ONLY: the screen text is already carefully lane-worded ("never an
eligibility determination") and it renders into the rigid GamePlanTdiu shape, so
this specialist never calls the model. It wraps the single screen dict into a
Finding so the firm can carry it uniformly.
"""

from __future__ import annotations

from ..base import Specialist


class TdiuSpecialist(Specialist):
    name = "tdiu"
    llm_enrich = False  # deterministic-only

    def seed(self, dossier) -> list[dict]:
        from ...strategy.rating_rules import screen_tdiu

        screen = screen_tdiu(dossier.conditions, dossier.current_combined)
        if not screen:
            return []
        # Wrap the screen (which has no key/kind/title/body) into a seed dict the
        # framework understands, preserving every original TDIU field for render.
        return [{
            **screen,
            "key": "tdiu",
            "kind": "tdiu",
            "title": "TDIU screen (§4.16)",
            "body": screen.get("why") or screen.get("what_it_is") or "",
            "severity": "high" if screen.get("eligible_schedular") else "medium",
        }]
