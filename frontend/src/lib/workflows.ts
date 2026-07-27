/**
 * Defined workflows — the "pick your situation" spine.
 *
 * Veterans don't think in features ("Nexus organizer", "TDIU screener"); they
 * think in moments ("the VA denied me — now what?", "what am I missing?"). The
 * app already has a built feature for almost every one of those moments, but
 * scattered across the nav. This module is the bridge: 15 named workflows drawn
 * from real veteran research (docs/research/veteran-workflows-research-2026-07),
 * each pointing — in the right order — at the existing route(s) that serve it.
 *
 * We are WIRING existing features into guided flows, not building engines. Every
 * `route` below is confirmed to exist in App.tsx. A step with no built feature
 * carries `route: null` and is rendered as an honest off-app pointer, never a
 * dead link.
 *
 * Legal lane: every workflow organizes and educates, then routes the veteran to
 * self-file on VA.gov or to a free VA-accredited VSO. Nothing here files,
 * diagnoses, represents, or predicts a VA outcome. The `lane` field mirrors the
 * research's sensitivity key so the UI can reinforce "your call" on the flows
 * that touch medical/eligibility judgment.
 *
 * PURE module — no React, no side effects. `icon` holds a lucide component
 * *reference* (a value, not JSX), so this stays a plain .ts file (journey.ts
 * pattern).
 */

import {
  AlarmClock,
  Briefcase,
  Calculator,
  ClipboardCheck,
  ClipboardList,
  Gavel,
  Hourglass,
  LifeBuoy,
  MessageSquareQuote,
  ScanText,
  Shield,
  Sparkles,
  Stethoscope,
  TrendingUp,
  UserPlus,
  type LucideIcon,
} from 'lucide-react'
import type { Hue } from './hues'

/** 1 = start here, 2 = build next, 3 = steady value / trust / retention. */
export type WorkflowTier = 1 | 2 | 3

/** Research legal-lane key: green = deterministic/education; amber =
 * organize-and-educate (guard against advice/prediction); red = high-sensitivity
 * (diagnosis / eligibility / outcome-adjacent — hard "your call" guardrails). */
export type WorkflowLane = 'green' | 'amber' | 'red'

/** One ordered step in a workflow — a link to an EXISTING in-app route. */
export interface WorkflowStep {
  /** Short action label ("Review your filing date"). */
  label: string
  /** One line: what the veteran does at this step. */
  detail: string
  /** The in-app route this step opens. `null` = no built feature yet (honest —
   * rendered with the external pointer below, never a dead link). */
  route: string | null
  /** Honest off-app reference for a step with no built route (real, not a dead
   * internal link). */
  externalHref?: string
  externalLabel?: string
}

export interface Workflow {
  id: string
  /** Plain-language workflow name. */
  title: string
  /** The veteran's trigger(s), in their own words. */
  triggers: string[]
  /** One line: what this workflow does for them. */
  whatItDoes: string
  tier: WorkflowTier
  hue: Hue
  icon: LucideIcon
  lane: WorkflowLane
  /** Ordered steps, each linking a built route (first is the deep-link target). */
  steps: WorkflowStep[]
  /** Key forms / regs, shown as quiet reference chips. */
  refs?: string[]
  /** Set when this workflow surfaces the guided appeal-lane chooser (workflow 3 —
   * the one decision-tree the app otherwise lacks). */
  laneChooser?: boolean
  /** True when no built feature backs this workflow at all (marked honestly).
   * None of the 15 currently — every workflow maps to a shipped route. */
  comingSoon?: boolean
}

/**
 * The 15 workflows, ranked by (frequency × impact) per the research, grouped by
 * tier. Route mappings confirmed against App.tsx.
 */
