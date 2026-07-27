/**
 * Synthetic demo data for the README screenshot gallery.
 *
 * EVERYTHING in this file is invented. There is no real veteran here: no real
 * name, email, date of birth, address, claim number, decision letter, or
 * document. The fixture user is "Synthetic Veteran <synthetic@example.test>"
 * and every identifier is a zero-padded placeholder UUID.
 *
 * The screenshots the README ships are captured by driving the REAL React app
 * against these mocked API responses (see showcase.spec.ts), so what you see in
 * the gallery is the actual product UI — only the record behind it is fake.
 *
 * If you extend the gallery, keep this rule: realistic shapes, obviously
 * synthetic content, and never a byte of production data.
 */
import type { Page, Route } from '@playwright/test'

export const SYNTHETIC_USER_ID = '00000000-0000-0000-0000-0000000000a1'
export const SYNTHETIC_WORKSPACE_ID = '00000000-0000-0000-0000-0000000000c3'

const CONDITION_IDS = {
  back: '00000000-0000-0000-0000-000000000101',
  tinnitus: '00000000-0000-0000-0000-000000000102',
  ptsd: '00000000-0000-0000-0000-000000000103',
  apnea: '00000000-0000-0000-0000-000000000104',
  migraine: '00000000-0000-0000-0000-000000000105',
  knee: '00000000-0000-0000-0000-000000000106',
}

export async function json(route: Route, body: unknown) {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })
}

/* ─────────────────────────────  ACCOUNT / SHELL  ───────────────────────────── */

const authConfig = {
  sso_enabled: false,
  sso_label: 'Unicorn Commander',
  password_login_enabled: true,
  registration_open: false,
  registration_mode: 'closed',
  email_enabled: false,
  password_reset_enabled: false,
}

const me = {
  id: SYNTHETIC_USER_ID,
  email: 'synthetic@example.test',
  full_name: 'Synthetic Veteran',
  email_verified: true,
  avatar_url: null,
  platform_admin: false,
  created_at: '2026-07-20T00:00:00Z',
}

const workspaces = {
  workspaces: [
    {
      id: SYNTHETIC_WORKSPACE_ID,
      name: 'Personal',
      kind: 'personal',
      plan_tier: 'free',
      status: 'active',
      role: 'owner',
    },
  ],
  current_workspace_id: SYNTHETIC_WORKSPACE_ID,
}

const entitlements = {
  workspace_id: SYNTHETIC_WORKSPACE_ID,
  kind: 'personal',
  tier: 'free',
  role: 'owner',
  features: [],
  seat_limit: 1,
}

const meta = {
  // Mirrors backend config.app_name — the product is Veteran-Ops; Rating Raider
  // is the in-product agent (docs/BRANDING.md).
  name: 'Veteran-Ops',
  version: 'synthetic',
  disclaimer: '',
  va_enabled: false,
  billing_self_serve: false,
  kb_stale: false,
  kb_verified_as_of: '2026-07-20',
  kb_status: 'current',
}

const profile = {
  branch: 'Army',
  service_start: null,
  service_end: null,
  discharge_type: 'honorable',
  combat_service: true,
  current_rating: 50,
  state: null,
  notes: null,
  service_periods: [],
  exposures: {},
}

/* ────────────────────────────────  CONDITIONS  ──────────────────────────────── */

