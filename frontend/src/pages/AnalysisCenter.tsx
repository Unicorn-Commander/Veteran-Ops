import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Banknote,
  Briefcase,
  CalendarClock,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  Coins,
  FileStack,
  FileText,
  FolderPlus,
  Gauge,
  History,
  Layers,
  Loader2,
  Plus,
  RefreshCw,
  ScanSearch,
  ScanText,
  Shield,
  Sparkles,
  TrendingUp,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ProSeDisclaimer } from '../components/Disclaimer'
import { KbFreshnessNote } from '../components/KbFreshnessNote'
import { CreditLimitNotice } from '../components/CreditLimitNotice'
import { GlitterImportOpportunity } from '../components/SuiteConnections'
import { useToast } from '../components/Toast'
import { cx, EmptyState, ErrorBlock, LoadingBlock, Panel, Skeleton } from '../components/ui'
import { Legend, type LegendGroup } from '../components/Legend'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { ApiError, analysisApi, conditionsApi } from '../lib/api'
import { nextRingsAfterAnalysis, progressInputFromParts } from '../lib/claimProgress'
import { formatBytes, formatDate, formatDateTime, formatProvenance, humanize } from '../lib/format'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type {
  AnalysisRun,
  AnalysisPrerequisites,
  AnalysisStep,
  AutomationItem,
  AutomationStatus,
  CasePicture,
  CasePictureCondition,
  CasePictureReadCompleteness,
  CasePictureTimelineEvent,
  ClaimedCondition,
  ComprehensiveRan,
  ConditionMapping,
  GapItem,
  IntakeBenchmark,
  PresumptiveMatch,
  Provenance,
  SecondarySuggestion,
} from '../types'

// /analysis — the Analysis Center. The single, clear home for RUNNING analyses
// over the veteran's case. One headline action (a full comprehensive pass) sits
// above a menu of targeted analyses, then the two richest outputs get their own
// panels: the whole-C-file Case Picture and a plain-language read of everything
// we've automated. Educational self-help only — options to consider, estimates
// labeled, never a prediction of what VA will decide.

const HUE: Hue = 'fuchsia'

/** How often to poll a running comprehensive job for live progress. */
const POLL_MS = 2000
const ACTIVE_RUN_STATUSES = new Set<AnalysisRun['status']>(['queued', 'leased', 'running', 'retryable'])
const COMPLETED_RUN_STATUSES = new Set<AnalysisRun['status']>(['completed', 'complete'])

/** Precise seconds (per-step / total wall-clock) → "12.3s" or "1m 05s". Tabular. */
function fmtSecs(s: number | null | undefined): string {
  if (s == null) return '—'
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const r = Math.round(s - m * 60)
  return `${m}m ${r < 10 ? '0' : ''}${r}s`
}

/** Whole-second live elapsed → "9s" or "1m 05s" (ticks each second, no jitter). */
function fmtElapsed(s: number): string {
  const whole = Math.max(0, Math.floor(s))
  if (whole < 60) return `${whole}s`
  const m = Math.floor(whole / 60)
  const r = whole % 60
  return `${m}m ${r < 10 ? '0' : ''}${r}s`
}

/** Re-render every second while `active`, so a live elapsed clock stays current.
 * Clears its interval when it goes inactive or the caller unmounts. */
function useTicker(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    setNow(Date.now())
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [active])
  return now
}

/** Start + poll the background comprehensive run. Resumes any in-flight (or last)
 * run on mount, polls every ~2s while queued/running, and stops cleanly on a
 * terminal status or unmount (no interval leaks, no setState-after-unmount).
 * `onComplete` fires once per run that completes so the page can refresh
 * the sibling read panels (case picture, automation, benchmark, history). */
