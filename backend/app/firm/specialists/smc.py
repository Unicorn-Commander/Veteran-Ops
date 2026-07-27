"""SMC educational specialist — statutory housebound / SMC-S screen (§3.350).

When the dossier carries rated percentages, reuse the rating engine's educational
``smc_flags`` (SMC-S remainder with bilateral factor, plus the general SMC-K
nature note). TDIU flags are skipped — TdiuSpecialist already owns that screen.

DETERMINISTIC-ONLY. Educational self-help — never "you qualify for SMC", never
an entitlement determination. Language always points the veteran to discuss with
an accredited VSO.
"""

from __future__ import annotations

from ...rating.engine import RatingEntry, combined_rating
from ..base import Specialist

_REG = "38 CFR §3.350 (Special Monthly Compensation); educational screen only"

# TDIU is handled by TdiuSpecialist — never re-surface those flags here.
_SMC_FLAG_KEYS = frozenset({"smc_s", "smc_k_note"})


def _entries_from_dossier(dossier) -> list[RatingEntry]:
    """Build RatingEntry list from condition current_rating (+ optional side)."""
    out: list[RatingEntry] = []
    for c in dossier.conditions or []:
        if not isinstance(c, dict):
            continue
        pct = c.get("current_rating")
        if pct is None:
            continue
        try:
            p = int(pct)
        except (TypeError, ValueError):
            continue
        if p <= 0:
            continue
        side = c.get("side")
        if side not in ("left", "right"):
            side = None
        name = (c.get("name") or "condition").strip() or "condition"
        out.append(RatingEntry(label=name, percent=p, side=side))
    return out


class SmcSpecialist(Specialist):
    name = "smc_screen"
    llm_enrich = False  # deterministic-only — educational screen, no model paraphrase

    def seed(self, dossier) -> list[dict]:
        entries = _entries_from_dossier(dossier)
        if not entries:
            return []

        result = combined_rating(entries)
        flags = [f for f in (result.smc_flags or []) if f.get("key") in _SMC_FLAG_KEYS]
        if not flags:
            return []

        out: list[dict] = []
        for flag in flags:
            key = str(flag.get("key") or "smc")
            title = str(flag.get("title") or "SMC educational screen")
            text = str(flag.get("text") or "").strip()
            source = str(flag.get("source") or _REG)
            # Reinforce educational lane — never entitlement language.
            body = text
            if body and "vso" not in body.lower():
                body = (
                    f"{body} This is an educational screen only — not a determination "
                    "that you qualify for SMC. You may want to discuss with an "
                    "accredited VSO."
                )
            elif body and "qualify" not in body.lower():
                # Engine text already mentions VSO; keep it and add a soft close.
                if "educational" not in body.lower() and "not a determination" not in body.lower():
                    body = f"{body} Educational only — not an eligibility determination."
            severity = "high" if key == "smc_s" else "low"
            out.append({
                "key": f"smc_education:{key}",
                "kind": "smc_education",
                "title": title,
                "body": body,
                "reg": source,
                "smc_flag_key": key,
                "combined": result.combined,
                "raw_combined": result.raw,
                "severity": severity,
                "needs_nexus": False,
                "open_route": "/rating",
            })
        return out