const conditions = [
  {
    id: CONDITION_IDS.back,
    name: 'Lumbosacral strain',
    body_system: 'musculoskeletal',
    diagnostic_code: '5237',
    claim_type: 'increase',
    secondary_to: null,
    current_rating: 10,
    target_rating: 20,
    status: 'gathering',
    va_status: 'service_connected',
    onset_date: null,
    in_service_event: 'Recurrent low-back pain documented during service.',
    nexus_notes: null,
    dbq_form: null,
    notes: null,
    created_at: '2026-07-20T00:00:00Z',
    updated_at: '2026-07-20T00:00:00Z',
  },
  {
    id: CONDITION_IDS.tinnitus,
    name: 'Tinnitus',
    body_system: 'auditory',
    diagnostic_code: '6260',
    claim_type: 'existing',
    secondary_to: null,
    current_rating: 10,
    target_rating: 10,
    status: 'ready',
    va_status: 'service_connected',
    onset_date: null,
    in_service_event: 'Noise exposure on the flight line.',
    nexus_notes: null,
    dbq_form: null,
    notes: null,
    created_at: '2026-07-20T00:00:00Z',
    updated_at: '2026-07-20T00:00:00Z',
  },
  {
    id: CONDITION_IDS.ptsd,
    name: 'PTSD',
    body_system: 'mental',
    diagnostic_code: '9411',
    claim_type: 'increase',
    secondary_to: null,
    current_rating: 30,
    target_rating: 50,
    status: 'gathering',
    va_status: 'service_connected',
    onset_date: null,
    in_service_event: 'Deployment stressor described in the veteran statement.',
    nexus_notes: null,
    dbq_form: null,
    notes: null,
    created_at: '2026-07-20T00:00:00Z',
    updated_at: '2026-07-20T00:00:00Z',
  },
  {
    id: CONDITION_IDS.apnea,
    name: 'Sleep apnea',
    body_system: 'respiratory',
    diagnostic_code: '6847',
    claim_type: 'secondary',
    secondary_to: 'PTSD',
    current_rating: null,
    target_rating: 50,
    status: 'gathering',
    va_status: 'unknown',
    onset_date: null,
    in_service_event: null,
    nexus_notes: 'Secondary theory under 38 CFR 3.310 — still needs a nexus opinion.',
    dbq_form: null,
    notes: null,
    created_at: '2026-07-20T00:00:00Z',
    updated_at: '2026-07-20T00:00:00Z',
  },
  {
    id: CONDITION_IDS.migraine,
    name: 'Migraine headaches',
    body_system: 'neurological',
    diagnostic_code: '8100',
    claim_type: 'new',
    secondary_to: null,
    current_rating: null,
    target_rating: 30,
    status: 'considering',
    va_status: 'denied',
    onset_date: null,
    in_service_event: null,
    nexus_notes: null,
    dbq_form: null,
    notes: null,
    created_at: '2026-07-20T00:00:00Z',
    updated_at: '2026-07-20T00:00:00Z',
  },
  {
    id: CONDITION_IDS.knee,
    name: 'Right knee strain',
    body_system: 'musculoskeletal',
    diagnostic_code: '5260',
    claim_type: 'new',
    secondary_to: null,
    current_rating: null,
    target_rating: 10,
    status: 'considering',
    va_status: 'unknown',
    onset_date: null,
    in_service_event: null,
    nexus_notes: null,
    dbq_form: null,
    notes: null,
    created_at: '2026-07-20T00:00:00Z',
    updated_at: '2026-07-20T00:00:00Z',
  },
]

const duplicates = {
  clusters: [
    {
      key: 'lumbar',
      family: 'Low back',
      count: 2,
      keep_name: 'Lumbosacral strain',
      keep_id: CONDITION_IDS.back,
      keep_va_status: 'service_connected',
      park_names: ['Lower back pain'],
      park_ids: ['00000000-0000-0000-0000-000000000107'],
      title: 'Two entries look like the same low-back condition',
      body: 'Keeping one entry makes the plan readable. Parking the duplicate does not remove anything from your VA record.',
      severity: 'low',
      link: '/conditions?dupes=1',
    },
  ],
  note: 'Similar-name clusters found while reading your own uploaded records.',
}

