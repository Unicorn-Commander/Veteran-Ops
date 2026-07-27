"""Dependency workflow — respond to a VA action on your dependents (VA Form 21-686c).

Two situations this covers:
  • You want to ADD or RE-ADD a dependent (a spouse, child, or dependent parent) —
    e.g. the VA removed a spouse and you need them back on your award.
  • The VA proposed or made a change REMOVING a dependent and you want to respond.

Adding or removing a dependent CHANGES your monthly compensation, so it is a filing
action with real money attached. Rating Raider organizes the situation and formats a
21-686c worksheet + a plain-language cover statement the veteran REVIEWS, SIGNS, and
FILES (or hands to a VSO). It never files anything, never renders a legal opinion,
and never collects SSNs or VA file numbers — those go on the signed form only.

Legal lane: this is educational self-help. Because dependency decisions affect pay
and appeal rights, a free VA-accredited VSO is the right partner. No LLM — pure
template. Due-process / effective-date statements are general and reg-anchored; the
veteran's letter should reflect their own facts.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import current_user_id
from ..schemas import (
    DependencyForm,
    DependencyGuidanceOut,
    DependencyWorksheetIn,
    DependencyWorksheetOut,
)

router = APIRouter(prefix="/dependency", tags=["dependency"])

FORM = "VA Form 21-686c"
FORM_TITLE = "Application Request to Add and/or Remove Dependents"

WHAT_IT_IS = (
    "Your VA disability compensation includes extra money for qualifying dependents "
    "(a spouse, dependent children, and in some cases a dependent parent) once your "
    "combined rating is 30% or higher. When your family changes — or when the VA "
    "changes your dependents on its own — you keep your award correct by filing VA "
    "Form 21-686c. This tool helps you organize that filing and write a clear cover "
    "statement; you review it, sign it, and submit it."
)

ADD_PATH = [
    "Add or re-add the dependent on VA Form 21-686c, listing the dependent and the "
    "event that qualifies them (a marriage, a birth or adoption, or a dependent "
    "parent's circumstances).",
    "Attach proof — a marriage certificate for a spouse, a birth certificate for a "
    "child, and VA Form 21-674 for a child aged 18–23 who is in school.",
    "Effective date matters: reporting the change within one year of the event "
    "generally lets the added compensation reach back to the event date, so don't "
    "wait once you have the paperwork.",
    "If a dependent was removed and you believe that was an error, ADD them back "
    "AND ask the VA to correct the removal (a Supplemental Claim on the removal "
    "decision) so any pay taken back can be restored — a VSO can pick the right lane.",
]

REMOVAL_PATH = [
    "If the VA sent a letter PROPOSING to reduce your pay by removing a dependent, "
    "you have a due-process window to respond BEFORE it takes effect — send your "
    "evidence and, if you want a hearing, request one within the time the letter "
    "states.",
    "If your evidence shows the dependent still qualifies (for example, you are "
    "still married), lay that out plainly and attach the proof.",
    "If the removal already happened and was correct (a divorce, a child aging out), "
    "no response is needed — but make sure your other dependents are still listed.",
    "If the removal already happened and was WRONG, file a Supplemental Claim (VA "
    "Form 20-0995) with new evidence to restore the dependent and any pay owed.",
]

TIMELINE_NOTE = (
    "When the VA proposes to reduce your compensation, it must give you advance "
    "notice and a chance to respond before the reduction takes effect (38 CFR "
    "§3.105(h)). The letter you received states your exact deadlines — typically a "
    "window to submit evidence and a separate window to request a predetermination "
    "hearing. Read those dates carefully and respond within them; a free VSO can "
    "help you meet the deadline. If the reduction has already happened, you can "
    "still add the dependent going forward and dispute the decision."
)

EVIDENCE = [
    "VA Form 21-686c, completed and signed",
    "Marriage certificate (to add or keep a spouse)",
    "Birth or adoption certificate (for a child)",
    "VA Form 21-674 (for a child aged 18–23 attending school)",
    "A copy of the VA letter you're responding to, if this is about a removal",
    "A short statement in your own words explaining the situation (this worksheet "
    "drafts one you can attach)",
]

GUIDANCE_PROMPTS = [
    "Who is the dependent — their full name and relationship to you (spouse, child, "
    "stepchild, or dependent parent).",
    "The event and its date — the marriage, birth, adoption, or (for a removal) what "
    "the VA changed and when.",
    "If you're responding to a VA letter: what the letter said, the date on it, and "
    "the deadline it gave you.",
    "In your own words: what happened and why the dependent should be on your award "
    "(for example, 'We were married on ___ and remain married; the removal was an "
    "error').",
]

DRAFT_GUIDANCE = [
    "Read every line — this becomes part of a filing that changes your pay. Make "
    "sure every name, date, and fact is exactly right.",
    "Do NOT write Social Security or VA file numbers on this worksheet — put those "
    "only on the signed official form.",
    "Attach your proof — a marriage or birth certificate carries far more weight "
    "than the statement alone.",
    "If you're responding to a proposed removal, file BEFORE the deadline in your VA "
    "letter. When it reads true and complete, sign and submit VA Form 21-686c (or "
    "hand it to your VSO) — Rating Raider never files it for you.",
]

VSO_NOTE = (
    "Dependency changes affect your pay and your effective date, and a wrongful "
    "removal can involve an overpayment or a debt. A free VA-accredited VSO (VFW, "
    "DAV, The American Legion, or your state/county veterans office) can file the "
    "21-686c with you and make sure the effective date and any restored pay are right."
)

DISCLAIMER = (
    "Adding or removing a dependent changes your VA compensation — it is a filing "
    "that affects your pay, so review it carefully. Rating Raider organizes your "
    "answers and drafts a worksheet and cover statement FOR YOUR REVIEW AND "
    "SIGNATURE; it does not decide your dependents, does not give legal advice, and "
    "never files anything for you. Deadlines on any VA letter you received are real — "
    "meet them. A free VA-accredited VSO can help."
)

_FORMS = [
    DependencyForm(
        form="VA Form 21-686c",
        title="Application Request to Add and/or Remove Dependents",
        url="https://www.va.gov/find-forms/about-form-21-686c/",
        who="you",
    ),
    DependencyForm(
        form="VA Form 21-674",
        title="Request for Approval of School Attendance (child aged 18–23)",
        url="https://www.va.gov/find-forms/about-form-21-674/",
        who="you (with the school)",
    ),
    DependencyForm(
        form="VA Form 20-0995",
        title="Supplemental Claim (to correct a wrongful removal)",
        url="https://www.va.gov/find-forms/about-form-20-0995/",
        who="you, if disputing a removal",
    ),
]


@router.get("", response_model=DependencyGuidanceOut)
async def dependency_guidance(uid: str = Depends(current_user_id)) -> DependencyGuidanceOut:
    """What a dependency action involves and how to respond. Deterministic; no DB,
    no LLM. The veteran files the actual form."""
    return DependencyGuidanceOut(
        what_it_is=WHAT_IT_IS,
        add_path=ADD_PATH,
        removal_path=REMOVAL_PATH,
        timeline_note=TIMELINE_NOTE,
        evidence=EVIDENCE,
        forms=_FORMS,
        guidance_prompts=GUIDANCE_PROMPTS,
        disclaimer=DISCLAIMER,
        vso_note=VSO_NOTE,
    )


_RELATIONSHIP_LABELS = {
    "spouse": "Spouse",
    "child": "Child",
    "stepchild": "Stepchild",
    "parent": "Dependent parent",
}


def _render_worksheet(p: DependencyWorksheetIn) -> str:
    """Format the veteran's answers into a 21-686c worksheet + cover statement. The
    explanation and per-dependent notes go through VERBATIM. No SSNs collected."""
    name = (p.veteran_name or "").strip() or "____________________________"
    is_removal = p.action == "respond_to_removal"
    heading = (
        "Response to a Proposed/Completed Dependency Change"
        if is_removal else "Request to Add a Dependent"
    )

    real_deps = [
        d for d in p.dependents
        if any((getattr(d, f) or "").strip() for f in ("full_name", "event", "event_date", "notes"))
    ]
    if real_deps:
        blocks = []
        for i, d in enumerate(real_deps, 1):
            rel = _RELATIONSHIP_LABELS.get(d.relationship, "Dependent")
            lines = [f"**{i}. {d.full_name.strip() or 'Name'} — {rel}**", ""]
            lines.append(f"- Event: {d.event.strip() or '____________'}")
            lines.append(f"- Date: {d.event_date.strip() or '____________'}")
            if (d.event_place or "").strip():
                lines.append(f"- Place: {d.event_place.strip()}")
            if (d.notes or "").strip():
                lines.append(f"- Notes (my words): {d.notes.strip()}")
            blocks.append("\n".join(lines))
        deps_md = "\n\n".join(blocks)
    else:
        deps_md = "_(List each dependent: full name, relationship, the qualifying event, and its date.)_"

    explanation = (p.explanation or "").strip() or (
        "_(In your own words: what happened and why this dependent should be on your "
        "award. If you're answering a VA letter, name the letter's date and what it said.)_"
    )
    prior = (p.prior_removal_note or "").strip()
    prior_block = ""
    if is_removal or prior:
        prior_block = (
            "\n\n## The VA action I'm responding to\n\n"
            + (prior or "_(The date on the VA letter and what it said it would change.)_")
        )

    return f"""# {heading}

