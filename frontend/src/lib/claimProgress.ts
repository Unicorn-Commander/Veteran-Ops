/**
 * Single source of truth for "where is this veteran on the claim path?"
 *
 * Home next-step, claim spine chips, Journey rings, and Analysis "next rings"
 * all derive from `buildClaimProgress` / `resolveNextAction` so completion rules
 * and CTAs cannot drift.
 *
 * Soft suggestions (identity still available, checklist todos) NEVER reopen a
 * completed step.
 *
 * Legal lane: progress organizes and prepares; the veteran decides and files.
 */

export type ClaimStepId =
  | 'profile'
  | 'records'
  | 'review'
  | 'case'
  | 'analysis'
  | 'plan'
  | 'file'

export interface ClaimProgressInput {
  profileIsEmpty: boolean
  /** Total documents on file (including still processing). */
  docsTotal: number
  readyDocs: number
  /** Docs currently processing or queued. */
  processingDocs: number
  /** Pending review-queue items; null = unknown (do not treat as zero). */
  reviewPending: number | null
  conditionCount: number
  analysisDone: boolean
  hasPlan: boolean
  fileReady: boolean
  /** Optional side signal — not a main spine gate. */
  itfActive?: boolean
}

export interface ClaimProgressStep {
  id: ClaimStepId
  /** Short chip label */
  label: string
  /** Longer ring / list title */
  title: string
  detail: string
  route: string
  cta: string
  done: boolean
  /** Highlight as the single current focus */
  current: boolean
}

export interface NextClaimAction {
  stepId: ClaimStepId | 'processing' | 'done'
  title: string
  detail: string
  route: string
  cta: string
  /** When true, show a busy spinner on the CTA icon area */
  busy?: boolean
}

const STEP_COPY: Record<
  ClaimStepId,
  { label: string; title: string; detail: string; route: string; cta: string }
> = {
  profile: {
    label: 'Profile',
    title: 'Confirm your profile',
    detail: 'Identity and service history power forms, presumptives, and checklists.',
    route: '/profile?start=1',
    cta: 'Open profile',
  },
  records: {
    label: 'Records',
    title: 'Upload & process records',
    detail: 'C-file, decisions, STRs, and medical records — Rating Raider reads them privately.',
    route: '/documents',
    cta: 'Go to documents',
  },
  review: {
    label: 'Confirm',
    title: 'Confirm flagged findings',
    detail: 'Values we extracted need your eyes before they count as fact.',
    route: '/review-queue',
    cta: 'Open review queue',
  },
  case: {
    label: 'Case',
    title: 'Populate case from records',
    detail: 'Suggest conditions named in your documents — you confirm what to add.',
    route: '/build-case',
    cta: 'Populate case',
  },
  analysis: {
    label: 'Analysis',
    title: 'Run full analysis',
    detail: 'Specialists, gaps, secondaries, and a whole-file picture — educational only.',
    route: '/analysis',
    cta: 'Open analysis',
  },
  plan: {
    label: 'Plan',
    title: 'Review claim plan',
    detail: 'Prioritized next actions from your conditions and evidence.',
    route: '/strategy',
    cta: 'Open claim plan',
  },
  file: {
    label: 'File',
    title: 'Prepare filing packet',
    detail: 'Draft 21-526EZ and handoff — you or a free VSO submit. We never e-file.',
    route: '/application',
    cta: 'Prepare application',
  },
}

/** Stable main path order — never re-sorted by open/closed. */
export const CLAIM_STEP_ORDER: ClaimStepId[] = [
  'profile',
  'records',
  'review',
  'case',
  'analysis',
  'plan',
  'file',
]

function stepDone(id: ClaimStepId, input: ClaimProgressInput): boolean {
  switch (id) {
    case 'profile':
      return !input.profileIsEmpty
    case 'records':
      return input.readyDocs > 0
    case 'review':
      // No ready docs yet → not started (not done). With ready docs, done when no pending flags.
      // Unknown pending (null) → don't claim done.
      if (input.readyDocs <= 0) return false
      if (input.reviewPending === null) return false
      return input.reviewPending === 0
    case 'case':
      return input.conditionCount > 0
    case 'analysis':
      return input.analysisDone
    case 'plan':
      return input.hasPlan
    case 'file':
      return input.fileReady
    default:
      return false
  }
}

/**
 * Build the ordered progress list. Exactly one step is `current` (first incomplete),
 * unless everything is done (last step is current).
 */
export function buildClaimProgress(input: ClaimProgressInput): ClaimProgressStep[] {
  const steps: ClaimProgressStep[] = CLAIM_STEP_ORDER.map((id) => {
    const copy = STEP_COPY[id]
    let detail = copy.detail
    if (id === 'review' && input.reviewPending != null && input.reviewPending > 0) {
      detail = `${input.reviewPending} item${input.reviewPending === 1 ? '' : 's'} need your confirmation.`
    }
    if (id === 'records' && input.processingDocs > 0) {
      detail = `${input.processingDocs} record${input.processingDocs === 1 ? '' : 's'} still processing.`
    }
    return {
      id,
      label: copy.label,
      title: copy.title,
      detail,
      route: copy.route,
      cta: copy.cta,
      done: stepDone(id, input),
      current: false,
    }
  })

  const firstOpen = steps.find((s) => !s.done)
  if (firstOpen) firstOpen.current = true
  else if (steps.length) steps[steps.length - 1].current = true

  return steps
}

