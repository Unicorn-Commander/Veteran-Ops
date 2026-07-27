/**
 * Curated, dated, sourced VA rating-rule changes surfaced so a veteran isn't
 * relying on criteria that shifted under them. Hand-curated FACTS (not model
 * output). `changed` = a final rule already in effect; `proposed` = published but
 * NOT final (never state a proposed change is certain or predict its effect).
 *
 * Cross-cutting requirement from docs/research/veteran-workflows-research-2026-07.md.
 */

export interface RuleChange {
  id: string
  /** Diagnostic codes this note applies to. */
  diagnosticCodes: string[]
  status: 'changed' | 'proposed'
  /** ISO date the rule took effect (changed) or was proposed (proposed). */
  date: string
  title: string
  /** Plain-language, legal-lane summary — what the rule says, not what VA will do. */
  summary: string
  /** A non-predictive "worth reviewing" nudge. */
  actionHint: string
  sourceUrl: string
}

export const RULE_CHANGES: RuleChange[] = [
  {
    id: 'digestive-2024',
    diagnosticCodes: ['7203', '7204', '7205', '7206', '7301', '7304', '7305', '7306', '7307', '7319', '7346'],
    status: 'changed',
    date: '2024-05-19',
    title: 'The digestive rating rules changed',
    summary:
      'VA revised the digestive schedule effective May 19, 2024. GERD now has its own code (DC 7206), with criteria focused on esophageal stricture and prescribed daily medication; several other digestive codes also changed.',
    actionHint:
      'If your evidence or decision uses the older schedule, compare it with the current rule and confirm which version applies before you file anything.',
    sourceUrl: 'https://www.federalregister.gov/documents/2024/03/20/2024-05138/schedule-for-rating-disabilities-the-digestive-system',
  },
  {
    id: 'sleep-apnea-proposed',
    diagnosticCodes: ['6847'],
    status: 'proposed',
    date: '2022-02-15',
    title: 'A sleep apnea rule change is proposed',
    summary:
      'VA proposed replacing the current device-based sleep-apnea criteria with criteria focused on treatment effectiveness and functional impairment. A proposal does not change the current rating schedule.',
    actionHint:
      'Nothing is final. Use the current published criteria today, and check the Federal Register for any final rule before relying on the proposal.',
    sourceUrl: 'https://www.federalregister.gov/documents/2022/02/15/2022-02049/schedule-for-rating-disabilities-ear-nose-throat-and-audiology-disabilities-special-provisions',
  },
  {
    id: 'tinnitus-proposed',
    diagnosticCodes: ['6260'],
    status: 'proposed',
    date: '2022-04-19',
    title: 'A tinnitus rule change is proposed',
    summary:
      'VA has proposed removing the standalone tinnitus rating (DC 6260) and evaluating tinnitus as a symptom of its underlying condition instead. This is proposed only — not final.',
    actionHint:
      'Use the current published criteria today, and check the Federal Register for any final rule before relying on the proposal.',
    sourceUrl: 'https://www.federalregister.gov/documents/2022/02/15/2022-02049/schedule-for-rating-disabilities-ear-nose-throat-and-audiology-disabilities-special-provisions',
  },
  {
    id: 'mental-health-proposed',
    diagnosticCodes: ['9201', '9202', '9203', '9204', '9205', '9208', '9210', '9211', '9300', '9301', '9304', '9305', '9310', '9312', '9326', '9400', '9403', '9404', '9410', '9411', '9412', '9413', '9416', '9417', '9421', '9422', '9423', '9424', '9425', '9431', '9432', '9433', '9434', '9435', '9440'],
    status: 'proposed',
    date: '2022-12-12',
    title: 'A mental-health rating rule change is proposed',
    summary:
      'VA has proposed replacing the current symptom-based mental-health formula with one based on functional domains, with a minimum 10% rating for any service-connected mental condition. This is proposed only — not final.',
    actionHint:
      'Nothing is final. Use the current published criteria today, and check the Federal Register for any final rule before relying on the proposal.',
    sourceUrl: 'https://www.federalregister.gov/documents/2022/02/15/2022-02051/schedule-for-rating-disabilities-mental-disorders',
  },
]

/** The rule-change note whose diagnostic codes include `dc`, if any. */
export function ruleChangeForDc(dc: string | null | undefined): RuleChange | null {
  const code = (dc ?? '').trim()
  if (!code) return null
  return RULE_CHANGES.find((r) => r.diagnosticCodes.includes(code)) ?? null
}
