/**
 * "Your VA journey" — the cradle-to-grave stage model.
 *
 * Veterans arrive at Rating Raider at wildly different points: someone still in
 * uniform locking in a Benefits Delivery at Discharge date, someone who filed a
 * decade ago and got shorted, a survivor after a veteran passes. The app already
 * has a feature for almost every one of those moments — but scattered across the
 * nav as separate pages. This module is the unifying spine: one ordered list of
 * stages, each pointing at the built feature that serves it, plus a best-effort
 * detector that guesses where a given veteran is standing right now.
 *
 * Legal lane: every stage is framed as "organize and prepare" — the veteran
 * decides and files. Nothing here predicts a VA decision or promises an outcome.
 *
 * PURE module — no React, no side effects. The icon field holds a lucide
 * component *reference* (a value, not JSX), so this stays a plain .ts file.
 */

import {
  ClipboardList,
  Compass,
  FileCheck2,
  Flag,
  HeartHandshake,
  Hourglass,
  RefreshCw,
  Scale,
  ShieldCheck,
  Users,
  type LucideIcon,
} from 'lucide-react'
import type { Hue } from './hues'
import type { ClaimedCondition, Profile } from '../types'

export type JourneyStageId =
  | 'transitioning'
  | 'never_filed'
  | 'building'
  | 'ready_to_file'
  | 'filed_waiting'
  | 'rated'
  | 'denied'
  | 'life_changes'
  | 'ongoing'
  | 'survivors'

/** A related feature to surface as a secondary link under a stage. */
export interface JourneyLink {
  label: string
  route: string
}

export interface JourneyStage {
  id: JourneyStageId
  /** 1-based position on the timeline. */
  order: number
  /** Plain-language stage name. */
  title: string
  /** One-line description of the moment this stage represents. */
  tagline: string
  hue: Hue
  icon: LucideIcon
  /** Veteran-facing "what this step is." */
  whatItIs: string
  /** Veteran-facing "what to do" — the concrete next move. */
  whatToDo: string
  /** The primary in-app feature that serves this stage. `null` = not built yet
   * (rendered as an honest "coming soon", never a dead link). */
  route: string | null
  /** Label for the primary CTA. */
  cta: string
  /** True when there's no built feature for this stage yet. */
  comingSoon?: boolean
  /** An honest off-app reference (e.g. a VA.gov page) for coming-soon stages —
   * this is real, not a dead internal route. */
  externalHref?: string
  externalLabel?: string
  /** Other built features relevant at this stage. */
  also?: JourneyLink[]
}

/**
 * The stages, cradle to grave. Order is the veteran's arc; detection can land on
 * any of them and the whole path stays visible so they see what's behind and
 * ahead.
 */
