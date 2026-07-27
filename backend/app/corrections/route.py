"""Route a records-correction to the right military board + form — PURE, deterministic.

The rules mirror the authored KB (kb/data/corrections.json) and the governing law:
- DRB  (DD Form 293, 10 U.S.C. §1553): upgrade a discharge characterization or change
  the narrative reason, WITHIN 15 YEARS of separation. Cannot touch a discharge given
  by a GENERAL court-martial.
- BCMR/BCNR (DD Form 149, 10 U.S.C. §1552): the catch-all — any error or injustice,
  including discharge upgrades beyond 15 years, after a DRB denial, general
  court-martial discharges, and record errors (names, dates, awards, rank, RE codes).
- PDBR (DD Form 294, 10 U.S.C. §1554a): re-review a DoD disability rating for members
  MEDICALLY SEPARATED (not retired) 2001–2009 with a combined rating of 20% or less.
- Liberal consideration (Hagel/Carson/Kurta/Wilkie memos): boards MUST apply it to
  discharge upgrades connected to PTSD, TBI, other mental-health conditions, or MST.

Educational only — this points you at the right door; it is not legal advice, and the
board decides. Nothing here files anything.
"""

from __future__ import annotations

# Separation-related goals (not pure clerical record errors). `re_code` belongs here
# so it isn't mis-classified as a records error — BUT the DRB itself only upgrades the
# characterization and narrative reason; a standalone RE-code fix is a BCMR matter, so
# only `_DRB_GOALS` make the DRB the right door.
_DISCHARGE_GOALS = {"discharge_upgrade", "narrative_reason", "re_code"}
_DRB_GOALS = {"discharge_upgrade", "narrative_reason"}
_LIBERAL = {"ptsd", "tbi", "mental_health", "mst"}

_DRB = {
    "board": "DRB",
    "board_full": "Discharge Review Board (your service's DRB)",
    "form": "DD Form 293",
    "form_title": "Application for the Review of Discharge",
    "source": "10 U.S.C. §1553; DD Form 293; DoDI 1332.28",
}
_BCMR = {
    "board": "BCMR",
    "board_full": "Board for Correction of Military/Naval Records (your service's board)",
    "form": "DD Form 149",
    "form_title": "Application for Correction of Military Record",
    "source": "10 U.S.C. §1552; DD Form 149; 32 CFR (per-service board rules)",
}
_PDBR = {
    "board": "PDBR",
    "board_full": "Physical Disability Board of Review",
    "form": "DD Form 294",
    "form_title": "Application for Physical Disability Board of Review",
    "source": "10 U.S.C. §1554a; DD Form 294; DoDI 6040.44",
}

_LIBERAL_NOTE = (
    "Because your discharge is connected to PTSD, TBI, another mental-health "
    "condition, or military sexual trauma, the board is REQUIRED to give your request "
    '"liberal consideration" (the Hagel, Carson, Kurta, and Wilkie policy memos). Say '
    "so plainly in your statement and connect the condition to what happened. The "
    "absence of records at the time is expected and does not defeat the claim."
)

_COD_NOTE = (
    "Discharge characterization drives VA eligibility: VA benefits generally require a "
    "discharge \"under conditions other than dishonorable.\" An Other-Than-Honorable "
    "discharge triggers a separate VA character-of-discharge determination — but that "
    "bar is NOT automatic, and upgrading your discharge (or winning the VA "
    "determination) can restore eligibility. These are two different processes; a VSO "
    "can help you run both."
)

_VSO = (
    "A VA-accredited Veterans Service Officer (VFW, DAV, The American Legion, or your "
    "state/county veterans office) can help with a records correction for free."
)
_LEGAL_AID = (
    "Discharge upgrades in particular are worth free legal help: law-school veterans "
    "clinics, the National Veterans Legal Services Program (NVLSP), Swords to "
    "Plowshares, and similar nonprofits take these cases at no cost. You never have to "
    "pay for help correcting your record."
)
_DISCLAIMER = (
    "This is educational self-help, not legal advice. Rating Raider is not a lawyer or "
    "an accredited representative and does not file or decide anything. These boards "
    "are part of your military service department, not the VA. Deadlines and eligibility "
    "have exceptions — confirm your specific situation with a VSO or a free legal-aid "
    "veterans clinic."
)


