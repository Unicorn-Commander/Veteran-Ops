"""Personal-statement builder — VA Form 21-4138 (Statement in Support of Claim).

Legal lane (BUILD-SPEC): a 21-4138 is the VETERAN'S OWN sworn statement — the
narrative the records don't show (an in-service event or stressor with dates and
places, why records may be missing, how the condition affects work and daily
life). Rating Raider FORMATS what the veteran writes into a clean, deterministic
21-4138-style statement they read, sign, and submit themselves. The veteran's
words go through VERBATIM — the app never reworders, never embellishes, never
fabricates a fact, never signs, and never files anything with VA. A VA-accredited
VSO can help for free.

Distinct from the symptom-log export (that one is symptom-derived, assembled from
logged entries); THIS is free-form narrative the veteran authors.

TWO paths:
  * POST /draft  — PURE TEMPLATE. Formats the veteran's own typed words verbatim. No LLM.
  * POST /assist — ASSISTED DRAFTING (statement_assist.py). Proposes a first-person DRAFT
    built ONLY from facts the veteran already recorded (their in-service event, notes,
    logged symptoms) + condition prompts to consider. Invents nothing; the veteran edits
    every line, adopts it as their own words, and attests before signing. Still never
    signs, never submits, never files — assisting the way a VSO does (propose + organize;
    the veteran authors + attests).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import statement_assist
from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, SymptomLogEntry
from ..schemas import StatementDraftIn, StatementDraftOut, StatementGuidanceOut

router = APIRouter(prefix="/statement", tags=["statement"])

FORM = "VA Form 21-4138"
FORM_TITLE = "Statement in Support of Claim"
FORM_URL = "https://www.va.gov/find-forms/about-form-21-4138/"

DISCLAIMER = (
    "This is a draft prepared FOR YOUR REVIEW AND SIGNATURE — the words are "
    "yours, and Rating Raider formats them without rewording, adding, or "
    "changing any fact. A Statement in Support of Claim (VA Form 21-4138) is "
    "your own account of what happened and how it affects you; it carries "
    "weight when it is specific, first-person, and true. Rating Raider never "
    "signs it and never files it for you — you read it over, sign and date it, "
    "and submit it (or hand it to your representative). A VA-accredited "
    "Veterans Service Officer (VFW, DAV, The American Legion, or your "
    "state/county veterans office) can help you file it for free."
)

# What a strong personal statement covers — the veteran's own first-person account.
GUIDANCE_PROMPTS = [
    "The specific event or stressor — what happened, with the dates and places "
    "as close as you can pin them down (e.g. 'in March 2004, at Camp Victory, "
    "our convoy was hit by an IED').",
    "What you personally experienced — what you saw, heard, felt, and did, in "
    "the first person and in your own words.",
    "Why records may be missing — if there's no paperwork for the event or a "
    "gap in your file, explain why (never reported it, records lost, treated in "
    "the field, told to 'tough it out').",
    "How the condition affects your work — days missed, tasks you can no longer "
    "do, jobs you've lost or had to change because of it.",
    "How it affects your daily life — sleep, relationships, driving, crowds, "
    "concentration, the things you used to do and can't anymore.",
    "Be specific, not general — 'I wake up three or four nights a week soaked in "
    "sweat' says far more than 'I don't sleep well.'",
]

# How to write it so it carries weight — true, specific, first-person, signed.
GUIDANCE_TIPS = [
    "Tell the truth — only what actually happened and what you actually "
    "experienced. A statement that overreaches can hurt your claim more than it "
    "helps.",
    "Be specific — dates, places, names, and frequency wherever you can. "
    "Concrete details are far more persuasive than 'always' or 'a lot.'",
    "Write in the first person — this is YOUR account. 'I remember,' 'I "
    "experienced,' 'I still.' Plain language, your own voice.",
    "Stick to what you know first-hand — what you lived through and how it "
    "affects you. You don't need medical terms or a diagnosis to describe your "
    "own symptoms.",
    "Give dates and places for the event — even approximate ('sometime in the "
    "summer of 2005') is better than leaving it out.",
    "Sign and date it — an unsigned statement isn't evidence. Read every line, "
    "make sure it's all true and in your own words, then sign and date it.",
]

# Reminders that ride along with every generated draft.
DRAFT_GUIDANCE = [
    "Read every line — this is your sworn statement. Make sure every fact is "
    "true and every sentence is how you'd actually say it.",
    "Add dates, places, and specific examples wherever the draft is vague — the "
    "more concrete, the stronger.",
    "Delete anything that isn't accurate or that you're not sure about. Only "
    "keep what you know first-hand to be true.",
    "When it reads true and complete, print it, sign and date the signature "
    "block, then submit it with your claim (or give it to your VSO).",
]


@router.get("/guidance", response_model=StatementGuidanceOut)
async def guidance(uid: str = Depends(current_user_id)) -> StatementGuidanceOut:
    """What makes a strong 21-4138 Statement in Support of Claim. The words stay
    the veteran's — this is only guidance. Deterministic, no DB, no LLM."""
    return StatementGuidanceOut(
        form=FORM,
        form_title=FORM_TITLE,
        form_url=FORM_URL,
        prompts=GUIDANCE_PROMPTS,
        tips=GUIDANCE_TIPS,
        disclaimer=DISCLAIMER,
    )