export const JOURNEY_STAGES: JourneyStage[] = [
  {
    id: 'transitioning',
    order: 1,
    title: 'Transitioning or just separated',
    tagline: 'Still in, or newly out — review filing dates and transition options.',
    hue: 'sky',
    icon: Compass,
    whatItIs:
      'An effective date can affect when VA starts a benefit. An Intent to File may preserve a potential date while you get organized, and Benefits Delivery at Discharge has its own pre-separation timing rules.',
    whatToDo:
      'Review the Intent to File and Benefits Delivery at Discharge timing, confirm the right option with VA or a VSO, and organize your service history.',
    route: '/itf',
    cta: 'Review Intent to File',
    also: [
      { label: 'Connect your VA data', route: '/va-sync' },
      { label: 'Bring in your records', route: '/documents' },
    ],
  },
  {
    id: 'never_filed',
    order: 2,
    title: 'Never filed a claim',
    tagline: 'First time — turn your records into a conditions list.',
    hue: 'emerald',
    icon: Flag,
    whatItIs:
      'A claim identifies the conditions you want VA to review. You can begin by privately recording symptoms, diagnoses, and possible service connections, then confirm the filing and evidence requirements.',
    whatToDo:
      'Add the conditions you are tracking, or upload records so Rating Raider can surface mentions for you to confirm. Review whether an Intent to File is appropriate while you organize.',
    route: '/conditions',
    cta: 'Start your conditions list',
    also: [
      { label: 'Set up your profile', route: '/profile' },
      { label: 'File an Intent to File', route: '/itf' },
      { label: 'Bring in your records', route: '/documents' },
      { label: 'Populate case from records', route: '/build-case' },
    ],
  },
  {
    id: 'building',
    order: 3,
    title: 'Building the claim',
    tagline: 'Evidence, DBQs, and the nexus that ties it to service.',
    hue: 'teal',
    icon: ClipboardList,
    whatItIs:
      'For direct service connection, VA generally reviews evidence of a current condition, an in-service event or exposure, and a connection between them. Other claim types can use different rules.',
    whatToDo:
      'Organize records, log symptoms accurately over time, and review whether a provider opinion or DBQ could address a documented gap.',
    route: '/evidence',
    cta: 'Build your evidence',
    also: [
      { label: 'Check your readiness', route: '/readiness' },
      { label: 'Prepare a nexus letter', route: '/nexus' },
      { label: 'Keep a symptom log', route: '/symptom-log' },
    ],
  },
  {
    id: 'ready_to_file',
    order: 4,
    title: 'Ready to file',
    tagline: 'Evidence in hand — prepare the official form.',
    hue: 'indigo',
    icon: FileCheck2,
    whatItIs:
      'VA Form 21-526EZ is the disability-compensation application. Rating Raider can prepare a draft from the information you organized; you review every line and decide whether to file it.',
    whatToDo:
      'Open the prepared 21-526EZ, check every line, and review whether a factual personal or buddy statement would add useful context.',
    route: '/application',
    cta: 'Open your pre-filled 21-526EZ',
    also: [
      { label: 'Read the filing guide', route: '/filing' },
      { label: 'Write a personal statement', route: '/statement' },
      { label: 'Add a buddy statement', route: '/buddy' },
    ],
  },
  {
    id: 'filed_waiting',
    order: 5,
    title: 'Filed and waiting',
    tagline: 'Track the status and get ready for the C&P exam.',
    hue: 'amber',
    icon: Hourglass,
    whatItIs:
      'After filing, a claim moves through VA’s stages and may include a Compensation & Pension (C&P) exam. You can track available status information and prepare to describe your symptoms accurately.',
    whatToDo:
      'Track your claim status from your connected VA account, and use the C&P companion to know what to expect and how to describe your symptoms honestly.',
    route: '/claims',
    cta: 'Track your claim status',
    also: [
      { label: 'Prepare for your C&P exam', route: '/cp-companion' },
      { label: 'Connect your VA data', route: '/va-sync' },
    ],
  },
  {
    id: 'rated',
    order: 6,
    title: 'Rated',
    tagline: 'Review the decision, criteria, and possible next questions.',
    hue: 'fuchsia',
    icon: ShieldCheck,
    whatItIs:
      'A decision came back. Compare the listed conditions, percentages, reasons, and effective dates with your records. A Claim Plan can then organize questions about increases, secondary conditions, and TDIU.',
    whatToDo:
      'Open your Claim Plan to review possible paths and evidence questions, and use the calculator to model how hypothetical changes combine.',
    route: '/strategy',
    cta: 'Open your Claim Plan',
    also: [
      { label: 'Explore secondary conditions', route: '/secondaries' },
      { label: 'Look at TDIU (unemployability)', route: '/tdiu' },
      { label: 'Combined ratings calculator', route: '/calculator' },
    ],
  },
  {
    id: 'denied',
    order: 7,
    title: 'Denied or shorted',
    tagline: 'Decision reviews: Supplemental, Higher-Level, or Board.',
    hue: 'rose',
    icon: Scale,
    whatItIs:
      'If you disagree with a decision, VA offers three review lanes: a Supplemental Claim, a Higher-Level Review, or a Board Appeal. They handle evidence differently and important deadlines may apply.',
    whatToDo:
      'Decode the decision letter, compare all three review lanes, and prepare the option you choose. Confirm the deadline shown in your letter or with an accredited representative.',
    route: '/appeals',
    cta: 'Review your appeal options',
    also: [
      { label: 'Decode your decision letter', route: '/decode' },
      { label: 'Correct your military records', route: '/corrections' },
    ],
  },
  {
    id: 'life_changes',
    order: 8,
    title: 'Life changes',
    tagline: 'Dependents, address, and name updates.',
    hue: 'violet',
    icon: Users,
    whatItIs:
      'Marriage, a new child, divorce, a move, or a name change may affect VA records or payments. Adding or removing a dependent generally uses VA Form 21-686c.',
    whatToDo:
      'Prepare a dependents worksheet when your family changes, and keep your profile current so every form pre-fills correctly.',
    route: '/dependency',
    cta: 'Update your dependents',
    also: [
      { label: 'Update your profile', route: '/profile' },
      { label: 'Correct a name or record', route: '/corrections' },
    ],
  },
  {
    id: 'ongoing',
    order: 9,
    title: 'Ongoing',
    tagline: 'Re-check when rules change and review long-held ratings.',
    hue: 'cyan',
    icon: RefreshCw,
    whatItIs:
      'Rules, presumptive conditions, and related benefit programs can change over time. If you also draw military retired pay, CRDP or CRSC may be worth reviewing with DFAS or your branch.',
    whatToDo:
      'Revisit the published rules when your circumstances change. Review concurrent-pay criteria if you receive military retired pay, and let DFAS or your branch make the program determination.',
    route: '/benefits',
    cta: 'Re-check your benefits',
    also: [
      { label: 'Concurrent pay (CRDP / CRSC)', route: '/concurrent-pay' },
      { label: 'Check new presumptives', route: '/presumptives' },
      { label: 'Revisit your Claim Plan', route: '/strategy' },
    ],
  },
  {
    id: 'survivors',
    order: 10,
    title: 'Survivors',
    tagline: 'DIC and burial benefits for family.',
    hue: 'pink',
    icon: HeartHandshake,
    whatItIs:
      'When a veteran passes, surviving family may be eligible for Dependency and Indemnity Compensation (DIC), pension, education, or burial benefits. These use different forms and rules from a veteran’s own claim.',
    whatToDo:
      'Open the survivors guide to see what DIC, a survivors pension, burial benefits, and education (Chapter 35) a family may be eligible for — and the official form for each. A VSO can help a survivor file every one at no cost.',
    route: '/survivors',
    cta: 'Explore survivors benefits',
  },
]

