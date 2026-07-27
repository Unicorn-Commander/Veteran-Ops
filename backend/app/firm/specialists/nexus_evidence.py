"""Nexus-evidence gap specialist — claims-legal educational lane.

When a claimed condition's readiness band still lists a medical nexus (or a
secondary link opinion) as missing, seed an educational finding that points the
veteran to obtain a clinician nexus / DBQ opinion and the in-app nexus builder.

DETERMINISTIC-ONLY. Never asserts the link, never predicts a grant, never
originates a medical opinion — clinicians write nexus letters; this app organizes.
"""

from __future__ import annotations

from ..base import Specialist

# Labels emitted by analyze_gaps / score_condition for nexus-type gaps.
_NEXUS_LABEL_MARKERS = (
    "medical nexus",
    "nexus opinion",
    "nexus letter",
    "nexus",
    "linking to the primary",
)

_REG = "38 CFR §3.303 / §3.310 (medical nexus / secondary link); educational only"


def _missing_is_nexus(label: str) -> bool:
    low = (label or "").strip().lower()
    if not low:
        return False
    return any(m in low for m in _NEXUS_LABEL_MARKERS)


class NexusEvidenceSpecialist(Specialist):
    name = "nexus_evidence"
    llm_enrich = False  # deterministic-only

    def seed(self, dossier) -> list[dict]:
        out: list[dict] = []
        for c in dossier.conditions or []:
            if not isinstance(c, dict):
                continue
            name = (c.get("name") or "").strip()
            if not name:
                continue
            # Presumptive paths typically do not need a nexus opinion.
            claim_type = (c.get("claim_type") or "direct").lower()
            if claim_type == "presumptive":
                continue
            missing = [m for m in (c.get("missing") or []) if isinstance(m, str)]
            nexus_missing = [m for m in missing if _missing_is_nexus(m)]
            if not nexus_missing:
                continue
            out.append({
                "key": f"nexus_gap:{(c.get('id') or name).lower()}",
                "kind": "nexus_gap",
                "title": f"Obtain a nexus / DBQ opinion for {name}",
                "body": (
                    f"Readiness still lists a medical nexus gap for {name} "
                    f"({'; '.join(nexus_missing)}). A treating clinician or an "
                    "examiner via a completed DBQ can provide a medical opinion that "
                    "the condition is 'at least as likely as not' related to service "
                    "(or to a service-connected primary for a secondary claim). "
                    "Use the nexus letter builder to organize facts for your provider — "
                    "this app does not write the medical opinion, and nothing here is a "
                    "prediction that VA will grant the claim."
                ),
                "reg": _REG,
                "condition_name": name,
                "still_needed": nexus_missing,
                "open_route": "/nexus",
                "severity": "high",
                "needs_nexus": True,
            })
        return out