const evidenceByCondition: Record<string, unknown[]> = {
  [CONDITION_IDS.back]: [
    {
      id: '00000000-0000-0000-0000-000000000201',
      condition_id: CONDITION_IDS.back,
      document_id: null,
      kind: 'diagnosis',
      title: 'Current diagnosis in VA treatment records',
      status: 'have',
      source: 'VA medical records',
      file_ref: null,
      notes: null,
      rationale: {
        elements: ['Current disability'],
        why: 'A current diagnosis is the first element of service connection.',
      },
      citations: [],
      created_at: '2026-07-20T00:00:00Z',
      updated_at: '2026-07-20T00:00:00Z',
    },
    {
      id: '00000000-0000-0000-0000-000000000202',
      condition_id: CONDITION_IDS.back,
      document_id: null,
      kind: 'service_record',
      title: 'In-service back complaints (STRs)',
      status: 'have',
      source: 'Service treatment records',
      file_ref: null,
      notes: null,
      rationale: {
        elements: ['In-service event'],
        why: 'Documents that the problem began or worsened during service.',
      },
      citations: [],
      created_at: '2026-07-20T00:00:00Z',
      updated_at: '2026-07-20T00:00:00Z',
    },
    {
      id: '00000000-0000-0000-0000-000000000203',
      condition_id: CONDITION_IDS.back,
      document_id: null,
      kind: 'dbq',
      title: 'Range-of-motion measurements for the current rating criteria',
      status: 'need',
      source: null,
      file_ref: null,
      notes: 'Ask a provider whether current measurements reflect a flare-up week.',
      rationale: {
        elements: ['Severity'],
        why: 'The rating criteria turn on measured limitation of motion.',
      },
      citations: [],
      created_at: '2026-07-20T00:00:00Z',
      updated_at: '2026-07-20T00:00:00Z',
    },
  ],
  [CONDITION_IDS.ptsd]: [
    {
      id: '00000000-0000-0000-0000-000000000211',
      condition_id: CONDITION_IDS.ptsd,
      document_id: null,
      kind: 'treatment_record',
      title: 'Ongoing mental-health treatment notes',
      status: 'have',
      source: 'VA medical records',
      file_ref: null,
      notes: null,
      rationale: {
        elements: ['Current disability', 'Severity'],
        why: 'Treatment history shows both the diagnosis and how it presents over time.',
      },
      citations: [],
      created_at: '2026-07-20T00:00:00Z',
      updated_at: '2026-07-20T00:00:00Z',
    },
    {
      id: '00000000-0000-0000-0000-000000000212',
      condition_id: CONDITION_IDS.ptsd,
      document_id: null,
      kind: 'lay_statement',
      title: 'Buddy statement about changes after deployment',
      status: 'requested',
      source: null,
      file_ref: null,
      notes: 'You write and sign this yourself — Veteran-Ops never signs evidence for you.',
      rationale: {
        elements: ['Continuity', 'Severity'],
        why: 'Lay observation can describe symptoms the clinical record does not capture.',
      },
      citations: [],
      created_at: '2026-07-20T00:00:00Z',
      updated_at: '2026-07-20T00:00:00Z',
    },
  ],
  [CONDITION_IDS.apnea]: [
    {
      id: '00000000-0000-0000-0000-000000000221',
      condition_id: CONDITION_IDS.apnea,
      document_id: null,
      kind: 'diagnosis',
      title: 'Sleep study confirming the diagnosis',
      status: 'have',
      source: 'Private medical records',
      file_ref: null,
      notes: null,
      rationale: {
        elements: ['Current disability'],
        why: 'A sleep study is the usual proof of a current diagnosis here.',
      },
      citations: [],
      created_at: '2026-07-20T00:00:00Z',
      updated_at: '2026-07-20T00:00:00Z',
    },
    {
      id: '00000000-0000-0000-0000-000000000222',
      condition_id: CONDITION_IDS.apnea,
      document_id: null,
      kind: 'nexus_letter',
      title: 'Medical opinion linking sleep apnea to PTSD (38 CFR 3.310)',
      status: 'need',
      source: null,
      file_ref: null,
      notes: 'A qualified provider writes and signs this. Bring the provider brief to that appointment.',
      rationale: {
        elements: ['Nexus'],
        why: 'A secondary claim needs a medical link between the two conditions.',
      },
      citations: [],
      created_at: '2026-07-20T00:00:00Z',
      updated_at: '2026-07-20T00:00:00Z',
    },
  ],
  [CONDITION_IDS.migraine]: [
    {
      id: '00000000-0000-0000-0000-000000000231',
      condition_id: CONDITION_IDS.migraine,
      document_id: null,
      kind: 'continuity',
      title: 'Headache log showing frequency of prostrating attacks',
      status: 'need',
      source: null,
      file_ref: null,
      notes: null,
      rationale: {
        elements: ['Severity', 'Continuity'],
        why: 'The migraine criteria turn on how often attacks are prostrating.',
      },
      citations: [],
      created_at: '2026-07-20T00:00:00Z',
      updated_at: '2026-07-20T00:00:00Z',
    },
  ],
  [CONDITION_IDS.tinnitus]: [],
  [CONDITION_IDS.knee]: [],
}

/* ────────────────────────────────  CLAIM PLAN  ─────────────────────────────── */

const snapshot = {
  current_combined: 50,
  conditions_total: 6,
  ready_count: 1,
  needs_evidence_count: 4,
  denied_count: 1,
  active_itf: { type: 'compensation', deadline: '2027-03-14', days_remaining: 230 },
}

