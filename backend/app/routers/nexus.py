"""Nexus-letter builder — a medical-nexus opinion TEMPLATE (WAVE6 F2).

Legal lane (LOCKED CONTRACT): a nexus opinion — "at least as likely as not"
(50% or greater probability) that a condition is related to service — is the
linchpin of most VA claims, and it is a MEDICAL opinion. Only a qualified
treating PROVIDER can render and sign it. Rating Raider builds a deterministic
TEMPLATE the veteran brings to their provider; the opinion sentence is a
fill-in and the rationale is left BLANK for the provider to write in their own
clinical judgment. The app NEVER fabricates the opinion, never signs, never
submits. No LLM anywhere near this — pure template.

Grounded in: 38 CFR §3.303 (direct service connection) and §3.310 (secondary
service connection, including aggravation of a non-service-connected condition
by a service-connected one); the "at least as likely as not" (≥50%) benefit-of-
the-doubt standard that governs the nexus element (38 CFR §3.102).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import current_user_id
from ..schemas import (
    NexusDraftIn,
    NexusDraftOut,
    NexusGuidanceOut,
    NexusProviderBriefIn,
    NexusProviderBriefOut,
)

router = APIRouter(prefix="/nexus", tags=["nexus"])

WHAT_IT_IS = (
    "A nexus letter is a written medical opinion from a qualified provider that "
    "links your current diagnosed condition to your military service. It is the "
    'bridge — the "nexus" — between what happened in service and the disability '
    "you have today. This builder prepares a TEMPLATE for you to bring to your "
    "provider: it lays out the structure and the exact opinion language, but "
    "your provider fills in the medical rationale and signs it. Rating Raider "
    "cannot and does not supply the medical opinion itself."
)

WHY_IT_MATTERS = (
    "For most claims VA needs three things: a current diagnosis, an in-service "
    "event or exposure, and a medical link between them (38 CFR §3.303 for "
    "direct service connection; §3.310 for secondary conditions). That link is "
    "the nexus, and it is where claims are most often won or lost. A clear "
    'opinion using the "at least as likely as not" (50% or greater probability) '
    "standard, backed by a real clinical rationale, is often the single most "
    "decisive piece of evidence in the file."
)

# What the provider's opinion should cover — the anatomy of a strong nexus.
GUIDANCE_PROMPTS = [
    "A current diagnosis — the provider confirms the condition exists today and "
    "names it, ideally with the diagnostic criteria met.",
    "A review of the history — the provider states that they reviewed the "
    "veteran's relevant records, service history, and reported in-service event "
    "or exposure before forming the opinion.",
    'The "at least as likely as not" standard — the opinion must reach at least '
    "a 50% probability (50% or greater) that the condition is related to "
    "service. That is the legal threshold VA applies (38 CFR §3.102).",
    "A clear rationale — the heart of the letter: WHY, in the provider's "
    "clinical judgment, service is at least as likely as not the cause. It "
    "should cite clinical reasoning, the records, and medical literature or "
    "experience — not just restate the conclusion.",
    "For a secondary claim — the causal or aggravation link: whether the "
    "service-connected condition caused the new condition, or aggravated a "
    "condition beyond its natural progression (38 CFR §3.310).",
]

# How to make the letter carry weight — who writes it and what wins it.
GUIDANCE_TIPS = [
    "It must come from a qualified medical provider — a physician, or another "
    "licensed provider competent to diagnose and opine on the condition. VA "
    "weighs an opinion by the qualifications and reasoning behind it.",
    "The rationale is what wins or loses it — a bare conclusion (\"it is "
    'related") carries little weight. An opinion that explains the clinical '
    "reasoning, cites the records, and connects the dots is far more "
    "persuasive.",
    '"At least as likely as not" is the magic language — that exact phrase '
    "signals the 50%-or-greater standard VA applies. Weaker phrasing like "
    '"could be" or "possibly related" often falls short of the threshold.',
    "The provider signs it on their own letterhead — with their printed name, "
    "credentials, license number, and the date. An unsigned opinion is not "
    "usable evidence.",
    "Bring this template to your provider — you (or a free VA-accredited VSO) "
    "then submit the signed letter as evidence with your claim. Rating Raider "
    "never files it for you.",
]

DISCLAIMER = (
    "This is a TEMPLATE for a medical-nexus opinion — a scaffold to bring to a "
    "qualified treating provider, who completes the clinical rationale and "
    "signs it. It is NOT a medical opinion, and it is not medical or legal "
    "advice. Rating Raider and this app cannot render the medical opinion — the "
    'opinion (the "at least as likely as not" conclusion) and the rationale are '
    "the provider's to write and sign, in their own professional judgment, on "
    "their own letterhead. Service connection is governed by 38 CFR §3.303 "
    "(direct) and §3.310 (secondary); the benefit-of-the-doubt standard is at "
    "38 CFR §3.102. A VA-accredited Veterans Service Officer (VFW, DAV, The "
    "American Legion, or your state/county veterans office) can help you file "
    "this for free."
)

# Reminders that ride along with every generated template.
DRAFT_GUIDANCE = [
    "Bring this to your provider — the opinion sentence and the rationale are "
    "theirs to complete and sign. This template only lays out the structure and "
    "the language VA looks for.",
    "The rationale section is intentionally blank — that clinical reasoning, in "
    "the provider's own words, is what wins or loses the claim. Do not fill it "
    "in for them.",
    'Make sure the signed opinion uses the "at least as likely as not" (50% or '
    "greater) standard — that exact language is what VA weighs.",
    "The provider signs on their own letterhead with their credentials, license "
    "number, and date. Then you (or a free VA-accredited VSO) submit the signed "
    "letter as evidence — Rating Raider never files it for you.",
]


@router.get("/guidance", response_model=NexusGuidanceOut)
async def guidance(uid: str = Depends(current_user_id)) -> NexusGuidanceOut:
    """What a nexus letter is, why it decides claims, and what the provider's
    opinion should cover. Grounded in 38 CFR §3.303/§3.310 and the "at least as
    likely as not" (≥50%) standard. Deterministic, no DB, no LLM."""
    return NexusGuidanceOut(
        what_it_is=WHAT_IT_IS,
        why_it_matters=WHY_IT_MATTERS,
        prompts=GUIDANCE_PROMPTS,
        tips=GUIDANCE_TIPS,
        disclaimer=DISCLAIMER,
    )


