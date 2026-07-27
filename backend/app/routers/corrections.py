"""Military records corrections — route to the right board/form + assemble the
application packet. Stateless (pure engines on the submitted situation), auth-required.

Educational self-help: the veteran files with the military board (DRB/BCMR/PDBR),
not the VA; Rating Raider never files and never gives legal advice. Discharge-upgrade
paths route to free legal aid.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends

from ..corrections.draft import build_correction_packet
from ..corrections.rank import analyze_rank
from ..corrections.route import route_correction
from ..deps import current_user_id
from ..schemas import (
    CorrectionDraftIn,
    CorrectionPacketOut,
    CorrectionRouteOut,
    CorrectionSituationIn,
    RankAnalysisIn,
    RankAnalysisOut,
    RankGuidanceOut,
)

router = APIRouter(prefix="/corrections", tags=["corrections"])

_RANK_WHAT = (
    "Some officers separate or medically retire holding a lower grade than their time "
    "in grade would ordinarily have earned — most often a Second Lieutenant (2LT) who "
    "was never promoted to First Lieutenant (1LT) even though that promotion is "
    "essentially automatic at 18 months. If a promotion that should have happened isn't "
    "on your record, that can be an administrative ERROR a correction board can fix. "
    "Because your retired grade sets your retired pay, fixing it can matter."
)
_RANK_HOW = [
    "Enter your officer dates — commission, each date-of-rank, and your separation or "
    "retirement date.",
    "The analyzer compares your time in grade to the Army promotion rules and tells you "
    "whether there's a correctable missed promotion, and how strong the case is.",
    "For a solid case, it points you to the right board (ABCMR) and form (DD Form 149) "
    "and gives you a checklist of what only you can gather.",
    "You review, gather your records, sign, and file — or hand it to a free VSO. Rating "
    "Raider never promotes anyone and never files anything.",
]
_RANK_PROMPTS = [
    "When were you commissioned, and what was your date-of-rank as a 2LT?",
    "Were you ever promoted to 1LT? If so, on what date?",
    "When did you separate or retire?",
    "Were you ever selected for a promotion that was never carried out?",
]
_RANK_THRESHOLDS = [
    "2LT → 1LT (O-1→O-2): fully qualified, ~18 months in grade — the strong lane.",
    "1LT → CPT (O-2→O-3): competitive and board-SELECTED, ~2 years in grade — a "
    "correction only fixes a documented selection that wasn't executed, not a promotion "
    "you were never chosen for.",
    "Retired grade (10 U.S.C. §1370): correcting an owed promotion can raise your "
    "retired grade and pay.",
]
_RANK_DISCLAIMER = (
    "Educational self-help, not legal advice. Rating Raider does not promote anyone and "
    "does not file or decide anything — the Army Board for Correction of Military "
    "Records does. Promotion rules have exceptions (holds, flags, component, competitive "
    "category); confirm your situation with a VSO or a free veterans legal clinic."
)


@router.post("/route", response_model=CorrectionRouteOut)
async def route(
    situation: CorrectionSituationIn,
    _uid: str = Depends(current_user_id),
):
    """Which military board + form fits this correction (DRB / BCMR / PDBR)."""
    return CorrectionRouteOut(**route_correction(situation.model_dump()))


@router.post("/draft", response_model=CorrectionPacketOut)
async def draft(
    payload: CorrectionDraftIn,
    _uid: str = Depends(current_user_id),
):
    """Assemble the print-ready records-correction application packet."""
    packet = build_correction_packet(
        payload=payload.model_dump(),
        prepared_on=date.today().isoformat(),
    )
    return CorrectionPacketOut(**packet)


@router.get("/rank", response_model=RankGuidanceOut)
async def rank_guidance(_uid: str = Depends(current_user_id)):
    """What a promotion/rank correction involves and the time-in-grade thresholds."""
    return RankGuidanceOut(
        what_it_is=_RANK_WHAT,
        how_it_works=_RANK_HOW,
        prompts=_RANK_PROMPTS,
        thresholds=_RANK_THRESHOLDS,
        disclaimer=_RANK_DISCLAIMER,
    )


@router.post("/rank/analyze", response_model=RankAnalysisOut)
async def rank_analyze(
    facts: RankAnalysisIn,
    _uid: str = Depends(current_user_id),
):
    """Assess whether time-in-grade points to a missed promotion the board can correct.
    Pure/deterministic; no LLM; never asserts entitlement; nothing is filed."""
    return RankAnalysisOut(**analyze_rank(facts.model_dump()))