const coach = {
  do_this_first: {
    id: 'nexus-apnea',
    tier: 'first',
    title: 'Take the sleep-apnea provider brief to an appointment',
    why: 'The sleep study is already in your file; the medical link to PTSD is the one piece nobody but a qualified provider can supply.',
    link: '/nexus',
    category: 'evidence',
    condition_name: 'Sleep apnea',
    impact: 'high',
    kind: 'evidence',
  },
  do_this_first_reason:
    'Every other open item on this plan can move in parallel. This one is on someone else’s calendar, so it should start today.',
  then: [
    {
      id: 'rom-back',
      title: 'Ask about range-of-motion measurements for your low back',
      why: 'Your current rating turns on measured limitation of motion, and the last measurements in your file are two years old.',
      link: '/conditions',
      impact: 'medium',
    },
    {
      id: 'headache-log',
      title: 'Start a headache log before the next appointment',
      why: 'Frequency of prostrating attacks is the criterion; a contemporaneous log is far stronger than recall.',
      link: '/symptom-log',
      impact: 'medium',
    },
    {
      id: 'buddy-ptsd',
      title: 'Ask someone who served with you for a statement',
      why: 'You write and sign it — Veteran-Ops will not draft a signature or speak for another person.',
      link: '/buddy',
      impact: 'medium',
    },
  ],
  parked: [
    {
      id: 'knee-park',
      title: 'Right knee strain — parked until you have a current diagnosis',
      why: 'Nothing in the uploaded records shows a current knee diagnosis yet, so this would be a claim without its first element.',
      link: '/conditions',
      impact: 'low',
    },
    {
      id: 'dupe-park',
      title: 'Duplicate low-back entry parked to keep the plan readable',
      why: 'Parking a duplicate in this app changes nothing in your VA record.',
      link: '/conditions?dupes=1',
      impact: 'low',
    },
  ],
  outstanding_primary: [
    {
      id: 'reclaim-migraine',
      kind: 'reclaim',
      severity: 'high',
      title: 'Migraines were denied before — a supplemental path may exist',
      why: 'A prior denial is not the end of the road if there is new and relevant evidence. A VSO can tell you which lane fits.',
      link: '/appeals',
      checklist: [
        'Find the decision letter and note its date',
        'Identify what the decision said was missing',
        'Ask a VSO which review lane fits your facts',
      ],
      tier: 'primary',
    },
    {
      id: 'tdiu-screen',
      kind: 'tdiu',
      severity: 'medium',
      title: 'TDIU screen — worth a conversation, not an assumption',
      why: 'TDIU turns on employment facts this software cannot see. Bring your actual work history to an accredited representative.',
      link: '/tdiu',
      checklist: [
        'Write down the last five years of work, including missed days',
        'Note any accommodations an employer made',
        'Discuss with a VSO before filing anything',
      ],
      tier: 'primary',
    },
    {
      id: 'gap-apnea-nexus',
      kind: 'gap',
      severity: 'high',
      title: 'Sleep apnea has no medical nexus opinion on file',
      why: 'The secondary theory under 38 CFR 3.310 needs a provider’s opinion. Nothing in the app can substitute for it.',
      link: '/nexus',
      checklist: ['Print the provider brief', 'Bring the sleep study to the appointment'],
      tier: 'primary',
    },
  ],
  outstanding_more: [
    {
      id: 'caution-pyramiding',
      kind: 'trade-off',
      severity: 'low',
      title: 'Two musculoskeletal entries may overlap (38 CFR 4.14)',
      why: 'Rating the same impairment twice is not permitted. Worth raising with a representative before filing both.',
      link: '/conditions',
      tier: 'more',
      status: 'informational',
    },
    {
      id: 'cleanup-dupes',
      kind: 'cleanup',
      severity: 'low',
      title: 'One duplicate condition name to clean up',
      why: 'Housekeeping only — this affects the plan’s readability, not your VA record.',
      link: '/conditions?dupes=1',
      tier: 'more',
      status: 'informational',
    },
  ],
  outstanding_count: 3,
  duplicates: duplicates.clusters,
  section_guides: [
    {
      id: 'standing',
      title: 'Where you stand',
      what: 'What your records currently show, condition by condition.',
      why: 'A plan built on a misread record sends you to the wrong appointment.',
      do: 'Skim for anything that looks wrong, then correct it on Conditions.',
      status: 'clear',
    },
  ],
  post_analysis_cta: {
    title: 'Talk it through first',
    body: 'A short gap interview usually reorders this plan.',
    interview_path: '/raider?mode=post_analysis',
    plan_path: '/strategy',
  },
}

