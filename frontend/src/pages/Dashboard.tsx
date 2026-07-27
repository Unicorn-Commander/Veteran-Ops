import {
  AlertTriangle,
  ArrowRight,
  Calculator as CalculatorIcon,
  CheckCircle2,
  Circle,
  Compass,
  FileStack,
  Folder,
  Landmark,
  ListChecks,
  Shield,
  Sparkles,
  Star,
  UploadCloud,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { RatingDial } from '../components/RatingDial'
import { EmailVerifyBanner } from '../components/EmailVerifyBanner'
import { DeadlinePanel } from '../components/DeadlinePanel'
import { ClaimContinue } from '../components/ClaimContinue'
import { FileReadyHandoff } from '../components/FileReadyHandoff'
import { GlitterImportOpportunity, SuiteConnections } from '../components/SuiteConnections'
import { AnimatedNumber, EmptyState, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useToast } from '../components/Toast'
import { useAsync, errorMessage } from '../hooks/useAsync'
import { analysisApi, checklistApi, conditionsApi, deadlinesApi, documentsApi, itfApi, metaApi, profileApi, ratingApi, strategyApi, vaApi } from '../lib/api'
import { hueInk, hueSoftVar, hueStyle, hueVar, STATUS_HUES, type Hue } from '../lib/hues'
import { humanize } from '../lib/format'
import { isEmptyProfile, normalizeProfile } from '../lib/profileDefaults'
import { progressInputFromParts } from '../lib/claimProgress'
import type {
  ChecklistItem,
  ClaimedCondition,
  ConditionStatus,
  Deadline,
  DocumentSummary,
  FileReadiness,
  GamePlanOut,
  Profile,
} from '../types'

interface DashboardData {
  profile: Profile
  profileIsEmpty: boolean
  conditions: ClaimedCondition[]
  checklist: ChecklistItem[]
  nextActions: ChecklistItem[]
  gapCount: number | null
  documentsSummary: DocumentSummary | null
  /** Count of documents flagged for veteran confirmation (review queue). null
   * means the endpoint was unavailable — do not treat as zero. */
  reviewQueuePending: number | null
  gamePlan: GamePlanOut | null
  /** GET /deadlines — null means the request failed; an empty array is a real,
   * reassuring empty state and must not be confused with a connection error. */
  deadlines: Deadline[] | null
  /** §4.25-combined rating derived from the conditions the veteran has confirmed
   * a current_rating for — computed ONLY when the profile has no stored official
   * combined rating, so it's a best-available estimate that never overwrites or
   * understates an authoritative VA/manual value. null when there's nothing to
   * derive or the calc failed. `ratedConditionCount` drives the caption. */
  combinedFromConditions: number | null
  combinedRatingError: boolean
  ratedConditionCount: number
  vaEnabled: boolean
  /** GET /analysis/file-readiness — null when unavailable (older backend / error). */
  fileReadiness: FileReadiness | null
  /** True when a comprehensive analysis run has completed successfully. */
  analysisDone: boolean
  /** Real ITF from tracked records / VA sync — not checklist checkbox alone. */
  itfActive: boolean
  /** Optional sections stay distinguishable from a genuine empty result. */
  loadIssues: string[]
}

async function settle<T>(promise: Promise<T>, label: string): Promise<{ data: T | null; error: string | null }> {
  try {
    return { data: await promise, error: null }
  } catch (err) {
    return { data: null, error: `${label}: ${errorMessage(err)}` }
  }
}

async function loadDashboard(): Promise<DashboardData> {
  const [
    profileRaw,
    conditions,
    checklist,
    documentsResult,
    reviewQueueResult,
    gamePlanResult,
    deadlinesResult,
    metaResult,
    fileReadinessResult,
    itfListResult,
    vaItfResult,
  ] = await Promise.all([
    profileApi.get(),
    conditionsApi.list(),
    checklistApi.list(),
    settle(documentsApi.summary(), 'Records summary unavailable'),
    settle(documentsApi.reviewQueue(), 'Review queue unavailable'),
    settle(strategyApi.get(), 'Claim Plan unavailable'),
    settle(deadlinesApi.get(), 'Deadline check unavailable'),
    settle(metaApi.get(), 'App capabilities unavailable'),
    settle(analysisApi.fileReadiness(), 'File readiness unavailable'),
    settle(itfApi.list(), 'ITF status unavailable'),
    settle(vaApi.itfActive(), 'VA ITF status unavailable'),
  ])
  const profile = normalizeProfile(profileRaw)
  const itfActive =
    Boolean(vaItfResult.data?.active) || Boolean(itfListResult.data?.active)

  // Gap count from file-readiness (single backend pass) — never N+1 per-condition
  // /gaps calls, which hammered the API and slowed Home on large cases.
  const fileReadiness = fileReadinessResult.data
  const gapCount =
    fileReadinessResult.error || !fileReadiness
      ? null
      : !fileReadiness.has_conditions
        ? 0
        : fileReadiness.still_needed.reduce((n, need) => n + (need.conditions?.length ?? 1), 0)

  // A confirmed rating updates a condition's current_rating, but the profile's
  // stored current_combined_rating (what the hero dial reads) is only ever set
  // by VA import or manual entry — so a veteran who "accepts a rating" from a
  // document would otherwise never see it on the dashboard. Fill that gap: when
  // there's no stored official combined, derive one from the rated conditions via
  // the real §4.25 engine. We never do this when an official value exists, so we
  // can't overwrite or understate it.
  const rated = conditions.filter((c) => c.current_rating != null)
  let combinedFromConditions: number | null = null
  let ratingError: string | null = null
  if (profile.current_combined_rating == null && rated.length > 0) {
    const ratingResult = await settle(
      ratingApi.calculate(rated.map((c) => ({ label: c.name, percent: c.current_rating as number }))),
      'Combined-rating estimate unavailable',
    )
    combinedFromConditions = ratingResult.data?.combined ?? null
    ratingError = ratingResult.error
  }

  // Latest comprehensive analysis — spine "Analysis" is done only when a run finished.
  const latestRunResult = await settle(analysisApi.latestRun(), 'Analysis status unavailable')
  const latest = latestRunResult.data
  const analysisDone = !!(
    latest &&
    (latest.status === 'complete' || latest.status === 'completed')
  )

  // Review-queue failures degrade silently (older backends may 404) — a null
  // pending count simply skips that next-step, and is not treated as empty.
  const loadIssues = [
    documentsResult.error,
    gamePlanResult.error,
    deadlinesResult.error,
    fileReadinessResult.error,
    latestRunResult.error,
    ratingError,
  ].filter((issue): issue is string => !!issue)

  return {
    profile,
    profileIsEmpty: isEmptyProfile(profile),
    conditions,
    checklist,
    // The ITF item gets its own dedicated nudge card above — don't duplicate it here.
    nextActions: checklist.filter((c) => !c.done && c.category !== 'itf').slice(0, 8),
    gapCount,
    documentsSummary: documentsResult.data,
    reviewQueuePending: reviewQueueResult.data?.length ?? null,
    gamePlan: gamePlanResult.data,
    deadlines: deadlinesResult.data?.deadlines ?? null,
    combinedFromConditions,
    combinedRatingError: !!ratingError,
    ratedConditionCount: rated.length,
    vaEnabled: metaResult.data?.va_enabled ?? false,
    fileReadiness: fileReadinessResult.data,
    analysisDone,
    itfActive,
    loadIssues,
  }
}

const STATUS_ORDER: ConditionStatus[] = [
  'considering',
  'gathering_evidence',
  'ready_to_file',
  'filed',
  'decided',
]

export function Dashboard() {
  const { toast } = useToast()
  const { data, loading, error, reload, setData } = useAsync(loadDashboard)

  if (loading) return <LoadingBlock label="Loading your dashboard…" />
  if (error || !data) return <ErrorBlock message={error ?? 'Could not load your dashboard.'} onRetry={reload} />

  const ratingIsDerived = data.profile.current_combined_rating == null && data.combinedFromConditions != null
  const rating = data.profile.current_combined_rating ?? data.combinedFromConditions ?? 0
  const statusCounts = STATUS_ORDER.map((status) => ({
    status,
    count: data.conditions.filter((c) => c.status === status).length,
  })).filter((s) => s.count > 0)

  const toggleAction = async (item: ChecklistItem) => {
    try {
      await checklistApi.toggle(item.id, !item.done)
      setData((prev) =>
        prev ? { ...prev, nextActions: prev.nextActions.filter((a) => a.id !== item.id) } : prev
      )
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div className="vo-page mx-auto w-full max-w-6xl space-y-6 p-4 sm:p-6" data-section="home">
      <EmailVerifyBanner />

      <div className="vo-page-head vo-section-band">
        <h1 className="vo-page-title">Your claim, at a glance</h1>
        <p className="vo-page-sub">
          Here's where things stand. You drive every step — Rating Raider just keeps it organized.
        </p>
      </div>

      <ClaimContinue
        input={progressInputFromParts({
          profileIsEmpty: data.profileIsEmpty,
          docsTotal: data.documentsSummary?.total ?? 0,
          readyDocs: data.documentsSummary?.by_status.ready ?? 0,
          processingDocs:
            (data.documentsSummary?.processing ?? data.documentsSummary?.by_status.processing ?? 0) +
            (data.documentsSummary?.queued ?? data.documentsSummary?.by_status.uploaded ?? 0),
          reviewPending: data.reviewQueuePending,
          conditionCount: data.conditions.length,
          analysisDone: data.analysisDone,
          hasPlan: !!data.gamePlan,
          fileReady: !!data.fileReadiness?.all_ready,
          itfActive: data.itfActive,
        })}
      />

      <SuiteConnections compact />

      {/* Soft only when profile still empty — never reopens a completed profile step. */}
      {data.profileIsEmpty && (
        <ProfileSuggestBanner profileIsEmpty hasReadyDocs={(data.documentsSummary?.by_status.ready ?? 0) > 0} />
      )}

      {data.loadIssues.length > 0 && (
        <div className="border-l-[3px] border-warning bg-surface px-4 py-3" role="status">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-txt">Some dashboard sections did not load</p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted">
                Existing data is still shown. Missing sections are not being treated as empty.
              </p>
              <ul className="mt-2 space-y-1 text-xs text-muted">
                {[...new Set(data.loadIssues)].map((issue) => <li key={issue}>{issue}</li>)}
              </ul>
            </div>
            <button type="button" onClick={reload} className="vo-btn-secondary min-h-11 shrink-0 text-sm">
              Try again
            </button>
          </div>
        </div>
      )}

      {/* Needs list while incomplete; compact handoff once all_ready (no double fetch). */}
      {data.conditions.length > 0 &&
        (data.fileReadiness?.all_ready ? (
          <FileReadyHandoff compact />
        ) : data.fileReadiness ? (
          <FileReadinessPanel data={data.fileReadiness} />
        ) : null)}

      {/* Deadline guardian — distinguishes a true empty state from a failed check. */}
      <DeadlinePanel deadlines={data.deadlines} onRetry={reload} />

      {/* GM → claim import (self-hides when bridge down / still loading). */}
      <GlitterImportOpportunity />

      <GamePlanHero gamePlan={data.gamePlan} profileIsEmpty={data.profileIsEmpty} />

      <div className="grid gap-4 lg:grid-cols-[auto_1fr]">
        {/* Hero rating dial */}
        <Panel hue="violet" className="relative flex flex-col items-center justify-center gap-4 p-8">
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0"
            style={{
              background: 'radial-gradient(55% 55% at 50% 42%, var(--hue-violet-soft) 0%, transparent 75%)',
            }}
          />
          {data.combinedRatingError ? (
            <div className="relative max-w-xs">
              <ErrorBlock message="Your combined-rating estimate could not be calculated. It is not being shown as 0%." onRetry={reload} />
            </div>
          ) : (
            <div className="relative">
              <RatingDial
                value={rating}
                size={200}
                label={ratingIsDerived ? 'Estimated combined rating' : 'Current combined rating'}
              />
            </div>
          )}
          {ratingIsDerived && (
            <p className="relative max-w-xs text-center text-xs leading-snug text-muted">
              Estimated from the {data.ratedConditionCount} rating
              {data.ratedConditionCount === 1 ? '' : 's'} you've confirmed. Set your official VA
              combined rating in{' '}
              <Link to="/profile" className="font-semibold text-brand hover:text-brand-hover">
                Profile
              </Link>
              .
            </p>
          )}
          <Link to="/calculator" className="vo-btn-secondary relative text-sm">
            <CalculatorIcon size={15} /> Open calculator
          </Link>
        </Panel>

        {/* Summary tiles — each card wears the hue of the section it opens,
            so the dashboard doubles as a color-coded map of the app
            (conditions → claim/emerald, gaps → amber attention). */}
        <div className="grid gap-4 sm:grid-cols-2">
          <Panel hue="emerald" title="Conditions" subtitle="By status">
            <div className="p-5">
              {data.conditions.length === 0 ? (
                <EmptyState
                  hue="emerald"
                  icon={<Folder size={22} />}
                  title="No conditions yet"
                  description={
                    (data.documentsSummary?.by_status.ready ?? 0) > 0
                      ? 'Populate your case from records, or add a condition by hand.'
                      : 'Add your first condition to start tracking evidence.'
                  }
                  action={
                    <div className="flex flex-wrap justify-center gap-2">
                      {(data.documentsSummary?.by_status.ready ?? 0) > 0 && (
                        <Link to="/build-case" className="vo-btn-primary text-sm">
                          Populate case from records
                        </Link>
                      )}
                      <Link
                        to="/conditions"
                        className={
                          (data.documentsSummary?.by_status.ready ?? 0) > 0
                            ? 'vo-btn-secondary text-sm'
                            : 'vo-btn-primary text-sm'
                        }
                      >
                        Add manually
                      </Link>
                    </div>
                  }
                />
              ) : (
                <div className="space-y-2.5">
                  {statusCounts.map(({ status, count }) => (
                    <div key={status} className="flex items-center justify-between text-sm">
                      <span className="flex items-center gap-2 text-txt">
                        <span
                          className="h-2 w-2 rounded-full"
                          style={{ background: hueVar(STATUS_HUES[status]), boxShadow: `0 0 6px ${hueVar(STATUS_HUES[status])}` }}
                        />
                        {humanize(status)}
                      </span>
                      <span className="font-semibold tabular-nums text-txt">{count}</span>
                    </div>
                  ))}
                  <ArrowLink to="/conditions">View all conditions</ArrowLink>
                </div>
              )}
            </div>
          </Panel>

          <Panel hue="amber" title="Evidence gaps" subtitle="Across all conditions">
            <div className="flex h-full flex-col items-center justify-center gap-2 p-5 text-center">
              {data.gapCount === null ? (
                <ErrorBlock message="Evidence gaps could not be checked. They are not being shown as zero." onRetry={reload} />
              ) : data.gapCount > 0 ? (
                <>
                  <span className="flex h-11 w-11 items-center justify-center rounded-full bg-h-amber-soft text-warn">
                    <AlertTriangle size={22} />
                  </span>
                  <p className="text-3xl font-bold tabular-nums text-txt">
                    <AnimatedNumber value={data.gapCount} />
                  </p>
                  <p className="text-sm text-muted">gap{data.gapCount === 1 ? '' : 's'} to close before filing</p>
                  <ArrowLink to="/evidence">Review evidence</ArrowLink>
                </>
              ) : (
                <>
                  <span className="flex h-11 w-11 items-center justify-center rounded-full bg-h-emerald-soft text-success">
                    <CheckCircle2 size={22} />
                  </span>
                  <p className="text-sm text-muted">No open gaps detected yet — analyze a condition to check.</p>
                </>
              )}
            </div>
          </Panel>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        {/* Next actions */}
        <Panel
          hue="teal"
          title="Optional reminders"
          subtitle="Personal checklist — not the same as the claim spine above"
        >
          {data.nextActions.length === 0 ? (
            <div className="p-5">
              <EmptyState
                hue="teal"
                icon={<ListChecks size={22} />}
                title="No personal reminders"
                description="Use the claim spine and “Your next step” for the main path. This list is only for optional to-dos you add."
                action={
                  <div className="flex flex-wrap justify-center gap-2">
                    <Link to="/journey" className="vo-btn-primary text-sm">
                      See full journey
                    </Link>
                    <Link to="/build-case" className="vo-btn-secondary text-sm">
                      Populate case
                    </Link>
                  </div>
                }
              />
            </div>
          ) : (
            <ul className="divide-y divide-line">
              {data.nextActions.map((item) => (
                <li key={item.id} className="flex items-center gap-2 px-3 py-1.5 transition-colors duration-150 hover:bg-surface2/60 sm:px-4">
                  <button
                    onClick={() => void toggleAction(item)}
                    className="group/check relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-muted transition-colors hover:text-success"
                    aria-label={`Mark "${item.text}" done`}
                  >
                    <Circle size={19} className="transition-opacity duration-150 group-hover/check:opacity-0" />
                    <CheckCircle2
                      size={19}
                      className="absolute scale-90 opacity-0 transition-all duration-150 group-hover/check:scale-105 group-hover/check:opacity-100"
                    />
                  </button>
                  <div className="min-w-0 flex-1 py-1.5">
                    <p className="truncate text-sm text-txt">{item.text}</p>
                    <p className="text-xs text-faint">{humanize(item.category)}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {/* Quick links — each tile carries its destination section's hue, so
            this card is a mini legend of the whole app. */}
        <Panel title="Explore" subtitle="Color-coded by section">
          <div className="grid gap-2 p-4">
            <QuickLink to="/documents" icon={UploadCloud} label="My documents & uploads" hue="teal" />
            {data.vaEnabled && <QuickLink to="/va-sync" icon={Landmark} label="Connect your VA data" hue="sky" />}
            <QuickLink to="/calculator" icon={CalculatorIcon} label="Combined ratings calculator" hue="sky" />
            <QuickLink to="/secondaries" icon={Sparkles} label="Suggest secondaries" hue="fuchsia" />
            <QuickLink to="/presumptives" icon={Shield} label="Check presumptives" hue="pink" />
            <QuickLink to="/records" icon={FileStack} label="Request your records" hue="amber" />
            <QuickLink to="/filing" icon={ListChecks} label="Filing lanes guide" hue="indigo" />
          </div>
        </Panel>
      </div>
    </div>
  )
}

/**
 * Soft identity nudge when profile is still empty — never reopens a completed step.
 */
function ProfileSuggestBanner({
  profileIsEmpty,
  hasReadyDocs,
}: {
  profileIsEmpty: boolean
  hasReadyDocs: boolean
}) {
  const { data, loading } = useAsync(async () => {
    if (!hasReadyDocs) return null
    try {
      return await profileApi.identitySuggestions()
    } catch {
      return null
    }
  }, [hasReadyDocs])

  if (!hasReadyDocs || loading) return null

  const hasSuggestions = data?.has_suggestions === true
  if (!hasSuggestions && !profileIsEmpty) return null

  const name = data?.identity?.full_name?.trim()
  return (
    <div
      className="vo-card vo-accent flex flex-wrap items-start gap-3 p-4 sm:p-5"
      style={hueStyle('violet')}
      role="region"
      aria-label="Profile suggestions from your records"
    >
      <span
        aria-hidden
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar('violet'), color: hueInk('violet') }}
      >
        <Sparkles size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-micro font-bold uppercase tracking-wide" style={{ color: hueInk('violet') }}>
          Suggestions — confirm before saving
        </p>
        <h2 className="text-base font-bold text-txt">
          {hasSuggestions
            ? name
              ? `We found details for ${name} in your records`
              : 'We found profile details in your records'
            : 'Pull your profile from your records'}
        </h2>
        <p className="mt-0.5 text-sm leading-relaxed text-muted">
          {hasSuggestions
            ? 'Review name, contact, and related facts we extracted. Edit anything off, then save — nothing is auto-applied.'
            : 'Your records are ready. Scan them for identity and service details, then confirm each field on your profile.'}
        </p>
      </div>
      <Link to="/profile?start=1" className="vo-btn-primary min-h-11 shrink-0 text-sm">
        {hasSuggestions ? 'Review & confirm' : 'Open profile scan'}
        <ArrowRight size={15} />
      </Link>
    </div>
  )
}

/** "To file, you still need…" — uses the same file-readiness payload already loaded
 * for the dashboard (no second network round-trip / layout pop). */
function FileReadinessPanel({ data }: { data: FileReadiness }) {
  if (!data.has_conditions) return null

  if (data.all_ready) {
    return (
      <div
        className="vo-card vo-accent flex flex-wrap items-center gap-3 p-4 sm:p-5"
        style={hueStyle('emerald')}
      >
        <span
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar('emerald'), color: hueInk('emerald') }}
        >
          <CheckCircle2 size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-txt">Your core evidence is identified for every condition</p>
          <p className="text-sm text-muted">
            You've named the service-connection elements for all {data.total_conditions} — review your Claim Plan, then
            file when you're ready. A VSO can file it with you for free.
          </p>
        </div>
        <Link to="/strategy" className="vo-btn-primary shrink-0 text-sm">
          Claim Plan <ArrowRight size={15} />
        </Link>
      </div>
    )
  }

  return (
    <Panel
      hue="amber"
      title="To file, you still need…"
      subtitle={`${data.ready_conditions} of ${data.total_conditions} condition${data.total_conditions === 1 ? '' : 's'} have their core evidence identified`}
    >
      <div className="space-y-2.5 p-5">
        {data.still_needed.slice(0, 6).map((need, i) => (
          <Link
            key={i}
            to={need.route}
            className="vo-card vo-accent vo-card-hover flex items-start gap-3 p-3.5"
            style={hueStyle('amber')}
          >
            <span
              aria-hidden
              className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
              style={{ background: hueSoftVar('amber'), color: hueInk('amber') }}
            >
              <Circle size={13} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-semibold leading-snug text-txt">{need.label}</p>
              <p className="mt-0.5 text-sm leading-relaxed text-muted">{need.how}</p>
              <p className="mt-1 text-xs text-faint">
                For: {need.conditions.join(', ')}
              </p>
            </div>
            <ArrowRight size={15} className="mt-1 shrink-0 text-muted" />
          </Link>
        ))}
        <p className="pt-1 text-xs leading-relaxed text-faint">{data.disclaimer}</p>
      </div>
    </Panel>
  )
}

/** Compact "Your Claim Plan" card (WAVE8). Loads from GET /strategy, wired into
 * loadDashboard with a .catch(() => null) so an older backend / no data simply
 * HIDES this card — it never crashes the dashboard. Shows the recommended
 * pathway's title + its estimated combined (always with a short "estimate — not
 * a prediction" caption, never presented as an outcome) and the top 3 priority
 * actions as links. When there are no conditions, it degrades to a tiny nudge. */
function GamePlanHero({
  gamePlan,
  profileIsEmpty,
}: {
  gamePlan: GamePlanOut | null
  profileIsEmpty: boolean
}) {
  // Endpoint unavailable (older backend) or request failed → render nothing.
  if (!gamePlan) return null

  const HUE: Hue = 'fuchsia'

  // No conditions yet → a tiny nudge (skip it entirely while the big setup hero
  // is already inviting an empty-profile veteran, to avoid a double CTA).
  if (!gamePlan.has_conditions) {
    if (profileIsEmpty) return null
    return (
      <Link
        to="/conditions"
        className="vo-card vo-accent flex items-center gap-3 px-5 py-3.5 text-sm transition-colors duration-150 hover:bg-surface2/40"
        style={hueStyle(HUE) as React.CSSProperties}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full" style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}>
          <Compass size={16} />
        </span>
        <span className="min-w-0 flex-1 text-txt">Add your conditions to get a personalized Claim Plan.</span>
        <ArrowRight size={15} className="shrink-0 text-faint" />
      </Link>
    )
  }

  const recommended = gamePlan.pathways.find((p) => p.recommended) ?? gamePlan.pathways[0] ?? null
  const topActions = gamePlan.priority_actions.slice(0, 3)

  return (
    <div className="vo-card vo-accent relative overflow-hidden p-6" style={hueStyle(HUE) as React.CSSProperties}>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(55% 90% at 0% 0%, var(--hue-fuchsia-soft) 0%, transparent 70%), radial-gradient(45% 80% at 100% 100%, var(--hue-pink-soft) 0%, transparent 70%)',
        }}
      />
      <div className="relative">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl" style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}>
              <Compass size={20} />
            </span>
            <div>
              <p className="text-micro font-semibold uppercase tracking-wide" style={{ color: hueInk(HUE) }}>
                Your Claim Plan
              </p>
              {recommended ? (
                <>
                  <h2 className="mt-0.5 flex items-center gap-1.5 text-heading text-txt">
                    <Star size={15} className="shrink-0 fill-current" style={{ color: hueInk(HUE) }} />
                    {recommended.title}
                  </h2>
                  <p className="mt-1 max-w-xl text-sm leading-relaxed text-muted">{recommended.summary}</p>
                  {recommended.estimated_combined !== null ? (
                    <p className="mt-2 text-sm text-txt">
                      <span className="font-semibold tabular-nums" style={{ color: hueInk(HUE) }}>
                        ~{recommended.estimated_combined}% estimated combined
                      </span>{' '}
                      <span className="text-xs text-faint">— estimate only, not a prediction of VA's decision</span>
                    </p>
                  ) : (
                    <p className="mt-2 text-xs text-faint">{recommended.estimated_combined_basis}</p>
                  )}
                </>
              ) : (
                <h2 className="mt-0.5 text-heading text-txt">See your options and next steps</h2>
              )}
            </div>
          </div>
          <Link to="/strategy" className="vo-btn-primary group shrink-0 text-sm">
            See your full Claim Plan
            <ArrowRight size={15} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
          </Link>
        </div>

        {topActions.length > 0 && (
          <div className="mt-4 border-t border-line pt-4">
            <p className="mb-2 text-micro font-semibold uppercase tracking-wide text-faint">Do these next</p>
            <ul className="space-y-1.5">
              {topActions.map((a, i) => {
                const row = (
                  <span className="flex items-start gap-2 text-sm">
                    <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-micro font-bold" style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}>
                      {i + 1}
                    </span>
                    <span className="min-w-0 flex-1 text-txt">{a.title}</span>
                    {a.link && <ArrowRight size={14} className="mt-0.5 shrink-0 text-faint" />}
                  </span>
                )
                return (
                  <li key={i}>
                    {a.link ? (
                      <Link to={a.link} className="block rounded-control px-1.5 py-1 transition-colors duration-150 hover:bg-surface2/60">
                        {row}
                      </Link>
                    ) : (
                      <div className="px-1.5 py-1">{row}</div>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

function ArrowLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className="group mt-2 inline-flex items-center gap-1 text-sm font-semibold text-brand transition-colors hover:text-brand-hover"
    >
      {children}
      <ArrowRight size={14} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
    </Link>
  )
}

/** Hue-identified quick link (.vo-hue-link contract class): the icon + hover
 * tint carry the destination section's hue. */
function QuickLink({ to, icon: Icon, label, hue }: { to: string; icon: typeof Sparkles; label: string; hue: Hue }) {
  return (
    <Link to={to} className="vo-hue-link group" style={hueStyle(hue) as React.CSSProperties}>
      <Icon
        size={16}
        className="shrink-0 transition-transform duration-200 ease-out group-hover:scale-110"
        style={{ color: hueVar(hue) }}
      />
      <span className="flex-1">{label}</span>
      <ArrowRight
        size={14}
        className="-translate-x-1 text-faint opacity-0 transition-all duration-200 ease-out group-hover:translate-x-0 group-hover:opacity-100"
      />
    </Link>
  )
}