export const WORKFLOWS: Workflow[] = [
  // ───────────────────────── TIER 1 — start here ─────────────────────────
  {
    id: 'intent-to-file',
    title: 'Review an Intent to File',
    triggers: [
      'I want to file but I need to gather my records first.',
      'I got out years ago and didn’t know I could file.',
    ],
    whatItDoes:
      'Understand how an Intent to File may preserve a potential effective date while you gather records, then confirm the deadline before filing.',
    tier: 1,
    hue: 'teal',
    icon: AlarmClock,
    lane: 'green',
    steps: [
      { label: 'Review your Intent to File options', detail: 'See the one-year window, what gets submitted, and where to confirm it with VA.', route: '/itf' },
      { label: 'Start your conditions list', detail: 'Record the conditions and symptoms you may want VA or a VSO to review.', route: '/conditions' },
    ],
    refs: ['VA Form 21-0966', '38 CFR 3.155', '38 CFR 3.400'],
  },
  {
    id: 'build-my-claim',
    title: 'Build my claim',
    triggers: ['I want to file for my back and knees — what do I actually need?'],
    whatItDoes:
      'Turn “I have a bad back” into an organized record of the diagnosis, in-service event or exposure, and connection evidence VA may review.',
    tier: 1,
    hue: 'emerald',
    icon: ClipboardList,
    lane: 'amber',
    steps: [
      { label: 'List your conditions', detail: 'Name each condition you want the VA to look at.', route: '/conditions' },
      { label: 'Organize the evidence', detail: 'For each condition, gather records about diagnosis, service, symptoms, and any nexus opinion.', route: '/evidence' },
      { label: 'Review possible gaps', detail: 'Compare what you have with the evidence categories VA commonly reviews.', route: '/readiness' },
      { label: 'Prepare the application', detail: 'Pre-fill your 21-526EZ from what you’ve organized, then review and file.', route: '/application' },
    ],
    refs: ['VA Form 21-526EZ', 'VA Form 21-4142', '38 CFR 3.303', '38 CFR 3.304'],
  },
  {
    id: 'denied-now-what',
    title: 'Denied or lowballed — now what?',
    triggers: [
      'The VA denied me — do I appeal or start over?',
      'I got 30% and I think it should be higher.',
    ],
    whatItDoes:
      'Answer two questions to narrow the decision-review lanes worth comparing — then decode the letter and prepare a draft response.',
    tier: 1,
    hue: 'rose',
    icon: Gavel,
    lane: 'red',
    laneChooser: true,
    steps: [
      { label: 'Decode your decision letter', detail: 'See exactly what was denied or deferred, and why.', route: '/decode' },
      { label: 'Prepare a decision-review draft', detail: 'Organize a Supplemental Claim, Higher-Level Review, or Board Appeal draft for your review.', route: '/appeals' },
    ],
    refs: ['VA Form 20-0995', 'VA Form 20-0996', 'VA Form 10182', '38 CFR 3.2500', '1-year deadline'],
  },
  {
    id: 'under-rated',
    title: 'Am I being under-rated?',
    triggers: [
      'I got 30%, I think it should be higher.',
      'What does “deferred” mean?',
    ],
    whatItDoes:
      'Read your rating decision line by line and compare each granted condition with the published criteria for other rating levels.',
    tier: 1,
    hue: 'fuchsia',
    icon: ScanText,
    lane: 'amber',
    steps: [
      { label: 'Decode your decision letter', detail: 'Walk your rating decision section by section — granted, deferred, denied.', route: '/decode' },
      { label: 'Open your Claim Plan', detail: 'Compare the recorded evidence with the published criteria for nearby rating levels.', route: '/strategy' },
    ],
    refs: ['38 CFR 4.130', '38 CFR 4.124a', '38 CFR 4.71a'],
  },
  {
    id: 'secondary-finder',
    title: 'What am I missing? (secondaries)',
    triggers: [
      'I have PTSD and a bad back — what else can I claim?',
      'They denied my sleep apnea secondary to PTSD — is that even a thing?',
    ],
    whatItDoes:
      'See the conditions veterans commonly explore as secondary to what you already have — as topics to raise with your doctor.',
    tier: 1,
    hue: 'pink',
    icon: Sparkles,
    lane: 'red',
    steps: [
      { label: 'Find your secondaries', detail: 'Surface commonly-associated conditions to discuss with your clinician.', route: '/secondaries' },
      { label: 'Organize the evidence', detail: 'For each, gather a current diagnosis and a nexus (causation and aggravation).', route: '/evidence' },
      { label: 'Prepare a nexus letter', detail: 'Assemble a packet your own provider can turn into an opinion.', route: '/nexus' },
    ],
    refs: ['38 CFR 3.310', 'DC 7522 + SMC-K', 'DC 8520'],
  },
  {
    id: 'cp-exam-prep',
    title: 'Prep for my C&P exam',
    triggers: [
      'I have a C&P next week — what do I do?',
      'The examiner spent 10 minutes and wrote “full flexion” without testing me.',
    ],
    whatItDoes:
      'Prepare to describe your symptoms, functional limits, and flare-ups accurately — and organize your notes afterward.',
    tier: 1,
    hue: 'indigo',
    icon: ClipboardCheck,
    lane: 'red',
    steps: [
      { label: 'Prepare for your C&P', detail: 'Learn what the exam is, who runs it, and how to describe symptoms accurately.', route: '/cp-companion' },
      { label: 'Log your symptoms', detail: 'Track frequency, triggers, functional impact, and flare-ups in your own words.', route: '/symptom-log' },
      { label: 'Record concerns after the exam', detail: 'If something was missed or inaccurate, prepare your own factual account on Form 21-4138.', route: '/statement' },
    ],
    refs: ['38 CFR 3.655', '38 CFR 3.326', 'DBQ / ACE'],
  },

  // ───────────────────────── TIER 2 — build next ─────────────────────────
  {
    id: 'va-math',
    title: 'The VA math — why isn’t 50 + 30 = 80?',
    triggers: [
      'Why isn’t 50% + 30% = 80%?',
      'I added a condition and my rating didn’t go up.',
    ],
    whatItDoes:
      'See the combined-rating math on your own numbers and model how different percentages would combine.',
    tier: 2,
    hue: 'sky',
    icon: Calculator,
    lane: 'green',
    steps: [
      { label: 'Run the combined-rating math', detail: 'See the whole-person formula worked out (50 + 30 → 65 → 70).', route: '/calculator' },
      { label: 'Model a what-if', detail: 'Test how a hypothetical new or changed rating would combine.', route: '/scenarios' },
    ],
    refs: ['38 CFR 4.25', '38 CFR 4.26'],
  },
  {
    id: 'tdiu-readiness',
    title: 'Am I unemployable? (TDIU)',
    triggers: [
      'I’m at 90% but I can’t hold a job because of my back and migraines — everyone says file for TDIU but I don’t know how to start.',
    ],
    whatItDoes:
      'Learn how TDIU works, compare your recorded facts with its threshold rules, and organize an unemployability packet for review.',
    tier: 2,
    hue: 'amber',
    icon: Briefcase,
    lane: 'red',
    steps: [
      { label: 'Check your TDIU readiness', detail: 'Screen the schedular gateway and organize your 21-8940 and work history.', route: '/tdiu' },
    ],
    refs: ['VA Form 21-8940', 'VA Form 21-4192', '38 CFR 4.16(a)/(b)'],
  },
  {
    id: 'nexus-organizer',
    title: 'Denied for “no nexus” — what now?',
    triggers: ['Denied — “no nexus.” I’ve had this since Iraq in 2007. What else do they want?'],
    whatItDoes:
      'Understand the “at least as likely as not” standard and assemble a records packet for your own provider to review.',
    tier: 2,
    hue: 'orange',
    icon: Stethoscope,
    lane: 'red',
    steps: [
      { label: 'Prepare a nexus packet', detail: 'Organize the diagnosis, relevant records, medical question, and supporting rationale for a provider.', route: '/nexus' },
      { label: 'Review the Supplemental lane', detail: 'See how new and relevant evidence is handled in a Supplemental Claim.', route: '/appeals' },
    ],
    refs: ['38 CFR 3.303', '38 CFR 3.310', 'feeds VA Form 20-0995'],
  },
  {
    id: 'increase-safely',
    title: 'Review an increase',
    triggers: [
      'My condition got worse, but I’m scared that if I file they’ll cut my rating.',
      'I’m 100% and got a re-exam letter — are they dropping me?',
    ],
    whatItDoes:
      'Review re-examination considerations and the 5-, 10-, and 20-year rules that may affect how VA reviews a rating.',
    tier: 2,
    hue: 'cyan',
    icon: TrendingUp,
    lane: 'amber',
    steps: [
      { label: 'Weigh it in your Claim Plan', detail: 'Review the increase path and the protection rules that may apply to your ratings.', route: '/strategy' },
      { label: 'Log the worsening', detail: 'Gather new evidence that your condition got worse over time.', route: '/symptom-log' },
      { label: 'Prep for a re-exam', detail: 'If VA schedules a C&P, know how to describe your current state.', route: '/cp-companion' },
    ],
    refs: ['38 CFR 3.343', '38 CFR 3.344', '38 CFR 3.951', '38 CFR 3.957'],
  },
  {
    id: 'whats-changed-since-rated',
    title: 'See what changed since you were rated',
    triggers: [
      'I was rated years ago — did any rules change that could help me now?',
      'Is there anything new since my decision that I’m missing?',
    ],
    whatItDoes:
      'Compare your rating date with VA rule changes and new presumptives that took effect afterward, and flag the ones that touch your conditions or exposures — so you’re not relying on criteria that shifted under you.',
    tier: 2,
    hue: 'teal',
    icon: TrendingUp,
    lane: 'green',
    steps: [
      { label: 'See what changed since your rating', detail: 'Rule changes and new presumptives that took effect after your rating and touch your conditions or exposures — each with its source.', route: '/whats-changed' },
      { label: 'Weigh it in your Claim Plan', detail: 'If something applies, review the increase or new-claim path and the protection rules.', route: '/strategy' },
    ],
    refs: ['38 CFR Part 4', 'Federal Register', 'PACT Act'],
  },
  {
    id: 'presumptive-checker',
    title: 'Is my condition presumptive?',
    triggers: ['I was around burn pits — is my condition automatic?'],
    whatItDoes:
      'Compare your exposure, location, and dates with presumptive categories such as PACT Act, Agent Orange, Gulf War, and Camp Lejeune.',
    tier: 2,
    hue: 'lime',
    icon: Shield,
    lane: 'amber',
    steps: [
      { label: 'Check the presumptives', detail: 'Compare exposure, location, dates, and condition criteria without making an eligibility decision.', route: '/presumptives' },
      { label: 'Organize a possible claim', detail: 'Add the condition to your private list and gather the relevant service records for review.', route: '/conditions' },
    ],
    refs: ['38 CFR 3.307', '38 CFR 3.309', 'PACT Act (2022)'],
  },

  // ──────────────────── TIER 3 — steady value / trust ────────────────────
  {
    id: 'dependents',
    title: 'Add my spouse and kids',
    triggers: ['I just hit 30% — how do I add my spouse and kids?'],
    whatItDoes:
      'Review the 30% rating threshold, prepare Form 21-686c, and check how filing dates may affect a dependency payment.',
    tier: 3,
    hue: 'violet',
    icon: UserPlus,
    lane: 'green',
    steps: [
      { label: 'Prepare your dependents', detail: 'Confirm the 30% gate and build the 21-686c (and 21-674 for a child in school).', route: '/dependency' },
    ],
    refs: ['VA Form 21-686c', 'VA Form 21-674', '38 CFR 3.401'],
  },
  {
    id: 'buddy-statement',
    title: 'Prove it with a buddy statement',
    triggers: ['I was snoring in the barracks but it’s not in my records — how do I prove it years later?'],
    whatItDoes:
      'Draft a witness or personal statement that stays with specific, firsthand observations VA can consider.',
    tier: 3,
    hue: 'amber',
    icon: MessageSquareQuote,
    lane: 'amber',
    steps: [
      { label: 'Write a buddy statement', detail: 'Guide a witness to describe what they saw (21-10210) — facts, not conclusions.', route: '/buddy' },
      { label: 'Write your personal statement', detail: 'Put your own account of the event and its daily impact on 21-4138.', route: '/statement' },
    ],
    refs: ['VA Form 21-10210', 'VA Form 21-4138'],
  },
  {
    id: 'who-helps',
    title: 'Who should help me file?',
    triggers: ['Should I pay one of those companies that guarantee a rating?'],
    whatItDoes:
      'Understand accreditation, when fees may be allowed, why VSO help is free, and the warning signs of an unaccredited company.',
    tier: 3,
    hue: 'sky',
    icon: LifeBuoy,
    lane: 'green',
    steps: [
      { label: 'Read the filing guide', detail: 'Who can help, the fee rules, and the red flags of “we’ll get you to X%.”', route: '/filing' },
      {
        label: 'Find a free accredited VSO',
        detail: 'Search VA’s directory of accredited representatives — VFW, DAV, American Legion, your state office.',
        route: null,
        externalHref: 'https://www.va.gov/get-help-from-accredited-representative/',
        externalLabel: 'VA accredited-rep search',
      },
    ],
    refs: ['38 CFR 14.629', '38 CFR 14.636'],
  },
  {
    id: 'claim-tracker',
    title: 'What happens next? (claim tracker)',
    triggers: ['It’s been 3 months — is this normal or did they lose it?'],
    whatItDoes:
      'See the claim phases, available timeline information, what each stage means, and which updates may be useful while you wait.',
    tier: 3,
    hue: 'emerald',
    icon: Hourglass,
    lane: 'green',
    steps: [
      { label: 'Track your claim', detail: 'See where your claim stands, what each phase means, and what not to do.', route: '/claims' },
    ],
    refs: ['va.gov/disability/after-you-file-claim'],
  },
]

/** Tier metadata for the grouped hub ("Start here" / "Next" / "More"). */
export interface TierMeta {
  tier: WorkflowTier
  label: string
  blurb: string
}

export const WORKFLOW_TIERS: TierMeta[] = [
  { tier: 1, label: 'Start here', blurb: 'Common starting points: filing dates, evidence, decisions, and exam preparation.' },
  { tier: 2, label: 'Next', blurb: 'Rating math, TDIU education, nexus organization, increases, and presumptives.' },
  { tier: 3, label: 'More', blurb: 'Dependents, statements, accredited help, and claim tracking.' },
]

export function workflowsByTier(tier: WorkflowTier): Workflow[] {
  return WORKFLOWS.filter((w) => w.tier === tier)
}

/** Plain-language lane note — reinforces "your call" on the sensitive flows,
 * without VA jargon. Green flows need none (deterministic / education). */
export const LANE_NOTE: Record<WorkflowLane, string | null> = {
  green: null,
  amber: 'We organize and explain — you review, decide, and file.',
  red: 'Your call — we never diagnose, decide eligibility, or predict a rating.',
}