const caseBrief = {
  title: 'Case brief — for you or a VSO',
  disclaimer:
    'Educational self-help organization of the veteran’s own records. Not legal advice, not a medical opinion, and not a VA determination. Veteran-Ops does not file claims and Rating Raider does not represent you. Review with a VA-accredited representative before filing.',
  profile_summary:
    'Synthetic demo record — Army, honorable discharge, combat service indicated. Six conditions tracked, current combined rating 50%. Prepared for review with an accredited representative.',
  snapshot,
  service_connected: [
    { name: 'Lumbosacral strain', rating: 10, dc: '5237' },
    { name: 'Tinnitus', rating: 10, dc: '6260' },
    { name: 'PTSD', rating: 30, dc: '9411' },
  ],
  denied: [{ name: 'Migraine headaches', dc: '8100' }],
  do_this_first: coach.do_this_first,
  then: coach.then,
  outstanding_top: coach.outstanding_primary,
  cautions: [
    { title: 'Overlapping musculoskeletal entries', kind: 'pyramiding', reg: '38 CFR 4.14' },
    { title: 'Reduction risk when re-opening a stable rating', kind: 'reduction', reg: '38 CFR 3.344' },
  ],
  tdiu: {
    eligible_schedular: false,
    why: 'TDIU turns on employment facts this software cannot see. The screen is educational only — bring your real work history to an accredited representative.',
    what_it_is: 'A way to be paid at the 100% rate without a 100% schedular rating.',
    evidence: ['Employment history', 'Employer statements', 'Medical opinions on work capacity'],
    note: 'Not a determination of entitlement.',
    reg: '38 CFR 4.16',
    form: 'VA Form 21-8940',
  },
  duplicates: duplicates.clusters,
}

