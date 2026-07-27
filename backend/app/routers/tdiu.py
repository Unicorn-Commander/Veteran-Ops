"""TDIU workflow — Total Disability based on Individual Unemployability (§4.16).

TDIU pays at the 100% rate without a 100% schedular rating when service-connected
conditions keep a veteran from substantially gainful employment. This router turns
the Game Plan's TDIU *screen* into a working surface: it reads the veteran's own
conditions + combined rating to explain where they stand against the §4.16(a)
schedular door, lays out the evidence a TDIU claim turns on, and formats the
veteran's work history into a print-ready VA Form 21-8940 worksheet they review,
sign, and submit.

Legal lane: whether a veteran is unemployable is VA's determination, built on the
work record — this NEVER says "you qualify", only "you may meet the schedular
threshold". The unemployability narrative is the veteran's OWN words, reproduced
verbatim. No LLM anywhere near this — deterministic. A VA-accredited VSO (or an
accredited attorney/agent, which TDIU claims often warrant) can build the record
for free; we say so.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, VeteranProfile
from ..schemas import (
    TdiuForm,
    TdiuScreenOut,
    TdiuWorksheetIn,
    TdiuWorksheetOut,
)
from ..strategy.rating_rules import screen_tdiu

router = APIRouter(prefix="/tdiu", tags=["tdiu"])

FORM = "VA Form 21-8940"
FORM_TITLE = "Veteran's Application for Increased Compensation Based on Unemployability"

DISCLAIMER = (
    "TDIU (Individual Unemployability) is decided by the VA based on your work "
    "history and your service-connected conditions — Rating Raider does not and "
    "cannot decide whether you qualify. This screen organizes where you stand "
    "against the schedular thresholds in 38 CFR §4.16 and the evidence these "
    "claims turn on. Whether you are unemployable is VA's determination. Because "
    "TDIU claims turn on the strength of the unemployability record, a free "
    "VA-accredited Veterans Service Officer (VFW, DAV, The American Legion, or your "
    "state/county veterans office) — or an accredited attorney or agent — is worth "
    "having in your corner. Rating Raider never files anything for you."
)

VSO_NOTE = (
    "TDIU is one of the claims where representation helps most. A free VSO or an "
    "accredited attorney/agent can gather employer statements, line up a vocational "
    "opinion, and frame why your conditions prevent substantially gainful work."
)

HOW_IT_WORKS = [
    "TDIU pays at the 100% rate even without a 100% schedular rating, when your "
    "service-connected conditions keep you from holding substantially gainful "
    "employment (roughly, work that pays above the federal poverty level — odd jobs "
    "and 'sheltered' work generally don't count against you).",
    "There are two doors. Schedular TDIU (§4.16(a)): one service-connected "
    "disability rated 60% or more, OR a combined rating of 70% or more with at "
    "least one disability at 40% or more. For that count, disabilities from a "
    "common cause, or of both arms/legs, can be grouped as one.",
    "Extraschedular TDIU (§4.16(b)): even if you don't meet those numbers, the VA "
    "can still grant TDIU if your conditions uniquely prevent you from working — it "
    "gets referred to the Director of Compensation Service.",
    "It's about being unable to KEEP substantially gainful work because of "
    "service-connected conditions — not your age, and not disabilities that aren't "
    "service-connected.",
]

# What the veteran narrates in their own words for the worksheet.
GUIDANCE_PROMPTS = [
    "The last date you worked full-time — and what your job was then.",
    "For each job in your recent work history: the employer, your title, the dates, "
    "your hours a week, and — in your own words — why you left or had to stop.",
    "How your service-connected conditions limit your ability to work: what you "
    "can't do, how often symptoms flare, days you'd miss, tasks you can't sustain. "
    "Be specific and first-person.",
    "Any work restrictions a doctor has given you, and any accommodations an "
    "employer had to make (or couldn't).",
    "Your education and any training — TDIU weighs whether your background leaves "
    "you able to do OTHER substantially gainful work.",
]

DRAFT_GUIDANCE = [
    "Read every line — this becomes part of your sworn application. Make sure every "
    "date and fact is true and in your own words.",
    "Be specific about WHY each job ended and how your conditions limit work — 'I "
    "missed 6+ days a month from migraines and was let go' says far more than 'I "
    "couldn't work.'",
    "Attach the supporting evidence in the checklist — an employer statement "
    "(21-4192), a vocational opinion, and SSDI records carry real weight.",
    "This worksheet organizes your answers; file on the official VA Form 21-8940 "
    "(and have your employer complete 21-4192). A VSO can submit the package with "
    "you — Rating Raider never files it for you.",
]

POST_DENIAL_NOTE = (
    "If you applied for TDIU before and were denied, that is not the end of the "
    "road. The usual next step is a Supplemental Claim (VA Form 20-0995) with NEW "
    "evidence — most often a vocational assessment tying your conditions to being "
    "unable to work, updated employer statements, or newly worsened ratings. Filing "
    "within one year of the decision keeps your original effective date, which "
    "protects any back pay."
)

_FORMS = [
    TdiuForm(
        form="VA Form 21-8940",
        title="Application for Increased Compensation Based on Unemployability",
        url="https://www.va.gov/find-forms/about-form-21-8940/",
        who="you",
    ),
    TdiuForm(
        form="VA Form 21-4192",
        title="Request for Employment Information in Connection with a Claim",
        url="https://www.va.gov/find-forms/about-form-21-4192/",
        who="your most recent employer(s)",
    ),
]


def _condition_dicts(conditions) -> list[dict]:
    return [
        {
            "name": c.name,
            "va_status": c.va_status,
            "current_rating": c.current_rating,
            "claim_type": c.claim_type,
            "diagnostic_code": c.diagnostic_code,
        }
        for c in conditions
    ]


@router.get("", response_model=TdiuScreenOut)
async def tdiu_screen(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TdiuScreenOut:
    """Where the veteran stands on TDIU, from their own conditions + combined
    rating. Always returns educational content — even below the schedular door,
    extraschedular TDIU exists and is explained."""
    conditions = (
        await db.execute(
            select(ClaimedCondition).where(ClaimedCondition.user_id == uuid.UUID(uid))
        )
    ).scalars().all()
    profile = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid))
        )
    ).scalar_one_or_none()
    combined = profile.current_combined_rating if profile else None

    screen = screen_tdiu(_condition_dicts(conditions), combined)

    what_it_is = (
        "TDIU — Total Disability based on Individual Unemployability — is a way to be "
        "paid at the 100% rate without a 100% schedular rating, when your "
        "service-connected conditions keep you from substantially gainful work."
    )

    if screen:
        why = screen["why"]
        evidence = screen["evidence"]
        eligible = bool(screen["eligible_schedular"])
        at_or_near = True
    else:
        why = (
            "Your current service-connected ratings don't clearly meet the §4.16(a) "
            "schedular thresholds (one disability at 60%+, or a combined 70%+ with one "
            "at 40%+). That doesn't rule TDIU out — extraschedular TDIU (§4.16(b)) can "
            "still apply when your conditions uniquely prevent you from working, and if "
            "a claim raises your ratings you may reach the schedular door. It's worth "
            "understanding, and a VSO can look at grouping (disabilities from one cause "
            "or of both limbs can count as one)."
        )
        evidence = [
            "VA Form 21-8940 (your application) and 21-4192 (employer statement)",
            "Your work history — dates, jobs, why each ended or became unsustainable",
            "A vocational assessment tying your inability to work to your conditions",
            "SSDI award records, if you have them",
            "Statements from you and people who know how symptoms limit your work",
        ]
        eligible = False
        at_or_near = False

    return TdiuScreenOut(
        at_or_near_threshold=at_or_near,
        eligible_schedular=eligible,
        why=why,
        what_it_is=what_it_is,
        how_it_works=HOW_IT_WORKS,
        evidence=evidence,
        forms=_FORMS,
        post_denial_note=POST_DENIAL_NOTE,
        guidance_prompts=GUIDANCE_PROMPTS,
        disclaimer=DISCLAIMER,
        vso_note=VSO_NOTE,
    )


def _render_worksheet(p: TdiuWorksheetIn) -> str:
    """Deterministically format the veteran's work history into a 21-8940-style
    worksheet. Narrative fields go through VERBATIM — no rewording. The veteran
    reviews it, then completes and signs the official form."""
    name = (p.veteran_name or "").strip() or "____________________________"

    def line(label: str, value: str) -> str:
        v = (value or "").strip()
        return f"**{label}:** {v if v else '____________________________'}"

    jobs_md = ""
    real_jobs = [
        j for j in p.jobs
        if any((getattr(j, f) or "").strip() for f in ("employer", "job_title", "dates", "reason_ended"))
    ]
    if real_jobs:
        blocks = []
        for i, j in enumerate(real_jobs, 1):
            blocks.append(
                f"**{i}. {j.employer.strip() or 'Employer'} — {j.job_title.strip() or 'Position'}**\n\n"
                f"- Dates: {j.dates.strip() or '____________'}\n"
                f"- Hours per week: {j.hours_per_week.strip() or '____'}\n"
                f"- Why it ended (my words): {j.reason_ended.strip() or '____________________________'}"
            )
        jobs_md = "\n\n".join(blocks)
    else:
        jobs_md = "_(List each recent job: employer, title, dates, hours, and why it ended.)_"

    limits = (p.how_conditions_limit_work or "").strip() or (
        "_(In your own words: how your service-connected conditions keep you from "
        "working — what you can't do, how often symptoms flare, days you'd miss.)_"
    )
    restrictions = (p.doctor_restrictions or "").strip()
    restrictions_block = f"\n\n## Work restrictions from my providers\n\n{restrictions}" if restrictions else ""

    return f"""# Individual Unemployability (TDIU) — Work-History Worksheet