def _render_letter(payload: NexusDraftIn) -> str:
    """Deterministically render the nexus-letter TEMPLATE from the inputs only.

    The opinion sentence is a FILL-IN and the rationale is left BLANK — the app
    never asserts a completed medical opinion. Handles direct vs secondary
    framing. No fabrication: the provider completes and signs it.
    """
    condition = payload.condition.strip()
    veteran = (payload.veteran_name or "").strip()
    dc = (payload.diagnostic_code or "").strip()
    claim_type = (payload.claim_type or "direct").strip().lower()
    is_secondary = claim_type == "secondary"
    event = (payload.in_service_event or "").strip()
    secondary_to = (payload.secondary_to or "").strip()
    clinical_summary = (payload.clinical_summary or "").strip()

    veteran_ref = veteran or "the veteran"
    dc_note = f" (diagnostic code {dc})" if dc else ""

    # Background paragraph — frames what the provider is being asked to opine on.
    # Direct vs secondary framing, weaving in the in-service event and, for
    # secondary claims, the service-connected primary condition.
    if is_secondary:
        primary_ref = secondary_to or "a service-connected condition"
        background = (
            f"{veteran_ref} is seeking VA disability compensation for "
            f"{condition}{dc_note} as a condition SECONDARY to {primary_ref}. "
            f"Secondary service connection (38 CFR §3.310) asks whether the "
            f"service-connected {primary_ref} either CAUSED {condition} or has "
            f"AGGRAVATED it beyond its natural progression. "
        )
        if event:
            background += (
                f"For context, the veteran also reports the following in service: "
                f"{event}. "
            )
        opinion_tail = (
            f"the veteran's service-connected {primary_ref} "
            f"(caused by / aggravated by the service-connected condition)"
        )
    else:
        background = (
            f"{veteran_ref} is seeking VA disability compensation for "
            f"{condition}{dc_note} on a DIRECT basis — that the condition was "
            f"incurred in or is otherwise related to military service (38 CFR "
            f"§3.303). "
        )
        if event:
            background += (
                f"The veteran reports the following relevant in-service event or "
                f"exposure: {event}. "
            )
        opinion_tail = "the veteran's active military service"

    background += (
        "You are asked, as a qualified medical provider, to review the relevant "
        "records and history and — if your clinical judgment supports it — to "
        "provide the medical opinion below in your own words and sign it. This "
        "letter is a template prepared by the veteran; the medical opinion and "
        "its rationale are yours alone to determine."
    )

    # The OPINION line is a FILL-IN sentence — bracketed choices + a blank the
    # provider completes. The app never states a completed conclusion.
    opinion_sentence = (
        f"It is my professional medical opinion that the veteran's {condition} "
        f"is at least as likely as not (50% or greater probability) "
        f"[caused by / related to / aggravated by] "
        f"______________________________________ ({opinion_tail})."
    )

    # Optional veteran-provided background — explicitly NOT the medical opinion.
    clinical_block = ""
    if clinical_summary:
        clinical_block = f"""## Background provided by the veteran (for the provider's consideration)

*The following is context supplied by the veteran. It is NOT a medical opinion
and is offered only to assist the provider's independent review.*

{clinical_summary}

"""

    return f"""# Medical Nexus Opinion Letter (TEMPLATE)

*[PROVIDER LETTERHEAD — provider name, practice, address, phone]*

**Date:** ________________

**To:** Department of Veterans Affairs

**RE: Nexus opinion for {veteran or "____________________________"} — {condition}**

## Background

{background}

{clinical_block}## [PROVIDER TO COMPLETE] — OPINION

*The provider completes the sentence below by selecting the applicable phrase
and stating the conclusion in their own professional judgment:*

{opinion_sentence}

## [PROVIDER TO COMPLETE] — RATIONALE

*State the clinical reasoning that supports the opinion above: the current
diagnosis, the records and history reviewed, and WHY, in your medical judgment,
the connection is at least as likely as not. This rationale is what carries the
opinion — please complete it in your own words.*

________________________________________________________________

________________________________________________________________

________________________________________________________________

---

**Provider signature:** ______________________________________    **Date:** ________________

**Printed name:** ______________________________________

**Credentials / title:** ______________________________________

**Medical license number & state:** ______________________________________
"""