const strategy = {
  generated_at: '2026-07-20T12:00:00Z',
  snapshot,
  pathways: [
    {
      key: 'secondary-apnea',
      title: 'Develop the sleep-apnea secondary claim',
      summary:
        'The diagnosis is documented; what is missing is a medical opinion connecting it to your service-connected PTSD.',
      steps: [
        'Print the nexus provider brief',
        'Bring the sleep study and the brief to a qualified provider',
        'If the provider agrees and signs an opinion, review the packet with a VSO',
      ],
      included_conditions: ['Sleep apnea'],
      estimated_combined: 70,
      estimated_combined_basis:
        '38 CFR 4.25 math on the target ratings YOU entered — an arithmetic illustration, not a prediction of any VA decision.',
      tradeoff: 'Re-opening a stable file invites a fresh look at everything in it. Weigh that with a representative.',
      recommended: true,
    },
    {
      key: 'increase-back',
      title: 'Refresh the evidence behind the low-back rating',
      summary:
        'Current measurements are the usual gap for an increase on limitation-of-motion criteria.',
      steps: [
        'Ask a provider about current range-of-motion measurements',
        'Note whether measurements were taken during a flare-up',
        'Review the result before deciding whether to file',
      ],
      included_conditions: ['Lumbosacral strain'],
      estimated_combined: 60,
      estimated_combined_basis: '38 CFR 4.25 math on your own target ratings — educational only.',
      tradeoff: 'An increase request can also result in a reduction. 38 CFR 3.344 is worth reading first.',
      recommended: false,
    },
  ],
  priority_actions: [
    {
      title: 'Take the sleep-apnea provider brief to an appointment',
      why: 'The medical link is the only element nobody but a provider can supply.',
      category: 'evidence',
      condition_name: 'Sleep apnea',
      impact: 'high',
      link: '/nexus',
    },
    {
      title: 'Ask about current range-of-motion measurements',
      why: 'The low-back criteria turn on measured limitation of motion.',
      category: 'evidence',
      condition_name: 'Lumbosacral strain',
      impact: 'medium',
      link: '/conditions',
    },
    {
      title: 'Bring the migraine denial to a VSO',
      why: 'Which review lane fits a prior denial is a judgment call for an accredited representative.',
      category: 'process',
      condition_name: 'Migraine headaches',
      impact: 'medium',
      link: '/appeals',
    },
  ],
  has_conditions: true,
  disclaimer:
    'Educational organizing only. Veteran-Ops does not file claims, represent you, diagnose you, or predict a VA decision.',
  vso_referral:
    'A VA-accredited representative or VSO can review this plan with you at no cost — recommended, not required.',
  source_note: 'Built from the records you uploaded and the conditions you entered.',
  briefing: {
    headline: 'One appointment is holding up the strongest part of your file.',
    paragraphs: [
      'Your service connection is established for three conditions, and your combined rating currently reads 50%. The open work is not paperwork volume — it is two specific pieces of evidence and one conversation with a representative.',
      'The sleep-apnea claim is the clearest example. The diagnosis is documented in your own records. What is missing is a medical opinion connecting it to your service-connected PTSD, and only a qualified provider can write that.',
    ],
    strengths: [
      'Service connection already established for three conditions',
      'Sleep study on file supports the current diagnosis',
      'An intent to file is active, which protects an effective date while you gather evidence',
    ],
    watch_outs: [
      'Two musculoskeletal entries may describe the same impairment (38 CFR 4.14)',
      'Requesting an increase re-opens a stable rating to review (38 CFR 3.344)',
      'TDIU depends on employment facts this software cannot see',
    ],
    generated_by: 'local',
  },
  condition_lines: [
    {
      id: CONDITION_IDS.ptsd,
      name: 'PTSD',
      claim_type: 'increase',
      status: 'gathering',
      va_status: 'service_connected',
      band: 'strong',
      band_label: 'Well documented',
      ready: false,
      missing: ['Current severity evidence'],
      current_rating: 30,
      target_rating: 50,
      link: `/conditions/${CONDITION_IDS.ptsd}`,
    },
    {
      id: CONDITION_IDS.back,
      name: 'Lumbosacral strain',
      claim_type: 'increase',
      status: 'gathering',
      va_status: 'service_connected',
      band: 'building',
      band_label: 'Getting there',
      ready: false,
      missing: ['Current range-of-motion measurements'],
      current_rating: 10,
      target_rating: 20,
      link: `/conditions/${CONDITION_IDS.back}`,
    },
    {
      id: CONDITION_IDS.tinnitus,
      name: 'Tinnitus',
      claim_type: 'existing',
      status: 'ready',
      va_status: 'service_connected',
      band: 'complete',
      band_label: 'Nothing outstanding',
      ready: true,
      missing: [],
      current_rating: 10,
      target_rating: 10,
      link: `/conditions/${CONDITION_IDS.tinnitus}`,
    },
    {
      id: CONDITION_IDS.apnea,
      name: 'Sleep apnea',
      claim_type: 'secondary',
      status: 'gathering',
      va_status: 'unknown',
      band: 'building',
      band_label: 'Getting there',
      ready: false,
      missing: ['Medical nexus opinion'],
      current_rating: null,
      target_rating: 50,
      link: `/conditions/${CONDITION_IDS.apnea}`,
    },
    {
      id: CONDITION_IDS.migraine,
      name: 'Migraine headaches',
      claim_type: 'new',
      status: 'considering',
      va_status: 'denied',
      band: 'early',
      band_label: 'Just started',
      ready: false,
      missing: ['Frequency of prostrating attacks'],
      current_rating: null,
      target_rating: 30,
      link: `/conditions/${CONDITION_IDS.migraine}`,
    },
  ],
  money: {
    current_combined: 50,
    current_monthly: 1102,
    basis: 'VA compensation rate table for the selected year, veteran alone. Illustrative only — VA determines what you are paid.',
    rate_year: 2026,
  },
  process_roadmap: [
    { key: 'gather', title: 'Gather your record', body: 'Upload what you have; request what you do not.', state: 'done' },
    { key: 'read', title: 'Read the whole file', body: 'Full-file review, condition by condition.', state: 'done' },
    { key: 'gaps', title: 'Close the gaps', body: 'Two pieces of evidence are open right now.', state: 'now' },
    { key: 'review', title: 'Review with a human', body: 'A free VA-accredited VSO can file it with you.', state: 'upcoming' },
  ],
  focus: {
    title: 'The sleep-apnea nexus opinion',
    why: 'It is the only open item that depends on someone else’s calendar.',
    link: '/nexus',
  },
  cautions: [
    {
      key: 'pyramiding',
      kind: 'pyramiding',
      title: 'Two musculoskeletal entries may describe one impairment',
      body: 'VA does not rate the same impairment twice. Raising this with a representative before filing avoids a confusing decision later.',
      reg: '38 CFR 4.14',
      conditions: ['Lumbosacral strain', 'Right knee strain'],
      severity: 'medium',
    },
    {
      key: 'reduction',
      kind: 'reduction',
      title: 'Asking for an increase re-opens a stable rating',
      body: 'A review can go down as well as up. This is a trade-off to weigh with a representative — not a reason to avoid filing.',
      reg: '38 CFR 3.344',
      conditions: ['PTSD', 'Lumbosacral strain'],
      severity: 'medium',
    },
  ],
  tdiu: caseBrief.tdiu,
  opportunities: [
    {
      key: 'secondary-apnea',
      kind: 'secondary',
      title: 'Sleep apnea as secondary to PTSD',
      body: 'A recognized secondary theory. It still needs its own medical nexus opinion — this app cannot supply one.',
      reg: '38 CFR 3.310',
      primary: ['PTSD'],
      secondary: 'Sleep apnea',
      needs_nexus: true,
      severity: 'high',
      pathway: 'secondary',
      form: 'VA Form 21-526EZ',
      attach_checklist: ['Sleep study', 'Signed medical opinion'],
    },
    {
      key: 'reclaim-migraine',
      kind: 'reclaim',
      title: 'Previously denied migraines',
      body: 'A prior denial can sometimes be revisited with new and relevant evidence. Which lane applies is a question for an accredited representative.',
      reg: '38 CFR 3.156',
      primary: ['Migraine headaches'],
      secondary: 'Migraine headaches',
      needs_nexus: false,
      severity: 'medium',
      pathway: 'supplemental',
      form: 'VA Form 20-0995',
      attach_checklist: ['Headache log', 'Any new treatment records'],
    },
  ],
  coach,
}

