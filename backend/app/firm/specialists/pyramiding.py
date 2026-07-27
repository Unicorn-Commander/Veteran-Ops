"""Pyramiding + under-rating specialist (§4.14 / §4.130 / Esteban).

Seed: `rating_rules.find_pyramiding_cautions` (overlapping conditions VA won't pay
twice → `pyramiding` cautions) PLUS `rating_rules.find_underrating_opportunities`
(Esteban-positive separate ratings the veteran may be under-rated for →
`underrating` opportunities).

DETERMINISTIC-ONLY: both seeds are already precisely reg-worded and the reduction/
overlap reasoning is exactly the surface where a paraphrase is most dangerous, so
this specialist never calls the model — it returns the seed notes as Findings.
"""

from __future__ import annotations

from ..base import Specialist


class PyramidingSpecialist(Specialist):
    name = "pyramiding"
    llm_enrich = False  # deterministic-only — no model call, ever

    def seed(self, dossier) -> list[dict]:
        from ...strategy.rating_rules import (
            find_pyramiding_cautions,
            find_underrating_opportunities,
        )

        return (
            find_pyramiding_cautions(dossier.conditions)
            + find_underrating_opportunities(dossier.conditions)
        )
