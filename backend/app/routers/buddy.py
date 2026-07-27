"""Buddy-statement builder — VA Form 21-10210 (Lay/Witness Statement).

Legal lane (BUILD-SPEC): a buddy statement is LAY EVIDENCE the WITNESS writes,
reviews, and SIGNS in their own words. Rating Raider generates a plain,
deterministic 21-10210-style draft grounded ONLY in the inputs the veteran and
witness provide — it never fabricates observations, never signs for anyone, and
never submits anything to VA. A VA-accredited VSO can help for free.

Why this matters: lay evidence from someone who personally observed the veteran
is competent evidence VA must consider (38 CFR §3.159(a)(2); Layno v. Brown,
6 Vet. App. 465 (1994)). It's strongest when it's first-hand, specific, and
dated. No LLM anywhere near this — pure template.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import current_user_id
from ..schemas import (
    BuddyDraftIn,
    BuddyDraftOut,
    BuddyGuidanceOut,
    BuddySituationBriefIn,
    BuddySituationBriefOut,
)

router = APIRouter(prefix="/buddy", tags=["buddy"])

FORM = "VA Form 21-10210"
FORM_TITLE = "Lay/Witness Statement"
FORM_URL = "https://www.va.gov/find-forms/about-form-21-10210/"

DISCLAIMER = (
    "This is a draft prepared for the WITNESS to review, edit into their own "
    "words, and sign — Rating Raider never writes, signs, or submits a "
    "statement for anyone. A buddy/lay statement is competent evidence VA must "
    "consider when the witness describes what they personally saw or "
    "experienced (38 CFR §3.159(a)(2); Layno v. Brown, 6 Vet. App. 465 "
    "(1994)). Only include things that are true and first-hand. A "
    "VA-accredited Veterans Service Officer (VFW, DAV, The American Legion, or "
    "your state/county veterans office) can help you file this for free."
)

# What a strong buddy statement covers — the witness's own first-hand knowledge.
GUIDANCE_PROMPTS = [
    "Who you are and how you know the veteran — your relationship and how long "
    "you've known them.",
    "What you personally saw, heard, or experienced — not opinions or "
    "diagnoses, just the concrete things you witnessed yourself.",
    "When it happened and how often — approximate dates, and whether it was a "
    "one-time event or something ongoing (e.g. 'about twice a week since 2019').",
    "Before-and-after service — if you knew the veteran before service, "
    "describe the change you saw afterward.",
    "Specific examples, not conclusions — instead of 'his knee is bad,' write "
    "'I saw him stop and grip a railing every time we took stairs.'",
    "How it affects daily life and work — missed events, tasks they can no "
    "longer do, help they now need.",
]

# How to write it so it carries weight — first-hand, dated, plain, signed.
GUIDANCE_TIPS = [
    "First-hand only: write what YOU witnessed. You don't need to be a doctor — "
    "lay observation of symptoms you can see or hear is competent evidence "
    "(38 CFR §3.159(a)(2); Layno v. Brown).",
    "Use dates and frequency wherever you can — 'since roughly March 2020,' "
    "'about three times a month' — specifics are far more persuasive than "
    "'a lot' or 'always.'",
    "Plain language in your own words — this is your account, not a legal brief. "
    "Don't guess at medical terms or diagnoses.",
    "Never exaggerate or invent anything — a statement that overreaches can hurt "
    "the claim more than help it. Only what's true and what you saw yourself.",
    "Sign and date it — an unsigned statement isn't evidence. Print it, read it "
    "over, edit anything that isn't in your own words, then sign.",
    "Attach it as evidence — the veteran (or their VSO) submits it with the "
    "claim on VA Form 21-10210. You don't file it for them.",
]

# Reminders that ride along with every generated draft.
DRAFT_GUIDANCE = [
    "This is a starting point — read every line and rewrite anything that isn't "
    "how you'd actually say it. It has to be YOUR words.",
    "Add dates, frequency, and specific examples wherever the draft is vague — "
    "the more concrete, the stronger.",
    "Delete anything you didn't personally witness or aren't sure is true.",
    "When it reads true and complete, print it, sign, and date the signature "
    "block — then give it to the veteran to submit with their claim.",
]


@router.get("/guidance", response_model=BuddyGuidanceOut)
async def guidance(uid: str = Depends(current_user_id)) -> BuddyGuidanceOut:
    """What makes a strong buddy/lay statement — grounded in 38 CFR
    §3.159(a)(2) and Layno v. Brown. Deterministic, no DB, no LLM."""
    return BuddyGuidanceOut(
        form=FORM,
        form_title=FORM_TITLE,
        form_url=FORM_URL,
        prompts=GUIDANCE_PROMPTS,
        tips=GUIDANCE_TIPS,
        disclaimer=DISCLAIMER,
    )


def _render_statement(payload: BuddyDraftIn) -> str:
    """Deterministic 21-10210-style statement markdown built ONLY from the
    inputs. No fabrication — the witness edits and signs it."""
    witness = payload.witness_name.strip()
    relationship = payload.witness_relationship.strip()
    veteran = (payload.veteran_name or "").strip()
    condition = (payload.condition or "").strip()
    period = (payload.period or "").strip()
    observations = payload.observations.strip()

    veteran_ref = veteran or "the veteran"
    # Opener: "I, <witness>, <relationship> of <veteran>, state the following"
    opener = f"I, {witness}, {relationship} of {veteran_ref}, state the following"
    if period:
        opener += f", based on what I personally observed {period}"
    opener += "."

    # Subject line weaves in the condition when given.
    if condition:
        subject = (
            f"This statement is offered in support of {veteran_ref}'s VA "
            f"disability compensation claim for {condition}."
        )
    else:
        subject = (
            f"This statement is offered in support of {veteran_ref}'s VA "
            "disability compensation claim."
        )

    # First-hand attestation — the legal weight of a lay statement.
    attestation = (
        "The above is based on my own first-hand knowledge — things I "
        "personally saw, heard, or experienced. I am competent to describe "
        "what I observed. I have not exaggerated anything, and everything in "
        "this statement is true to the best of my knowledge and belief."
    )

    return f"""# Lay/Witness Statement in Support of a Claim