def _deadline_note(board: str, years: int | None) -> str:
    if board == "DRB":
        base = (
            "The DRB accepts applications within 15 YEARS of your discharge. Past 15 "
            "years, the BCMR (DD Form 149) is the route instead."
        )
        if isinstance(years, int) and years >= 13:
            base += (
                f" You reported ~{years} years — you're close to the 15-year cutoff. If "
                "there's any chance you're already past 15 years, file with the BCMR "
                "(DD Form 149) as well or instead; it has no firm cutoff."
            )
        return base
    if board == "BCMR":
        return (
            "The BCMR asks you to file within 3 years of discovering the error, BUT the "
            "board routinely waives this \"in the interest of justice,\" so a decades-old "
            "record can still be corrected. Explain any delay and file as soon as you can."
        )
    if board == "PDBR":
        return (
            "The PDBR reviews qualifying 2001–2009 medical separations; there is no "
            "hard filing deadline, but apply as soon as you can."
        )
    return ""


def route_correction(situation: dict) -> dict:
    """situation → the routed board/form recommendation (the CorrectionRouteOut dict).

    Keys used: goals[list], years_since_separation[int|None], general_court_martial,
    drb_denied, related_to[list], medically_separated_2001_2009, dod_rating_20_or_less,
    discharge_char[str|None].
    """
    goals = set(situation.get("goals") or [])
    years = situation.get("years_since_separation")
    gcm = bool(situation.get("general_court_martial"))
    drb_denied = bool(situation.get("drb_denied"))
    related = set(situation.get("related_to") or [])
    med_0109 = bool(situation.get("medically_separated_2001_2009"))
    low_rating = bool(situation.get("dod_rating_20_or_less"))
    char = (situation.get("discharge_char") or "").strip().lower() or None

    # Liberal consideration is about discharge-CHARACTERIZATION upgrades tied to
    # PTSD/TBI/mental-health/MST — not a standalone RE-code or clerical fix.
    liberal_applies = bool(related & _LIBERAL) and bool(goals & _DRB_GOALS)
    liberal = {
        "applies": liberal_applies,
        "note": _LIBERAL_NOTE if liberal_applies else "",
    }

    base = {
        "liberal_consideration": liberal,
        "vso_referral": _VSO,
        "legal_aid_referral": _LEGAL_AID,
        "disclaimer": _DISCLAIMER,
        "character_of_discharge_note": None,
        "also_consider": [],
        "warnings": [],
    }

    # Nothing selected yet — guide, don't route.
    if not goals:
        return {
            **base,
            "routed": False,
            "board": None, "board_full": None, "form": None, "form_title": None,
            "source": None, "deadline_note": None,
            "why": (
                "Tell us what you want to correct — a discharge upgrade, the narrative "
                "reason or RE code, an error on your DD-214 (name, dates, awards), or a "
                "low medical-separation rating — and we'll point you to the right board "
                "and form."
            ),
        }

    warnings: list[str] = []
    also: list[dict] = []
    cod_note = None

    # 1) PDBR is the specialized medical-rating lane.
    if "medical_rating" in goals and med_0109 and low_rating:
        board = _PDBR
        why = (
            "You were medically SEPARATED (not retired) between 2001 and 2009 with a DoD "
            "rating of 20% or less — exactly what the Physical Disability Board of Review "
            "re-examines. If the PDBR raises you to 30%+, the separation can convert to a "
            "medical RETIREMENT (with its benefits)."
        )
        if goals & _DISCHARGE_GOALS:
            also.append({
                "board": _BCMR["board"], "form": _BCMR["form"],
                "when": "Separately, to change your discharge characterization or narrative reason.",
            })

    # 2) Separation-related goals → DRB if it has a DRB-eligible goal, is in-window, and
    #    isn't a general court-martial / prior DRB denial; else BCMR.
    elif goals & _DISCHARGE_GOALS:
        has_drb_goal = bool(goals & _DRB_GOALS)
        drb_ok = (
            has_drb_goal
            and isinstance(years, int) and 0 <= years <= 15
            and not gcm and not drb_denied
        )
        if drb_ok:
            board = _DRB
            why = (
                "You're within 15 years of separation and your discharge wasn't from a "
                "general court-martial, so the Discharge Review Board can upgrade your "
                "characterization and change the narrative reason for separation on a "
                "DD Form 293."
            )
            if "re_code" in goals:
                why += (
                    " Your reenlistment (RE) code typically follows from the narrative "
                    "reason, so ask the DRB to correct it as part of the same request."
                )
            also.append({
                "board": _BCMR["board"], "form": _BCMR["form"],
                "when": "If the DRB denies you, or for corrections the DRB can't make.",
            })
        else:
            board = _BCMR
            reasons = []
            if not has_drb_goal and "re_code" in goals:
                reasons.append("a reenlistment (RE) code correction, which the BCMR handles")
            if gcm:
                reasons.append("a general court-martial discharge (the DRB can't change those)")
                warnings.append(
                    "The DRB cannot change a discharge given by a general court-martial — "
                    "the BCMR is the correct route."
                )
            if drb_denied:
                reasons.append("a prior DRB denial")
            if isinstance(years, int) and years > 15:
                reasons.append("more than 15 years since separation")
            if years is None or (isinstance(years, int) and years < 0):
                reasons.append("an unknown separation date (the BCMR has no firm cutoff)")
            because = "; ".join(reasons) or "your situation"
            why = (
                "The Board for Correction of Military/Naval Records is the right route "
                f"because of {because}. It can correct any error or injustice in your "
                "record — including discharge upgrades and RE codes — on a DD Form 149."
            )
        # A medical-rating need riding along that isn't PDBR-eligible is a SEPARATE BCMR
        # matter — surface it so it isn't silently dropped (unless BCMR is already the route).
        if "medical_rating" in goals and board["board"] != "BCMR":
            also.append({
                "board": _BCMR["board"], "form": _BCMR["form"],
                "when": "Separately, for your medical separation-vs-retirement determination and rating.",
            })
        # Character-of-discharge / VA note: only the barring characterizations (OTH/BCD),
        # or when the goal is a discharge upgrade. General (under honorable) does NOT
        # trigger the VA character-of-discharge bar, so it's excluded.
        if char in {"oth", "other_than_honorable", "bcd", "bad_conduct"} or "discharge_upgrade" in goals:
            cod_note = _COD_NOTE

    # 3) No discharge lane and not PDBR-eligible → BCMR (records error, or a
    #    medical-rating correction that falls outside the PDBR window).
    else:
        board = _BCMR
        if "medical_rating" in goals:
            why = (
                "The Board for Correction of Military/Naval Records reviews your medical "
                "separation — including whether you should have been medically RETIRED "
                "rather than separated, and the disability rating behind that decision — "
                "on a DD Form 149. (The specialized PDBR only covers medical separations "
                "from 2001–2009 rated 20% or less.)"
            )
        else:
            why = (
                "For fixing an error or injustice in your record — a wrong name, date, "
                "rank, missing award or decoration, a reenlistment (RE) code, or an "
                "administrative mistake — the Board for Correction of Military/Naval "
                "Records is the route, on a DD Form 149."
            )

    return {
        **base,
        "routed": True,
        "board": board["board"],
        "board_full": board["board_full"],
        "form": board["form"],
        "form_title": board["form_title"],
        "source": board["source"],
        "why": why,
        "deadline_note": _deadline_note(board["board"], years),
        "character_of_discharge_note": cod_note,
        "also_consider": also,
        "warnings": warnings,
    }
