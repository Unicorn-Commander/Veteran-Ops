"""Officer rank / promotion-correction analyzer — PURE, deterministic, no clock.

Some veterans separate or medically retire holding a lower grade than their
time-in-grade would ordinarily have earned. The classic case is an Army officer
who stayed a Second Lieutenant (2LT / O-1) well past the point where promotion to
First Lieutenant (1LT / O-2) is fully-qualified and essentially automatic. If the
record never reflects a promotion that should have happened, that can be an
administrative ERROR a correction board (BCMR, DD Form 149) can fix — and because
retired grade drives retired pay, fixing it can matter.

This engine reasons about time-in-grade against the governing Army rules and
returns an OPPORTUNITY assessment with a candor level, never a promise. It does not
promote anyone, does not assert entitlement, and does not file anything. The board
decides. Rules encoded (Army / DOPMA):

- 2LT → 1LT (O-1 → O-2): a FULLY-QUALIFIED (non-competitive) promotion. Standard
  time-in-grade is 18 months; a qualified officer is promoted on schedule. Staying a
  2LT far beyond 18 months is the strong records-error signal. (10 U.S.C. §619;
  AR 600-8-29.)
- 1LT → CPT (O-2 → O-3): a COMPETITIVE, board-SELECTED promotion — minimum ~2 years
  time-in-grade as a 1LT and ~4 years commissioned service, but the board picks the
  best-qualified; the board does not promote you just for serving the time. A
  records correction can only fix a clear error (e.g. you were SELECTED but the
  promotion was never executed), not substitute for a board that never chose you.
  The Captain's Career Course is normally expected. This lane is weak absent a
  documented selection.
- Retired grade (10 U.S.C. §1370): an officer generally retires in the highest grade
  in which they served satisfactorily. Correcting an owed-but-missed promotion can
  raise the retired grade — which is why this is worth pursuing.

Educational self-help only. Not legal advice, not an accredited representative.
"""

from __future__ import annotations

from datetime import date

# Army time-in-grade thresholds (months). Sourced from 10 U.S.C. §619 / AR 600-8-29.
_TIG_2LT_TO_1LT_MONTHS = 18
_TIG_1LT_TO_CPT_MONTHS = 24

_BCMR_FORM = "DD Form 149"
_BCMR_FORM_TITLE = "Application for Correction of Military Record"
_BCMR_BOARD = "Army Board for Correction of Military Records (ABCMR)"


def _parse(d: str | None) -> date | None:
    """Lenient ISO-date parse; returns None on anything unusable (no exceptions)."""
    if not d:
        return None
    s = str(d).strip()
    if not s:
        return None
    # Accept a bare year or year-month by padding to the first of the period.
    parts = s.split("-")
    try:
        if len(parts) == 1:
            return date(int(parts[0]), 1, 1)
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _months_between(start: date | None, end: date | None) -> int | None:
    """Whole months from start to end, or None if either is missing / end precedes start."""
    if start is None or end is None:
        return None
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months if months >= 0 else None


def _fmt_duration(months: int | None) -> str:
    if months is None:
        return "an unknown length of time"
    years, rem = divmod(months, 12)
    bits = []
    if years:
        bits.append(f"{years} year{'s' if years != 1 else ''}")
    if rem or not years:
        bits.append(f"{rem} month{'s' if rem != 1 else ''}")
    return " ".join(bits)


_VSO = (
    "A VA-accredited Veterans Service Officer (VFW, DAV, The American Legion, or your "
    "state/county veterans office) can help you file a records correction for free."
)
_LEGAL_AID = (
    "Free legal help exists for records corrections: law-school veterans clinics, the "
    "National Veterans Legal Services Program (NVLSP), and similar nonprofits. You "
    "never have to pay to correct your record."
)
_DISCLAIMER = (
    "This is educational self-help, not legal advice. Rating Raider is not a lawyer or "
    "an accredited representative, does not promote anyone, and does not file or decide "
    "anything — the Army Board for Correction of Military Records does. Promotion rules "
    "have exceptions (branch, component, competitive category, promotion holds); "
    "confirm your specific situation with a VSO or a free veterans legal clinic."
)


def _non_army_note(branch: str | None) -> str | None:
    b = (branch or "").strip().lower()
    if b and b not in ("army", "usa", "u.s. army", "army national guard", "arng", "army reserve", "usar"):
        return (
            f"These thresholds are the ARMY officer rules. You listed {branch}. The "
            "other services follow the same DOPMA framework with similar time-in-grade "
            "(18 months O-1→O-2), but confirm your service's board and specifics."
        )
    return None