function useComprehensiveRun(onComplete: () => void): {
  run: AnalysisRun | null
  running: boolean
  loadingLatest: boolean
  error: string | null
  syncError: string | null
  credit: boolean
  start: () => void
  cancel: () => void
  cancelling: boolean
} {
  const [run, setRun] = useState<AnalysisRun | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [loadingLatest, setLoadingLatest] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [credit, setCredit] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const startingRef = useRef(false)
  const startKeyRef = useRef<string | null>(null)
  const mountedRef = useRef(true)
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  // Resume on mount: show the latest run, and keep polling it if still in flight.
  // The sibling panels load on their own on mount, so a resumed completed run
  // needs no onComplete here.
  useEffect(() => {
    let cancelled = false
    analysisApi
      .latestRun()
      .then((latest) => {
        setSyncError(null)
        if (cancelled || !latest) return
        setRun(latest)
        if (ACTIVE_RUN_STATUSES.has(latest.status)) setRunId(latest.id)
      })
      .catch((err) => {
        if (!cancelled) setSyncError(`Could not check your recent analyses. ${errorMessage(err)}`)
      })
      .finally(() => {
        if (!cancelled) setLoadingLatest(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Poll the active run until terminal. Keyed only on runId so it subscribes once
  // per run; self-schedules with setTimeout and clears on unmount / id change.
  useEffect(() => {
    if (!runId) return
    let cancelled = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const next = await analysisApi.comprehensiveRun(runId)
        if (cancelled) return
        setSyncError(null)
        setRun(next)
        if (COMPLETED_RUN_STATUSES.has(next.status) || next.status === 'failed' || next.status === 'cancelled') {
          if (COMPLETED_RUN_STATUSES.has(next.status)) onCompleteRef.current()
          setRunId(null)
          return // terminal — stop polling
        }
      } catch (err) {
        // Keep the last known run visible while retrying; an outage is not an empty run.
        if (cancelled) return
        setSyncError(`Live progress is temporarily unavailable. ${errorMessage(err)} Retrying…`)
      }
      timer = window.setTimeout(tick, POLL_MS)
    }
    timer = window.setTimeout(tick, POLL_MS)
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [runId])

  const start = useCallback(() => {
    if (startingRef.current) return
    startingRef.current = true
    setStarting(true)
    setError(null)
    setSyncError(null)
    setCredit(false)
    const idempotencyKey = startKeyRef.current ?? crypto.randomUUID()
    startKeyRef.current = idempotencyKey
    void analysisApi
      .startComprehensive(idempotencyKey)
      .then((started) => {
        startKeyRef.current = null
        if (!mountedRef.current) return
        setRun(started)
        setRunId(started.id)
      })
      .catch((err) => {
        if (!mountedRef.current) return
        if (err instanceof ApiError && err.status === 402) setCredit(true)
        else setError(errorMessage(err))
      })
      .finally(() => {
        startingRef.current = false
        if (mountedRef.current) setStarting(false)
      })
  }, [])

  const cancel = useCallback(() => {
    if (!run || !ACTIVE_RUN_STATUSES.has(run.status) || cancelling) return
    setCancelling(true)
    void analysisApi
      .cancelComprehensive(run.id)
      .then((next) => {
        if (!mountedRef.current) return
        setRun(next)
        if (next.status === 'cancelled') setRunId(null)
      })
      .catch((err) => {
        if (mountedRef.current) setSyncError(`Cancellation could not be requested. ${errorMessage(err)}`)
      })
      .finally(() => {
        if (mountedRef.current) setCancelling(false)
      })
  }, [cancelling, run])

  const running = starting || !!(run && ACTIVE_RUN_STATUSES.has(run.status))
  return { run, running, loadingLatest, error, syncError, credit, start, cancel, cancelling }
}

const SECTIONS = [
  { id: 'comprehensive', label: 'Comprehensive' },
  { id: 'targeted', label: 'Targeted analyses' },
  { id: 'case-picture', label: 'Case picture' },
  { id: 'automated', label: 'Automated' },
] as const

/** A small chip that mirrors exactly how the page renders identity chips
 * (.vo-chip-hue + inline hue), so the legend matches what's on screen. */
function LegendChip({ hue, icon, children }: { hue: Hue; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className="vo-chip-hue" style={hueStyle(hue) as CSSProperties}>
      {icon}
      {children}
    </span>
  )
}

/** The Analysis Center key: the comprehensive-pass step chips, each condition's
 * service-connection element states, and VA's confidence register — explained
 * once so the symbols scattered across the page read plainly. */
const ANALYSIS_LEGEND_GROUPS: LegendGroup[] = [
  {
    label: 'Service-connection elements (per condition)',
    items: [
      {
        badge: (
          <LegendChip hue="emerald" icon={<CheckCircle2 size={12} />}>
            Present
          </LegendChip>
        ),
        desc: 'This element (a diagnosis, nexus, or in-service event) is supported somewhere in your file.',
      },
      {
        badge: (
          <LegendChip hue="amber" icon={<AlertCircle size={12} />}>
            Weak
          </LegendChip>
        ),
        desc: "Present, but it may not meet VA's standard yet — worth strengthening.",
      },
      {
        badge: (
          <LegendChip hue="rose" icon={<XCircle size={12} />}>
            Missing
          </LegendChip>
        ),
        desc: 'Not found yet — this element still needs evidence before the condition is complete.',
      },
    ],
  },
  {
    label: 'Comprehensive pass',
    items: [
      {
        badge: (
          <LegendChip hue="emerald" icon={<CheckCircle2 size={12} />}>
            Specialist review
          </LegendChip>
        ),
        desc: 'A green step chip means that part of the full pass ran over your file.',
      },
      {
        badge: <LegendChip hue="sky">Rating deep dive · skipped</LegendChip>,
        desc: 'A blue "skipped" chip means that part wasn’t needed for your file this run.',
      },
    ],
  },
  {
    label: 'Confidence — how VA weighs a theory',
    items: [
      {
        badge: <LegendChip hue="emerald">More likely than not</LegendChip>,
        desc: 'The evidence points more toward service connection than against it (>50%).',
      },
      {
        badge: <LegendChip hue="teal">At least as likely as not</LegendChip>,
        desc: 'The evidence is roughly balanced — VA resolves reasonable doubt in your favor.',
      },
      {
        badge: <LegendChip hue="amber">Less likely than not</LegendChip>,
        desc: 'The evidence currently weighs against the connection (<50%).',
      },
      {
        badge: <LegendChip hue="sky">Insufficient evidence yet</LegendChip>,
        desc: 'There isn’t enough in your file yet to weigh this — add records to strengthen it.',
      },
    ],
  },
]

export function AnalysisCenter() {
  // The comprehensive pass runs as a BACKGROUND job (start + poll — see
  // useComprehensiveRun) so a big C-file can't time out. The read panels load on
  // mount and refresh when a run completes; the intake benchmark + run history
  // pair with the run's per-step timing to show the full time-to-complete-a-file.
  const [searchParams, setSearchParams] = useSearchParams()
  const needStart = searchParams.get('need') === 'start'
  useEffect(() => {
    if (!needStart) return
    const next = new URLSearchParams(searchParams)
    next.delete('need')
    setSearchParams(next, { replace: true })
  }, [needStart, searchParams, setSearchParams])

  const {
    data: casePicture,
    loading: cpLoading,
    error: cpError,
    reload: reloadCasePicture,
  } = useAsync(() => analysisApi.casePicture())
  const {
    data: automation,
    loading: autoLoading,
    error: autoError,
    reload: reloadAutomation,
  } = useAsync(() => analysisApi.automationStatus())
  const { data: benchmark, loading: benchLoading, reload: reloadBenchmark } = useAsync(() =>
    analysisApi.intakeBenchmark(),
  )
  const { data: runHistory, loading: runsLoading, reload: reloadRuns } = useAsync(() =>
    analysisApi.runs(10),
  )
  const {
    data: prerequisites,
    loading: prerequisitesLoading,
    error: prerequisitesError,
    reload: reloadPrerequisites,
  } = useAsync(() => analysisApi.comprehensivePrerequisites())

  const onRunComplete = useCallback(() => {
    // A run's outputs feed all of these — refresh them when it finishes.
    reloadCasePicture()
    reloadAutomation()
    reloadBenchmark()
    reloadRuns()
  }, [reloadCasePicture, reloadAutomation, reloadBenchmark, reloadRuns])

  const { run, running, loadingLatest, error: compError, syncError, credit: compCredit, start, cancel, cancelling } =
    useComprehensiveRun(onRunComplete)

  return (
    <div
      data-section="insight"
      className="vo-page mx-auto w-full max-w-5xl space-y-6 p-4 pb-20 sm:p-6"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: hueLabel(HUE) }}>
          Insights · Analysis Center
        </p>
        <h1 className="vo-page-title">Analysis Center</h1>
        <p className="vo-page-sub">
          One place to put Rating Raider to work on your case. <strong className="font-semibold text-txt">Run full case
          review</strong> is the long whole-file pass (briefing, specialists, deep dive, comprehension). That is
          different from <strong className="font-semibold text-txt">Refresh Claim Plan</strong> on Your Claim Plan,
          which only re-runs specialists + briefing. Run a full pass here, or pick a targeted
          one — then read the whole-file picture and everything we've already checked for you automatically. It's all
          educational self-help; a free VSO files with you.
        </p>
      </div>

      <ProSeDisclaimer />
      <KbFreshnessNote hue={HUE} />

      {needStart && (
        <div
          className="vo-card vo-accent border-l-[3px] border-warning px-4 py-3"
          style={hueStyle('amber') as CSSProperties}
          role="status"
        >
          <p className="text-sm font-semibold text-txt">Full analysis did not start from Build Case</p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            Your conditions were added. Use the button below to run the comprehensive pass when you are ready — or open
            Claim Plan for the deterministic plan now.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Link to="/strategy" className="vo-btn-secondary min-h-9 text-xs">
              Open Claim Plan
            </Link>
          </div>
        </div>
      )}

      <SectionRail />

      <Legend groups={ANALYSIS_LEGEND_GROUPS} />

      {/* (A) The headline action + its live timing story. */}
      <section id="comprehensive" className="scroll-mt-24 space-y-4">
        <ComprehensiveHero
          run={run}
          running={running}
          loadingLatest={loadingLatest}
          error={compError}
          syncError={syncError}
          credit={compCredit}
          prerequisites={prerequisites}
          prerequisitesLoading={prerequisitesLoading}
          prerequisitesError={prerequisitesError}
          onRetryPrerequisites={reloadPrerequisites}
          onRun={start}
          onCancel={cancel}
          cancelling={cancelling}
        />
        {/* Import opportunity self-hides when GM is down; next-rings always useful. */}
        {(!run || COMPLETED_RUN_STATUSES.has(run.status)) && <GlitterImportOpportunity />}
        {(!run || !ACTIVE_RUN_STATUSES.has(run.status)) && (
          <NextRingsStrip
            analysisJustDone={
              !!run && (run.status === 'completed' || run.status === 'complete')
            }
            conditionCount={prerequisites?.conditions ?? 0}
          />
        )}
        <BenchmarkStrip
          benchmark={benchmark ?? null}
          benchLoading={benchLoading}
          runs={runHistory ?? null}
          runsLoading={runsLoading}
          activeRunId={run?.id ?? null}
        />
      </section>

      {/* (B) The targeted-analysis menu. */}
      <section id="targeted" className="scroll-mt-24 space-y-4">
        <SectionHeading
          icon={<Sparkles size={16} />}
          title="Run a targeted analysis"
          sub="Each one looks at your case from a different angle. Quick ones run right here; the deeper workspaces open in their own page. Nothing runs until you choose it."
        />
        <TargetedMenu />
      </section>

      {/* (C) The whole-C-file picture. */}
      <section id="case-picture" className="scroll-mt-24 space-y-4">
        <SectionHeading
          icon={<FileStack size={16} />}
          title="Your case picture"
          sub="Everything Rating Raider read across your entire file, assembled into one picture — your timeline, each condition's service-connection elements, contradictions to resolve, and how completely your file could be read."
        />
        <CasePicturePanel
          data={casePicture ?? null}
          loading={cpLoading}
          error={cpError}
          onRetry={reloadCasePicture}
          onRun={start}
          running={running}
          canRun={prerequisites?.ready === true}
        />
      </section>

      {/* (D) What we've automated for you. */}
      <section id="automated" className="scroll-mt-24 space-y-4">
        <SectionHeading
          icon={<Gauge size={16} />}
          title="What we've automated for you"
          sub="Work Rating Raider does in the background so you don't have to — what ran, what's ready, and what's waiting on your review."
        />
        <AutomationPanel data={automation ?? null} loading={autoLoading} error={autoError} onRetry={reloadAutomation} />
      </section>
    </div>
  )
}

/* ─────────────────────────────  SECTION RAIL  ────────────────────────────── */

/** Sticky in-page rail with scroll-spy — same pattern as the Battle Plan's,
 * so the long page reads as one navigable surface. Smooth-scrolls (honoring
 * reduced-motion) and marks the section you're reading with aria-current. */
function SectionRail() {
  const [active, setActive] = useState<string>(SECTIONS[0].id)

  useEffect(() => {
    const ids = SECTIONS.map((s) => s.id)
    const sections = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null)
    if (sections.length === 0) return
    const visible = new Set<string>()
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id)
          else visible.delete(entry.target.id)
        }
        const current = ids.find((id) => visible.has(id))
        if (current) setActive(current)
      },
      { rootMargin: '-104px 0px -55% 0px', threshold: 0 }
    )
    sections.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [])

  const go = (id: string) => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    document.getElementById(id)?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
    setActive(id)
  }

  return (
    <nav
      aria-label="Analysis Center sections"
      className="vo-no-print -mx-1 flex gap-1.5 overflow-x-auto rounded-full border border-line bg-surface px-2 py-1.5 sm:flex-wrap sm:overflow-visible"
      style={hueStyle(HUE) as CSSProperties}
    >
      {SECTIONS.map((s) => {
        const isActive = s.id === active
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => go(s.id)}
            aria-current={isActive ? 'true' : undefined}
            className={cx(
              'shrink-0 whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand',
              !isActive && 'text-muted hover:bg-surface2 hover:text-txt'
            )}
            style={
              isActive
                ? { background: hueSoftVar(HUE), color: hueInk(HUE), boxShadow: `inset 0 0 0 1px ${hueVar(HUE)}` }
                : undefined
            }
          >
            {s.label}
          </button>
        )
      })}
    </nav>
  )
}

/** Post-analysis journey strip — next rings after a full case review. */
function NextRingsStrip({
  analysisJustDone = false,
  conditionCount = 0,
}: {
  analysisJustDone?: boolean
  conditionCount?: number
}) {
  // Same path model as Home — prefer incomplete plan/file steps after a completed run.
  const rings = nextRingsAfterAnalysis(
    progressInputFromParts({
      profileIsEmpty: false,
      readyDocs: 1,
      reviewPending: 0,
      conditionCount,
      analysisDone: analysisJustDone,
      hasPlan: false,
      fileReady: false,
    }),
  )
  return (
    <div
      className="vo-card flex flex-wrap items-center gap-2 px-4 py-3"
      role="navigation"
      aria-label="Next steps after analysis"
    >
      <span className="text-xs font-semibold text-muted">Next rings</span>
      <span className="hidden text-faint sm:inline" aria-hidden>
        ·
      </span>
      {rings.map((r, i) => (
        <span key={r.to} className="flex items-center gap-2">
          {i > 0 && (
            <ArrowRight size={12} className="shrink-0 text-faint" aria-hidden />
          )}
          <Link to={r.to} className="text-xs font-semibold text-brand hover:underline">
            {r.label}
          </Link>
        </span>
      ))}
    </div>
  )
}

/* ──────────────────────────  A · COMPREHENSIVE HERO  ─────────────────────── */

const RAN_LABELS: { key: keyof ComprehensiveRan; label: string }[] = [
  { key: 'firm', label: 'Specialist review' },
  { key: 'briefing', label: 'Plain-language briefing' },
  { key: 'deep_dive', label: 'Rating deep dive' },
  { key: 'mapping', label: 'Rating-floor mapping' },
  { key: 'comprehension', label: 'Whole-case comprehension' },
]

/** The hero: one prominent button that runs every analysis over the whole file,
 * with a reassuring in-progress state and a consolidated result summary that
 * links onward into the Battle Plan and the case picture. THE headline action. */