**{FORM} — {FORM_TITLE}**

_A worksheet to organize your answers. File on the official VA Form 21-8940; have
your most recent employer(s) complete VA Form 21-4192._

{line("Veteran", name)}
{line("Last date I worked full-time", p.last_full_time_date)}
{line("Most I ever earned in a year (amount and year)", p.highest_earnings)}
{line("Education", p.education)}
{line("Other training", p.training)}

## My work history

{jobs_md}

## How my service-connected conditions keep me from working

{limits}{restrictions_block}

## Certification

I certify that the statements above are true and correct to the best of my
knowledge and belief. These are my own words, describing my work history and how my
service-connected conditions affect my ability to work.

---

**Signature:** ______________________________________    **Date:** ________________

**Printed name:** {name}
"""


@router.post("/worksheet", response_model=TdiuWorksheetOut)
async def tdiu_worksheet(
    payload: TdiuWorksheetIn, uid: str = Depends(current_user_id)
) -> TdiuWorksheetOut:
    """Format the veteran's work history into a print-ready 21-8940 worksheet they
    review, sign, and submit. Deterministic; narrative verbatim; never filed."""
    return TdiuWorksheetOut(
        form=FORM,
        form_title=FORM_TITLE,
        worksheet_markdown=_render_worksheet(payload),
        guidance=DRAFT_GUIDANCE,
        disclaimer=DISCLAIMER,
    )