**{FORM} — {FORM_TITLE}**

_A worksheet to organize your answers and a cover statement to attach. File on the
official VA Form 21-686c — do not write Social Security or VA file numbers here._

**Veteran:** {name}
**What I'm requesting:** {"Respond to a dependency removal / proposed reduction" if is_removal else "Add or re-add a dependent"}

## Dependent(s)

{deps_md}{prior_block}

## My statement

{explanation}

## Certification

I certify that the statements above are true and correct to the best of my
knowledge and belief, and I understand this request affects my VA compensation.

---

**Signature:** ______________________________________    **Date:** ________________

**Printed name:** {name}
"""


@router.post("/worksheet", response_model=DependencyWorksheetOut)
async def dependency_worksheet(
    payload: DependencyWorksheetIn, uid: str = Depends(current_user_id)
) -> DependencyWorksheetOut:
    """Format the veteran's answers into a print-ready 21-686c worksheet + cover
    statement they review, sign, and file. Deterministic; narrative verbatim; never
    filed; no SSNs collected."""
    return DependencyWorksheetOut(
        form=FORM,
        form_title=FORM_TITLE,
        worksheet_markdown=_render_worksheet(payload),
        guidance=DRAFT_GUIDANCE,
        disclaimer=DISCLAIMER,
    )