function ComprehensiveHero({
  run,
  running,
  loadingLatest,
  error,
  syncError,
  credit,
  prerequisites,
  prerequisitesLoading,
  prerequisitesError,
  onRetryPrerequisites,
  onRun,
  onCancel,
  cancelling,
}: {
  run: AnalysisRun | null
  running: boolean
  loadingLatest: boolean
  error: string | null
  syncError: string | null
  credit: boolean
  prerequisites: AnalysisPrerequisites | null
  prerequisitesLoading: boolean
  prerequisitesError: string | null
  onRetryPrerequisites: () => void
  onRun: () => void
  onCancel: () => void
  cancelling: boolean
}) {
  const complete = !!run && COMPLETED_RUN_STATUSES.has(run.status)
  const summary = complete ? run?.summary ?? null : null
  const ran = complete ? run?.ran ?? null : null
  const hasRun = run != null
  const canRun = prerequisites?.ready === true
  const runDisabled = running || prerequisitesLoading || !!prerequisitesError || !canRun
  return (
    <div
      className="vo-card relative overflow-hidden p-0"
      style={{ ...(hueStyle(HUE) as CSSProperties), borderColor: hueVar(HUE) }}
    >
      <div className="relative p-5 sm:p-7">
        <div className="mb-3 flex items-center gap-2.5">
          <span
            aria-hidden
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
            style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}
          >
            <ScanSearch size={20} />
          </span>
          <div className="leading-tight">
            <span className="block text-micro font-bold uppercase tracking-wide" style={{ color: hueLabel(HUE) }}>
              Full case review
            </span>
            <span className="block text-xs text-muted">reviews the conditions and records you have added</span>
          </div>
        </div>

        <h2 className="max-w-3xl text-2xl font-bold leading-snug text-txt sm:text-[1.7rem]">
          Run a full case review
        </h2>
        <p className="mt-2 max-w-3xl text-[0.975rem] leading-relaxed text-txt/90">
          Rating Raider reviews your readable records, checks each condition, and prepares a plain-language summary.
          It can take several minutes. You can leave this page and return while it runs.
        </p>

        {prerequisitesLoading && (
          <p className="mt-4 flex items-center gap-2 text-sm text-muted" role="status">
            <RefreshCw size={14} className="animate-spin" /> Checking that your case is ready…
          </p>
        )}
        {prerequisitesError && (
          <div className="mt-4 border-l-[3px] border-danger px-3 py-2" role="alert">
            <p className="text-sm text-danger">Could not check whether the review is ready. {prerequisitesError}</p>
            <button type="button" onClick={onRetryPrerequisites} className="vo-btn-ghost mt-2 min-h-11 text-sm">
              <RefreshCw size={14} /> Check again
            </button>
          </div>
        )}
        {prerequisites && !prerequisites.ready && (
          <div id="analysis-missing-inputs" className="mt-4 border-l-[3px] border-warning pl-3" role="status">
            <p className="text-sm font-semibold text-txt">Before a full review can run</p>
            <div className="mt-2 divide-y divide-line">
              {prerequisites.missing.map((item) => (
                <Link
                  key={item.key}
                  to={item.route}
                  className="flex min-h-11 items-start gap-3 py-2.5 text-left hover:text-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-semibold text-txt">{item.label}</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-muted">{item.detail}</span>
                  </span>
                  <ArrowRight size={15} className="mt-1 shrink-0" />
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* The primary call-to-action. */}
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onRun}
            disabled={runDisabled}
            aria-busy={running}
            aria-describedby={!canRun && prerequisites ? 'analysis-missing-inputs' : undefined}
            className="vo-btn-primary w-full sm:w-auto"
          >
            {running ? (
              <>
                <RefreshCw size={16} className="animate-spin" /> Running full case review…
              </>
            ) : hasRun ? (
              <>
                <RefreshCw size={16} /> Run the full review again
              </>
            ) : (
              <>
                <Sparkles size={16} /> Run full case review
              </>
            )}
          </button>
          {run && ACTIVE_RUN_STATUSES.has(run.status) && (
            <button
              type="button"
              onClick={onCancel}
              disabled={cancelling || run.cancel_requested}
              className="vo-btn-secondary w-full sm:w-auto"
            >
              <XCircle size={16} />
              {run.cancel_requested ? 'Cancellation requested' : cancelling ? 'Requesting…' : 'Cancel analysis'}
            </button>
          )}
          {complete && (
            <>
              <Link
                to="/raider?mode=post_analysis&from=analysis"
                className="vo-btn-primary w-full sm:w-auto"
                onClick={() => {
                  try {
                    sessionStorage.setItem('vo_post_analysis_flow', '1')
                  } catch {
                    /* ignore */
                  }
                }}
              >
                <Sparkles size={15} /> Talk through your plan first
              </Link>
              <Link to="/strategy?from=analysis" className="vo-btn-secondary w-full sm:w-auto">
                <ArrowRight size={15} /> Skip to Claim Plan
              </Link>
            </>
          )}
        </div>
        {complete && (
          <p className="mt-3 text-xs leading-relaxed text-muted">
            Recommended: answer a few gap questions with Rating Raider, then open Claim Plan for{' '}
            <strong className="text-txt">Do this first</strong>. Educational only — you decide what to file.
          </p>
        )}

        {loadingLatest && !hasRun && (
          <p className="mt-3 flex items-center gap-1.5 text-xs text-muted">
            <RefreshCw size={12} className="animate-spin" /> Checking for a recent run…
          </p>
        )}
        {syncError && (
          <p className="mt-3 flex items-start gap-2 text-sm leading-relaxed text-warning" role="status">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" /> {syncError}
          </p>
        )}

        {/* Live per-step progress + running total — THE headline timing feature. */}
        {run && <LiveProgressPanel run={run} />}

        {(run?.status === 'failed' || run?.status === 'cancelled') && (
          <p
            className="mt-5 flex items-start gap-2 rounded-control border border-danger/30 bg-danger-soft px-3 py-2 text-sm leading-relaxed text-danger"
            role="alert"
          >
            <XCircle size={15} className="mt-0.5 shrink-0" />
            <span>
              {run.status === 'cancelled' ? 'The analysis was cancelled.' : 'The analysis stopped before finishing.'}
              {run.error ? ` ${run.error}` : ''} Your records are untouched — you can try again.
            </span>
          </p>
        )}

        {credit && (
          <div className="mt-5">
            <CreditLimitNotice />
          </div>
        )}
        {error && (
          <p
            className="mt-5 flex items-start gap-2 rounded-control border border-danger/30 bg-danger-soft px-3 py-2 text-sm leading-relaxed text-danger"
            role="alert"
          >
            <AlertCircle size={15} className="mt-0.5 shrink-0" /> The analysis couldn't start. {error} Check your
            connection, then try again.
          </p>
        )}

        {summary && (
          <div className="mt-6 space-y-4">
            {(summary.quality === 'partial' || summary.quality === 'minimal' || summary.degraded) && (
              <p
                className="flex items-start gap-2 rounded-control border border-warn/30 bg-h-amber-soft px-3 py-2 text-sm leading-relaxed text-txt"
                role="status"
              >
                <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" />
                <span>
                  Some analysis steps could not finish; results may be incomplete.
                  {summary.quality_notes && summary.quality_notes.length > 0
                    ? ` Missing: ${summary.quality_notes.join('; ')}.`
                    : ''}{' '}
                  You can run the full review again when ready.
                </span>
              </p>
            )}

            {ran && (
              <div className="flex flex-wrap gap-1.5">
                {RAN_LABELS.map(({ key, label }) => {
                  const didRun = ran[key]
                  return (
                    <span
                      key={key}
                      className="vo-chip-hue"
                      style={hueStyle(didRun ? 'emerald' : 'sky') as CSSProperties}
                    >
                      {didRun ? <CheckCircle2 size={12} /> : null}
                      {label}
                      {!didRun && ' · skipped'}
                    </span>
                  )
                })}
              </div>
            )}

            <div className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-3">
              <StatTile label="Conditions read" value={summary.conditions} />
              <StatTile label="Pathways mapped" value={summary.pathways} />
              <StatTile
                label="Deep-dive findings"
                value={summary.deep_dive_findings}
                badge={
                  summary.new_findings > 0 ? (
                    <span className="vo-chip-hue" style={hueStyle('teal') as CSSProperties}>
                      <Sparkles size={11} /> {summary.new_findings} new
                    </span>
                  ) : undefined
                }
              />
            </div>

            <CasePictureReadyLine ready={summary.case_picture_ready} />
          </div>
        )}
      </div>
    </div>
  )
}

/** THE headline: live, per-step progress of the running (or finished) job, with a
 * prominent running TOTAL and each step's own wall-clock seconds in tabular
 * numerals — the real computer burden and time to complete a file. */
function LiveProgressPanel({ run }: { run: AnalysisRun }) {
  const active = ACTIVE_RUN_STATUSES.has(run.status)
  const completed = COMPLETED_RUN_STATUSES.has(run.status)
  const now = useTicker(active)
  const terminal = completed || run.status === 'failed' || run.status === 'cancelled'
  const startedMs = run.started_at ? Date.parse(run.started_at) : NaN
  const liveElapsed = Number.isNaN(startedMs) ? 0 : Math.max(0, (now - startedMs) / 1000)
  const totalValue = terminal
    ? fmtSecs(run.total_seconds)
    : run.status === 'retryable'
      ? 'Waiting'
    : Number.isNaN(startedMs)
      ? 'Starting…'
      : fmtElapsed(liveElapsed)

  const headHue: Hue = run.status === 'failed' || run.status === 'cancelled' ? 'rose' : completed ? 'emerald' : HUE
  const headMsg =
    run.status === 'queued'
      ? 'Queued durably — waiting for a worker…'
      : run.status === 'leased'
        ? 'A worker has leased this analysis…'
      : run.status === 'running'
        ? 'Reading your whole file and running every analysis…'
        : run.status === 'retryable'
          ? `Retry scheduled${run.next_attempt_at ? ` for ${formatDateTime(run.next_attempt_at)}` : ''}`
        : completed
          ? 'Comprehensive analysis complete'
          : run.status === 'cancelled'
            ? 'Comprehensive analysis cancelled'
            : 'Comprehensive analysis stopped'
  const HeadIcon =
    run.status === 'failed' || run.status === 'cancelled' ? XCircle : completed ? CheckCircle2 : run.status === 'queued' || run.status === 'retryable' ? Clock : RefreshCw

  return (
    <div
      className="mt-5 rounded-control border p-4 sm:p-5"
      style={{ borderColor: hueVar(HUE), background: 'var(--surface)' }}
      role="status"
      aria-live="polite"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex items-center gap-2 text-sm font-semibold text-txt">
          <HeadIcon
            size={16}
            className={run.status === 'running' ? 'animate-spin' : ''}
            style={{ color: hueInk(headHue) }}
          />
          {headMsg}
          {run.attempt_count > 0 && (
            <span className="vo-chip text-micro">
              Attempt {run.attempt_count} of {run.max_attempts}
            </span>
          )}
        </p>
        <div className="shrink-0 text-right">
          <span className="block text-micro font-semibold uppercase tracking-wide text-faint">
            {terminal ? 'Total time' : run.status === 'retryable' ? 'State' : 'Elapsed'}
          </span>
          <span className="text-xl font-bold tabular-nums sm:text-2xl" style={{ color: hueInk(HUE) }}>
            {totalValue}
          </span>
        </div>
      </div>

      <ul className="mt-4 space-y-1">
        {run.steps.map((s) => (
          <StepRow key={s.key} step={s} />
        ))}
      </ul>

      <p className="mt-3 text-micro leading-relaxed text-faint">
        Per-step timing is real wall-clock — the computer burden of reading and analyzing your file. A cold run reads
        every page; later runs reuse cached work, so they finish faster.
      </p>
    </div>
  )
}

/** One step row: status indicator, label + detail, and per-step seconds (tabular). */
function StepRow({ step }: { step: AnalysisStep }) {
  const running = step.status === 'running'
  const secColor =
    step.status === 'complete' ? hueInk('emerald') : step.status === 'failed' ? hueInk('rose') : hueInk(HUE)
  const isDeepDive = step.key === 'deep_dive'
  const isComprehension = step.key === 'comprehension'
  return (
    <li
      className={cx('flex items-start gap-3 rounded-control px-3 py-2.5', running && isDeepDive && 'ring-1 ring-brand/25')}
      style={running ? { background: hueSoftVar(HUE) } : undefined}
    >
      <span aria-hidden className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
        <StepStatusIcon status={step.status} />
      </span>
      <span className="sr-only">{step.status}</span>
      <div className="min-w-0 flex-1">
        <p className={cx('text-sm', running ? 'font-semibold text-txt' : 'font-medium text-txt/90')}>
          {step.label}
          {running && isDeepDive && (
            <span className="ml-2 text-micro font-semibold uppercase tracking-wide text-brand">In progress</span>
          )}
        </p>
        {step.detail ? (
          <p className={cx('mt-0.5 text-xs leading-relaxed text-muted', running ? 'whitespace-normal' : 'line-clamp-2')}>
            {step.detail}
          </p>
        ) : running && isDeepDive ? (
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            Enumerating diagnostic codes, scoring CFR criteria, grounding findings — usually a few minutes.
          </p>
        ) : running && isComprehension ? (
          <p className="mt-0.5 text-xs leading-relaxed text-muted">
            Long-context pass over your records — often the longest step (~10–20+ min on a large file).
          </p>
        ) : null}
      </div>
      <span className="shrink-0 pt-0.5 text-sm font-bold tabular-nums" style={{ color: secColor }}>
        {step.seconds != null ? fmtSecs(step.seconds) : running ? '…' : ''}
      </span>
    </li>
  )
}

function StepStatusIcon({ status }: { status: AnalysisStep['status'] }) {
  if (status === 'complete')
    return <CheckCircle2 size={16} style={{ color: hueInk('emerald') }} />
  if (status === 'failed') return <XCircle size={16} style={{ color: hueInk('rose') }} />
  if (status === 'running')
    return <RefreshCw size={15} className="animate-spin" style={{ color: hueInk(HUE) }} />
  return <span className="block h-3.5 w-3.5 rounded-full border-2 border-line" />
}

/* ──────────────────  A.1 · TIMING & BENCHMARKS  ─────────────────── */

/** The timing companion to the hero: the (approximate) intake benchmark plus a
 * small run-history table, so cold-vs-warm runs can be compared. */
function BenchmarkStrip({
  benchmark,
  benchLoading,
  runs,
  runsLoading,
  activeRunId,
}: {
  benchmark: IntakeBenchmark | null
  benchLoading: boolean
  runs: AnalysisRun[] | null
  runsLoading: boolean
  activeRunId: string | null
}) {
  return (
    <Panel
      hue={HUE}
      title="Time to complete a file"
      subtitle="Approximate — the computer burden of reading and analyzing your records"
    >
      <div className="space-y-6 p-5">
        <IntakeBenchmarkReadout benchmark={benchmark} loading={benchLoading} />
        <RunHistoryTable runs={runs} loading={runsLoading} activeRunId={activeRunId} />
      </div>
    </Panel>
  )
}

function IntakeBenchmarkReadout({ benchmark, loading }: { benchmark: IntakeBenchmark | null; loading: boolean }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SubHeading icon={<Clock size={15} />} title="Document intake" />
        <span className="vo-chip-hue" style={hueStyle('sky') as CSSProperties}>
          Approximate
        </span>
      </div>
      {loading && !benchmark ? (
        <div className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="bg-surface p-3.5">
              <Skeleton className="h-3 w-20" />
              <Skeleton className="mt-2 h-5 w-16" />
            </div>
          ))}
        </div>
      ) : !benchmark ? (
        <p className="text-sm text-muted">
          No intake benchmark yet — upload your records and this fills in with how long reading your file takes.
        </p>
      ) : (
        <>
          <div className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-3">
            <BenchTile
              label="Records ready"
              value={`${benchmark.ready} / ${benchmark.documents}`}
              sub={[
                benchmark.failed > 0 ? `${benchmark.failed} failed` : null,
                benchmark.processing > 0 ? `${benchmark.processing} processing` : null,
                benchmark.duplicates > 0 ? `${benchmark.duplicates} duplicate skipped` : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            />
            <BenchTile label="Total read time" value={fmtSecs(benchmark.total_processing_seconds)} sub="summed across records" />
            <BenchTile label="Wall-clock" value={fmtSecs(benchmark.wall_clock_seconds)} sub="first upload → last ready" />
            <BenchTile label="Avg per record" value={fmtSecs(benchmark.avg_seconds_per_doc)} sub="approximate" />
            <BenchTile
              label="Total size"
              value={formatBytes(benchmark.total_bytes)}
              sub={`${benchmark.documents} document${benchmark.documents === 1 ? '' : 's'}`}
            />
            <BenchTile
              label="Last record ready"
              value={benchmark.last_ready_at ? formatDate(benchmark.last_ready_at) : '—'}
              sub={benchmark.first_uploaded_at ? `since ${formatDate(benchmark.first_uploaded_at)}` : 'from your uploads'}
            />
          </div>
          <p className="text-micro leading-relaxed text-faint">
            These intake numbers are approximate — they pair with the per-step run timing above to show the full time to
            complete your file.
          </p>
        </>
      )}
    </div>
  )
}

function BenchTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-surface p-3.5">
      <p className="text-micro font-semibold uppercase tracking-wide text-faint">{label}</p>
      <p className="mt-1 text-lg font-bold tabular-nums text-txt">{value}</p>
      {sub && <p className="mt-0.5 text-micro text-muted">{sub}</p>}
    </div>
  )
}

/** Recent runs, newest-first, so a cold first run and warmer later runs can be
 * compared by their total time and step count. */
function RunHistoryTable({
  runs,
  loading,
  activeRunId,
}: {
  runs: AnalysisRun[] | null
  loading: boolean
  activeRunId: string | null
}) {
  const rows = runs ?? []
  return (
    <div className="space-y-3">
      <SubHeading icon={<History size={15} />} title="Recent runs" />
      {loading && rows.length === 0 ? (
        <div className="space-y-1.5">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted">
          No comprehensive runs yet — run the full pass above to start your benchmark history.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-control border border-line">
          <table className="w-full min-w-[26rem] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-micro uppercase tracking-wide text-faint">
                <th className="px-3 py-2 font-semibold">Ran</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 text-right font-semibold">Total time</th>
                <th className="px-3 py-2 text-right font-semibold">Steps</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const when = r.started_at ?? r.finished_at ?? r.created_at
                const isCurrent = r.id === activeRunId
                const statusHue: Hue = COMPLETED_RUN_STATUSES.has(r.status) ? 'emerald' : r.status === 'failed' || r.status === 'cancelled' ? 'rose' : HUE
                return (
                  <tr
                    key={r.id}
                    className="border-b border-line last:border-0"
                    style={isCurrent ? { background: hueSoftVar(HUE) } : undefined}
                  >
                    <td className="whitespace-nowrap px-3 py-2 text-txt/90">
                      {when ? formatDateTime(when) : '—'}
                      {isCurrent && (
                        <span className="ml-1.5 text-micro font-semibold" style={{ color: hueInk(HUE) }}>
                          · current
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className="vo-chip-hue" style={hueStyle(statusHue) as CSSProperties}>
                        {humanize(r.status)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right font-semibold tabular-nums text-txt">
                      {fmtSecs(r.total_seconds)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-muted">{r.steps.length}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/** After a run: whether the whole-case picture is assembled, with a jump to it. */
function CasePictureReadyLine({ ready }: { ready: boolean }) {
  const hue: Hue = ready ? 'emerald' : 'amber'
  const goToCasePicture = () => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    document.getElementById('case-picture')?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  }
  return (
    <div
      className="flex flex-col gap-2 rounded-control border-l-[3px] px-3.5 py-3 sm:flex-row sm:items-center sm:justify-between"
      style={{ borderColor: hueVar(hue), background: hueSoftVar(hue) }}
    >
      <p className="flex items-start gap-2 text-sm leading-relaxed text-txt/90">
        {ready ? (
          <CheckCircle2 size={15} className="mt-0.5 shrink-0" style={{ color: hueInk(hue) }} />
        ) : (
          <RefreshCw size={15} className="mt-0.5 shrink-0" style={{ color: hueInk(hue) }} />
        )}
        <span>
          {ready
            ? 'Your whole-case picture is ready to read below.'
            : 'Your case picture is still assembling — it will appear below in a moment.'}
        </span>
      </p>
      {ready && (
        <button
          type="button"
          onClick={goToCasePicture}
          className="shrink-0 self-start rounded-control px-3 py-1.5 text-sm font-semibold sm:self-auto"
          style={{ background: 'var(--surface)', color: hueInk(hue) }}
        >
          View case picture <ArrowRight size={14} className="inline" />
        </button>
      )}
    </div>
  )
}

function StatTile({ label, value, badge }: { label: string; value: string | number; badge?: ReactNode }) {
  return (
    <div className="bg-surface p-4">
      <p className="text-micro font-semibold uppercase tracking-wide text-faint">{label}</p>
      <p className="mt-1 flex flex-wrap items-center gap-2 text-2xl font-bold tabular-nums text-txt">
        {value}
        {badge}
      </p>
    </div>
  )
}

/* ────────────────────────────  B · TARGETED MENU  ────────────────────────── */

type TargetedKey = 'map' | 'gaps' | 'secondaries' | 'presumptives'

interface TargetedDef {
  key: string
  title: string
  desc: string
  icon: typeof Sparkles
  hue: Hue
  /** inline = runs on this page; link = opens a full workspace page. */
  kind: 'inline' | 'link'
  to?: string
  cta: string
}

const TARGETED: TargetedDef[] = [
  {
    key: 'map',
    title: 'Rating-floor mapping',
    desc: "The VA rating tiers each of your conditions maps to — and where your current rating may sit below the floor the schedule allows.",
    icon: Layers,
    hue: 'violet',
    kind: 'inline',
    cta: 'Run mapping',
  },
  {
    key: 'gaps',
    title: 'Evidence gaps by condition',
    desc: 'Check every condition for the evidence it still needs — a diagnosis, a nexus, or proof of the in-service event.',
    icon: AlertCircle,
    hue: 'amber',
    kind: 'inline',
    cta: 'Check gaps',
  },
  {
    key: 'secondaries',
    title: 'Secondary conditions',
    desc: "Conditions that often develop from what you've already claimed — worth discussing with your provider.",
    icon: Sparkles,
    hue: 'fuchsia',
    kind: 'inline',
    cta: 'Suggest secondaries',
  },
  {
    key: 'presumptives',
    title: 'Presumptive screen',
    desc: 'Screen your service periods and exposures against VA’s presumptive lists — PACT Act, Agent Orange, and more.',
    icon: Shield,
    hue: 'pink',
    kind: 'inline',
    cta: 'Screen presumptives',
  },
  {
    key: 'tdiu',
    title: 'TDIU (unemployability)',
    desc: 'See whether you may be paid at the 100% rate without a 100% rating because your conditions keep you from working.',
    icon: Briefcase,
    hue: 'emerald',
    kind: 'link',
    to: '/tdiu',
    cta: 'Open TDIU',
  },
  {
    key: 'concurrent',
    title: 'Concurrent pay (CRDP / CRSC)',
    desc: 'Military retirees: check which concurrent-receipt program may restore pay offset against your VA compensation.',
    icon: Banknote,
    hue: 'teal',
    kind: 'link',
    to: '/concurrent-pay',
    cta: 'Open concurrent pay',
  },
  {
    key: 'decode',
    title: 'Decision decoder',
    desc: 'Turn a VA decision letter into plain English — what was granted, what was denied, and your appeal options.',
    icon: ScanText,
    hue: 'fuchsia',
    kind: 'link',
    to: '/decode',
    cta: 'Open decoder',
  },
  {
    key: 'backpay',
    title: 'Back-pay estimate',
    desc: 'Estimate the retroactive pay you may be owed from your effective date — a deterministic planning number.',
    icon: Coins,
    hue: 'sky',
    kind: 'link',
    to: '/backpay',
    cta: 'Open back pay',
  },
]

function TargetedMenu() {
  const [open, setOpen] = useState<TargetedKey | null>(null)
  const resultsRef = useRef<HTMLDivElement>(null)

  const openInline = (key: TargetedKey) => {
    setOpen(key)
    // Let the panel mount, then bring it into view.
    window.setTimeout(() => {
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      resultsRef.current?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'nearest' })
    }, 60)
  }

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {TARGETED.map((def) => (
          <TargetedCard
            key={def.key}
            def={def}
            active={def.kind === 'inline' && open === (def.key as TargetedKey)}
            onOpen={() => openInline(def.key as TargetedKey)}
          />
        ))}
      </div>

      {open && (
        <div ref={resultsRef} className="scroll-mt-24">
          <TargetedResults key={open} targetedKey={open} />
        </div>
      )}
    </>
  )
}

function TargetedCard({ def, active, onOpen }: { def: TargetedDef; active: boolean; onOpen: () => void }) {
  const inner = (
    <>
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar(def.hue), color: hueInk(def.hue) }}
        >
          <def.icon size={17} />
        </span>
        <div className="min-w-0">
          <p className="font-semibold leading-snug text-txt">{def.title}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{def.desc}</p>
        </div>
      </div>
      <div
        className="mt-3 flex items-center gap-1.5 text-sm font-semibold"
        style={{ color: hueInk(def.hue) }}
      >
        {def.kind === 'inline' ? (active ? 'Showing results below' : def.cta) : def.cta}
        <ArrowRight size={14} />
      </div>
    </>
  )

  const className = 'vo-card vo-accent vo-card-hover flex h-full flex-col p-4 text-left'
  const style: CSSProperties = {
    ...(hueStyle(def.hue) as CSSProperties),
    ...(active ? { boxShadow: `0 0 0 1.5px ${hueVar(def.hue)}` } : {}),
  }

  if (def.kind === 'link' && def.to) {
    return (
      <Link to={def.to} className={className} style={style}>
        {inner}
      </Link>
    )
  }
  return (
    <button type="button" onClick={onOpen} aria-expanded={active} className={className} style={style}>
      {inner}
    </button>
  )
}

/** Small run-once helper for the inline panels: runs a loader on mount, exposes
 * loading / data / error, surfaces a credit (402) wall separately, and can retry. */
function useRun<T>(loader: () => Promise<T>): {
  data: T | null
  loading: boolean
  error: string | null
  credit: boolean
  retry: () => void
} {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: string | null; credit: boolean }>({
    data: null,
    loading: true,
    error: null,
    credit: false,
  })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let active = true
    setState((s) => ({ ...s, loading: true, error: null, credit: false }))
    loader()
      .then((data) => {
        if (active) setState({ data, loading: false, error: null, credit: false })
      })
      .catch((err) => {
        if (!active) return
        if (err instanceof ApiError && err.status === 402) {
          setState({ data: null, loading: false, error: null, credit: true })
        } else {
          setState({ data: null, loading: false, error: errorMessage(err), credit: false })
        }
      })
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce])

  return { ...state, retry: () => setNonce((n) => n + 1) }
}