def analyze_rank(facts: dict) -> dict:
    """facts → a promotion-correction opportunity assessment (the RankAnalysisOut dict).

    Keys used: commission_date, date_of_rank_2lt, promoted_to_1lt[bool],
    date_of_rank_1lt, separation_date, promoted_to_capt[bool], medically_retired[bool],
    selected_for_promotion[str|None: "1lt"/"capt"], completed_captains_career_course[bool],
    branch[str|None]. All dates ISO strings; everything optional.
    """
    commission = _parse(facts.get("commission_date"))
    dor_2lt = _parse(facts.get("date_of_rank_2lt")) or commission
    dor_1lt = _parse(facts.get("date_of_rank_1lt"))
    separation = _parse(facts.get("separation_date"))
    promoted_1lt = bool(facts.get("promoted_to_1lt"))
    promoted_capt = bool(facts.get("promoted_to_capt"))
    med_retired = bool(facts.get("medically_retired"))
    selected = (facts.get("selected_for_promotion") or "").strip().lower() or None
    has_ccc = bool(facts.get("completed_captains_career_course"))
    branch = facts.get("branch")

    findings: list[dict] = []

    # Time as a 2LT: from the 2LT date-of-rank (or commission) to promotion to 1LT if
    # it happened, otherwise to separation.
    tig_2lt_end = dor_1lt if (promoted_1lt and dor_1lt) else separation
    tig_2lt = _months_between(dor_2lt, tig_2lt_end)

    # ── Finding 1: 2LT → 1LT (the strong lane) ───────────────────────────────
    if not promoted_1lt:
        if tig_2lt is not None and tig_2lt >= _TIG_2LT_TO_1LT_MONTHS:
            findings.append({
                "grade_from": "2LT (O-1)",
                "grade_to": "1LT (O-2)",
                "strength": "strong",
                "headline": (
                    f"Your record shows you held 2LT for {_fmt_duration(tig_2lt)} without a "
                    "promotion to 1LT."
                ),
                "reasoning": (
                    "Promotion from Second Lieutenant to First Lieutenant is fully "
                    "qualified and essentially automatic at 18 months in grade for an "
                    f"officer in good standing (10 U.S.C. §619). Holding 2LT for "
                    f"{_fmt_duration(tig_2lt)} — well past that point — with no promotion "
                    "on record is exactly the kind of administrative error the board can "
                    "correct, UNLESS a promotion hold (a flag, a referred evaluation, a "
                    "pending investigation, or non-selection paperwork) explains it. Check "
                    "your records for any such flag first."
                ),
                "what_to_request": (
                    "Ask the ABCMR to correct your record to show promotion to 1LT (O-2) "
                    "effective the date you completed 18 months in grade, and to correct "
                    "any downstream effects (retired grade and pay, if you were retired at "
                    "2LT)."
                ),
            })
        elif tig_2lt is not None:
            findings.append({
                "grade_from": "2LT (O-1)",
                "grade_to": "1LT (O-2)",
                "strength": "weak",
                "headline": (
                    f"You held 2LT for about {_fmt_duration(tig_2lt)} — short of the "
                    "18-month point where 1LT promotion is normally automatic."
                ),
                "reasoning": (
                    "Below 18 months in grade there isn't yet a missed-promotion signal "
                    "for the board. If your dates are approximate and you were actually at "
                    "or past 18 months, re-check them — that changes the picture."
                ),
                "what_to_request": (
                    "No clear correction yet on the 2LT→1LT lane. Confirm your exact "
                    "date-of-rank and separation date."
                ),
            })
        else:
            findings.append({
                "grade_from": "2LT (O-1)",
                "grade_to": "1LT (O-2)",
                "strength": "needs_dates",
                "headline": "We can't assess the 2LT→1LT lane without your dates.",
                "reasoning": (
                    "Enter your 2LT date-of-rank (or commission date) and your separation "
                    "or retirement date. If the gap is 18 months or more with no promotion "
                    "on record, this is usually a correctable error."
                ),
                "what_to_request": "Provide the dates above to assess this.",
            })

    # ── Finding 2: 1LT → CPT (the weak / discretionary lane) ─────────────────
    if promoted_1lt and not promoted_capt:
        tig_1lt = _months_between(dor_1lt, separation)
        if selected == "capt":
            findings.append({
                "grade_from": "1LT (O-2)",
                "grade_to": "CPT (O-3)",
                "strength": "moderate",
                "headline": (
                    "You indicated you were SELECTED for Captain but the promotion was "
                    "never executed."
                ),
                "reasoning": (
                    "A board selection that was never carried out (because of separation, "
                    "a medical board, or an administrative gap) is a documentable error — "
                    "not the app's opinion. If your promotion selection list or orders show "
                    "you were selected, the ABCMR can be asked to execute or restore that "
                    "promotion. This turns on the selection paperwork, so gather it."
                ),
                "what_to_request": (
                    "Ask the ABCMR to correct your record to reflect the Captain promotion "
                    "you were selected for, effective the appropriate date, with the "
                    "selection documentation attached."
                ),
            })
        else:
            weak_bits = [
                "Promotion to Captain is COMPETITIVE and board-selected — the board picks "
                "the best-qualified; time in grade alone does not earn it.",
            ]
            if tig_1lt is not None and tig_1lt < _TIG_1LT_TO_CPT_MONTHS:
                weak_bits.append(
                    f"You also show only about {_fmt_duration(tig_1lt)} as a 1LT, under the "
                    "~2-year minimum time in grade."
                )
            if not has_ccc:
                weak_bits.append(
                    "You noted you did not complete the Captain's Career Course, which is "
                    "normally expected for the O-3 path."
                )
            findings.append({
                "grade_from": "1LT (O-2)",
                "grade_to": "CPT (O-3)",
                "strength": "weak",
                "headline": (
                    "Captain is a much higher bar — a records correction is unlikely here "
                    "unless you were actually selected."
                ),
                "reasoning": (
                    " ".join(weak_bits)
                    + " A correction board fixes clear errors; it cannot substitute its "
                    "judgment for a promotion board that never selected you. Pursue this "
                    "only if you have documentation that you WERE selected."
                ),
                "what_to_request": (
                    "No clear correction on the CPT lane without a documented selection. "
                    "If you believe you were selected, find the promotion list or orders "
                    "first."
                ),
            })

    strong = any(f["strength"] == "strong" for f in findings)
    moderate = any(f["strength"] == "moderate" for f in findings)

    if strong or moderate:
        overall = (
            "There is a promotion-correction worth pursuing. Because retired grade sets "
            "retired pay (10 U.S.C. §1370), correcting an owed-but-missed promotion can "
            "raise both — this is a concrete reason to file. The board decides; gather "
            "your promotion and separation records and file a DD Form 149."
        )
    elif any(f["strength"] == "needs_dates" for f in findings):
        overall = (
            "Enter your officer dates and we'll tell you whether your time in grade "
            "points to a missed promotion the board can correct."
        )
    else:
        overall = (
            "Based on what you entered, there isn't a clear promotion-correction signal "
            "right now. If any of your dates are approximate, re-check them — the "
            "18-month 2LT→1LT threshold is where this usually turns."
        )

    return {
        "findings": findings,
        "overall": overall,
        "retired_grade_note": (
            "If you were medically retired holding 2LT and the board corrects a missed "
            "1LT promotion, your RETIRED GRADE and retired pay may be recomputed at the "
            "higher grade. Ask the board to correct the retired grade as part of the same "
            "application, and send the corrected record to DFAS and VA afterward."
            if med_retired else
            "If a correction is granted after separation, ask the board to correct the "
            "grade shown on your DD-214 and any downstream records, then send the "
            "corrected DD-214 to VA."
        ),
        "board": _BCMR_BOARD,
        "form": _BCMR_FORM,
        "form_title": _BCMR_FORM_TITLE,
        "human_checklist": _rank_checklist(strong or moderate),
        "non_army_note": _non_army_note(branch),
        "vso_referral": _VSO,
        "legal_aid_referral": _LEGAL_AID,
        "disclaimer": _DISCLAIMER,
    }