export function progressCounts(input: ClaimProgressInput): {
  completed: number
  total: number
  percent: number
} {
  const steps = buildClaimProgress(input)
  const completed = steps.filter((s) => s.done).length
  const total = steps.length
  return {
    completed,
    total,
    percent: total ? Math.round((completed / total) * 100) : 0,
  }
}

/**
 * The single primary CTA for Home / continue bars.
 * Transient "processing" overrides the next incomplete step so we never push
 * "populate case" while OCR is still running.
 */
export function resolveNextAction(input: ClaimProgressInput): NextClaimAction {
  // Cold start: no profile and no uploads at all → onboarding is friendlier than empty profile form.
  if (input.profileIsEmpty && input.docsTotal === 0 && input.readyDocs === 0) {
    return {
      stepId: 'profile',
      title: 'Start your claim setup',
      detail:
        'A short walkthrough for service history and what you want to track — or jump to profile and documents anytime.',
      route: '/onboarding',
      cta: 'Start setup',
    }
  }

  if (input.processingDocs > 0) {
    return {
      stepId: 'processing',
      title: `Wait for ${input.processingDocs} record${input.processingDocs === 1 ? '' : 's'} to finish`,
      detail: 'Rating Raider is still reading your upload. Check status before building your conditions list.',
      route: '/documents',
      cta: 'Check record status',
      busy: true,
    }
  }

  const steps = buildClaimProgress(input)
  const next = steps.find((s) => !s.done)

  if (!next) {
    return {
      stepId: 'done',
      title: "You're ready to prepare filing",
      detail:
        'Core evidence is identified. Assemble the application packet, then you or a free VSO submit — Rating Raider never files for you.',
      route: '/application',
      cta: 'Prepare application',
    }
  }

  // Richer titles for the home hero while reusing the same step gates.
  if (next.id === 'profile') {
    return {
      stepId: 'profile',
      title: input.readyDocs > 0 ? 'Confirm profile details from your records' : 'Set up your profile',
      detail:
        input.readyDocs > 0
          ? 'Review name, contact, and service facts. Save when it looks right — nothing auto-applies.'
          : STEP_COPY.profile.detail,
      route: STEP_COPY.profile.route,
      cta: input.readyDocs > 0 ? 'Review profile' : STEP_COPY.profile.cta,
    }
  }

  if (next.id === 'records' && input.docsTotal === 0) {
    return {
      stepId: 'records',
      title: 'Add your first records',
      detail: 'Upload service, medical, exam, or decision records. You stay in control of every item the app uses.',
      route: '/documents',
      cta: 'Add records',
    }
  }

  if (next.id === 'case' && input.readyDocs === 0) {
    // Edge: profile done but no ready docs — still need records before case scan is useful.
    return {
      stepId: 'records',
      title: 'Add records before building your case',
      detail: 'Populate case reads conditions named in processed documents.',
      route: '/documents',
      cta: 'Go to documents',
    }
  }

  return {
    stepId: next.id,
    title: next.title,
    detail: next.detail,
    route: next.route,
    cta: next.cta,
  }
}

/** Map dashboard-ish bags into ClaimProgressInput. */
export function progressInputFromParts(parts: {
  profileIsEmpty: boolean
  docsTotal?: number
  readyDocs: number
  processingDocs?: number
  reviewPending: number | null
  conditionCount: number
  analysisDone: boolean
  hasPlan: boolean
  fileReady: boolean
  itfActive?: boolean
}): ClaimProgressInput {
  return {
    profileIsEmpty: parts.profileIsEmpty,
    docsTotal: parts.docsTotal ?? parts.readyDocs,
    readyDocs: parts.readyDocs,
    processingDocs: parts.processingDocs ?? 0,
    reviewPending: parts.reviewPending,
    conditionCount: parts.conditionCount,
    analysisDone: parts.analysisDone,
    hasPlan: parts.hasPlan,
    fileReady: parts.fileReady,
    itfActive: parts.itfActive,
  }
}

/** Spine-compatible steps for ClaimSpine component. */
export function toSpineSteps(input: ClaimProgressInput): {
  id: string
  label: string
  route: string
  done: boolean
  current?: boolean
}[] {
  return buildClaimProgress(input).map((s) => ({
    id: s.id,
    label: s.label,
    route: s.route,
    done: s.done,
    current: s.current,
  }))
}

/** Post-analysis strip: only incomplete steps after analysis, or filing path. */
export function nextRingsAfterAnalysis(input: ClaimProgressInput): { to: string; label: string }[] {
  const steps = buildClaimProgress(input)
  const open = steps.filter((s) => !s.done)
  if (open.length === 0) {
    return [
      { to: '/application', label: 'Application (526EZ)' },
      { to: '/filing', label: 'How to submit' },
    ]
  }
  // Prefer plan/file after analysis is done; otherwise show next 3 open steps.
  const preferred = open.filter((s) => s.id === 'plan' || s.id === 'file' || s.id === 'analysis')
  const list = (preferred.length ? preferred : open).slice(0, 3)
  return list.map((s) => ({ to: s.route, label: s.label }))
}
