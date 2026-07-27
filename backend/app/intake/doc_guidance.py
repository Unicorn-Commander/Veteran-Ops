"""Plain-language "what to upload" guidance, keyed by document type.

Pure data + a single deterministic lookup — no LLM, no network, nothing that
can drift at runtime. This is EDUCATIONAL SELF-HELP content, not legal advice:
it tells a veteran what a document type generally IS and what commonly counts
as an example of it, never what rating or outcome they'll get. Examples are
kept intentionally generic (no invented VA form numbers or rules) — "your VA
rating decision letter", "any private doctor's diagnosis and opinion", "your
DD-214 or service treatment records" — because the exact paperwork a veteran
holds varies case by case.

One entry per value in `classify.DOC_TYPES` (kept in lockstep — see the
module-level assertion below), plus a safe default for anything else.
"""

from __future__ import annotations

from .classify import DOC_TYPES

DOC_TYPE_GUIDANCE: dict[str, dict] = {
    "rating_decision": {
        "label": "VA Rating Decision",
        "what_it_is": (
            "The official VA letter that lists each condition it reviewed and "
            "the percentage (if any) it assigned for each one."
        ),
        "what_to_upload": [
            "The full VA rating decision packet, every page (not just the summary page)",
            "The 'Codesheet' or 'Evaluation' pages that list each condition and percentage",
            "Any attached 'Reasons for Decision' pages explaining the outcome",
        ],
        "why_it_helps": (
            "It's the clearest record of what the VA already decided, which "
            "conditions are already service-connected, and what to appeal or add to next."
        ),
    },
    "decision_letter": {
        "label": "VA Decision Letter",
        "what_it_is": (
            "A VA letter notifying you of an action on your claim — a grant, "
            "denial, deferral, or other administrative decision."
        ),
        "what_to_upload": [
            "The complete decision letter, including any enclosures",
            "The envelope or cover page showing the date it was sent, if separate",
            "Any follow-up letters referencing the same claim",
        ],
        "why_it_helps": (
            "It shows the VA's official position and the date the clock started "
            "on any appeal window."
        ),
    },
    "str": {
        "label": "Service Treatment Record (STR)",
        "what_it_is": (
            "Your military medical records — the health record the service "
            "kept on you while you were on active duty."
        ),
        "what_to_upload": [
            "Your DD-214 (for dates and character of service)",
            "Sick call or clinic visit notes from your service record",
            "Entrance and separation physical exams (e.g. reports of medical examination)",
            "Any in-service injury, illness, or line-of-duty paperwork",
        ],
        "why_it_helps": (
            "It documents what happened to your health WHILE you were serving, "
            "which is often the first link in showing a condition is connected to service."
        ),
    },
    "dbq": {
        "label": "Disability Benefits Questionnaire (DBQ)",
        "what_it_is": (
            "A structured VA or private-provider exam form that records findings "
            "for a specific condition in the format VA raters use."
        ),
        "what_to_upload": [
            "The completed DBQ for the condition being claimed",
            "Any C&P (Compensation & Pension) exam report covering the same condition",
            "A private DBQ completed and signed by your own treating provider, if you have one",
        ],
        "why_it_helps": (
            "It puts an exam finding directly into the format VA already uses "
            "to rate that condition."
        ),
    },
    "treatment_record": {
        "label": "Treatment Record",
        "what_it_is": (
            "Any medical record showing you were seen, diagnosed, or treated for a "
            "condition — from the VA, a private doctor, or another provider."
        ),
        "what_to_upload": [
            "VA or private clinic visit notes mentioning the condition",
            "Hospital discharge summaries",
            "Imaging or lab reports (e.g. X-ray, MRI, bloodwork) tied to the condition",
            "Prescription or medication records showing ongoing treatment",
        ],
        "why_it_helps": (
            "It shows the condition exists and how it has been treated over time, "
            "which supports both diagnosis and continuity."
        ),
    },
    "private_medical_opinion": {
        "label": "Private Medical Opinion",
        "what_it_is": (
            "A signed letter or statement from a private (non-VA) physician giving "
            "a diagnosis or an opinion connecting a condition to your service."
        ),
        "what_to_upload": [
            "A signed letter from your doctor stating the diagnosis",
            "A nexus letter where the doctor gives their opinion on the service connection",
            "Any supporting records the doctor's opinion is based on",
        ],
        "why_it_helps": (
            "A private doctor's own diagnosis and opinion can directly support the "
            "medical link between your service and the condition."
        ),
    },
    "lay_statement": {
        "label": "Lay / Buddy Statement",
        "what_it_is": (
            "A written, signed statement from you, a family member, or a fellow "
            "servicemember describing what you personally observed or experienced."
        ),
        "what_to_upload": [
            "Your own signed statement describing symptoms, events, or their impact",
            "A signed statement from a spouse, family member, or friend who observed the condition",
            "A signed 'buddy statement' from someone who served with you and witnessed an event",
        ],
        "why_it_helps": (
            "It gives firsthand, personal detail that medical records alone often can't "
            "capture, such as when symptoms started or how an event unfolded."
        ),
    },
    "service_record": {
        "label": "Service Record",
        "what_it_is": (
            "Records showing your service history — where you were, what you did, "
            "and what happened, separate from your medical file."
        ),
        "what_to_upload": [
            "Your DD-214 or other discharge paperwork",
            "Orders showing deployments, duty stations, or exposures",
            "Performance evaluations, incident reports, or awards referencing an event",
        ],
        "why_it_helps": (
            "It helps establish where you served and what you were exposed to, "
            "which can support a connection between service and a condition."
        ),
    },
    "other": {
        "label": "Other Document",
        "what_it_is": (
            "A document that doesn't fit the categories above but may still be "
            "relevant to your claim."
        ),
        "what_to_upload": [
            "Anything you believe is relevant evidence for your claim",
            "Correspondence with the VA not covered by the other categories",
        ],
        "why_it_helps": (
            "Even when a document doesn't fit a standard category, it can still "
            "round out the picture of your claim."
        ),
    },
}

# Kept in lockstep with classify.DOC_TYPES on purpose — a doc type with no
# guidance entry is a spec bug, not a silent gap.
assert set(DOC_TYPE_GUIDANCE) == set(DOC_TYPES), (
    "DOC_TYPE_GUIDANCE must have exactly one entry per classify.DOC_TYPES value"
)

_DEFAULT_GUIDANCE = {
    "label": "Document",
    "what_it_is": (
        "A document type Valor doesn't have specific guidance for yet."
    ),
    "what_to_upload": [
        "Anything you believe is relevant evidence for your claim",
    ],
    "why_it_helps": (
        "Any record that documents your service, your health, or the VA's "
        "handling of your claim can help round out your case."
    ),
}


def guidance_for(doc_type: str | None) -> dict:
    """PURE, deterministic lookup — never raises. Unknown/invented doc types
    (and None) fall back to a safe generic entry so the caller can always rely
    on the shape."""
    if isinstance(doc_type, str) and doc_type in DOC_TYPE_GUIDANCE:
        return DOC_TYPE_GUIDANCE[doc_type]
    return _DEFAULT_GUIDANCE