def _rank_checklist(actionable: bool) -> list[str]:
    """The 'things only you can do' list — the human's part of the workflow."""
    base = [
        "Pull your Officer Record Brief (ORB)/personnel file and your DD-214 and confirm "
        "your exact date-of-rank for each grade and your separation/retirement date.",
        "Look for any promotion HOLD in your records — a flag (suspension of favorable "
        "actions), a referred officer evaluation, a pending investigation, or "
        "non-selection paperwork. If one exists, it likely explains the delay and the "
        "board will weigh it.",
        "Gather any promotion orders, promotion selection lists, or memoranda that "
        "mention you — these are the strongest evidence of a promotion that was due or "
        "selected.",
    ]
    if actionable:
        base += [
            "Complete DD Form 149 (Application for Correction of Military Record) — "
            "download the current version from the Army Review Boards Agency site.",
            "Write a short statement, in your own words, explaining the time-in-grade gap "
            "and asking the board to correct the grade (this tool drafts a starting point "
            "you edit).",
            "If you were retired, ask the board to correct your RETIRED GRADE and pay, and "
            "note it should be forwarded to DFAS and VA.",
            "Consider a free VSO or veterans legal clinic — this is exactly the kind of "
            "case they handle at no cost.",
            "File with the ABCMR, keep a full copy, and note the date you filed.",
        ]
    else:
        base += [
            "If your records show you were at or past 18 months as a 2LT with no promotion "
            "and no hold, re-run this — that's the correctable case.",
        ]
    return base