**{FORM} — {FORM_TITLE}**

**Witness:** {witness}
**Relationship to the veteran:** {relationship}
**Veteran:** {veteran or "____________________________"}

{subject}

{opener}

## What I observed

{observations}

## First-hand knowledge

{attestation}

---

**Signature:** ______________________________________    **Date:** ________________

**Printed name:** {witness}
"""


@router.post("/draft", response_model=BuddyDraftOut)
async def draft(
    payload: BuddyDraftIn, uid: str = Depends(current_user_id)
) -> BuddyDraftOut:
    """Render a 21-10210-style draft the witness reviews, edits, and signs.
    Deterministic; grounded only in the inputs. Never auto-submitted."""
    return BuddyDraftOut(
        form=FORM,
        form_title=FORM_TITLE,
        statement_markdown=_render_statement(payload),
        guidance=DRAFT_GUIDANCE,
        disclaimer=DISCLAIMER,
    )


# Case-aware situation brief — bullets the witness hits in THEIR own words.
# Never fabricates observations; only structures what the veteran asked for.
_DEFAULT_HIT_THEMES = (
    "how you know the veteran and for how long",
    "what you personally saw change after service or after the condition worsened",
    "concrete examples (stairs, work tasks, social events, sleep, pain flares)",
    "how often and roughly when (dates/frequency beat vague words)",
    "how it limits daily life and work — missed shifts, help needed, abandoned hobbies",
)

_AVOID = (
    "Medical diagnoses or guessing what a doctor would say",
    "Legal conclusions (“this proves service connection”)",
    "Anything you did not personally witness or are unsure of",
    "Exaggeration — overreach hurts more than it helps",
)


def _situation_hit_list(payload: BuddySituationBriefIn) -> list[str]:
    condition = payload.condition.strip()
    veteran = (payload.veteran_name or "the veteran").strip()
    period = (payload.period or "").strip()
    hits: list[str] = [
        f"State who you are and your relationship to {veteran}.",
        f"Describe only what you personally observed about {condition}"
        + (f" {period}." if period else "."),
    ]
    themes = [t.strip() for t in payload.themes if t and t.strip()]
    if themes:
        for t in themes[:8]:
            hits.append(f"If true and first-hand, cover: {t}.")
    else:
        for t in _DEFAULT_HIT_THEMES:
            hits.append(f"If true and first-hand, cover: {t}.")
    for fact in payload.known_facts[:12]:
        f = (fact or "").strip()
        if f:
            hits.append(
                f"Only if you personally saw it: the veteran notes “{f}” — "
                "put it in your own words or drop it."
            )
    hits.append(
        "End with a short first-hand attestation and sign/date the statement yourself."
    )
    return hits


def _situation_outline(payload: BuddySituationBriefIn) -> str:
    condition = payload.condition.strip()
    veteran = (payload.veteran_name or "the veteran").strip()
    period = (payload.period or "the period I know about").strip()
    return (
        f"# Buddy situation brief — points to hit (your words only)\n\n"
        f"**Condition:** {condition}\n"
        f"**Veteran:** {veteran}\n"
        f"**Period focus:** {period}\n\n"
        "Use this as a checklist while YOU write. Do not copy medical language. "
        "Only include first-hand observations.\n\n"
        "## Suggested structure\n"
        "1. Who I am / how I know the veteran\n"
        "2. What I saw before vs after (or as the condition worsened)\n"
        "3. Specific examples with approximate dates/frequency\n"
        "4. Impact on work and daily life I personally witnessed\n"
        "5. Sign and date\n"
    )


@router.post("/situation-brief", response_model=BuddySituationBriefOut)
async def situation_brief(
    payload: BuddySituationBriefIn, uid: str = Depends(current_user_id)
) -> BuddySituationBriefOut:
    """Case-aware bullet list for a lay/witness statement. Deterministic.
    The witness still writes, edits, and signs in their own words."""
    return BuddySituationBriefOut(
        condition=payload.condition.strip(),
        form=FORM,
        form_url=FORM_URL,
        hit_list=_situation_hit_list(payload),
        avoid=list(_AVOID),
        starter_outline=_situation_outline(payload),
        disclaimer=DISCLAIMER,
    )
