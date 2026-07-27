import { ArrowRight, Check, ChevronRight, Circle, ExternalLink, MapPin, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { ClaimContinue } from '../components/ClaimContinue'
import { EmptyState, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { analysisApi, conditionsApi, documentsApi, itfApi, profileApi, strategyApi, vaApi } from '../lib/api'
import {
  buildClaimProgress,
  progressInputFromParts,
  type ClaimProgressStep,
} from '../lib/claimProgress'
import { isEmptyProfile, normalizeProfile } from '../lib/profileDefaults'
import { hueInk, hueSoftVar, hueStyle, hueVar } from '../lib/hues'
import {
  detectStage,
  getStage,
  JOURNEY_STAGES,
  JOURNEY_STAGE_IDS,
  type JourneyStage,
  type JourneyStageId,
  type StageDetection,
} from '../lib/journey'
import type { ClaimedCondition, Profile } from '../types'

// /journey — full VA lifecycle map + the SAME claim path as Home (claimProgress).
// Legal lane: organize and prepare; the veteran decides and files.

const OVERRIDE_KEY = 'vo_journey_stage'

interface JourneyData {
  profile: Profile
  profileIsEmpty: boolean
  conditions: ClaimedCondition[]
  itfActive: boolean
  docsTotal: number
  readyDocs: number
  processingDocs: number
  reviewPending: number | null
  analysisDone: boolean
  hasPlan: boolean
  fileReady: boolean
}

async function loadJourney(): Promise<JourneyData> {
  const [rawProfile, conditions, itfResult, vaItf, docs, review, latestRun, plan, fileReady] =
    await Promise.all([
      profileApi.get(),
      conditionsApi.list(),
      itfApi.list(),
      vaApi.itfActive().catch(() => null),
      documentsApi.summary().catch(() => null),
      documentsApi.reviewQueue().catch(() => null),
      analysisApi.latestRun().catch(() => null),
      strategyApi.get().catch(() => null),
      analysisApi.fileReadiness().catch(() => null),
    ])
  const profile = normalizeProfile(rawProfile)
  const itfActive = Boolean(vaItf?.active) || Boolean(itfResult?.active)
  const analysisDone =
    latestRun?.status === 'completed' || latestRun?.status === 'complete'
  return {
    profile,
    profileIsEmpty: isEmptyProfile(profile),
    conditions,
    itfActive,
    docsTotal: docs?.total ?? 0,
    readyDocs: docs?.by_status?.ready ?? 0,
    processingDocs:
      (docs?.processing ?? docs?.by_status?.processing ?? 0) +
      (docs?.queued ?? docs?.by_status?.uploaded ?? 0),
    reviewPending: review ? review.length : null,
    analysisDone,
    hasPlan: !!plan,
    fileReady: !!fileReady?.all_ready,
  }
}

function progressFromJourney(data: JourneyData) {
  return progressInputFromParts({
    profileIsEmpty: data.profileIsEmpty,
    docsTotal: data.docsTotal,
    readyDocs: data.readyDocs,
    processingDocs: data.processingDocs,
    reviewPending: data.reviewPending,
    conditionCount: data.conditions.length,
    analysisDone: data.analysisDone,
    hasPlan: data.hasPlan,
    fileReady: data.fileReady,
    itfActive: data.itfActive,
  })
}

function readOverride(): JourneyStageId | null {
  try {
    const raw = localStorage.getItem(OVERRIDE_KEY)
    if (raw && (JOURNEY_STAGE_IDS as string[]).includes(raw)) return raw as JourneyStageId
  } catch {
    /* storage unavailable — ignore */
  }
  return null
}

export function Journey() {
  const { data, loading, error, reload } = useAsync(loadJourney)
  const [override, setOverride] = useState<JourneyStageId | null>(() => readOverride())

  // Persist the veteran's manual pick so the page remembers where they said
  // they are between visits.
  useEffect(() => {
    try {
      if (override) localStorage.setItem(OVERRIDE_KEY, override)
      else localStorage.removeItem(OVERRIDE_KEY)
    } catch {
      /* storage unavailable — non-fatal */
    }
  }, [override])

  const detection: StageDetection = useMemo(
    () =>
      data
        ? detectStage(data)
        : { stageId: 'never_filed', confident: false },
    [data]
  )

  const currentId: JourneyStageId = override ?? detection.stageId
  const current = getStage(currentId)
  const currentOrder = current.order
  // We only claim to have detected a spot when we're confident AND the veteran
  // hasn't overridden it.
  const showDetectedNote = !override && detection.confident
  const showAskNote = !override && !detection.confident

  return (
    <div data-section="home" className="vo-page mx-auto w-full max-w-5xl space-y-6 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Start here</p>
        <h1 className="vo-page-title">Your claim path & VA journey</h1>
        <p className="vo-page-sub">
          One main path (same as Home): profile → records → confirm → case → analysis → plan → file. Soft
          suggestions never reopen a finished step. Below that is the broader VA lifecycle map if you want context.
          You decide and file every step.
        </p>
      </div>

      {loading && !data ? (
        <div className="flex min-h-[24rem] items-center justify-center">
          <LoadingBlock label="Mapping your journey…" />
        </div>
      ) : error && !data ? (
        <ErrorBlock
          message={`We couldn't read the records used to map your journey. ${error} Check your connection, then try again.`}
          onRetry={reload}
        />
      ) : !data ? (
        <EmptyState
          hue="violet"
          icon={<MapPin size={20} />}
          title="Your journey details are not available yet"
          description="Add your profile and conditions, then return here for a suggested starting point. You can still choose any guide yourself."
          action={<Link to="/profile" className="vo-btn-primary">Add your profile</Link>}
        />
      ) : (
        <>
          {error && (
            <ErrorBlock
              message={`We couldn't refresh your journey. The map below uses the last records we loaded. ${error}`}
              onRetry={reload}
            />
          )}
          {loading && (
            <p className="text-sm text-muted" role="status" aria-live="polite">
              Refreshing your journey…
            </p>
          )}

          <ClaimContinue input={progressFromJourney(data)} />

          <ClaimPathPanel steps={buildClaimProgress(progressFromJourney(data))} itfActive={data.itfActive} />

          {/* Where you are — detected banner + the selector to override it. */}
          <Panel hue={current.hue} className="overflow-visible">
            <div className="p-5">
              <div className="flex items-start gap-3">
                <span
                  aria-hidden
                  className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
                  style={{ background: hueSoftVar(current.hue), color: hueInk(current.hue) }}
                >
                  <MapPin size={18} />
                </span>
                <div className="min-w-0">
                  <p
                    className="text-micro font-semibold uppercase tracking-wide"
                    style={{ color: hueInk(current.hue) }}
                  >
                    {override
                      ? 'You told us you’re here'
                      : showDetectedNote
                        ? 'You look like you’re around here'
                        : 'Where are you with the VA?'}
                  </p>
                  <h2 className="mt-0.5 text-heading text-txt">{current.title}</h2>
                  <p className="mt-1 text-sm leading-relaxed text-muted">
                    {showAskNote
                      ? 'We couldn’t tell from your data yet — pick the point that sounds most like you. You can change it anytime.'
                      : current.tagline}
                  </p>
                </div>
              </div>

              {override && (
                <div className="mt-4 border-t border-line pt-4">
                  <button
                    type="button"
                    onClick={() => setOverride(null)}
                    className="vo-chip min-h-10 justify-center border-line text-muted transition-colors duration-150 hover:text-txt"
                  >
                    <Sparkles size={12} aria-hidden="true" /> Use suggested stage
                  </button>
                </div>
              )}
            </div>
          </Panel>

          {/* The whole path on one screen — a horizontal flow map that wraps, with
              every stage tappable to pull up its detail below. */}
          <JourneyFlow currentId={currentId} currentOrder={currentOrder} onSelect={setOverride} />

          {/* Focused detail + actions for the selected stage. */}
          <StageDetailCard stage={current} isCurrent />

          <p className="px-1 text-xs leading-relaxed text-faint">
            This map is a guide, not legal advice or a prediction of any VA decision. Rating Raider helps you
            organize and prepare your claim — you review, decide, and file everything yourself, and a Veterans
            Service Officer (VSO) can help at no cost.
          </p>
        </>
      )}
    </div>
  )
}

/** Same steps as Home — stable order, one current step highlighted. */
function ClaimPathPanel({
  steps,
  itfActive,
}: {
  steps: ClaimProgressStep[]
  itfActive: boolean
}) {
  const open = steps.filter((s) => !s.done).length
  return (
    <Panel
      hue="violet"
      title="Main claim path"
      subtitle={
        open === 0
          ? 'Main path complete — refine evidence and prepare filing when you are ready.'
          : `${open} step${open === 1 ? '' : 's'} remaining · same sequence as Home`
      }
    >
      <ul className="divide-y divide-line">
        {steps.map((step) => (
          <li key={step.id}>
            <Link
              to={step.route}
              className="flex items-start gap-3 px-4 py-3.5 transition-colors hover:bg-surface2/60"
            >
              <span
                aria-hidden
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
                style={{
                  background: step.done
                    ? hueSoftVar('emerald')
                    : step.current
                      ? hueSoftVar('violet')
                      : hueSoftVar('sky'),
                  color: step.done
                    ? hueInk('emerald')
                    : step.current
                      ? hueInk('violet')
                      : hueInk('sky'),
                }}
              >
                {step.done ? <Check size={16} /> : step.current ? <ArrowRight size={16} /> : <Circle size={16} />}
              </span>
              <span className="min-w-0 flex-1">
                <span
                  className={`block text-sm font-semibold ${
                    step.done ? 'text-muted' : step.current ? 'text-txt' : 'text-muted'
                  }`}
                >
                  {step.current ? 'Next: ' : ''}
                  {step.title}
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted">{step.detail}</span>
              </span>
              <span className="mt-1 shrink-0 text-xs font-semibold text-brand">
                {step.done ? 'Revisit' : step.cta} <ArrowRight size={12} className="inline" />
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <div className="border-t border-line px-4 py-3 text-xs text-muted">
        Intent to File is optional and does not block the main path.{' '}
        {itfActive ? (
          <span className="font-semibold text-success">You have an active ITF on file.</span>
        ) : (
          <Link to="/itf" className="font-semibold text-brand hover:underline">
            Review ITF
          </Link>
        )}
      </div>
    </Panel>
  )
}

type StagePosition = 'behind' | 'current' | 'ahead'

function positionOf(stage: JourneyStage, currentOrder: number): StagePosition {
  return stage.order < currentOrder ? 'behind' : stage.order > currentOrder ? 'ahead' : 'current'
}

/** The whole path on one screen: a horizontal flow map of every stage that wraps
 * (serpentine) so the veteran sees the entire journey at a glance. Nodes are
 * clickable — picking one selects that stage below. Behind = soft check, current
 * = filled + glow, ahead = quiet outline; chevrons show the flow direction. */
function JourneyFlow({
  currentId,
  currentOrder,
  onSelect,
}: {
  currentId: JourneyStageId
  currentOrder: number
  onSelect: (id: JourneyStageId) => void
}) {
  return (
    <nav aria-label="Your VA journey map" className="vo-card p-4 sm:p-5">
      <ol className="flex flex-wrap items-stretch justify-center gap-y-3">
        {JOURNEY_STAGES.map((stage, i) => {
          const position = positionOf(stage, currentOrder)
          const Icon = stage.icon
          const ink = hueInk(stage.hue)
          const active = stage.id === currentId
          return (
            <li key={stage.id} className="flex flex-1 basis-[7rem] items-stretch">
              <button
                type="button"
                onClick={() => onSelect(stage.id)}
                aria-current={active ? 'step' : undefined}
                aria-label={`Stage ${stage.order}: ${stage.title}${active ? ' (current)' : ''}`}
                className="flex flex-1 flex-col gap-1.5 rounded-control border p-2.5 text-left transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                style={
                  position === 'current'
                    ? { borderColor: hueVar(stage.hue), background: hueSoftVar(stage.hue), boxShadow: `0 0 0 1.5px ${hueVar(stage.hue)}` }
                    : position === 'behind'
                      ? { borderColor: 'transparent', background: hueSoftVar(stage.hue) }
                      : { borderColor: 'var(--border)', background: 'var(--surface)' }
                }
              >
                <span className="flex items-center justify-between">
                  <span
                    aria-hidden
                    className="flex h-7 w-7 items-center justify-center rounded-full border"
                    style={
                      position === 'current'
                        ? { background: hueVar(stage.hue), color: 'var(--surface)', borderColor: hueVar(stage.hue) }
                        : position === 'behind'
                          ? { background: 'transparent', color: ink, borderColor: 'transparent' }
                          : { background: 'var(--surface)', color: 'var(--muted)', borderColor: 'var(--border)' }
                    }
                  >
                    {position === 'behind' ? <Check size={15} /> : <Icon size={15} />}
                  </span>
                  <span className="text-micro font-semibold tabular-nums text-faint">{stage.order}</span>
                </span>
                <span
                  className="text-xs font-semibold leading-snug"
                  style={{ color: position === 'ahead' ? 'var(--muted)' : 'var(--txt)' }}
                >
                  {stage.title}
                </span>
              </button>
              {i < JOURNEY_STAGES.length - 1 && (
                <span aria-hidden className="flex items-center px-1 text-faint">
                  <ChevronRight size={16} />
                </span>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

/** The detail + actions for the selected stage — shown below the flow map so the
 * veteran gets the focused "what to do here" for wherever they've tapped. */
function StageDetailCard({ stage, isCurrent }: { stage: JourneyStage; isCurrent: boolean }) {
  const ink = hueInk(stage.hue)
  return (
    <div
      className="vo-card vo-accent min-w-0 p-4 sm:p-5"
      style={{
        ...(hueStyle(stage.hue) as CSSProperties),
        ...(isCurrent ? { borderColor: hueVar(stage.hue), boxShadow: `0 0 0 1.5px ${hueVar(stage.hue)}` } : {}),
      }}
    >
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-micro font-semibold uppercase tracking-wide tabular-nums text-faint">Stage {stage.order}</span>
          {isCurrent && (
            <span className="vo-chip" style={{ borderColor: hueVar(stage.hue), background: hueSoftVar(stage.hue), color: ink }}>
              You’re here
            </span>
          )}
          {stage.comingSoon && (
            <span className="vo-chip border-line text-muted">Coming soon</span>
          )}
        </div>

        <h3 className="mt-1 text-lg font-semibold text-txt">{stage.title}</h3>
        <p className="mt-1 text-sm leading-relaxed text-txt">{stage.whatItIs}</p>
        <p className="mt-2 text-sm leading-relaxed text-muted">
          <span className="font-semibold text-txt">What to do: </span>
          {stage.whatToDo}
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {stage.route ? (
            <Link
              to={stage.route}
              className={isCurrent ? 'vo-btn-primary group text-sm' : 'vo-btn-secondary group text-sm'}
            >
              {stage.cta}
              <ArrowRight size={15} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
            </Link>
          ) : stage.externalHref ? (
            <a href={stage.externalHref} target="_blank" rel="noreferrer" className="vo-btn-secondary text-sm">
              <ExternalLink size={14} aria-hidden="true" />
              {stage.externalLabel ?? 'Learn more'}
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          ) : (
            <span className="text-sm text-faint">Not built yet.</span>
          )}
        </div>

        {stage.also && stage.also.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-line pt-3">
            {stage.also.map((link) => (
              <Link
                key={link.route}
                to={link.route}
                className="group inline-flex min-h-10 items-center gap-1 rounded-control px-1 text-xs font-medium text-muted transition-colors hover:text-txt"
              >
                {link.label}
                <ArrowRight size={12} className="text-faint transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
              </Link>
            ))}
          </div>
        )}
      </div>
  )
}