const deepDive = {
  generated_at: '2026-07-20T12:00:00Z',
  candidates: [],
  candidates_considered: 0,
  findings: [],
  projected_combined: 50,
  current_combined: 50,
  delta: 0,
  notes: [
    'Run the rating deep dive to compare your entered target ratings against the criteria in your own records.',
  ],
  notification: null,
}

const interviewSeed = {
  mode: 'post_analysis',
  opening:
    'I read the whole file. Before you work the plan, there are a few things your records cannot tell me — work impact, what a bad week actually looks like, and what you are hoping to change. Educational only; I never file anything for you.',
  starter_user_message:
    'I just finished a full case review. Please interview me about the real gaps in my file and then give me an ordered next-step plan.',
  questions: [
    {
      id: 'work',
      topic: 'Work impact',
      question: 'How do your conditions affect your ability to work reliably week to week?',
      why: 'Work impact can change which questions belong in your plan.',
    },
    {
      id: 'evidence',
      topic: 'Evidence',
      question: 'Which symptoms or limitations are hardest to find in your records?',
      why: 'Your lived experience may point to a record gap.',
    },
    {
      id: 'goals',
      topic: 'Goals',
      question: 'What would a good outcome actually change in your day-to-day life?',
      why: 'Goals decide which trade-offs are worth taking to a representative.',
    },
  ],
  closing_hint: 'When you are ready, open Claim Plan for the ordered next steps.',
}

/**
 * A short, obviously-synthetic assistant turn. Written to demonstrate the
 * product's voice: one question at a time, plain language, and an explicit
 * hand-off to a human. It makes no promise about any VA outcome.
 */
const raiderAnswer = [
  'Understood — thank you. Let me start with the one your file cannot answer.',
  '',
  '**How many days in a typical month do your symptoms keep you from working a full day?**',
  '',
  'I ask because work impact changes which questions belong in your plan. It is also the single fact an accredited representative will ask you first if TDIU ever comes up — and TDIU is a conversation for them, not a determination I can make.',
  '',
  'A rough number is fine. If it varies a lot by month, tell me the good month and the bad month.',
].join('\n')

function sse(): string {
  const frames: string[] = []
  frames.push(`data: ${JSON.stringify({ type: 'tool', name: 'read_case_file', status: 'start' })}\n\n`)
  frames.push(`data: ${JSON.stringify({ type: 'tool', name: 'read_case_file', status: 'done' })}\n\n`)
  frames.push(`data: ${JSON.stringify({ type: 'token', text: raiderAnswer })}\n\n`)
  frames.push(`data: ${JSON.stringify({ type: 'done' })}\n\n`)
  return frames.join('')
}

/* ────────────────────────  BROWSER-LOCAL SEED (Raider)  ───────────────────── */

/** Two prior conversations so "Past chats" is populated, exactly as the
 * browser-local store would hold them after real use on one device. */
export const PAST_CHATS = [
  {
    id: '00000000-0000-0000-0000-000000000301',
    title: 'What does "nexus" actually mean?',
    createdAt: '2026-07-18T15:04:00Z',
    updatedAt: '2026-07-18T15:22:00Z',
    kind: 'general' as const,
    messages: [
      { id: 1, role: 'user' as const, content: 'What does "nexus" actually mean?' },
      {
        id: 2,
        role: 'assistant' as const,
        content:
          'A nexus is the medical link between something that happened in service and a condition you have now. A qualified provider writes and signs it — I can help you prepare for that appointment, but I cannot write or sign it for you.',
      },
    ],
  },
  {
    id: '00000000-0000-0000-0000-000000000302',
    title: 'Should I file before I have the sleep study?',
    createdAt: '2026-07-19T09:11:00Z',
    updatedAt: '2026-07-19T09:30:00Z',
    kind: 'general' as const,
    messages: [
      { id: 1, role: 'user' as const, content: 'Should I file before I have the sleep study?' },
      {
        id: 2,
        role: 'assistant' as const,
        content:
          'That is a timing judgment an accredited representative should make with you — it depends on your intent-to-file date and what you can gather before a decision. Here is what each option would mean, so the conversation with them is a short one.',
      },
    ],
  },
]

