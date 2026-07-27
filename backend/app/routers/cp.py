"""C&P (Compensation & Pension) exam companion — WAVE5 Feature 5.

Educational preparation for a veteran's C&P exam, per claimed condition. The
companion assembles, deterministically:

  * the veteran's own claimed conditions for a picker,
  * the DBQ the examiner most likely uses (reusing the same map_dbq +
    load_dbq_catalog path the gaps/packet endpoints use),
  * the §4 rating-criteria TIERS for the condition's diagnostic code — grounded
    in the KB rating_criteria cards via the EXACT retrieval packet.py uses (no
    reinvented retrieval, no LLM in this path), so the veteran can see what is
    actually being assessed,
  * fixed educational guidance: what to expect, how to describe symptoms
    HONESTLY (worst-day / frequency / duration / functional-impact framing),
    dos, and don'ts (chief among them: never exaggerate — it can invalidate the
    exam and cost credibility).

Legal lane, same as the whole app: educational self-help only, not medical or
legal advice; the examiner's findings drive the rating; a VA-accredited VSO can
help prepare for free.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analysis.gaps import map_dbq
from ..analysis.mapping import extract_tiers
from ..deps import current_user_id, get_db
from ..kb.store import _GENERIC_TERMS, load_dbq_catalog, retrieve_cards
from ..models import ClaimedCondition
from ..schemas import CpCompanionOut, CpConditionOut, CpCriteriaTierOut

router = APIRouter(prefix="/cp", tags=["cp"])


# ── Deterministic educational content (no LLM, no PII) ───────────────────────
_WHAT_TO_EXPECT = [
    "The examiner will confirm your identity and review your claim file and "
    "medical records before or during the exam.",
    "The exam is usually built around a Disability Benefits Questionnaire (DBQ) — "
    "the examiner works through its questions and measurements for your condition.",
    "Length varies: some exams take 15–20 minutes, others much longer, depending "
    "on the condition and what needs to be measured or discussed.",
    "It may be in person at a VA facility or a contracted clinic, or virtual by "
    "video — check your appointment letter for where and how.",
    "The examiner records what they observe and what you report; their findings, "
    "not this app, are what the VA uses to decide your rating.",
    "Arrive on time (or log in early for a virtual exam) and bring a photo ID.",
    "Bring a short written list of your symptoms, medications, and your worst days "
    "so you don't forget anything under pressure.",
]

_HOW_TO_DESCRIBE = [
    "Describe your WORST days and how often they happen — the VA rates the "
    "disabling picture over time, not just how you feel at that one appointment.",
    "Don't minimize on a good day. If you happen to feel better the morning of the "
    "exam, say so, and describe how bad it typically gets.",
    "Be concrete about FREQUENCY and DURATION: how many times a week or month, and "
    "how long each episode or flare-up lasts.",
    "Explain the FUNCTIONAL IMPACT: what the condition stops you from doing at work, "
    "at home, and in relationships — specific tasks you've had to give up or change.",
    "Mention flare-ups even if you're not having one at the exam — describe what "
    "triggers them, what they feel like, and how long they last.",
    "Use your own words and be specific with examples ('I can't stand more than "
    "10 minutes before the pain forces me to sit') rather than vague labels.",
    "Answer honestly. If you don't know or can't remember, say so — a guess that "
    "turns out wrong can undercut your credibility.",
]

_DOS = [
    "Be honest and consistent — your account should match your records and what "
    "you've told your own providers.",
    "Be specific: real examples, frequencies, and durations paint a clearer picture "
    "than general statements.",
    "Describe how the condition affects your daily life and ability to work "
    "(the functional impact).",
    "Mention flare-ups and your worst days, even if today happens to be a good day.",
    "Bring your symptom log, medication list, and any recent relevant records.",
    "Ask the examiner to clarify a question if you don't understand it.",
]

_DONTS = [
    "NEVER exaggerate or invent symptoms. Overstating can invalidate the exam, hurt "
    "your credibility, and damage your whole claim.",
    "Don't guess or speculate about medical causes or diagnoses — describe what you "
    "experience and let the evidence speak.",
    "Don't downplay or tough it out. Minimizing your symptoms leads to an exam that "
    "understates how the condition really affects you.",
    "Don't assume the examiner already knows your history — describe your symptoms "
    "even if you think they're in the file.",
    "Don't argue percentages or outcomes with the examiner; their job is to observe "
    "and document, and the rating decision comes later.",
]

_DISCLAIMER = (
    "This companion is educational self-help only — not medical or legal advice, "
    "and not a substitute for a VA-accredited representative. It explains what a "
    "C&P exam involves and how to describe your symptoms honestly; the examiner's "
    "findings, not this app, drive your rating. Never exaggerate. A VA-accredited "
    "VSO can help you prepare for free — Rating Raider organizes your information, "
    "a VSO can act on your behalf."
)


# ── Helpers ──────────────────────────────────────────────────────────────────
async def _owned_condition(
    db: AsyncSession, condition_id: uuid.UUID, uid: str
) -> ClaimedCondition:
    """Fetch the caller's condition or 404. RLS makes a wrong-owner id invisible
    in production; the explicit user_id filter is defense-in-depth (and the only
    isolation the SQLite test harness has)."""
    obj = (
        await db.execute(
            select(ClaimedCondition).where(
                ClaimedCondition.id == condition_id,
                ClaimedCondition.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found")
    return obj


async def _rating_criteria_tiers(
    db: AsyncSession, cond: ClaimedCondition
) -> list[CpCriteriaTierOut]:
    """The §4 rating tiers for the condition's diagnostic code, grounded in the KB
    rating_criteria cards. REUSES packet.py's retrieval EXACTLY: retrieve top-k
    rating_criteria cards for the condition name, prefer the condition's own DC,
    and keep only a card that is actually RELEVANT (its DC matches, or a
    meaningful name token appears) — retrieval always returns top-k of *something*,
    and showing the wrong criteria set is worse than showing none."""
    rows = await retrieve_cards(db, cond.name, k=4, card_type="rating_criteria")
    if cond.diagnostic_code:
        rows = sorted(rows, key=lambda r: r.diagnostic_code != cond.diagnostic_code)

    def _relevant(r) -> bool:
        if cond.diagnostic_code and r.diagnostic_code == cond.diagnostic_code:
            return True
        name_tokens = {
            t
            for t in (cond.name or "").lower().split()
            if len(t) >= 4 and t not in _GENERIC_TERMS
        }
        card_text = f"{r.title} {r.content}".lower()
        return any(t in card_text for t in name_tokens)

    rows = [r for r in rows if _relevant(r)]
    if not rows:
        return []

    tiers = extract_tiers(rows[0].data)
    # CpCriteriaTierOut.criteria is a list of phrases; a card tier stores one
    # authored criteria string — surface it as a single phrase, dropping empties.
    return [
        CpCriteriaTierOut(
            percent=t["percent"],
            criteria=[t["criteria"]] if t.get("criteria") else [],
        )
        for t in tiers
    ]


def _condition_out(cond: ClaimedCondition) -> CpConditionOut:
    return CpConditionOut(
        id=cond.id,
        name=cond.name,
        diagnostic_code=cond.diagnostic_code,
        claim_type=cond.claim_type,
    )


# ── GET /cp/conditions ───────────────────────────────────────────────────────
@router.get("/conditions", response_model=list[CpConditionOut])
async def list_conditions(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The caller's claimed conditions for the companion's picker. RLS scopes this
    in production; the explicit user_id filter is defense-in-depth."""
    rows = (
        await db.execute(
            select(ClaimedCondition)
            .where(ClaimedCondition.user_id == uuid.UUID(uid))
            .order_by(ClaimedCondition.created_at.desc())
        )
    ).scalars().all()
    return [_condition_out(c) for c in rows]


# ── GET /cp/{condition_id} ───────────────────────────────────────────────────
@router.get("/{condition_id}", response_model=CpCompanionOut)
async def get_companion(
    condition_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Assemble the educational C&P companion for one of the caller's conditions."""
    cond = await _owned_condition(db, condition_id, uid)

    dbq = cond.dbq_form or map_dbq(cond.name, cond.body_system, load_dbq_catalog())
    rating_criteria = await _rating_criteria_tiers(db, cond)

    return CpCompanionOut(
        condition=_condition_out(cond),
        dbq=dbq,
        what_to_expect=list(_WHAT_TO_EXPECT),
        rating_criteria=rating_criteria,
        how_to_describe=list(_HOW_TO_DESCRIBE),
        dos=list(_DOS),
        donts=list(_DONTS),
        disclaimer=_DISCLAIMER,
    )
