# Veteran disability workflow research

Curated product-research brief, reviewed 2026-07-20. This document captures product
conclusions and public sources only. It is not legal or medical advice, a prediction of
any claim outcome, or a substitute for a VA-accredited representative.

## Product conclusion

Veterans need a deadline-aware evidence workspace more than another generic chatbot.
The product should explain official processes, organize records the veteran already
controls, show the source and review date for every rule, and hand the veteran a clear
next action. It must not diagnose conditions, manufacture evidence, predict a rating,
select a legal strategy, represent a claimant, or submit a claim on the veteran's behalf.

Three capabilities should span the entire product:

1. **Deadline guardian:** track the intent-to-file window, the deadline stated in each
   decision letter, requested-evidence dates, exams, and dependent-event dates. Treat
   dates extracted from documents as suggestions until the veteran confirms them.
2. **Evidence map:** organize each issue around the evidence VA says it needs, identify
   missing categories, retain citations to the uploaded source, and distinguish facts
   from user-entered notes or model suggestions.
3. **Rule-currency control:** attach an effective date, primary source, content
   fingerprint, and human review status to every rating or eligibility rule. Fail closed
   for new guidance when current authoritative text cannot be verified.

## Prioritized workflows

| Priority | Workflow | Product behavior | Safety boundary |
|---|---|---|---|
| 1 | Intent to file | Explain the available VA channels, Form 21-0966, the benefit-specific nature of an intent, and the one-year completion window; create reminders after user confirmation. | Do not claim an effective date or that VA received a filing without authoritative confirmation. |
| 2 | Claim evidence organizer | Build a per-issue checklist from VA's evidence guidance; connect diagnoses, service events, records, lay statements, and medical opinions to their original sources. | Do not diagnose, alter records, or generate a clinician's opinion. |
| 3 | Decision-letter workspace | Extract issues, outcomes, reasons, favorable findings, dates, and requested actions with page citations; require user confirmation. | Explain the letter without asserting entitlement or a likely percentage. |
| 4 | Decision-review explorer | Compare Supplemental Claim, Higher-Level Review, and Board Appeal using current VA descriptions, evidence rules, forms, and the deadline printed on the decision. | Present options and tradeoffs; do not choose a lane. Escalate individualized strategy to an accredited representative. |
| 5 | Claim-exam preparation | Explain the purpose of a C&P exam, DBQs, records submission, scheduling, and what VA says to expect; help the veteran create a factual symptom and functional-impact timeline. | Encourage accuracy and completeness, never exaggeration or coached answers. |
| 6 | Rating explanation | Show the current cited criteria and explain VA combined-rating math with reproducible calculations. | Never predict an award; label hypothetical calculations as estimates. |
| 7 | Secondary-condition evidence map | Let the veteran record conditions already diagnosed by a clinician and organize possible causation or aggravation evidence for clinician or representative review. | Never infer a diagnosis or tell a veteran that one condition caused another. |
| 8 | TDIU information and records organizer | Explain current threshold rules and organize employment, education, medical, and vocational records around the official form. | Provide an informational screen only; do not predict eligibility or advise the veteran to stop working. |
| 9 | Presumptive-eligibility explorer | Match user-confirmed service locations and dates against current VA eligibility material, with citations and a verification date. | Do not guarantee eligibility; unresolved or conflicting service data must remain unresolved. |
| 10 | Increase and reexamination explainer | Organize evidence of changed severity and explain that VA may review the condition and the full current record. | Do not promise an increase or characterize reduction risk as certain. |
| 11 | Dependents workflow | Explain VA's current rating threshold and forms for adding or removing dependents; track requested evidence and status. | Do not calculate retroactive entitlement without verified VA dates and rules. |
| 12 | Lay-statement builder | Structure first-person observations by date, event, frequency, and functional impact; preserve the author's own words and revision history. | Do not invent observations, medical conclusions, or signatures. |
| 13 | Accredited-help finder | Link directly to VA's accreditation search and explain the roles of VSOs, accredited attorneys, and accredited claims agents. | Never present an unaccredited service as authorized representation. |
| 14 | Claim and review status explainer | Translate official VA status labels into plain language and maintain an action/request timeline. | Do not estimate a completion date as a promise. |
| 15 | Export and handoff | Produce a source-linked, veteran-reviewed evidence index for self-service or an accredited representative. | Never transmit to VA without an explicit, separately authorized integration and legal review. |

## Current-rule findings

- VA currently describes three decision-review options: Supplemental Claim,
  Higher-Level Review, and Board Appeal. Evidence rules and deadlines differ, so the
  product must use the decision letter and current VA guidance rather than a static
  recommendation.
