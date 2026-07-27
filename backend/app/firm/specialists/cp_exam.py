"""C&P exam prep specialist — claims-legal educational lane.

For each claimed condition, seed a deterministic prep note: the likely DBQ
(via map_dbq), that C&P prep is available in the companion, and any still-needed
evidence from the dossier readiness band.

DETERMINISTIC-ONLY. Educational self-help — never predicts a rating percentage,
never asserts service connection, never says "you will get X%".
"""

from __future__ import annotations

from ...analysis.gaps import map_dbq
from ...kb.store import load_dbq_catalog
from ..base import Specialist

_REG = "38 CFR Part 4 (Disability Benefits Questionnaires); educational C&P prep"


class CpExamSpecialist(Specialist):
    name = "cp_exam"
    llm_enrich = False  # deterministic-only — educational prep, no model paraphrase

    def seed(self, dossier) -> list[dict]:
        conditions = list(dossier.conditions or [])
        if not conditions:
            return []
        catalog = load_dbq_catalog()
        out: list[dict] = []
        for c in conditions:
            if not isinstance(c, dict):
                continue
            name = (c.get("name") or "").strip()
            if not name:
                continue
            dbq = map_dbq(name, c.get("body_system"), catalog)
            still_needed = list(c.get("missing") or [])
            still_txt = (
                " Still needed for readiness: " + "; ".join(still_needed[:6]) + "."
                if still_needed
                else " Readiness items look covered — still prepare to describe "
                "worst days, frequency, and functional impact honestly."
            )
            dbq_txt = (
                f" The examiner most often uses the {dbq}."
                if dbq
                else " The examiner will use a condition-specific DBQ from your claim file."
            )
            out.append({
                "key": f"cp_exam_prep:{(c.get('id') or name).lower()}",
                "kind": "cp_exam_prep",
                "title": f"C&P exam prep for {name}",
                "body": (
                    f"Educational C&P preparation for {name}.{dbq_txt} "
                    "Open the C&P companion to review what to expect, how to describe "
                    "symptoms (worst day / frequency / functional impact), and what to "
                    "bring. The examiner documents findings; VA decides the rating later — "
                    "this is not a prediction of any percentage."
                    f"{still_txt}"
                ),
                "reg": _REG,
                "condition_name": name,
                "likely_dbq": dbq,
                "still_needed": still_needed,
                "open_route": "/cp-companion",
                "severity": "low",
                "needs_nexus": False,
            })
        return out