def _render_statement(payload: StatementDraftIn) -> str:
    """Deterministically format the veteran's OWN words into a 21-4138-style
    statement. The `statement` body goes through VERBATIM — no rewording, no
    embellishment, no fabricated facts. The veteran reviews and signs it."""
    veteran = (payload.veteran_name or "").strip()
    condition = (payload.condition or "").strip()
    topic = payload.topic.strip()
    period = (payload.period or "").strip()
    body = payload.statement.strip()  # the veteran's own words — verbatim

    veteran_ref = veteran or "the undersigned veteran"

    # Opener — weaves in the topic/condition (and period, when given). This is
    # framing only; the substance is the veteran's verbatim body below.
    subject = topic
    if condition and condition.lower() not in topic.lower():
        subject = f"{topic} ({condition})"
    opener = (
        f"I, {veteran_ref}, am submitting this statement in support of my "
        f"claim regarding {subject}"
    )
    if period:
        opener += f", covering {period}"
    opener += "."

    # Truthfulness attestation — the veteran certifies their own account.
    attestation = (
        "I certify that the statements above are true and correct to the best "
        "of my knowledge and belief. These are my own words, describing what I "
        "personally experienced and know first-hand."
    )

    return f"""# Statement in Support of Claim

**{FORM} — {FORM_TITLE}**

**Veteran:** {veteran or "____________________________"}
**Regarding:** {subject}

{opener}

## My statement

{body}

## Certification

{attestation}

---

**Signature:** ______________________________________    **Date:** ________________

**Printed name:** {veteran or "____________________________"}
"""


@router.post("/draft", response_model=StatementDraftOut)
async def draft(
    payload: StatementDraftIn, uid: str = Depends(current_user_id)
) -> StatementDraftOut:
    """Format the veteran's own words into a 21-4138-style draft they review,
    sign, and submit. Deterministic; verbatim body; never auto-submitted."""
    return StatementDraftOut(
        form=FORM,
        form_title=FORM_TITLE,
        statement_markdown=_render_statement(payload),
        guidance=DRAFT_GUIDANCE,
        disclaimer=DISCLAIMER,
    )


# ── Assisted drafting: PROPOSE + DRAFT from the veteran's OWN facts; they edit + attest ──
_ATTEST = (
    "This is a DRAFT built only from what you've already recorded — it may be incomplete "
    "or not quite right. Read every line, fix anything that isn't exactly true, add the "
    "details only you know, and delete anything you didn't experience. It becomes your "
    "sworn statement only when the words are yours and you sign it. Rating Raider never "
    "signs or files it for you."
)


class StatementAssistIn(BaseModel):
    condition_id: uuid.UUID | None = None
    condition: str | None = Field(default=None, max_length=255)


class StatementAssistOut(BaseModel):
    draft: str  # first-person draft from the veteran's facts ("" if nothing to draft from)
    prompts: list[str] = Field(default_factory=list)  # memory-jogger questions to consider
    has_facts: bool
    attestation: str
    disclaimer: str


@router.post("/assist", response_model=StatementAssistOut)
async def assist(
    payload: StatementAssistIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> StatementAssistOut:
    """Assisted drafting — proposes a first-person draft from the veteran's OWN recorded
    facts (their in-service event, condition notes, logged symptoms) plus condition
    prompts to consider. The veteran edits every line and adopts + attests it as their
    own. Invents nothing; never signs or files. Local model; degrades to prompts-only."""
    user_uuid = uuid.UUID(uid)
    cond: ClaimedCondition | None = None
    if payload.condition_id is not None:
        cond = (
            await db.execute(
                select(ClaimedCondition).where(
                    ClaimedCondition.user_id == user_uuid,
                    ClaimedCondition.id == payload.condition_id,
                )
            )
        ).scalar_one_or_none()
    elif payload.condition:
        cond = (
            await db.execute(
                select(ClaimedCondition).where(
                    ClaimedCondition.user_id == user_uuid,
                    ClaimedCondition.name.ilike(payload.condition.strip()),
                )
            )
        ).scalars().first()

    name = cond.name if cond else (payload.condition or "")
    entries: list[dict] = []
    if cond is not None:
        rows = (
            await db.execute(
                select(SymptomLogEntry)
                .where(
                    SymptomLogEntry.user_id == user_uuid,
                    SymptomLogEntry.condition_id == cond.id,
                )
                .order_by(SymptomLogEntry.entry_date.desc())
                .limit(12)
            )
        ).scalars().all()
        entries = [
            {
                "entry_date": e.entry_date.isoformat() if e.entry_date else None,
                "symptoms": e.symptoms,
                "severity": e.severity,
                "functional_impact": e.functional_impact,
            }
            for e in rows
        ]

    facts = {
        "condition_name": name,
        "in_service_event": cond.in_service_event if cond else None,
        "notes": cond.notes if cond else None,
        "symptom_entries": entries,
    }
    has_facts = bool(facts["in_service_event"] or facts["notes"] or entries)
    draft = await statement_assist.draft_from_facts(facts) if has_facts else ""
    prompts = await statement_assist.suggest_prompts(name) if name else []
    return StatementAssistOut(
        draft=draft, prompts=prompts, has_facts=has_facts,
        attestation=_ATTEST, disclaimer=DISCLAIMER,
    )