- An intent to file can preserve a possible earlier effective date when the completed
  claim is filed within VA's stated one-year window. It is benefit-specific, and only
  one active intent per benefit type may apply.
- VA may decide a claim from existing records through the Acceptable Clinical Evidence
  process or request a C&P exam. The exam gathers information; it is not treatment.
- Combined disability ratings are not ordinary addition. The calculator must reproduce
  the current VA table/rules and disclose every input and rounding step.
- Presumptive programs depend on current diagnosis plus qualifying service facts. Lists,
  locations, and date ranges can change and therefore require live rule governance.
- The digestive-system rating schedule changed through a final rule effective
  2024-05-19. This is concrete evidence that product guidance cannot be shipped as
  timeless prose.
- Proposals, news coverage, and practitioner commentary are not final rules. A proposed
  change must be labeled as proposed and must never replace current eCFR text.

## Legal and clinical boundaries

- Keep the default posture educational and organizational. Claims representation and
  individualized legal strategy belong with a VA-accredited representative.
- Preserve provenance. Every extracted fact needs a document/page citation; every
  generated suggestion needs a visible generated status and user confirmation.
- Treat uploaded records, claim details, and health information as sensitive. Research,
  evaluation, demos, monitoring, and canaries must use synthetic fixtures only.
- Never create a nexus opinion, diagnosis, signature, service fact, symptom, or witness
  observation. The system may help organize an opinion authored by a qualified clinician.
- Never use a veteran's VA.gov credentials or imply that a generated packet has been
  filed, received, accepted, or approved.
- Route urgent legal questions, complex appeals, suspected error, fraud concerns, and
  high-risk medical questions to qualified human help.

## Primary sources

### Filing and evidence

- [Intent to file overview](https://www.va.gov/resources/your-intent-to-file-a-va-claim/)
- [VA Form 21-0966](https://www.va.gov/forms/21-0966/)
- [How to file a disability claim](https://www.va.gov/disability/how-to-file-claim/)
- [Evidence needed for a disability claim](https://www.va.gov/disability/how-to-file-claim/evidence-needed/)
- [Supporting forms for VA claims](https://www.va.gov/supporting-forms-for-claims/)
- [VA Form 21-10210 lay or witness statement](https://www.va.gov/forms/21-10210/)

### Decisions, exams, and ratings

- [Decision review options](https://www.va.gov/decision-reviews/)
- [Decision review FAQs](https://www.va.gov/resources/decision-reviews-faqs/)
- [Supplemental Claims](https://www.va.gov/decision-reviews/supplemental-claim/)
- [Higher-Level Reviews](https://www.va.gov/decision-reviews/higher-level-review/)
- [Board Appeals](https://www.va.gov/decision-reviews/board-appeal/)
- [VA claim exam](https://www.benefits.va.gov/COMPENSATION/claimexam.asp)
- [About disability ratings](https://www.va.gov/disability/about-disability-ratings/)
- [Current 38 CFR Part 3](https://www.ecfr.gov/current/title-38/chapter-I/part-3)
- [Current 38 CFR Part 4](https://www.ecfr.gov/current/title-38/chapter-I/part-4)
- [Digestive-system final rule effective 2024-05-19](https://www.federalregister.gov/documents/2024/03/20/2024-05138/schedule-for-rating-disabilities-the-digestive-system)

### Eligibility, dependents, and accredited help

- [Disability eligibility](https://www.va.gov/disability/eligibility/)
- [PACT Act and VA benefits](https://www.va.gov/resources/the-pact-act-and-your-va-benefits/)
- [Add or remove a dependent](https://www.va.gov/disability/add-remove-dependent/)
- [Get help from an accredited representative](https://www.va.gov/get-help-from-accredited-representative)
- [VA accreditation search](https://www.va.gov/ogc/apps/accreditation/)
- [VA-accredited representative FAQs](https://www.va.gov/resources/va-accredited-representative-faqs/)
- [38 CFR 14.629](https://www.law.cornell.edu/cfr/text/38/14.629)
- [38 CFR 14.636](https://www.law.cornell.edu/cfr/text/38/14.636)

## Research limits

The source set is intentionally weighted toward VA, eCFR, and Federal Register material.
Community discussions and practitioner articles informed the workflow hypotheses but are
not authority and are not retained here as proof of a rule. Workflow priority still
requires moderated veteran usability research, accessibility testing, accredited legal
review, and outcome measurement using consented or synthetic data.