@router.post("/draft", response_model=NexusDraftOut)
async def draft(
    payload: NexusDraftIn, uid: str = Depends(current_user_id)
) -> NexusDraftOut:
    """Render the deterministic nexus-letter TEMPLATE the veteran brings to their
    provider. The opinion is a fill-in and the rationale is blank — the app never
    asserts a completed medical opinion. No DB, no LLM, never auto-submitted."""
    condition = payload.condition.strip()
    return NexusDraftOut(
        title=f"Nexus opinion template — {condition}",
        letter_markdown=_render_letter(payload),
        guidance=DRAFT_GUIDANCE,
        disclaimer=DISCLAIMER,
    )


_ELEMENT_PLAIN = {
    "current_disability": "Current diagnosis meeting diagnostic criteria today",
    "in_service_event": "In-service event, injury, disease, or exposure",
    "nexus": "Medical link (“nexus”) between service (or a service-connected condition) and the current disability",
    "continuity": "Continuity of symptoms or chronicity after service",
    "secondary_link": "Causal or aggravation link from a service-connected primary (§3.310)",
}


def _provider_missing(payload: NexusProviderBriefIn) -> list[str]:
    out: list[str] = []
    for el in payload.missing_elements:
        key = (el or "").strip().lower().replace(" ", "_")
        out.append(_ELEMENT_PLAIN.get(key, el.strip()))
    if payload.prior_denial_notes and payload.prior_denial_notes.strip():
        out.append(
            "Address the prior denial rationale explicitly: "
            + payload.prior_denial_notes.strip()
        )
    if not out:
        claim = (payload.claim_type or "direct").strip().lower()
        if claim == "secondary":
            out = [
                _ELEMENT_PLAIN["current_disability"],
                _ELEMENT_PLAIN["secondary_link"],
                "Rationale that reaches “at least as likely as not” (≥50%)",
            ]
        else:
            out = [
                _ELEMENT_PLAIN["current_disability"],
                _ELEMENT_PLAIN["in_service_event"],
                _ELEMENT_PLAIN["nexus"],
                "Rationale that reaches “at least as likely as not” (≥50%)",
            ]
    return out