function TargetedResults({ targetedKey }: { targetedKey: TargetedKey }) {
  switch (targetedKey) {
    case 'map':
      return <MapConditionsPanel />
    case 'gaps':
      return <GapsPanel />
    case 'secondaries':
      return <SecondariesPanel />
    case 'presumptives':
      return <PresumptivesPanel />
    default:
      return null
  }
}

/* ---- B.1 · rating-floor mapping (GET cache / POST once, saved) ---- */

function MapConditionsPanel() {
  // Prefer saved map; only compute on first open or explicit refresh.
  const { data, loading, error, credit, retry } = useRun(async () => {
    const cached = await analysisApi.getMapConditions()
    if (cached.items.length > 0) return cached
    return analysisApi.mapConditions([], false)
  })
  const [refreshing, setRefreshing] = useState(false)

  const refresh = async () => {
    setRefreshing(true)
    try {
      await analysisApi.mapConditions([], true)
      retry()
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <Panel
      hue="violet"
      title="Rating-floor mapping"
      subtitle="Saved after the first run (and as part of full analysis). Refresh only when conditions change."
    >
      <div className="space-y-4 p-5">
        {loading || refreshing ? (
          <LoadingBlock
            label={
              refreshing
                ? 'Updating mapping…'
                : 'Loading saved mapping (or running once if new)…'
            }
          />
        ) : credit ? (
          <CreditLimitNotice />
        ) : error ? (
          <ErrorBlock message={error} onRetry={retry} />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            hue="violet"
            icon={<Layers size={20} />}
            title="No conditions to map yet"
            description="Add the conditions you're claiming, then run this (or full analysis) to map them to the VA rating schedule. Results are saved."
            action={
              <div className="flex flex-wrap gap-2">
                <Link to="/conditions" className="vo-btn-primary text-sm">
                  Add conditions
                </Link>
                <button type="button" onClick={() => void refresh()} className="vo-btn-secondary text-sm">
                  Run mapping
                </button>
              </div>
            }
          />
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-muted">
                Saved mapping for your current conditions list. Full analysis also refreshes this when needed.
              </p>
              <button
                type="button"
                onClick={() => void refresh()}
                disabled={refreshing}
                className="vo-btn-ghost text-xs"
              >
                Update mapping
              </button>
            </div>
            <MapConditionsWithActions items={data.items} />
            <p className="text-xs leading-relaxed text-faint">{data.disclaimer}</p>
          </>
        )}
      </div>
    </Panel>
  )
}

function MapConditionsWithActions({ items }: { items: ConditionMapping[] }) {
  const { data: claimed } = useAsync(() => conditionsApi.list())
  return (
    <>
      {items.map((m, i) => (
        <ConditionMappingCard key={`${m.name}-${i}`} m={m} claimed={claimed ?? []} />
      ))}
    </>
  )
}

function ConditionMappingCard({
  m,
  claimed,
}: {
  m: ConditionMapping
  claimed: ClaimedCondition[]
}) {
  const hue: Hue = m.under_rated ? 'amber' : 'violet'
  const existing = claimed.find(
    (c) => c.name.trim().toLowerCase() === m.name.trim().toLowerCase(),
  )
  return (
    <div className="vo-card vo-accent p-4" style={hueStyle(hue) as CSSProperties}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-semibold leading-snug text-txt">{m.name}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            {m.diagnostic_code && <span>DC {m.diagnostic_code}</span>}
            {m.body_system && <span>{m.body_system}</span>}
          </div>
        </div>
        {m.under_rated && (
          <span className="vo-chip-hue" style={hueStyle('amber') as CSSProperties}>
            <TrendingUp size={12} /> May be under-rated
          </span>
        )}
      </div>

      {m.rationale && <p className="mt-2.5 text-sm leading-relaxed text-txt/85">{m.rationale}</p>}

      {m.tiers.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {m.tiers.map((t, i) => {
            const suggested = m.suggested_discussion_tier != null && t.percent === m.suggested_discussion_tier
            return (
              <li
                key={i}
                className={cx(
                  'flex items-start gap-3 rounded-control border px-3 py-2',
                  !suggested && 'border-line bg-surface2'
                )}
                style={suggested ? { borderColor: hueVar(hue), background: hueSoftVar(hue) } : undefined}
              >
                <span
                  className="mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-micro font-bold tabular-nums"
                  style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
                >
                  {t.percent}%
                </span>
                <div className="min-w-0">
                  <p className="text-sm leading-snug text-txt/90">{t.criteria}</p>
                  {t.evidence_needed.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {t.evidence_needed.map((e, j) => (
                        <span key={j} className="vo-chip text-micro">
                          {e}
                        </span>
                      ))}
                    </div>
                  )}
                  {suggested && (
                    <p className="mt-1.5 text-micro font-semibold uppercase tracking-wide" style={{ color: hueInk(hue) }}>
                      Worth discussing with your provider
                    </p>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
        {existing ? (
          <>
            <Link to={`/conditions/${existing.id}`} className="vo-btn-primary min-h-9 text-xs">
              Open condition <ArrowRight size={12} />
            </Link>
            {m.under_rated && (
              <Link to={`/conditions/${existing.id}`} className="vo-btn-secondary min-h-9 text-xs">
                Review evidence for increase
              </Link>
            )}
          </>
        ) : (
          <Link
            to={`/conditions?add=${encodeURIComponent(m.name)}`}
            className="vo-btn-primary min-h-9 text-xs"
          >
            <Plus size={12} /> Add to case
          </Link>
        )}
        <Link to="/readiness" className="vo-btn-ghost min-h-9 text-xs">
          Evidence readiness
        </Link>
        <Link to="/strategy" className="vo-btn-ghost min-h-9 text-xs">
          Claim plan
        </Link>
      </div>

      {m.caveat && <p className="mt-3 text-micro leading-relaxed text-faint">{m.caveat}</p>}
    </div>
  )
}

/* ---- B.2 · evidence gaps per condition (GET /conditions/:id/gaps) ---- */

interface ConditionGaps {
  condition: ClaimedCondition
  gaps: GapItem[]
}

function GapsPanel() {
  const { data, loading, error, retry } = useRun<ConditionGaps[]>(async () => {
    const conditions = await conditionsApi.list()
    const rows = await Promise.all(
      conditions.map(async (condition) => {
        try {
          const res = await conditionsApi.gaps(condition.id)
          return { condition, gaps: res.gaps }
        } catch {
          // A single condition's gap read failing shouldn't sink the whole panel.
          return { condition, gaps: [] as GapItem[] }
        }
      })
    )
    // Conditions with open gaps first, then by gap count (most first).
    return rows.sort((a, b) => b.gaps.length - a.gaps.length)
  })

  return (
    <Panel
      hue="amber"
      title="Evidence gaps by condition"
      subtitle="What each condition still needs — open one to work its gaps"
    >
      <div className="space-y-3 p-5">
        {loading ? (
          <LoadingBlock label="Checking each condition for evidence gaps…" />
        ) : error ? (
          <ErrorBlock message={error} onRetry={retry} />
        ) : !data || data.length === 0 ? (
          <EmptyState
            hue="amber"
            icon={<AlertCircle size={20} />}
            title="No conditions to check yet"
            description="Add the conditions you're claiming, then run this to see the evidence each one still needs."
            action={
              <Link to="/conditions" className="vo-btn-primary text-sm">
                Add conditions
              </Link>
            }
          />
        ) : (
          data.map(({ condition, gaps }) => <ConditionGapRow key={condition.id} condition={condition} gaps={gaps} />)
        )}
      </div>
    </Panel>
  )
}

function ConditionGapRow({ condition, gaps }: { condition: ClaimedCondition; gaps: GapItem[] }) {
  const hasGaps = gaps.length > 0
  const hue: Hue = hasGaps ? 'amber' : 'emerald'
  return (
    <Link
      to={`/conditions/${condition.id}`}
      className="vo-card vo-accent vo-card-hover block p-4"
      style={hueStyle(hue) as CSSProperties}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold leading-snug text-txt">{condition.name}</p>
          {condition.diagnostic_code && <p className="mt-0.5 text-xs text-muted">DC {condition.diagnostic_code}</p>}
        </div>
        <span className="vo-chip-hue shrink-0" style={hueStyle(hue) as CSSProperties}>
          {hasGaps ? (
            <>
              <AlertCircle size={12} /> {gaps.length} gap{gaps.length === 1 ? '' : 's'}
            </>
          ) : (
            <>
              <CheckCircle2 size={12} /> Core evidence in place
            </>
          )}
        </span>
      </div>
      {hasGaps && (
        <ul className="mt-2.5 space-y-1">
          {gaps.slice(0, 4).map((g, i) => (
            <li key={i} className="flex items-start gap-2 text-sm leading-snug text-txt/85">
              <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: hueVar(hue) }} />
              <span>{g.label}</span>
            </li>
          ))}
          {gaps.length > 4 && <li className="text-xs text-faint">+{gaps.length - 4} more — open to see all</li>}
        </ul>
      )}
    </Link>
  )
}

/* ---- B.3 · secondary conditions (POST /analysis/secondaries) ---- */

function useClaimedIndex() {
  const { data, reload } = useAsync(() => conditionsApi.list())
  const byName = useMemo(() => {
    const m = new Map<string, ClaimedCondition>()
    for (const c of data ?? []) m.set(c.name.trim().toLowerCase(), c)
    return m
  }, [data])
  return { claimed: data ?? [], byName, reloadClaimed: reload }
}

function SecondariesPanel() {
  const { toast } = useToast()
  const { data, loading, error, credit, retry } = useRun(() => analysisApi.secondaries())
  const { claimed, byName, reloadClaimed } = useClaimedIndex()
  const items = data?.items ?? []
  const [busy, setBusy] = useState<string | null>(null)

  const addSecondary = async (s: SecondarySuggestion) => {
    const key = s.secondary.trim().toLowerCase()
    if (byName.has(key)) {
      toast('Already on your case', 'info')
      return
    }
    setBusy(key)
    try {
      const primary = byName.get(s.primary.trim().toLowerCase())
      await conditionsApi.create({
        name: s.secondary.trim(),
        claim_type: 'secondary',
        secondary_to: primary?.id ?? null,
        status: 'considering',
        notes: s.rationale
          ? `Suggested secondary to ${s.primary}. ${s.rationale}`
          : `Suggested secondary to ${s.primary}.`,
        nexus_notes: s.rationale || null,
        dbq_form: s.dbq || null,
      })
      toast(`Added “${s.secondary}” as secondary — review on Conditions`, 'success')
      await reloadClaimed()
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setBusy(null)
    }
  }

  const openOnes = items.filter((s) => !byName.has(s.secondary.trim().toLowerCase()))

  return (
    <Panel
      hue="fuchsia"
      title="Suggested secondaries"
      subtitle="Common secondary patterns — add ones you want on your case, then gather evidence. Educational only; VA decides."
    >
      <div className="space-y-4 p-5">
        {loading ? (
          <LoadingBlock label="Checking the secondary-conditions map…" />
        ) : credit ? (
          <CreditLimitNotice />
        ) : error ? (
          <ErrorBlock message={error} onRetry={retry} />
        ) : items.length === 0 ? (
          <EmptyState
            hue="fuchsia"
            icon={<Sparkles size={20} />}
            title="No mapped patterns for your current conditions"
            description="This list only covers common, well-documented secondary patterns — a provider or VSO may see connections it doesn't."
          />
        ) : (
          <>
            {openOnes.length > 0 && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-line bg-surface2 px-3 py-2.5">
                <p className="text-xs text-muted">
                  {openOnes.length} not on your case yet. Adding marks them as{' '}
                  <strong className="text-txt">considering</strong> — you choose whether to file.
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!!busy}
                    onClick={() =>
                      void (async () => {
                        for (const s of openOnes) await addSecondary(s)
                      })()
                    }
                    className="vo-btn-primary min-h-9 text-xs"
                  >
                    {busy ? <Loader2 size={12} className="animate-spin" /> : <FolderPlus size={12} />}
                    Add all to case
                  </button>
                  <Link to="/build-case" className="vo-btn-secondary min-h-9 text-xs">
                    Populate case from records
                  </Link>
                </div>
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              {items.map((s, i) => {
                const onCase = byName.get(s.secondary.trim().toLowerCase())
                const primary = byName.get(s.primary.trim().toLowerCase())
                const key = s.secondary.trim().toLowerCase()
                return (
                  <div
                    key={i}
                    className="vo-card vo-accent flex flex-col p-5"
                    style={hueStyle('pink') as CSSProperties}
                  >
                    <h3 className="text-base font-semibold text-txt">{s.secondary}</h3>
                    <p className="mt-0.5 text-xs font-medium" style={{ color: hueInk('pink') }}>
                      secondary to {s.primary}
                      {primary ? '' : ' (add the primary on your case if missing)'}
                    </p>
                    <p className="mt-3 flex-1 text-sm text-muted">{s.rationale}</p>
                    {(s.dbq || s.source) && (
                      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-3">
                        {s.dbq && (
                          <span className="vo-chip">
                            <FileText size={11} className="shrink-0 text-brand" /> DBQ {s.dbq}
                          </span>
                        )}
                        {s.source && <span className="vo-chip">{s.source}</span>}
                      </div>
                    )}
                    <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
                      {onCase ? (
                        <>
                          <span className="vo-chip-hue text-xs" style={hueStyle('emerald') as CSSProperties}>
                            <CheckCircle2 size={12} /> On your case
                          </span>
                          <Link to={`/conditions/${onCase.id}`} className="vo-btn-primary min-h-9 text-xs">
                            Open condition <ArrowRight size={12} />
                          </Link>
                          <Link to="/readiness" className="vo-btn-ghost min-h-9 text-xs">
                            Evidence readiness
                          </Link>
                        </>
                      ) : (
                        <>
                          <button
                            type="button"
                            disabled={busy === key}
                            onClick={() => void addSecondary(s)}
                            className="vo-btn-primary min-h-9 text-xs"
                          >
                            {busy === key ? (
                              <Loader2 size={12} className="animate-spin" />
                            ) : (
                              <Plus size={12} />
                            )}
                            Include in case
                          </button>
                          <Link
                            to={`/build-case?q=${encodeURIComponent(s.secondary)}`}
                            className="vo-btn-secondary min-h-9 text-xs"
                          >
                            Match to records
                          </Link>
                          <Link
                            to={`/conditions?add=${encodeURIComponent(s.secondary)}`}
                            className="vo-btn-ghost min-h-9 text-xs"
                          >
                            Add manually
                          </Link>
                        </>
                      )}
                      <Link to="/strategy" className="vo-btn-ghost min-h-9 text-xs">
                        Claim plan
                      </Link>
                    </div>
                  </div>
                )
              })}
            </div>
            {claimed.length > 0 && openOnes.length === 0 && (
              <p className="text-xs text-muted">All suggested secondaries are already on your case.</p>
            )}
            {data?.disclaimer && <p className="text-xs leading-relaxed text-faint">{data.disclaimer}</p>}
          </>
        )}
      </div>
    </Panel>
  )
}

/* ---- B.4 · presumptive screen (GET /analysis/presumptives) ---- */

function PresumptivesPanel() {
  const { toast } = useToast()
  const { data, loading, error, retry } = useRun(() => analysisApi.presumptives())
  const { byName, reloadClaimed } = useClaimedIndex()
  const matches = data?.matches ?? []
  const [busy, setBusy] = useState<string | null>(null)

  const namesFromMatch = (m: PresumptiveMatch): string[] => {
    const fromList = (m.conditions ?? []).map((n) => n.trim()).filter(Boolean)
    if (fromList.length) return fromList
    return m.condition?.trim() ? [m.condition.trim()] : []
  }

  const addPresumptive = async (name: string, m: PresumptiveMatch) => {
    const key = name.trim().toLowerCase()
    if (byName.has(key)) {
      toast(`“${name}” is already on your case`, 'info')
      return
    }
    setBusy(key)
    try {
      await conditionsApi.create({
        name: name.trim(),
        claim_type: 'presumptive',
        status: 'considering',
        notes: m.program
          ? `Presumptive screen: ${m.program}. ${m.matched_reason || m.rationale || ''}`.trim()
          : m.rationale || null,
      })
      toast(`Added “${name}” as presumptive candidate — review on Conditions`, 'success')
      await reloadClaimed()
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel
      hue="pink"
      title="Presumptive screen"
      subtitle="Rule-based screen of service + exposures. Add candidates you want on your case, then confirm with records or a VSO."
    >
      <div className="space-y-3 p-5">
        {loading ? (
          <LoadingBlock label="Screening your profile…" />
        ) : error ? (
          <ErrorBlock message={error} onRetry={retry} />
        ) : matches.length === 0 ? (
          <EmptyState
            hue="pink"
            icon={<Shield size={20} />}
            title="No presumptive matches yet"
            description="Based on what's in your profile now, nothing matched. Add or update your service periods and exposures so Veteran-Ops can check them against VA's presumptive lists."
            action={
              <Link to="/profile?start=1" className="vo-btn-primary text-sm">
                Go to profile
              </Link>
            }
          />
        ) : (
          matches.map((m, i) => {
            const names = namesFromMatch(m)
            return (
              <div key={i} className="vo-card vo-accent p-4" style={hueStyle('pink') as CSSProperties}>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-semibold text-txt">{m.condition}</h3>
                  {m.program && (
                    <span className="vo-chip-hue" style={hueStyle('emerald') as CSSProperties}>
                      {m.program}
                    </span>
                  )}
                </div>
                {m.matched_reason && (
                  <p className="mt-2 text-sm font-medium leading-snug" style={{ color: hueInk('pink') }}>
                    Why this matched: {m.matched_reason}
                  </p>
                )}
                <p className="mt-1.5 text-sm text-muted">{m.rationale}</p>
                {m.source && <span className="vo-chip mt-2.5 inline-flex">{m.source}</span>}

                {names.length > 0 && (
                  <ul className="mt-3 space-y-2 border-t border-line pt-3">
                    {names.map((name) => {
                      const onCase = byName.get(name.toLowerCase())
                      const key = name.toLowerCase()
                      return (
                        <li
                          key={name}
                          className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-line bg-surface2 px-3 py-2"
                        >
                          <span className="text-sm font-medium text-txt">{name}</span>
                          <div className="flex flex-wrap gap-2">
                            {onCase ? (
                              <Link to={`/conditions/${onCase.id}`} className="vo-btn-primary min-h-9 text-xs">
                                <CheckCircle2 size={12} /> On case — open
                              </Link>
                            ) : (
                              <button
                                type="button"
                                disabled={busy === key}
                                onClick={() => void addPresumptive(name, m)}
                                className="vo-btn-primary min-h-9 text-xs"
                              >
                                {busy === key ? (
                                  <Loader2 size={12} className="animate-spin" />
                                ) : (
                                  <Plus size={12} />
                                )}
                                Include in case
                              </button>
                            )}
                            <Link
                              to={`/build-case?q=${encodeURIComponent(name)}`}
                              className="vo-btn-ghost min-h-9 text-xs"
                            >
                              Match to records
                            </Link>
                          </div>
                        </li>
                      )
                    })}
                  </ul>
                )}

                <div className="mt-3 flex flex-wrap gap-2">
                  <Link to="/profile?start=1" className="vo-btn-ghost min-h-9 text-xs">
                    Update service / exposures
                  </Link>
                  <Link to="/strategy" className="vo-btn-ghost min-h-9 text-xs">
                    Claim plan
                  </Link>
                  <Link to="/application" className="vo-btn-ghost min-h-9 text-xs">
                    Filing packet
                  </Link>
                </div>
              </div>
            )
          })
        )}
      </div>
    </Panel>
  )
}

/* ────────────────────────────  C · CASE PICTURE  ─────────────────────────── */

function CasePicturePanel({
  data,
  loading,
  error,
  onRetry,
  onRun,
  running,
  canRun,
}: {
  data: { status: 'ready' | 'not_generated'; generated_at: string | null; picture: CasePicture | null } | null
  loading: boolean
  error: string | null
  onRetry: () => void
  onRun: () => void
  running: boolean
  canRun: boolean
}) {
  if (loading && !data) {
    return (
      <Panel hue={HUE}>
        <div className="p-5">
          <LoadingBlock label="Loading your case picture…" />
        </div>
      </Panel>
    )
  }
  if (error && !data) {
    return (
      <Panel hue="rose">
        <div className="p-5">
          <ErrorBlock message={error} onRetry={onRetry} />
        </div>
      </Panel>
    )
  }

  const picture = data?.status === 'ready' ? data.picture : null
  if (!picture) {
    return (
      <Panel hue={HUE}>
        <div className="p-5">
          <EmptyState
            hue={HUE}
            icon={<FileStack size={22} />}
            title="No case picture yet"
            description="Run the full comprehensive analysis above and Rating Raider reads your entire file, then assembles the whole picture right here — your timeline, every condition's service-connection elements, and any contradictions to resolve."
            action={
              canRun ? <button type="button" onClick={onRun} disabled={running} className="vo-btn-primary text-sm">
                {running ? (
                  <>
                    <RefreshCw size={15} className="animate-spin" /> Running…
                  </>
                ) : (
                  <>
                    <Sparkles size={15} /> Run full case review
                  </>
                )}
              </button> : <button
                type="button"
                onClick={() => document.getElementById('comprehensive')?.scrollIntoView({ block: 'start' })}
                className="vo-btn-secondary text-sm"
              >
                <ArrowRight size={15} /> Review missing inputs
              </button>
            }
          />
        </div>
      </Panel>
    )
  }

  return (
    <div className="space-y-4">
      {picture.read_completeness && <ReadCompletenessBanner rc={picture.read_completeness} />}

      <Panel
        hue={HUE}
        title="The whole picture"
        subtitle={data?.generated_at ? `Assembled ${formatDateTime(data.generated_at)}` : 'Assembled from your file'}
      >
        <div className="space-y-6 p-5">
          <InventoryStrip picture={picture} />

          {picture.condition_roster.length > 0 && (
            <div className="space-y-3">
              <SubHeading icon={<CheckCircle2 size={15} />} title="Condition roster" />
              {picture.condition_roster.map((c, i) => (
                <RosterCard key={`${c.name}-${i}`} c={c} />
              ))}
            </div>
          )}

          {picture.timeline.length > 0 && (
            <div className="space-y-3">
              <SubHeading icon={<CalendarClock size={15} />} title="Your timeline" />
              <ol className="relative space-y-3.5 pl-1">
                <span aria-hidden className="absolute bottom-2 left-[6px] top-2 w-px bg-line" />
                {picture.timeline.map((e, i) => (
                  <TimelineRow key={i} event={e} />
                ))}
              </ol>
            </div>
          )}

          {picture.contradictions.length > 0 && (
            <div className="space-y-3">
              <SubHeading icon={<AlertTriangle size={15} />} title="Contradictions to resolve" hue="rose" />
              {picture.contradictions.map((c, i) => (
                <NoteRow key={i} note={c.note} provenance={c.provenance} hue="rose" />
              ))}
            </div>
          )}

          {picture.coverage_gaps.length > 0 && (
            <div className="space-y-3">
              <SubHeading icon={<AlertCircle size={15} />} title="Coverage gaps" hue="amber" />
              {picture.coverage_gaps.map((g, i) => (
                <CoverageGapRow key={i} condition={g.condition} missing={g.missing_elements} note={g.note} />
              ))}
            </div>
          )}

          {picture.grounding_excerpts.length > 0 && <GroundingExcerpts excerpts={picture.grounding_excerpts} />}
        </div>
      </Panel>
    </div>
  )
}

function ReadCompletenessBanner({ rc }: { rc: CasePictureReadCompleteness }) {
  const hue: Hue = rc.complete ? 'emerald' : rc.truncated || rc.segments_failed > 0 || rc.pages_unreadable > 0 ? 'amber' : 'sky'
  const Icon = rc.complete ? CheckCircle2 : AlertTriangle
  return (
    <div className="vo-card vo-accent p-4 sm:p-5" style={hueStyle(hue) as CSSProperties} role="status">
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
        >
          <Icon size={16} />
        </span>
        <div className="min-w-0">
          <p className="font-semibold text-txt">
            {rc.complete ? 'Your whole file was read' : 'Most of your file was read'}
          </p>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1.5 text-sm">
            <ReadStat label="Segments read" done={rc.segments_read} total={rc.segments_total} hue={hue} />
            <ReadStat label="Pages read" done={rc.pages_read} total={rc.pages_total} hue={hue} />
            {rc.segments_failed > 0 && <ReadStat label="Segments failed" done={rc.segments_failed} hue="rose" />}
            {rc.pages_unreadable > 0 && <ReadStat label="Pages unreadable" done={rc.pages_unreadable} hue="rose" />}
          </div>
          {rc.truncated && (
            <p className="mt-2 flex items-center gap-1.5 text-xs font-medium" style={{ color: hueInk('amber') }}>
              <AlertTriangle size={12} /> The read was truncated — some of your file wasn't included in this pass.
            </p>
          )}
          {rc.note && <p className="mt-2 text-xs leading-relaxed text-muted">{rc.note}</p>}
        </div>
      </div>
    </div>
  )
}

function ReadStat({ label, done, total, hue }: { label: string; done: number; total?: number; hue: Hue }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-lg font-bold tabular-nums" style={{ color: hueInk(hue) }}>
        {done}
        {total != null && <span className="text-sm font-semibold text-muted">/{total}</span>}
      </span>
      <span className="text-xs text-muted">{label}</span>
    </span>
  )
}

/** A quiet strip of what was catalogued from the file (exams / nexus opinions /
 * decisions). Their item shapes are the backend's; we show only the counts. */
function InventoryStrip({ picture }: { picture: CasePicture }) {
  const stats = [
    { label: 'Exams catalogued', n: picture.exam_inventory.length },
    { label: 'Nexus opinions', n: picture.nexus_inventory.length },
    { label: 'Decisions', n: picture.decision_inventory.length },
  ]
  if (stats.every((s) => s.n === 0)) return null
  return (
    <div className="grid gap-px overflow-hidden rounded-control border border-line bg-line sm:grid-cols-3">
      {stats.map((s) => (
        <div key={s.label} className="bg-surface p-3.5">
          <p className="text-xl font-bold tabular-nums text-txt">{s.n}</p>
          <p className="text-micro font-semibold uppercase tracking-wide text-faint">{s.label}</p>
        </div>
      ))}
    </div>
  )
}

function SubHeading({ icon, title, hue = HUE }: { icon: ReactNode; title: string; hue?: Hue }) {
  return (
    <p className="flex items-center gap-2 text-sm font-semibold text-txt">
      <span style={{ color: hueInk(hue) }}>{icon}</span>
      {title}
    </p>
  )
}

const SC_ELEMENTS: { key: keyof CasePictureCondition['sc_elements']; label: string }[] = [
  { key: 'current_diagnosis', label: 'Current diagnosis' },
  { key: 'nexus', label: 'Nexus' },
  { key: 'in_service_event', label: 'In-service event' },
]

function RosterCard({ c }: { c: CasePictureCondition }) {
  return (
    <div className="vo-card vo-accent p-4" style={hueStyle(HUE) as CSSProperties}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="font-semibold leading-snug text-txt">{c.name}</h4>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            {c.diagnostic_code && <span>DC {c.diagnostic_code}</span>}
            {c.rating_percent != null && <span>Rated {c.rating_percent}%</span>}
            {c.decision && <span>{c.decision}</span>}
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {SC_ELEMENTS.map(({ key, label }) => {
          const el = c.sc_elements[key]
          const weak = key === 'nexus' && el.present && c.sc_elements.nexus.meets_standard === false
          return <ScElementChip key={key} label={label} present={el.present} weak={weak} basis={el.basis} />
        })}
      </div>

      {c.missing_elements.length > 0 && (
        <div className="mt-2.5">
          <p className="text-micro font-semibold uppercase tracking-wide text-faint">Still missing</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {c.missing_elements.map((el, i) => (
              <span key={i} className="vo-chip-hue" style={hueStyle('amber') as CSSProperties}>
                {el}
              </span>
            ))}
          </div>
        </div>
      )}

      {formatProvenance(c.provenance) && (
        <p className="mt-2.5 text-micro leading-relaxed text-faint">Source: {formatProvenance(c.provenance)}</p>
      )}
    </div>
  )
}

function ScElementChip({
  label,
  present,
  weak,
  basis,
}: {
  label: string
  present: boolean
  weak?: boolean
  basis: string | null
}) {
  const hue: Hue = present ? (weak ? 'amber' : 'emerald') : 'rose'
  const Icon = present ? (weak ? AlertCircle : CheckCircle2) : XCircle
  return (
    <span className="vo-chip-hue" style={hueStyle(hue) as CSSProperties} title={basis ?? undefined}>
      <Icon size={12} /> {label}
      {weak && ' (weak)'}
    </span>
  )
}

function TimelineRow({ event }: { event: CasePictureTimelineEvent }) {
  const prov = formatProvenance(event.provenance)
  return (
    <li className="relative flex gap-3 pl-5">
      <span
        aria-hidden
        className="absolute left-0 top-1.5 h-3 w-3 rounded-full ring-4 ring-[var(--surface)]"
        style={{ background: hueVar(HUE) }}
      />
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold tabular-nums text-txt">{formatDate(event.date)}</span>
          {event.kind && (
            <span className="vo-chip-hue text-micro" style={hueStyle('sky') as CSSProperties}>
              {event.kind}
            </span>
          )}
        </div>
        <p className="mt-0.5 text-sm leading-snug text-txt/90">{event.label}</p>
        {prov && <p className="mt-0.5 text-micro text-faint">Source: {prov}</p>}
      </div>
    </li>
  )
}

function NoteRow({ note, provenance, hue }: { note: string; provenance: Provenance; hue: Hue }) {
  const prov = formatProvenance(provenance)
  return (
    <div
      className="rounded-control border-l-[3px] px-3.5 py-3 text-sm leading-relaxed text-txt/90"
      style={{ borderColor: hueVar(hue), background: hueSoftVar(hue) }}
    >
      <p>{note}</p>
      {prov && <p className="mt-1 text-micro text-faint">Source: {prov}</p>}
    </div>
  )
}

function CoverageGapRow({
  condition,
  missing,
  note,
}: {
  condition: string | null
  missing: string[]
  note: string | null
}) {
  return (
    <div
      className="rounded-control border-l-[3px] px-3.5 py-3"
      style={{ borderColor: hueVar('amber'), background: hueSoftVar('amber') }}
    >
      {condition && <p className="text-sm font-semibold text-txt">{condition}</p>}
      {missing.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {missing.map((m, i) => (
            <span key={i} className="vo-chip-hue" style={hueStyle('amber') as CSSProperties}>
              {m}
            </span>
          ))}
        </div>
      )}
      {note && <p className="mt-1.5 text-sm leading-relaxed text-txt/85">{note}</p>}
    </div>
  )
}

function GroundingExcerpts({
  excerpts,
}: {
  excerpts: { document_id: string; excerpt: string; char_start: number }[]
}) {
  return (
    <details className="rounded-control border border-line bg-surface2 px-3.5 py-2.5">
      <summary className="cursor-pointer text-xs font-semibold text-muted">
        Grounding excerpts · {excerpts.length}
      </summary>
      <div className="mt-3 space-y-2.5">
        {excerpts.map((e, i) => (
          <blockquote
            key={i}
            className="border-l-2 pl-3 text-xs leading-relaxed text-txt/80"
            style={{ borderColor: hueVar(HUE) }}
          >
            <span className="italic">“{e.excerpt}”</span>
            <span className="mt-0.5 block text-micro text-faint">
              {e.document_id} · char {e.char_start}
            </span>
          </blockquote>
        ))}
      </div>
    </details>
  )
}

/* ─────────────────────────────  D · AUTOMATION  ──────────────────────────── */

function AutomationPanel({
  data,
  loading,
  error,
  onRetry,
}: {
  data: AutomationStatus | null
  loading: boolean
  error: string | null
  onRetry: () => void
}) {
  if (loading && !data) {
    return (
      <Panel hue={HUE}>
        <div className="p-5">
          <LoadingBlock label="Checking what's running for you…" />
        </div>
      </Panel>
    )
  }
  if ((error && !data) || !data) {
    return (
      <Panel hue="rose">
        <div className="p-5">
          <ErrorBlock message={error ?? 'Could not load your automation status.'} onRetry={onRetry} />
        </div>
      </Panel>
    )
  }

  return (
    <Panel hue={HUE} title="Running in the background" subtitle="What Rating Raider does for you automatically">
      <div className="space-y-5 p-5">
        {/* Headline metrics. */}
        <div className="grid gap-3 sm:grid-cols-2">
          <AutoMetric
            icon={<ScanSearch size={16} />}
            hue="fuchsia"
            title="Rating deep dive"
            value={data.deep_dive.last_run ? `Last run ${formatDate(data.deep_dive.last_run)}` : 'Not yet run'}
            note={data.deep_dive.auto_on_intake ? 'Runs automatically when you add records.' : 'Runs when you ask for it.'}
            badge={
              data.deep_dive.has_new_findings ? (
                <span className="vo-chip-hue" style={hueStyle('teal') as CSSProperties}>
                  <Sparkles size={11} /> New findings
                </span>
              ) : undefined
            }
          />
          <AutoMetric
            icon={<FileStack size={16} />}
            hue="violet"
            title="Whole-case comprehension"
            value={
              data.comprehension.available
                ? data.comprehension.generated_at
                  ? `Ready · ${formatDate(data.comprehension.generated_at)}`
                  : 'Ready'
                : 'Not yet available'
            }
            note={
              data.comprehension.auto_on_intake
                ? 'Refreshes automatically when you add records.'
                : 'Built when you run the comprehensive analysis.'
            }
          />
          <AutoMetric
            icon={<ClipboardCheck size={16} />}
            hue="amber"
            title="Document verification"
            value={`${data.verification.flagged_docs} flagged for review`}
            note={data.verification.enabled ? 'Every uploaded record is checked.' : 'Currently off.'}
            action={
              data.verification.flagged_docs > 0 ? { to: '/review-queue', label: 'Review flagged docs' } : undefined
            }
          />
          <AutoMetric
            icon={<AlertCircle size={16} />}
            hue="sky"
            title="OCR cross-read"
            value={`${data.cross_read.disagreement_pages} page${data.cross_read.disagreement_pages === 1 ? '' : 's'} disagreed`}
            note="Two readers compare every scanned page; disagreements are flagged."
          />
          <AutoMetric
            icon={<ClipboardCheck size={16} />}
            hue="teal"
            title="Review queue"
            value={`${data.review_queue.pending} waiting on you`}
            note="Items Rating Raider needs you to confirm."
            action={data.review_queue.pending > 0 ? { to: '/review-queue', label: 'Open review queue' } : undefined}
          />
        </div>

        {/* The automations themselves. */}
        {data.automations.length > 0 && (
          <div className="space-y-2.5">
            <p className="text-micro font-semibold uppercase tracking-wide text-faint">Automations</p>
            {data.automations.map((a) => (
              <AutomationRow key={a.key} item={a} />
            ))}
          </div>
        )}
      </div>
    </Panel>
  )
}

function AutoMetric({
  icon,
  hue,
  title,
  value,
  note,
  badge,
  action,
}: {
  icon: ReactNode
  hue: Hue
  title: string
  value: string
  note: string
  badge?: ReactNode
  action?: { to: string; label: string }
}) {
  return (
    <div className="vo-card vo-accent flex flex-col p-4" style={hueStyle(hue) as CSSProperties}>
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
        >
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-txt">{title}</p>
            {badge}
          </div>
          <p className="mt-0.5 text-sm font-medium" style={{ color: hueInk(hue) }}>
            {value}
          </p>
          <p className="mt-0.5 text-xs leading-relaxed text-muted">{note}</p>
          {action && (
            <Link
              to={action.to}
              className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
            >
              {action.label} <ArrowRight size={13} />
            </Link>
          )}
        </div>
      </div>
    </div>
  )
}

function AutomationRow({ item }: { item: AutomationItem }) {
  const hue: Hue = item.on ? 'emerald' : 'sky'
  return (
    <div className="flex items-start gap-3 rounded-control border border-line bg-surface2 p-3.5">
      <span
        className="mt-0.5 shrink-0 rounded-full px-2 py-0.5 text-micro font-bold uppercase tracking-wide"
        style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
      >
        {item.on ? 'On' : 'Off'}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-txt">{item.label}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-muted">{item.plain}</p>
      </div>
    </div>
  )
}

/* ─────────────────────────────  SHARED  ──────────────────────────────────── */

function SectionHeading({ icon, title, sub }: { icon: ReactNode; title: string; sub: string }) {
  return (
    <div className="flex items-start gap-3">
      <span
        aria-hidden
        className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}
      >
        {icon}
      </span>
      <div>
        <h2 className="text-heading text-txt">{title}</h2>
        <p className="mt-0.5 max-w-2xl text-sm leading-relaxed text-muted">{sub}</p>
      </div>
    </div>
  )
}
