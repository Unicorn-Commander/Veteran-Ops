"""Curated, dated, sourced VA regulatory CHANGES — the generic-facts database the
"what's changed since you were rated" workflow compares a veteran's rating date
against.

GENERIC FACTS, NOT AI. Every entry is hand-curated with an effective date and a real
source URL. This is deliberately NOT model output: a wrong date or a fabricated change
would tell a veteran they qualify when they don't — a real harm. AI is used only for the
PERSON-SPECIFIC judgment ("does THIS veteran's evidence support acting on this change"),
never to state what the change is.

`status`:
  * "changed"   — a FINAL rule already in effect (safe to act on the new criteria).
  * "proposed"  — published but NOT final; surfaced as "watch," never as certain.

Matching:
  * `diagnostic_codes` — rule changes match a veteran's condition by DC.
  * `exposure_tags` / `service_tags` — presumptive additions match a veteran's service
    + exposure profile (see whats_changed.py). Empty lists mean "not matched this way."

This is the authoritative source; the frontend's older lib/ruleChanges.ts is a subset
and should migrate to fetch from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegulatoryChange:
    id: str
    status: str  # "changed" | "proposed"
    effective_date: str  # ISO date the rule took effect (changed) or was proposed
    title: str
    summary: str  # plain-language, legal-lane: what the rule says, not what VA will do
    action_hint: str  # non-predictive "worth reviewing" nudge
    source_url: str
    diagnostic_codes: tuple[str, ...] = ()
    exposure_tags: tuple[str, ...] = ()  # e.g. "burn_pit", "agent_orange", "gulf_war"
    service_tags: tuple[str, ...] = ()  # e.g. "vietnam", "gulf_war", "post_9_11"
    confidence: str = "established"  # "established" | "emerging"


# Ordered newest-first. Dates and sources verified against the Federal Register / VA.gov.
REGULATORY_CHANGES: list[RegulatoryChange] = [
    RegulatoryChange(
        id="digestive-2024",
        status="changed",
        effective_date="2024-05-19",
        title="The digestive-system rating rules changed",
        summary=(
            "VA revised the schedule for rating the digestive system effective "
            "May 19, 2024. GERD now has its own diagnostic code (DC 7206) with criteria "
            "focused on esophageal stricture and daily prescribed medication, and several "
            "other digestive codes were revised."
        ),
        action_hint=(
            "If your rating or evidence used the older digestive schedule, compare it "
            "with the current rule and confirm which version applies before you file."
        ),
        source_url="https://www.federalregister.gov/documents/2024/03/20/2024-05138/schedule-for-rating-disabilities-the-digestive-system",
        diagnostic_codes=("7203", "7204", "7205", "7206", "7207", "7301", "7304", "7305", "7306", "7307", "7319", "7346"),
        confidence="established",
    ),
    RegulatoryChange(
        id="pact-act-burn-pit-2022",
        status="changed",
        effective_date="2022-08-10",
        title="The PACT Act added burn-pit / airborne-hazard presumptives",
        summary=(
            "The PACT Act (signed Aug 10, 2022) made many conditions presumptive for "
            "veterans exposed to burn pits and other airborne hazards during Gulf War-era "
            "or post-9/11 service — including numerous cancers and respiratory conditions "
            "such as asthma, chronic rhinitis, and chronic sinusitis. Conditions that were "
            "not presumptive when you were rated may be now."
        ),
        action_hint=(
            "If you served in a qualifying location and have one of the listed conditions, "
            "you may qualify under a presumptive that did not exist at your rating — worth "
            "checking with a VSO."
        ),
        source_url="https://www.va.gov/resources/the-pact-act-and-your-va-benefits/",
        exposure_tags=("burn_pit", "airborne_hazard"),
        service_tags=("gulf_war", "post_9_11"),
        confidence="established",
    ),
    RegulatoryChange(
        id="pact-act-agent-orange-hypertension-2024",
        status="changed",
        effective_date="2024-01-01",
        title="Hypertension became an Agent Orange presumptive",
        summary=(
            "Under the PACT Act, hypertension (high blood pressure) was added as a "
            "presumptive condition for veterans presumed exposed to Agent Orange / "
            "herbicides. This was not a presumptive when many Vietnam-era veterans were "
            "originally rated."
        ),
        action_hint=(
            "If you have a qualifying herbicide-exposure history and a hypertension "
            "diagnosis, this presumptive may apply now even though it did not at your "
            "rating."
        ),
        source_url="https://www.va.gov/disability/eligibility/hazardous-materials-exposure/agent-orange/",
        diagnostic_codes=("7101",),
        exposure_tags=("agent_orange", "herbicide"),
        service_tags=("vietnam",),
        confidence="established",
    ),
    RegulatoryChange(
        id="agent-orange-additions-2021",
        status="changed",
        effective_date="2021-01-01",
        title="Bladder cancer, hypothyroidism, and parkinsonism were added as Agent Orange presumptives",
        summary=(
            "The FY2021 NDAA added bladder cancer, hypothyroidism, and Parkinsonism to the "
            "list of conditions presumptively linked to Agent Orange / herbicide exposure. "
            "Veterans rated before this may not have had these recognized."
        ),
        action_hint=(
            "If you have qualifying herbicide exposure and one of these conditions, a "
            "presumptive path may now be available that was not at your rating."
        ),
        source_url="https://www.va.gov/disability/eligibility/hazardous-materials-exposure/agent-orange/",
        exposure_tags=("agent_orange", "herbicide"),
        service_tags=("vietnam",),
        confidence="established",
    ),
    RegulatoryChange(
        id="sleep-apnea-proposed",
        status="proposed",
        effective_date="2022-02-15",
        title="A sleep-apnea rating rule change is proposed",
        summary=(
            "VA proposed replacing the current device-based sleep-apnea criteria with "
            "criteria focused on treatment effectiveness and functional impairment. A "
            "proposal does NOT change the current rating schedule."
        ),
        action_hint=(
            "Nothing is final. Use the current published criteria today and check the "
            "Federal Register for any final rule before relying on the proposal."
        ),
        source_url="https://www.federalregister.gov/documents/2022/02/15/2022-02049/schedule-for-rating-disabilities-ear-nose-throat-and-audiology-disabilities-special-provisions",
        diagnostic_codes=("6847",),
        confidence="established",
    ),
    RegulatoryChange(
        id="tinnitus-proposed",
        status="proposed",
        effective_date="2022-04-19",
        title="A tinnitus rating rule change is proposed",
        summary=(
            "VA proposed removing the standalone tinnitus rating (DC 6260) and evaluating "
            "tinnitus as a symptom of its underlying condition instead. This is proposed "
            "only — not final."
        ),
        action_hint=(
            "Use the current published criteria today and check the Federal Register for "
            "any final rule before relying on the proposal."
        ),
        source_url="https://www.federalregister.gov/documents/2022/02/15/2022-02049/schedule-for-rating-disabilities-ear-nose-throat-and-audiology-disabilities-special-provisions",
        diagnostic_codes=("6260",),
        confidence="established",
    ),
    RegulatoryChange(
        id="mental-health-proposed",
        status="proposed",
        effective_date="2022-12-12",
        title="A mental-health rating rule change is proposed",
        summary=(
            "VA proposed replacing the current symptom-based mental-health formula with one "
            "based on functional domains, with a minimum 10% rating for any "
            "service-connected mental condition. This is proposed only — not final."
        ),
        action_hint=(
            "Nothing is final. Use the current published criteria today and check the "
            "Federal Register for any final rule before relying on the proposal."
        ),
        source_url="https://www.federalregister.gov/documents/2022/12/12/2022-26533/schedule-for-rating-disabilities-mental-disorders",
        diagnostic_codes=(
            "9201", "9202", "9203", "9204", "9205", "9208", "9210", "9211", "9300", "9301",
            "9304", "9305", "9310", "9312", "9326", "9400", "9403", "9404", "9410", "9411",
            "9412", "9413", "9416", "9417", "9421", "9422", "9423", "9424", "9425", "9431",
            "9432", "9433", "9434", "9435", "9440",
        ),
        confidence="established",
    ),
]


def changes_after(iso_date: str | None) -> list[RegulatoryChange]:
    """Changes whose effective/proposed date is strictly after `iso_date` (the veteran's
    rating date). None → return all (an unknown rating date means 'show everything, let
    the veteran anchor it')."""
    if not iso_date:
        return list(REGULATORY_CHANGES)
    return [c for c in REGULATORY_CHANGES if c.effective_date > iso_date]