def _provider_scaffold(payload: NexusProviderBriefIn) -> str:
    condition = payload.condition.strip()
    claim = (payload.claim_type or "direct").strip().lower()
    secondary_to = (payload.secondary_to or "").strip()
    dc = (payload.diagnostic_code or "").strip()
    dc_note = f" (diagnostic code {dc})" if dc else ""
    if claim == "secondary" and secondary_to:
        opinion = (
            f"It is at least as likely as not (≥50% probability) that "
            f"{condition}{dc_note} is caused or aggravated beyond natural "
            f"progression by service-connected {secondary_to}."
        )
        theory = f"Secondary service connection under 38 CFR §3.310 to {secondary_to}."
    else:
        opinion = (
            f"It is at least as likely as not (≥50% probability) that "
            f"{condition}{dc_note} is related to military service."
        )
        theory = "Direct service connection under 38 CFR §3.303."
    return (
        f"# Provider nexus / DBQ brief — {condition}\n\n"
        f"**Theory to address:** {theory}\n\n"
        "## Opinion sentence (provider completes and signs)\n\n"
        f"> {opinion}\n\n"
        "## Clinical rationale (PROVIDER WRITES — leave blank until signed)\n\n"
        "_[Provider: state the records reviewed, diagnostic criteria met, and the "
        "clinical reasoning connecting the condition to service or to the "
        "service-connected primary. Do not use “could be” / “possibly.”]_\n\n"
        "---\n\n"
        "**Signature / credentials / license / date on provider letterhead**\n"
    )


@router.post("/provider-brief", response_model=NexusProviderBriefOut)
async def provider_brief(
    payload: NexusProviderBriefIn, uid: str = Depends(current_user_id)
) -> NexusProviderBriefOut:
    """Case-aware brief for the treating provider: what was historically missing
    plus a blank opinion scaffold. Never fills the medical opinion or signs."""
    condition = payload.condition.strip()
    records = [r.strip() for r in payload.records_to_review if r and r.strip()]
    if not records:
        records = [
            "Service treatment records (including any newly digitized STRs)",
            "Prior VA rating decisions / denial letters for this condition",
            "Current treatment notes and diagnostic workup",
            "Relevant private medical records the veteran brings",
        ]
    return NexusProviderBriefOut(
        condition=condition,
        title=f"Provider brief — {condition}",
        what_was_missing=_provider_missing(payload),
        records_to_review=records,
        opinion_scaffold=_provider_scaffold(payload),
        blank_rationale_prompt=(
            "Write the clinical rationale in your own professional judgment. "
            "Cite records reviewed and explain WHY the standard is met. "
            "Rating Raider never supplies this opinion."
        ),
        disclaimer=DISCLAIMER,
    )