/** Ordered stage ids, for timeline math. */
export const JOURNEY_STAGE_IDS: JourneyStageId[] = JOURNEY_STAGES.map((s) => s.id)

export function getStage(id: JourneyStageId): JourneyStage {
  const stage = JOURNEY_STAGES.find((s) => s.id === id)
  // Every id in the union is present in JOURNEY_STAGES; the fallback keeps the
  // signature total for the type checker.
  return stage ?? JOURNEY_STAGES[0]
}

/** Result of best-effort stage detection. `confident:false` = we could not tell
 * from the data on hand and the veteran should pick their own starting point. */
export interface StageDetection {
  stageId: JourneyStageId
  confident: boolean
}

export interface StageDetectionInput {
  profile: Profile | null
  /** Pass the app's isEmptyProfile(profile) result so detection agrees with the
   * rest of the app about what "no profile yet" means. */
  profileIsEmpty: boolean
  conditions: ClaimedCondition[]
  /** Whether the veteran has an active Intent to File (VA connector or tracked). */
  itfActive: boolean
}

/** Separated within the last ~6 months, or a future/near separation date (the
 * BDD window while still in uniform). Either way: the "transitioning" moment. */
function isTransitioning(profile: Profile | null): boolean {
  if (!profile) return false
  const now = Date.now()
  const WINDOW_MS = 180 * 24 * 60 * 60 * 1000
  // service_periods can come back null from the API (e.g. a profile whose only
  // inputs were cleared) even though the type says array — guard it so the
  // journey spine never crashes the whole Dashboard.
  return (profile.service_periods ?? []).some((p) => {
    if (!p.end_date) return false
    const t = new Date(p.end_date).getTime()
    if (Number.isNaN(t)) return false
    // Recent past (within the window) OR any future date (still in / about to separate).
    return t >= now - WINDOW_MS
  })
}

/**
 * Best-effort: infer the veteran's CURRENT stage from data already on the client.
 * Deliberately not over-fit — it returns a single "you look like you're around
 * here" and the page always lets them pick a different stage.
 *
 * Precedence walks the claim lifecycle from the freshest live moment backward:
 * a claim actively in the VA's hands (filed/pending) is the most immediate
 * "now", then a decision that came back short (denied), then a standing rating,
 * then the pre-file build states, then the cold-start states.
 */
export function detectStage({
  profile,
  profileIsEmpty,
  conditions,
  itfActive,
}: StageDetectionInput): StageDetection {
  const rating = profile?.current_combined_rating ?? 0
  const hasRating = rating > 0
  const conds = conditions ?? []
  const anyDenied = conds.some((c) => c.va_status === 'denied')
  const anyServiceConnected = conds.some((c) => c.va_status === 'service_connected')
  const anyPending = conds.some((c) => c.va_status === 'pending')
  const anyFiled = conds.some((c) => c.status === 'filed')
  const anyReady = conds.some((c) => c.status === 'ready_to_file')
  const hasConditions = conds.length > 0

  const confident = (stageId: JourneyStageId): StageDetection => ({ stageId, confident: true })

  // A claim is actively in the VA's hands — the "filed, waiting" moment.
  if (anyFiled || anyPending) return confident('filed_waiting')
  // A decision came back and something was denied/shorted — the pressing move.
  if (anyDenied) return confident('denied')
  // A standing rating (combined %, or a service-connected condition) — grow it.
  if (hasRating || anyServiceConnected) return confident('rated')
  // Conditions staged as ready to file — the official form is next.
  if (anyReady) return confident('ready_to_file')
  // Conditions on the list but not yet ready — still building evidence.
  if (hasConditions) return confident('building')
  // No conditions yet: distinguish the just-separated veteran from a cold start.
  if (isTransitioning(profile) && !itfActive) return confident('transitioning')
  // Has some setup (an ITF or a filled profile) but no conditions — first claim.
  if (itfActive || !profileIsEmpty) return confident('never_filed')
  // Nothing to go on — ask them where they are.
  return { stageId: 'never_filed', confident: false }
}