/* ──────────────────────────────  ROUTE INSTALL  ────────────────────────────── */

/** Sign the synthetic session in and dismiss the one-time disclaimer modal so
 * the capture shows the working product rather than a first-run overlay. The
 * standing pro-se disclaimer stays visible in every screenshot. */
export async function seedSession(page: Page, opts: { pastChats?: boolean } = {}) {
  const chats = opts.pastChats ? PAST_CHATS : []
  await page.addInitScript(
    ({ chats }) => {
      sessionStorage.setItem('vo_token', 'synthetic-auth-token')
      localStorage.setItem('vo_disclaimer_ack', '1')
      localStorage.setItem('vo_disclaimer_footer_dismissed', '1')
      localStorage.setItem('vo_theme', 'dark')
      if (chats.length) {
        localStorage.setItem(['vo', 'raider', 'conversations', 'v1'].join('_'), JSON.stringify(chats))
      }
    },
    { chats },
  )
}

/** Every API response the gallery needs, all synthetic. Anything not listed
 * 404s loudly so a new screenshot cannot silently fall back to real data. */
export async function installSyntheticApi(page: Page) {
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname

    // account + shell
    if (path === '/api/auth/config') return json(route, authConfig)
    if (path === '/api/auth/me') return json(route, me)
    if (path === '/api/workspaces') return json(route, workspaces)
    if (path === '/api/entitlements') return json(route, entitlements)
    if (path === '/api/meta') return json(route, meta)
    if (path === '/api/profile') return json(route, profile)
    if (path === '/api/profile/identity-suggestions') return json(route, { suggestions: [] })
    if (path === '/api/profile/location-suggestions') return json(route, { locations: [], disclaimer: '' })

    // conditions + evidence
    if (path === '/api/conditions') return json(route, conditions)
    if (path === '/api/conditions/duplicates') return json(route, duplicates)
    const evidenceMatch = path.match(/^\/api\/conditions\/([^/]+)\/evidence$/)
    if (evidenceMatch) return json(route, evidenceByCondition[evidenceMatch[1]] ?? [])
    if (path === '/api/checklist') return json(route, [])

    // claim plan
    if (path === '/api/strategy') return json(route, strategy)
    if (path === '/api/strategy/deepdive') return json(route, deepDive)
    if (path === '/api/strategy/case-brief') return json(route, caseBrief)
    if (path === '/api/strategy/decision-statuses') {
      return json(route, { dry_run: true, updated: 0, updates: [] })
    }

    // analysis center
    if (path === '/api/analysis/comprehensive/latest') return json(route, null)
    if (path === '/api/analysis/case-picture') return json(route, null)
    if (path === '/api/analysis/comprehensive/runs') return json(route, [])
    if (path === '/api/analysis/comprehensive/prerequisites') {
      return json(route, {
        ready: true,
        conditions: conditions.length,
        ready_documents: 4,
        processing_documents: 0,
        failed_documents: 0,
        missing: [],
      })
    }
    if (path === '/api/analysis/automation-status') {
      return json(route, {
        deep_dive: { last_run: null, has_new_findings: false, auto_on_intake: false },
        comprehension: { available: false, generated_at: null, auto_on_intake: false },
        verification: { flagged_docs: 0, enabled: true },
        cross_read: { disagreement_pages: 0 },
        review_queue: { pending: 0 },
        automations: [],
      })
    }
    if (path === '/api/analysis/intake-benchmark') {
      return json(route, {
        documents: 4,
        ready: 4,
        failed: 0,
        processing: 0,
        duplicates: 0,
        total_bytes: 4_194_304,
        total_processing_seconds: 38,
        wall_clock_seconds: 22,
        avg_seconds_per_doc: 9.5,
        first_uploaded_at: '2026-07-20T00:00:00Z',
        last_ready_at: '2026-07-20T00:00:22Z',
      })
    }

    // rating raider
    if (path === '/api/raider/status') return json(route, { available: true })
    if (path === '/api/raider/interview-seed') return json(route, interviewSeed)
    if (path === '/api/raider/chat' && request.method() === 'POST') {
      return route.fulfill({
        status: 200,
        headers: { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' },
        body: sse(),
      })
    }

    // optional integrations the gallery deliberately shows as "not connected"
    if (path === '/api/glitter/status') return json(route, { connected: false })
    if (path === '/api/glitter/conditions') return json(route, [])

    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: '{"detail":"no synthetic fixture for this route"}',
    })
  })
}
