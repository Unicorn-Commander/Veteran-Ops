import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Banknote,
  Briefcase,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Compass,
  ExternalLink,
  Flag,
  LifeBuoy,
  ListChecks,
  MessagesSquare,
  Phone,
  Printer,
  RefreshCw,
  ScanSearch,
  Scale,
  ShieldCheck,
  Sparkles,
  Star,
  Target,
  TrendingUp,
} from 'lucide-react'
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ProSeDisclaimer } from '../components/Disclaimer'
import { KbFreshnessNote } from '../components/KbFreshnessNote'
import { useToast } from '../components/Toast'
import { cx, EmptyState, ErrorBlock, LoadingBlock, Panel, Skeleton, Spinner } from '../components/ui'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { analysisApi, strategyApi } from '../lib/api'
import { formatDate } from '../lib/format'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, VA_STATUS_BADGES, VA_STATUS_HUES, type Hue } from '../lib/hues'
import type {
  AnalysisRun,
  CandidateRating,
  CoachMove,
  DecisionStatusApplyOut,
  DeepDiveCitation,
  DeepDiveConfidenceLevel,
  DeepDiveFinding,
  DeepDiveOrigin,
  DeepDiveResult,
  GamePlanAction,
  GamePlanCaution,
  GamePlanCoach,
  GamePlanConditionLine,
  GamePlanImpact,
  GamePlanOpportunity,
  GamePlanOut,
  GamePlanPathway,
  GamePlanStep,
  GamePlanTdiu,
  OutstandingItem,
  SectionGuide as SectionGuideType,
} from '../types'

const FULL_ANALYSIS_ACTIVE = new Set(['queued', 'leased', 'running', 'retryable'])

// /strategy — WAVE9. The Battle Plan: one deterministic engine reads everything
// the app knows (conditions, evidence/gaps, readiness, decoded denials,
// suggested secondaries/presumptives, combined rating, ITF) and the on-fleet LLM
// writes a warm, plain-language briefing on top. Snapshot + money + a personalized
// briefing + your conditions + ranked PATHWAYS + prioritized ACTIONS + a
// what-to-expect roadmap. Educational self-help only. Every estimated combined
// rating is §4.25 math on the veteran's OWN targets, ALWAYS shown with its basis
// ("not a prediction"). No outcome promises — the veteran decides, a free VSO files.

const HUE: Hue = 'fuchsia'
export const GAME_PLAN_KEY = 'vo_game_plan'

/** Impact → identity hue for the priority-action pills. A calm priority ramp
 * (rose = act now, amber = soon, sky = when you can). */
const IMPACT_HUES: Record<GamePlanImpact, Hue> = { high: 'rose', medium: 'amber', low: 'sky' }
const IMPACT_LABELS: Record<GamePlanImpact, string> = {
  high: 'Do soon',
  medium: 'Next',
  low: 'When you can',
}

/** VA burden-of-proof register (Phase 2b theory findings) → plain-language chip +
 * hue. `insufficient_evidence` reads sober (slate-ish sky), the stronger registers
 * warmer. A deterministic "floor" finding carries no register (confidence_level null)
 * — it's settled rules, not a weighed opinion, so no chip is shown for it. */
const CONFIDENCE_LEVEL_LABELS: Record<DeepDiveConfidenceLevel, string> = {
  more_likely_than_not: 'More likely than not',
  at_least_as_likely: 'At least as likely as not',
  less_likely_than_not: 'Less likely than not',
  insufficient_evidence: 'Insufficient evidence yet',
}
const CONFIDENCE_LEVEL_HUES: Record<DeepDiveConfidenceLevel, Hue> = {
  more_likely_than_not: 'emerald',
  at_least_as_likely: 'teal',
  less_likely_than_not: 'amber',
  insufficient_evidence: 'sky',
}

/** Readiness band → hue, so the whole app speaks one color language for "how
 * close is this to ready" (green = ready, teal/amber = getting there, sky = new). */
const BAND_HUES: Record<string, Hue> = {
  complete: 'emerald',
  strong: 'teal',
  building: 'amber',
  early: 'sky',
}

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

export function Strategy() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data, loading, error, reload, setData } = useAsync(() => strategyApi.get())
  const {
    data: deepDive,
    loading: deepDiveLoading,
    error: deepDiveError,
    reload: reloadDeepDive,
    setData: setDeepDive,
  } = useAsync(() => strategyApi.deepDive())
  const [deepDiveRunning, setDeepDiveRunning] = useState(false)
  const [deepDiveRunError, setDeepDiveRunError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [fullRun, setFullRun] = useState<AnalysisRun | null>(null)
  const [decisionPreview, setDecisionPreview] = useState<DecisionStatusApplyOut | null>(null)
  const [applyingStatuses, setApplyingStatuses] = useState(false)

  // NOTE: the briefing is NOT auto-generated on load — that would silently spin the
  // GPU just by opening the Claim Plan. The cached briefing (if any) already rides
  // along on strategyApi.get(); a fresh plan refresh is POST /strategy/refresh only
  // (firm + briefing). The FULL case review is POST /analysis/comprehensive on
  // /analysis — different job, longer, includes whole-file comprehension.

  // Surface live full-analysis status here so "Re-analyze" is not mistaken for
  // the multi-step Run analysis pass while that is already going.
  useEffect(() => {
    let cancelled = false
    let timer: number | undefined
    const tick = async () => {
      try {
        const latest = await analysisApi.latestRun()
        if (cancelled) return
        setFullRun(latest)
        if (latest && FULL_ANALYSIS_ACTIVE.has(latest.status)) {
          timer = window.setTimeout(tick, 4000)
        }
      } catch {
        if (!cancelled) setFullRun(null)
      }
    }
    void tick()
    return () => {
      cancelled = true
      if (timer) window.clearTimeout(timer)
    }
  }, [])

  // Opt-in preview: decision letters may fill conditions still marked unknown.
  // Never auto-applies — panel only shows when updates.length > 0.
  useEffect(() => {
    if (!data?.has_conditions) {
      setDecisionPreview(null)
      return
    }
    let cancelled = false
    strategyApi
      .previewDecisionStatuses()
      .then((r) => {
        if (!cancelled) setDecisionPreview(r)
      })
      .catch(() => {
        if (!cancelled) setDecisionPreview(null)
      })
    return () => {
      cancelled = true
    }
  }, [data?.has_conditions, data?.generated_at])

  const fullAnalysisRunning = !!(fullRun && FULL_ANALYSIS_ACTIVE.has(fullRun.status))

  const runDeepDive = async () => {
    setDeepDiveRunning(true)
    setDeepDiveRunError(null)
    try {
      setDeepDive(await strategyApi.runDeepDive())
    } catch (err) {
      setDeepDiveRunError(errorMessage(err))
    } finally {
      setDeepDiveRunning(false)
    }
  }

  // Refresh Claim Plan only: specialist firm + briefing (POST /strategy/refresh).
  // Does NOT start whole-C-file comprehension or the full Analysis Center pipeline.
  const refreshPlan = async () => {
    setRefreshing(true)
    try {
      setData(await strategyApi.refresh())
      void reloadDeepDive()
    } catch {
      void reload() // on failure, fall back to a plain reload of the cached plan
    } finally {
      setRefreshing(false)
    }
  }

  const applyDecisionStatuses = async () => {
    setApplyingStatuses(true)
    try {
      const res = await strategyApi.applyDecisionStatuses()
      const n = res.updated
      toast(
        n > 0
          ? `Applied ${n} status update${n === 1 ? '' : 's'} from your decision letters.`
          : 'No statuses needed updating.',
        n > 0 ? 'success' : 'info',
      )
      setDecisionPreview(null)
      setData(await strategyApi.get())
      void reloadDeepDive()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setApplyingStatuses(false)
    }
  }

  const goToPrint = () => {
    sessionStorage.setItem(GAME_PLAN_KEY, JSON.stringify(data))
    navigate('/strategy/print')
  }

  return (
    <div
      data-section="insight"
      className="vo-page mx-auto w-full max-w-5xl space-y-6 p-4 pb-20 sm:p-6"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div className="vo-section-band">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="vo-caption mb-1" style={{ color: hueLabel(HUE) }}>
              Insights · Strategy
            </p>
            <h1 className="vo-page-title">Your Claim Plan</h1>
          </div>
          {data?.has_conditions && (
            <button
              type="button"
              onClick={() => void refreshPlan()}
              disabled={refreshing || loading}
              className="vo-btn-secondary shrink-0"
              title="Refresh specialists + Claim Plan briefing only — not the full Analysis Center pass"
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : undefined} />
              {refreshing ? 'Refreshing plan…' : 'Refresh Claim Plan'}
            </button>
          )}
        </div>
        <p className="vo-page-sub">
          Everything Rating Raider knows about your claim — read, organized, and explained in plain language. Here's
          where you stand, what it could mean, the options worth considering, and exactly what to do next. You decide;
          a free VSO can file it with you.
        </p>
        <p className="mt-2 text-xs leading-relaxed text-muted">
          <strong className="font-semibold text-txt">Refresh Claim Plan</strong> re-runs specialists + the plain-language
          plan (minutes).{' '}
          <strong className="font-semibold text-txt">Run full case review</strong> on{' '}
          <Link to="/analysis" className="font-semibold text-brand hover:text-brand-hover">
            Analysis Center
          </Link>{' '}
          is the long pass over your whole file (often ~15–25 min) — briefing, specialists, deep dive, and
          comprehension. They are not the same button.
        </p>
      </div>

      {fullAnalysisRunning && (
        <div
          className="vo-card vo-accent flex flex-wrap items-center gap-3 p-4"
          style={hueStyle('fuchsia') as CSSProperties}
          role="status"
        >
          <ScanSearch size={18} style={{ color: hueInk('fuchsia') }} />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-txt">Full case review is running</p>
            <p className="text-xs text-muted">
              That job is on Analysis Center (not this Refresh button). Progress and cancel live there.
            </p>
          </div>
          <Link to="/analysis" className="vo-btn-primary shrink-0 text-sm">
            Open Analysis Center <ArrowRight size={14} />
          </Link>
        </div>
      )}

      {(decisionPreview?.updates?.length ?? 0) > 0 && (
        <DecisionStatusPanel
          preview={decisionPreview!}
          applying={applyingStatuses}
          onApply={() => void applyDecisionStatuses()}
        />
      )}

      {/* Standing pro-se disclaimer — the briefing and findings below are advocate
          surfaces, so the "you represent yourself" framing stays in view. */}
      <ProSeDisclaimer />
      <KbFreshnessNote hue={HUE} />

      {loading ? (
        <LoadingBlock label="Building your Claim Plan…" />
      ) : error || !data ? (
        <ErrorBlock message={error ?? 'Could not build your Claim Plan.'} onRetry={reload} />
      ) : !data.has_conditions ? (
        <>
          <LegalLaneBanner />
          <Panel hue={HUE}>
            <EmptyState
              hue={HUE}
              icon={<Compass size={24} />}
              title="Add your conditions to build a Claim Plan"
              description="Once you've added the conditions you're claiming, Rating Raider maps out your whole situation — what to file now, which gaps to close first, what you might be missing, and what to expect at every step."
              action={
                <div className="flex flex-wrap items-center justify-center gap-3">
                  <Link to="/build-case" className="vo-btn-primary">
                    <Sparkles size={15} /> Populate case from records
                  </Link>
                  <Link to="/conditions" className="vo-btn-secondary text-sm">
                    Add conditions manually
                  </Link>
                </div>
              }
            />
          </Panel>
        </>
      ) : (
        <>
          {/* In-page section rail: turns the long scroll into a navigable,
              structured page. Only lists the sections actually present. */}
          <GamePlanSectionNav items={buildNavItems(data)} />

          {/* Coach spine: sticky next move + outstanding + then/parked (when present). */}
          {data.coach && (
            <CoachSpine coach={data.coach} />
          )}

          {/* 1 — The warm, personalized orientation + the one thing to do first. */}
          <section id="overview" className="scroll-mt-24 space-y-4">
            <SectionGuide guide={sectionGuide(data.coach, 'overview')} />
            <Briefing data={data} loading={refreshing} />
          </section>

          {/* 2 — Where you stand: money anchor + at-a-glance readiness. */}
          <section id="standing" className="scroll-mt-24">
            <WhereYouStand data={data} onPrint={goToPrint} />
          </section>

          {/* 3 — Your conditions, color-coded by readiness. */}
          <section id="conditions" className="scroll-mt-24">
            <ConditionList lines={data.condition_lines ?? []} />
          </section>

          {/* 3.5 — Poking the Bear: pyramiding / reduction / CFS–fibro / TDIU work risk. */}
          {(data.cautions ?? []).length > 0 && (
            <section id="cautions" className="scroll-mt-24 space-y-4">
              <SectionGuide guide={sectionGuide(data.coach, 'cautions')} />
              <SectionHeading
                icon={<Scale size={16} />}
                title="Poking the bear — weigh these before you file"
                sub="Filing can reopen settled ratings, stack mental-health claims that VA rates as one, or muddle CFS vs fibromyalgia symptom sets. TDIU also turns on how work and side gigs look on paper. These are trade-offs to understand — not reasons you cannot file. A VSO can confirm how yours apply."
              />
              <div className="space-y-3">
                {(data.cautions ?? []).map((c) => (
                  <CautionCard key={c.key} caution={c} />
                ))}
              </div>
            </section>
          )}

          {/* 4 — Options to consider. */}
          <section id="pathways" className="scroll-mt-24 space-y-4">
            <SectionGuide guide={sectionGuide(data.coach, 'pathways')} />
            <SectionHeading
              icon={<Sparkles size={16} />}
              title="Pathways to consider"
              sub="A few strategic options. The recommended one is ordered by evidence-readiness and known VA rules — not a prediction of what VA will do."
            />
            {data.pathways.length === 0 ? (
              <Panel hue={HUE}>
                <p className="p-5 text-sm text-muted">
                  No pathways to suggest yet. Add evidence to your conditions, or check the priority actions below.
                </p>
              </Panel>
            ) : (
              data.pathways.map((p) => <PathwayCard key={p.key} pathway={p} />)
            )}
            {data.tdiu && <TdiuCard tdiu={data.tdiu} />}
          </section>

          {/* 4.5 — Under-claimed + reclaim opportunities. */}
          {(data.opportunities ?? []).length > 0 && (
            <section id="opportunities" className="scroll-mt-24 space-y-4">
              <SectionGuide guide={sectionGuide(data.coach, 'opportunities')} />
              <SectionHeading
                icon={<TrendingUp size={16} />}
                title="Reclaim paths and under-claimed ratings"
                sub="Denied conditions that may reopen on a new secondary theory (Supplemental Claim + nexus), newly establishable secondaries, or ratings you may be under-counted for. Each still needs its own medical evidence — nothing here is decided. Bring these to a VSO."
              />
              <div className="space-y-3">
                {(data.opportunities ?? []).map((o) => (
                  <OpportunityCard
                    key={o.key}
                    opportunity={o}
                    hue={o.kind === 'reclaim' ? 'rose' : undefined}
                    badges={
                      o.kind === 'reclaim' ? (
                        <span className="vo-chip-hue" style={hueStyle('rose') as CSSProperties}>
                          reclaim · {o.form || 'Supplemental'}
                        </span>
                      ) : undefined
                    }
                    details={
                      (o.attach_checklist?.length ?? 0) > 0 ? (
                        <div className="mt-3">
                          <p className="text-micro font-semibold uppercase tracking-wide text-faint">
                            Attach checklist
                          </p>
                          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm text-txt/85">
                            {o.attach_checklist!.map((item, i) => (
                              <li key={i}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      ) : undefined
                    }
                    action={
                      o.kind === 'reclaim' ? (
                        <div className="mt-4 flex flex-wrap gap-2">
                          <Link
                            to={`/nexus?${new URLSearchParams({
                              condition: o.secondary || '',
                              claim_type: 'secondary',
                              secondary_to: (o.primary && o.primary[0]) || '',
                              brief: '1',
                              prior_denial: '1',
                            }).toString()}`}
                            className="inline-flex items-center gap-1.5 rounded-control px-3 py-1.5 text-sm font-semibold transition-colors"
                            style={{ background: hueSoftVar('rose'), color: hueInk('rose') }}
                          >
                            Build provider brief <ArrowRight size={14} />
                          </Link>
                          <Link
                            to={`/buddy?${new URLSearchParams({
                              condition: o.secondary || '',
                              brief: '1',
                              themes: 'daily function,work impact',
                            }).toString()}`}
                            className="inline-flex items-center gap-1.5 rounded-control px-3 py-1.5 text-sm font-semibold transition-colors"
                            style={{
                              background: hueSoftVar('orange'),
                              color: hueInk('orange'),
                            }}
                          >
                            Buddy situation brief <ArrowRight size={14} />
                          </Link>
                        </div>
                      ) : undefined
                    }
                  />
                ))}
              </div>
            </section>
          )}

          {/* 4.75 — Cached, exhaustive rating-space review. This independent
              read never blocks or changes the fast deterministic Battle Plan. */}
          <section id="deep-dive" className="scroll-mt-24 space-y-4">
            <SectionGuide guide={sectionGuide(data.coach, 'deep-dive')} />
            <DeepDiveSection
              result={deepDive}
              loading={deepDiveLoading}
              loadError={deepDiveError}
              runError={deepDiveRunError}
              running={deepDiveRunning}
              onRetry={reloadDeepDive}
              onRun={() => void runDeepDive()}
            />
          </section>

          {/* 5 — Concrete ranked next steps. */}
          <section id="actions" className="scroll-mt-24 space-y-4">
            <SectionGuide guide={sectionGuide(data.coach, 'actions')} />
            <SectionHeading
              icon={<CheckCircle2 size={16} />}
              title="Your next steps"
              sub="Concrete actions, ranked by how much each moves your claim forward. Every one links to where you take it."
            />
            {data.priority_actions.length === 0 ? (
              <Panel hue={HUE}>
                <p className="p-5 text-sm text-muted">No outstanding actions right now.</p>
              </Panel>
            ) : (
              <div className="space-y-2.5">
                {data.priority_actions.map((a, i) => (
                  <ActionRow key={i} action={a} />
                ))}
              </div>
            )}
          </section>

          {/* 6 — What to expect at every step (handholding roadmap). */}
          {(data.process_roadmap ?? []).length > 0 && (
            <section id="roadmap" className="scroll-mt-24 space-y-4">
              <SectionHeading
                icon={<Flag size={16} />}
                title="What to expect"
                sub="The VA claim journey, start to finish — with where you are right now marked. Knowing the road ahead is half the battle."
              />
              <Roadmap steps={data.process_roadmap ?? []} />
            </section>
          )}

          {/* 7 — You're not alone: VSO + crisis line. */}
          <section id="support" className="scroll-mt-24">
            <SupportResources data={data} />
          </section>

          <SourceAndDisclaimer data={data} />

          <div className="flex flex-col items-center gap-2 pt-1 sm:flex-row sm:justify-center sm:gap-3">
            <button onClick={goToPrint} className="vo-btn-primary">
              <Printer size={16} /> Print / save your Claim Plan
            </button>
            {data.coach && (
              <Link to="/strategy/case-brief" className="vo-btn-secondary">
                <Printer size={16} /> Print case brief
              </Link>
            )}
          </div>
          <p className="text-center text-xs text-faint">
            Opens a clean, letterhead copy you can keep or share with your VSO. Educational only — not a VA filing.
          </p>
        </>
      )}
    </div>
  )
}

/* ──────────────────────────  COACH SPINE  ─────────────────────────────────── */

function sectionGuide(coach: GamePlanCoach | null | undefined, id: string): SectionGuideType | null {
  return coach?.section_guides?.find((g) => g.id === id) ?? null
}

const SEVERITY_HUES: Record<string, Hue> = {
  high: 'rose',
  medium: 'amber',
  low: 'sky',
}

/** Sticky coach block: Do this first + Raider interview CTA + case brief + outstanding. */
function CoachSpine({ coach }: { coach: GamePlanCoach }) {
  const first = coach.do_this_first
  const then = coach.then ?? []
  const parked = coach.parked ?? []
  const primary = coach.outstanding_primary ?? coach.outstanding ?? []
  const more = coach.outstanding_more ?? []
  const count = coach.outstanding_count ?? primary.filter((o) => o.status !== 'informational').length

  return (
    <div id="next-move" className="scroll-mt-24 space-y-3">
      <div className="sticky top-[4.25rem] z-[5] space-y-3 bg-bg/95 pb-1 backdrop-blur-sm">
        <NextMoveCard first={first} reason={coach.do_this_first_reason} />
        <div className="flex flex-wrap gap-2">
          <Link
            to="/raider?mode=post_analysis&from=plan"
            className="vo-btn-primary text-sm"
          >
            <MessagesSquare size={14} /> Talk through my plan first
          </Link>
          <Link to="/strategy/case-brief" className="vo-btn-secondary text-sm">
            <Printer size={14} /> Print case brief
          </Link>
          {(coach.duplicates?.length ?? 0) > 0 && (
            <Link to="/conditions?dupes=1" className="vo-btn-secondary text-sm">
              <ListChecks size={14} /> Clean up {coach.duplicates!.length} duplicate name
              {coach.duplicates!.length === 1 ? '' : 's'}
            </Link>
          )}
        </div>
        <p className="text-xs text-muted">
          Recommended path after a full review: <strong className="text-txt">talk with Rating Raider</strong> about
          gaps, then work <strong className="text-txt">Do this first</strong> on this page.
        </p>
      </div>

      {(then.length > 0 || parked.length > 0) && (
        <ThenParkedPanel then={then} parked={parked} />
      )}

      {(primary.length > 0 || more.length > 0) && (
        <OutstandingPanel primary={primary} more={more} count={count} />
      )}
    </div>
  )
}

function NextMoveCard({
  first,
  reason,
}: {
  first: CoachMove | null | undefined
  reason?: string | null
}) {
  if (!first) {
    return (
      <Panel hue={HUE} className="shadow-soft">
        <div className="space-y-2 p-5">
          <p className="text-micro font-bold uppercase tracking-wide" style={{ color: hueLabel(HUE) }}>
            Your next move
          </p>
          <p className="text-sm text-muted">
            No single top action right now — work the outstanding list below, or talk it through with Rating Raider.
            Educational only; you decide and a free VSO can file with you.
          </p>
        </div>
      </Panel>
    )
  }

  const impact = (first.impact as GamePlanImpact) || 'medium'
  const impactHue = IMPACT_HUES[impact] ?? 'amber'
  const link = first.link || '/strategy'

  return (
    <div
      className="vo-card relative overflow-hidden p-0 shadow-soft"
      style={{ ...(hueStyle(HUE) as CSSProperties), borderColor: hueVar(HUE) }}
    >
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-90"
        style={{
          background: `radial-gradient(120% 80% at 0% 0%, ${hueSoftVar(HUE)} 0%, transparent 55%), radial-gradient(100% 80% at 100% 0%, ${hueSoftVar('rose')} 0%, transparent 45%)`,
        }}
      />
      <div className="relative p-5 sm:p-6">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <span className="text-micro font-bold uppercase tracking-wide" style={{ color: hueLabel(HUE) }}>
            Do this first
          </span>
          <span className="vo-chip-hue text-micro" style={hueStyle(impactHue) as CSSProperties}>
            {IMPACT_LABELS[impact] ?? impact}
          </span>
        </div>
        <h2 className="text-xl font-bold leading-snug text-txt sm:text-2xl">{first.title}</h2>
        {reason && (
          <p className="mt-2 max-w-3xl text-sm font-medium leading-relaxed text-txt/95">{reason}</p>
        )}
        {first.why && first.why !== reason && (
          <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-txt/80">{first.why}</p>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Link to={link} className="vo-btn-primary">
            Start this step <ArrowRight size={15} />
          </Link>
          <p className="text-xs text-muted">
            Organizing suggestion from your records — not a VA order or filing.
          </p>
        </div>
      </div>
    </div>
  )
}

function ThenParkedPanel({ then, parked }: { then: CoachMove[]; parked: CoachMove[] }) {
  const [open, setOpen] = useState(true)
  return (
    <Panel hue="violet">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-3 px-5 py-3 text-left"
        aria-expanded={open}
      >
        <span className="text-sm font-semibold text-txt">
          Then ({then.length}) · Parked ({parked.length})
        </span>
        {open ? <ChevronDown size={16} className="text-muted" /> : <ChevronRight size={16} className="text-muted" />}
      </button>
      {open && (
        <div className="space-y-4 border-t border-line px-5 py-4">
          {then.length > 0 && (
            <div>
              <p className="mb-2 text-micro font-bold uppercase tracking-wide text-faint">Then do these</p>
              <ul className="space-y-2">
                {then.map((m, i) => (
                  <CoachMoveRow key={m.id || `then-${i}`} move={m} />
                ))}
              </ul>
            </div>
          )}
          {parked.length > 0 && (
            <div>
              <p className="mb-2 text-micro font-bold uppercase tracking-wide text-faint">Parked for later</p>
              <ul className="space-y-2 opacity-90">
                {parked.map((m, i) => (
                  <CoachMoveRow key={m.id || `park-${i}`} move={m} muted />
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}

function CoachMoveRow({ move, muted }: { move: CoachMove; muted?: boolean }) {
  const body = (
    <>
      <span className={cx('font-medium', muted ? 'text-muted' : 'text-txt')}>{move.title}</span>
      {move.why && <span className="mt-0.5 block text-xs text-muted">{move.why}</span>}
    </>
  )
  if (move.link) {
    return (
      <li>
        <Link
          to={move.link}
          className="flex items-start justify-between gap-2 rounded-control border border-line bg-surface/60 px-3 py-2.5 text-sm transition-colors hover:border-brand/40"
        >
          <span className="min-w-0 flex-1">{body}</span>
          <ArrowRight size={14} className="mt-0.5 shrink-0 text-faint" />
        </Link>
      </li>
    )
  }
  return (
    <li className="rounded-control border border-line bg-surface/60 px-3 py-2.5 text-sm">{body}</li>
  )
}

function OutstandingPanel({
  primary,
  more,
  count,
}: {
  primary: OutstandingItem[]
  more: OutstandingItem[]
  count: number
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [showMore, setShowMore] = useState(false)
  const visible = showMore ? [...primary, ...more] : primary

  return (
    <Panel
      hue="amber"
      title={
        <span className="inline-flex items-center gap-2">
          Outstanding
          <span
            className="inline-flex min-w-[1.4rem] items-center justify-center rounded-full px-1.5 py-0.5 text-micro font-bold"
            style={{ background: hueSoftVar('amber'), color: hueInk('amber') }}
          >
            {count}
          </span>
        </span>
      }
      subtitle="Short list of open work — reclaim, TDIU, key gaps. Expand for trade-offs and cleanup."
    >
      <ul className="divide-y divide-line">
        {visible.map((item) => {
          const sev = item.severity || 'medium'
          const hue = SEVERITY_HUES[sev] ?? 'amber'
          const open = !!expanded[item.id]
          const checks = item.checklist ?? []
          return (
            <li key={item.id} className="px-5 py-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="vo-chip-hue text-micro" style={hueStyle(hue) as CSSProperties}>
                      {sev}
                    </span>
                    <span className="text-micro uppercase tracking-wide text-faint">{item.kind}</span>
                  </div>
                  <p className="mt-1 text-sm font-semibold text-txt">{item.title}</p>
                  {item.why && <p className="mt-0.5 text-xs leading-relaxed text-muted">{item.why}</p>}
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                  {checks.length > 0 && (
                    <button
                      type="button"
                      className="vo-btn-ghost text-xs"
                      onClick={() => setExpanded((e) => ({ ...e, [item.id]: !open }))}
                      aria-expanded={open}
                    >
                      {open ? 'Hide' : 'Checklist'} ({checks.length})
                    </button>
                  )}
                  {item.link && (
                    <Link to={item.link} className="vo-btn-secondary text-xs">
                      Open <ArrowRight size={12} />
                    </Link>
                  )}
                </div>
              </div>
              {open && checks.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-xs text-txt/85">
                  {checks.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              )}
            </li>
          )
        })}
      </ul>
      {more.length > 0 && (
        <div className="border-t border-line px-5 py-2">
          <button
            type="button"
            className="vo-btn-ghost text-xs"
            onClick={() => setShowMore((v) => !v)}
            aria-expanded={showMore}
          >
            {showMore ? 'Hide lower-priority items' : `Show ${more.length} more (trade-offs & cleanup)`}
          </button>
        </div>
      )}
    </Panel>
  )
}

/** Compact What / Why / Do strip at the start of a major Claim Plan section. */
function SectionGuide({ guide }: { guide: SectionGuideType | null }) {
  if (!guide) return null
  const openCount = guide.outstanding_ids?.length ?? 0
  const statusHue: Hue =
    guide.status === 'action' ? 'rose' : guide.status === 'clear' ? 'emerald' : 'sky'

  return (
    <div
      className="rounded-control border border-line bg-surface/70 px-4 py-3"
      style={hueStyle(statusHue) as CSSProperties}
    >
      <div className="mb-1.5 flex flex-wrap items-center gap-2">
        <span className="text-micro font-bold uppercase tracking-wide" style={{ color: hueLabel(statusHue) }}>
          {guide.title}
        </span>
        {openCount > 0 && (
          <span className="vo-chip-hue text-micro" style={hueStyle(statusHue) as CSSProperties}>
            {openCount} open
          </span>
        )}
      </div>
      <dl className="grid gap-1.5 text-xs leading-relaxed sm:grid-cols-3">
        {guide.what && (
          <div>
            <dt className="font-semibold text-faint">What</dt>
            <dd className="text-txt/90">{guide.what}</dd>
          </div>
        )}
        {guide.why && (
          <div>
            <dt className="font-semibold text-faint">Why</dt>
            <dd className="text-txt/90">{guide.why}</dd>
          </div>
        )}
        {guide.do && (
          <div>
            <dt className="font-semibold text-faint">Do</dt>
            <dd className="text-txt/90">{guide.do}</dd>
          </div>
        )}
      </dl>
    </div>
  )
}

/* ──────────────────────────  SECTION NAVIGATION  ─────────────────────────── */

type NavItem = { id: string; label: string }

/** The section rail's item list, built from what's actually rendered for this
 * veteran. `overview`/`standing`/`pathways`/`actions` always render in the
 * populated Battle Plan; the rest render only when their data is present, so we
 * gate those to keep every pill pointing at a real on-page target. */
function buildNavItems(data: GamePlanOut): NavItem[] {
  const items: NavItem[] = []
  if (data.coach) items.push({ id: 'next-move', label: 'Your next move' })
  items.push({ id: 'overview', label: 'Overview' }, { id: 'standing', label: 'Where you stand' })
  if ((data.condition_lines ?? []).length > 0) items.push({ id: 'conditions', label: 'Your conditions' })
  if ((data.cautions ?? []).length > 0) items.push({ id: 'cautions', label: 'Poking the bear' })
  items.push({ id: 'pathways', label: 'Pathways' })
  if ((data.opportunities ?? []).length > 0) items.push({ id: 'opportunities', label: 'Opportunities' })
  items.push({ id: 'deep-dive', label: 'Deep dive' })
  items.push({ id: 'actions', label: 'Next steps' })
  if ((data.process_roadmap ?? []).length > 0) items.push({ id: 'roadmap', label: 'What to expect' })
  return items
}

/** Sticky in-page section rail with scroll-spy. Smooth-scrolls to each section
 * (honoring prefers-reduced-motion) and highlights the one you're reading via an
 * IntersectionObserver over the section ids. Real <button>s with visible focus
 * and aria-current for keyboard/AT users. Horizontal scroll strip on mobile;
 * wraps on desktop. Sits below the shared Shell topbar (h-16), like the other
 * anchor-navs in this app; targets carry scroll-mt-24 so headings clear it. */
function GamePlanSectionNav({ items }: { items: NavItem[] }) {
  const [active, setActive] = useState(items[0]?.id ?? '')

  useEffect(() => {
    const ids = items.map((it) => it.id)
    const sections = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null)
    if (sections.length === 0) return

    // A section is "current" while its box sits in a band just below the sticky
    // topbar + rail. The topmost section in that band (DOM order) wins.
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
  }, [items])

  const go = (id: string) => {
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    document.getElementById(id)?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
    setActive(id)
  }

  if (items.length <= 1) return null

  return (
    <nav
      aria-label="Claim Plan sections"
      className="vo-no-print -mx-1 flex gap-1.5 overflow-x-auto rounded-full border border-line bg-surface px-2 py-1.5 sm:flex-wrap sm:overflow-visible"
      style={hueStyle(HUE) as CSSProperties}
    >
      {items.map((it) => {
        const isActive = it.id === active
        return (
          <button
            key={it.id}
            type="button"
            onClick={() => go(it.id)}
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
            {it.label}
          </button>
        )
      })}
    </nav>
  )
}

/* ─────────────────────────────  1 · BRIEFING  ────────────────────────────── */

/** The hero: a warm plain-language read of the veteran's situation (on-fleet
 * LLM, with a deterministic fallback), plus the single most important next
 * step as a big call-to-action. This is what makes the page feel like a guide. */
function Briefing({ data, loading }: { data: GamePlanOut; loading: boolean }) {
  const b = data.briefing
  const focus = data.focus
  return (
    <div
      className="vo-card relative overflow-hidden p-0"
      style={{ ...(hueStyle(HUE) as CSSProperties), borderColor: hueVar(HUE) }}
    >
      {/* Aurora wash so the hero reads as the warm anchor of the page. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-90"
        style={{
          background: `radial-gradient(120% 80% at 0% 0%, ${hueSoftVar(HUE)} 0%, transparent 55%), radial-gradient(120% 90% at 100% 0%, ${hueSoftVar('violet')} 0%, transparent 50%)`,
        }}
      />
      <div className="relative p-5 sm:p-7">
        <div className="mb-3 flex items-center gap-2.5">
          <img
            src="/rating-raider-cwo.png"
            alt="Rating Raider, your CWO battle-buddy"
            width={40}
            height={40}
            draggable={false}
            className="h-10 w-10 shrink-0 rounded-full object-cover ring-1 ring-white/10"
          />
          <div className="leading-tight">
            <span className="block text-micro font-bold uppercase tracking-wide" style={{ color: hueLabel(HUE) }}>
              Rating Raider · your CWO
            </span>
            <span className="block text-xs text-muted">reading your situation</span>
          </div>
        </div>

        {b ? (
          <>
            <h2 className="max-w-3xl text-2xl font-bold leading-snug text-txt sm:text-[1.7rem]">{b.headline}</h2>
            <div className="mt-3 max-w-3xl space-y-2.5">
              {b.paragraphs.map((p, i) => (
                <p key={i} className="text-[0.975rem] leading-relaxed text-txt/90">
                  {p}
                </p>
              ))}
            </div>

            {(b.strengths.length > 0 || b.watch_outs.length > 0) && (
              <div className="mt-5 grid gap-3 sm:grid-cols-2">
                {b.strengths.length > 0 && (
                  <PointList
                    hue="emerald"
                    icon={<CheckCircle2 size={15} />}
                    title="Working in your favor"
                    points={b.strengths}
                  />
                )}
                {b.watch_outs.length > 0 && (
                  <PointList
                    hue="amber"
                    icon={<AlertCircle size={15} />}
                    title="Keep an eye on"
                    points={b.watch_outs}
                  />
                )}
              </div>
            )}
          </>
        ) : (
          <div className="space-y-2">
            <h2 className="text-xl font-bold text-txt">Here's your Claim Plan.</h2>
            {loading && <p className="text-sm text-muted">Preparing the plain-language briefing…</p>}
          </div>
        )}

        {focus && (
          <div
            className="mt-5 flex flex-col gap-3 rounded-control border p-4 sm:flex-row sm:items-center sm:justify-between"
            style={{ borderColor: hueVar(HUE), background: 'var(--surface)' }}
          >
            <div className="min-w-0">
              <p className="text-micro font-bold uppercase tracking-wide" style={{ color: hueInk(HUE) }}>
                Start here
              </p>
              <p className="mt-0.5 font-semibold text-txt">{focus.title}</p>
              <p className="mt-0.5 text-sm leading-relaxed text-muted">{focus.why}</p>
            </div>
            {focus.link && (
              <Link to={focus.link} className="vo-btn-primary shrink-0 self-start sm:self-auto">
                Do this now <ArrowRight size={15} />
              </Link>
            )}
          </div>
        )}

        {b?.generated_by === 'summary' && (
          <p className="mt-3 text-micro text-faint">
            Summary view — your on-device analysis assistant is warming up; refresh for a fuller read.
          </p>
        )}
      </div>
    </div>
  )
}

function PointList({
  hue,
  icon,
  title,
  points,
}: {
  hue: Hue
  icon: ReactNode
  title: string
  points: string[]
}) {
  return (
    <div
      className="rounded-control border border-line p-3.5"
      style={{ ...(hueStyle(hue) as CSSProperties), background: hueSoftVar(hue) }}
    >
      <p className="mb-2 flex items-center gap-1.5 text-micro font-bold uppercase tracking-wide" style={{ color: hueInk(hue) }}>
        {icon}
        {title}
      </p>
      <ul className="space-y-1.5">
        {points.map((p, i) => (
          <li key={i} className="flex gap-2 text-sm leading-snug text-txt">
            <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: hueVar(hue) }} />
            <span>{p}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* ───────────────────────────  2 · WHERE YOU STAND  ─────────────────────────── */

function WhereYouStand({ data, onPrint }: { data: GamePlanOut; onPrint: () => void }) {
  const s = data.snapshot
  const money = data.money
  const itf = s.active_itf
  return (
    <div className="grid gap-4 lg:grid-cols-[1.05fr_1fr]">
      {/* Money + rating — the "what this means" anchor. */}
      <div className="vo-card vo-accent p-5" style={hueStyle('emerald') as CSSProperties}>
        <div className="flex items-center justify-between">
          <p className="text-micro font-bold uppercase tracking-wide" style={{ color: hueLabel('emerald') }}>
            Where you stand today
          </p>
          <button onClick={onPrint} className="vo-btn-ghost text-xs">
            <Printer size={13} /> Save
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-x-8 gap-y-3">
          <div>
            <p className="text-4xl font-bold tabular-nums leading-none" style={{ color: hueInk('emerald') }}>
              {s.current_combined === null ? '—' : `${s.current_combined}%`}
            </p>
            <p className="mt-1 text-micro font-semibold uppercase tracking-wide" style={{ color: hueLabel('emerald') }}>
              Current combined rating
            </p>
          </div>
          {money && money.current_monthly != null && (
            <div>
              <p className="flex items-baseline gap-1 text-4xl font-bold tabular-nums leading-none text-txt">
                {usd.format(money.current_monthly)}
                <span className="text-base font-semibold text-muted">/mo</span>
              </p>
              <p className="mt-1 flex items-center gap-1 text-micro font-semibold uppercase tracking-wide text-muted">
                <Banknote size={12} /> VA monthly compensation
              </p>
            </div>
          )}
        </div>
        {money?.basis && (
          <p className="mt-3 text-xs leading-relaxed text-faint">{money.basis}</p>
        )}
        {s.current_combined === null && (
          <p className="mt-3 text-xs leading-relaxed text-muted">
            No combined rating on file yet.{' '}
            <Link to="/profile" className="font-semibold text-brand hover:text-brand-hover">
              Add your current rating
            </Link>{' '}
            to see what you receive today.
          </p>
        )}
      </div>

      {/* Readiness at a glance — a colored bar + stat chips. */}
      <div className="vo-card vo-accent p-5" style={hueStyle(HUE) as CSSProperties}>
        <p className="text-micro font-bold uppercase tracking-wide" style={{ color: hueLabel(HUE) }}>
          Your {s.conditions_total} condition{s.conditions_total === 1 ? '' : 's'}
        </p>
        <ReadinessBar
          total={s.conditions_total}
          ready={s.ready_count}
          needs={s.needs_evidence_count}
          denied={s.denied_count}
        />
        <div className="mt-3 flex flex-wrap gap-x-5 gap-y-2">
          <MiniStat n={s.ready_count} label="Ready to file" hue="emerald" />
          <MiniStat n={s.needs_evidence_count} label="Need evidence" hue="amber" />
          {s.denied_count > 0 && <MiniStat n={s.denied_count} label="Denied" hue="rose" />}
        </div>
        {itf ? (
          <p className="mt-3 flex items-start gap-2 text-sm text-txt">
            <CalendarClock size={15} className="mt-0.5 shrink-0" style={{ color: hueInk('sky') }} />
            <span>
              <strong className="font-semibold">Intent to File active</strong>
              {itf.deadline ? ` — protects your date through ${formatDate(itf.deadline)}` : ''}
              {typeof itf.days_remaining === 'number' ? ` (${itf.days_remaining} days left)` : ''}.
            </span>
          </p>
        ) : (
          <p className="mt-3 flex items-start gap-2 text-sm text-txt">
            <AlertCircle size={15} className="mt-0.5 shrink-0" style={{ color: hueInk('amber') }} />
            <span>
              No active Intent to File —{' '}
              <Link to="/itf" className="font-semibold text-brand hover:text-brand-hover">
                filing one locks in your date (and back pay) for a year
              </Link>
              .
            </span>
          </p>
        )}
      </div>
    </div>
  )
}

/** A single proportional bar: ready (emerald) / needs (amber) / denied (rose)
 * over the total, remainder neutral (filed or still being decided). */
function ReadinessBar({
  total,
  ready,
  needs,
  denied,
}: {
  total: number
  ready: number
  needs: number
  denied: number
}) {
  const denom = Math.max(total, ready + needs + denied, 1)
  const seg = (n: number, hue: Hue) =>
    n > 0 ? (
      <span
        className="h-full first:rounded-l-full last:rounded-r-full"
        style={{ width: `${(n / denom) * 100}%`, background: hueVar(hue) }}
        title={`${n}`}
      />
    ) : null
  const rest = denom - ready - needs - denied
  return (
    <div className="mt-3 flex h-2.5 w-full overflow-hidden rounded-full bg-surface2">
      {seg(ready, 'emerald')}
      {seg(needs, 'amber')}
      {seg(denied, 'rose')}
      {rest > 0 && <span className="h-full" style={{ width: `${(rest / denom) * 100}%` }} />}
    </div>
  )
}

function MiniStat({ n, label, hue }: { n: number; label: string; hue: Hue }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="h-2 w-2 shrink-0 self-center rounded-full" style={{ background: hueVar(hue) }} />
      <span className="text-lg font-bold tabular-nums" style={{ color: hueInk(hue) }}>
        {n}
      </span>
      <span className="text-xs text-muted">{label}</span>
    </span>
  )
}

/* ────────────────────────────  3 · CONDITIONS  ───────────────────────────── */

function ConditionList({ lines }: { lines: GamePlanConditionLine[] }) {
  if (lines.length === 0) return null
  return (
    <section className="space-y-4">
      <SectionHeading
        icon={<Target size={16} />}
        title="Your conditions"
        sub="Every condition you're working on and how close each is to being ready. Tap one to open it and close its gaps."
      />
      <div className="grid gap-2.5 sm:grid-cols-2">
        {lines.map((c, i) => (
          <ConditionCard key={c.id ?? i} c={c} />
        ))}
      </div>
    </section>
  )
}

function ConditionCard({ c }: { c: GamePlanConditionLine }) {
  const hue = BAND_HUES[c.band] ?? 'sky'
  const body = (
    <div
      className="vo-card vo-accent group h-full p-4 transition-shadow duration-150 hover:shadow-md"
      style={hueStyle(hue) as CSSProperties}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="font-semibold leading-snug text-txt">{c.name}</p>
        <span
          className="shrink-0 rounded-full px-2 py-0.5 text-micro font-bold uppercase tracking-wide"
          style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
        >
          {c.band_label}
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
        <span>{c.claim_type}</span>
        {c.current_rating != null && <span>Rated {c.current_rating}%</span>}
        {c.target_rating != null && <span>Target {c.target_rating}%</span>}
        {(c.va_status === 'denied' || c.va_status === 'service_connected') && (
          <span
            className="rounded-full px-2 py-0.5 text-micro font-bold uppercase tracking-wide"
            style={{ background: hueSoftVar(VA_STATUS_HUES[c.va_status]), color: hueInk(VA_STATUS_HUES[c.va_status]) }}
          >
            {VA_STATUS_BADGES[c.va_status]}
          </span>
        )}
      </div>
      {c.missing.length > 0 ? (
        <p className="mt-2.5 flex items-start gap-1.5 text-xs leading-snug" style={{ color: hueInk('amber') }}>
          <AlertCircle size={13} className="mt-0.5 shrink-0" />
          <span>Still needs {c.missing[0]}</span>
        </p>
      ) : c.ready ? (
        <p className="mt-2.5 flex items-center gap-1.5 text-xs font-medium" style={{ color: hueInk('emerald') }}>
          <CheckCircle2 size={13} /> Core evidence in place
        </p>
      ) : null}
    </div>
  )
  return c.link ? (
    <Link to={c.link} className="block">
      {body}
    </Link>
  ) : (
    body
  )
}

/* ────────────────────────────  4 · PATHWAYS  ─────────────────────────────── */

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

function PathwayCard({ pathway: p }: { pathway: GamePlanPathway }) {
  const hue: Hue = p.recommended ? 'fuchsia' : 'violet'
  const ink = hueInk(hue)
  return (
    <div
      className="vo-card vo-accent overflow-hidden p-0"
      style={{
        ...(hueStyle(hue) as CSSProperties),
        ...(p.recommended
          ? { borderColor: hueVar(hue), boxShadow: `0 0 0 1.5px ${hueVar(hue)}, 0 12px 34px -18px ${hueVar(hue)}` }
          : {}),
      }}
    >
      {p.recommended && (
        <div
          className="flex items-center gap-1.5 px-5 py-2.5 text-micro font-bold uppercase tracking-wide"
          style={{ background: hueVar(hue), color: 'var(--surface)' }}
        >
          <Star size={13} className="fill-current" /> Recommended starting point
        </div>
      )}
      <div className="p-5">
        <h3 className="text-lg font-semibold text-txt">{p.title}</h3>
        <p className="mt-1 text-sm leading-relaxed text-txt/85">{p.summary}</p>

        <EstimateBlock pathway={p} hue={hue} />

        {p.steps.length > 0 && (
          <ol className="mt-4 space-y-2.5 text-sm text-txt">
            {p.steps.map((step, i) => (
              <li key={i} className="flex gap-2.5">
                <span
                  aria-hidden
                  className="mt-0.5 flex h-[20px] w-[20px] shrink-0 items-center justify-center rounded-full text-micro font-bold"
                  style={{ background: hueSoftVar(hue), color: ink }}
                >
                  {i + 1}
                </span>
                <span className="leading-relaxed">{step}</span>
              </li>
            ))}
          </ol>
        )}

        {p.included_conditions.length > 0 && (
          <div className="mt-4">
            <p className="mb-1.5 text-micro font-semibold uppercase tracking-wide" style={{ color: hueLabel(hue) }}>
              Conditions in this path
            </p>
            <div className="flex flex-wrap gap-1.5">
              {p.included_conditions.map((c, i) => (
                <span key={i} className="vo-chip-hue" style={hueStyle(hue) as CSSProperties}>
                  {c}
                </span>
              ))}
            </div>
          </div>
        )}

        {p.tradeoff && (
          <div
            className="mt-4 rounded-control border-l-[3px] px-3.5 py-2.5 text-xs leading-relaxed text-txt/85"
            style={{ borderColor: hueVar(hue), background: hueSoftVar(hue) }}
          >
            <span className="font-semibold text-txt">Trade-off: </span>
            {p.tradeoff}
          </div>
        )}
      </div>
    </div>
  )
}

/** A rating-strategy trade-off (poking the bear). Amber for a general caution,
 * rose when higher-severity. Reg-grounded; never a bar. */
function CautionCard({ caution: c }: { caution: GamePlanCaution }) {
  const hue: Hue =
    c.kind === 'tdiu_employment'
      ? c.severity === 'high'
        ? 'violet'
        : 'sky'
      : c.severity === 'high'
        ? 'rose'
        : 'amber'
  return (
    <div className="vo-card vo-accent p-0 overflow-hidden" style={hueStyle(hue) as CSSProperties}>
      <div className="p-5">
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
            style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
          >
            <AlertTriangle size={16} />
          </span>
          <div className="min-w-0">
            <h3 className="text-base font-semibold text-txt">{c.title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-txt/85">{c.body}</p>
            {c.conditions.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {c.conditions.map((name, i) => (
                  <span key={i} className="vo-chip-hue" style={hueStyle(hue) as CSSProperties}>
                    {name}
                  </span>
                ))}
              </div>
            )}
            <p className="mt-3 text-micro font-medium uppercase tracking-wide text-faint">{c.reg}</p>
            {c.kind === 'tdiu_employment' && (
              <Link
                to="/tdiu"
                className="mt-4 inline-flex items-center gap-1.5 rounded-control px-3 py-1.5 text-sm font-semibold transition-colors"
                style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
              >
                Open TDIU workspace <ArrowRight size={14} />
              </Link>
            )}
            {c.kind === 'filing_tradeoff' && (
              <Link
                to="/nexus"
                className="mt-4 inline-flex items-center gap-1.5 rounded-control px-3 py-1.5 text-sm font-semibold transition-colors"
                style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
              >
                Provider brief for distinct symptoms <ArrowRight size={14} />
              </Link>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

type OpportunityCardView = Pick<GamePlanOpportunity, 'title' | 'body' | 'reg'> & {
  kind: string
  needs_nexus?: boolean
  form?: string | null
  attach_checklist?: string[]
}

/** An under-claimed opportunity — a §3.310 secondary theory (often for a condition
 * denied on a direct basis) or an Esteban-positive separate rating. Framed as
 * something to EXPLORE with a VSO; never asserts the link or predicts a rating.
 * Optional slots let the grounded deep dive reuse this exact card treatment;
 * all defaults preserve the existing Game Plan opportunity rendering. */
function OpportunityCard({
  opportunity: o,
  hue: hueOverride,
  icon,
  badges,
  bodyLabel,
  details,
  action,
}: {
  opportunity: OpportunityCardView
  hue?: Hue
  icon?: ReactNode
  badges?: ReactNode
  bodyLabel?: string
  details?: ReactNode
  /** undefined keeps the existing Secondaries link; null intentionally omits it. */
  action?: ReactNode
}) {
  const hue: Hue =
    hueOverride ??
    (o.kind === 'reclaim' ? 'rose' : o.kind === 'secondary' ? 'violet' : 'sky')
  const ink = hueInk(hue)
  return (
    <div className="vo-card vo-accent p-0 overflow-hidden" style={hueStyle(hue) as CSSProperties}>
      <div className="p-5">
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full"
            style={{ background: hueSoftVar(hue), color: ink }}
          >
            {icon ?? <TrendingUp size={16} />}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold text-txt">{o.title}</h3>
              {o.needs_nexus && (
                <span className="vo-chip-hue" style={hueStyle('amber') as CSSProperties}>
                  needs a nexus opinion
                </span>
              )}
              {badges}
            </div>
            {bodyLabel && (
              <p className="mt-3 text-micro font-semibold uppercase tracking-wide" style={{ color: hueLabel(hue) }}>
                {bodyLabel}
              </p>
            )}
            <p className="mt-1.5 text-sm leading-relaxed text-txt/85">{o.body}</p>
            <p className="mt-3 text-micro font-medium uppercase tracking-wide text-faint">{o.reg}</p>
            {details}
            {action === undefined ? (
              <Link
                to="/secondaries"
                className="mt-4 inline-flex items-center gap-1.5 rounded-control px-3 py-1.5 text-sm font-semibold transition-colors"
                style={{ background: hueSoftVar(hue), color: ink }}
              >
                Explore this option <ArrowRight size={14} />
              </Link>
            ) : (
              action
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────  DEEP-DIVE ORCHESTRATION  ────────────────────── */

/** Plain-language phrasing for each theory, so the raw backend word never shows.
 * Every phrase is a "may" — a possibility to weigh with a VSO, never a claim. */
const DEEP_DIVE_ORIGIN_LABELS: Record<DeepDiveOrigin, string> = {
  direct: 'May be directly service-connected',
  increase: 'May be rated higher',
  secondary: 'May be caused by a service-connected condition',
  presumptive: 'May be presumed service-connected',
  concurrent: 'May be a separate rating',
}

/** Sort/label order for finding severity — mirrors IMPACT_LABELS (Do soon → When you can). */
const DEEP_DIVE_SEVERITY_ORDER: GamePlanImpact[] = ['high', 'medium', 'low']

function DeepDiveRunButton({ running, onRun }: { running: boolean; onRun: () => void }) {
  return (
    <button type="button" className="vo-btn-secondary" onClick={onRun} disabled={running}>
      <RefreshCw size={14} className={running ? 'animate-spin' : undefined} />
      {running ? 'Running deep dive…' : 'Run deep dive'}
    </button>
  )
}

function DeepDiveSection({
  result,
  loading,
  loadError,
  runError,
  running,
  onRetry,
  onRun,
}: {
  result: DeepDiveResult | null
  loading: boolean
  loadError: string | null
  runError: string | null
  running: boolean
  onRetry: () => void
  onRun: () => void
}) {
  const hasSavedRun = Boolean(
    result && (result.generated_at || result.candidates_considered > 0 || result.findings.length > 0)
  )

  return (
    <div className="space-y-4">
      <SectionHeading
        icon={<ScanSearch size={16} />}
        title="Deep dive"
        sub="A rating-by-rating review of every option your records might support. Each item is checked against the VA's rating schedule and is worth bringing to your VSO — never a prediction of what VA will decide."
      />

      {loading && !result ? (
        <Panel hue={HUE}>
          <div className="flex items-center gap-2.5 p-5 text-sm text-muted" role="status" aria-live="polite">
            <RefreshCw size={15} className="animate-spin" /> Loading your saved deep dive…
          </div>
        </Panel>
      ) : loadError && !result ? (
        <Panel
          hue="rose"
          title="The saved deep dive could not be loaded"
          action={
            <button type="button" className="vo-btn-secondary" onClick={onRetry}>
              Try again
            </button>
          }
        >
          <div className="space-y-3 p-5">
            <p className="text-sm leading-relaxed text-muted">{loadError}</p>
            <DeepDiveRunButton running={running} onRun={onRun} />
          </div>
        </Panel>
      ) : !hasSavedRun || !result ? (
        <div className="space-y-4">
          <EmptyState
            hue={HUE}
            icon={<ScanSearch size={22} />}
            title="No saved deep dive yet"
            description="We'll go through every rating your records might support — one at a time — check each against the VA's rating schedule, and flag anything worth bringing to your VSO. This takes about a minute, and you can keep reading your plan while it runs."
            action={<DeepDiveRunButton running={running} onRun={onRun} />}
          />
          {running && <DeepDiveRunningPanel />}
          {runError && <DeepDiveInlineError message={runError} />}
        </div>
      ) : (
        <DeepDiveResultView result={result} running={running} runError={runError} onRun={onRun} />
      )}
    </div>
  )
}

function DeepDiveInlineError({ message }: { message: string }) {
  return (
    <p
      className="mt-3 flex items-start gap-2 rounded-control border border-danger/30 bg-danger-soft px-3 py-2 text-xs leading-relaxed text-danger"
      role="alert"
    >
      <AlertCircle size={14} className="mt-0.5 shrink-0" /> {message}
    </p>
  )
}

/** Reassuring in-progress state while the ~minute-long review runs. */
function DeepDiveRunningPanel() {
  return (
    <Panel hue={HUE}>
      <div className="space-y-3 p-5" role="status" aria-live="polite">
        <p className="flex items-center gap-2.5 text-sm font-semibold text-txt">
          <RefreshCw size={15} className="animate-spin" style={{ color: hueInk(HUE) }} /> Going through your records,
          one rating at a time…
        </p>
        <p className="text-sm leading-relaxed text-muted">
          This takes about a minute. You can keep reading the rest of your plan while it runs — we'll show what we find
          right here.
        </p>
        <div className="space-y-2 pt-1">
          <Skeleton className="h-3 w-2/3" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-1/2" />
        </div>
      </div>
    </Panel>
  )
}

function DeepDiveResultView({
  result,
  running,
  runError,
  onRun,
}: {
  result: DeepDiveResult
  running: boolean
  runError: string | null
  onRun: () => void
}) {
  const candidateCount = Math.max(result.candidates_considered, result.candidates.length)
  const activeCount = result.findings.filter((finding) => finding.active).length
  const newFindingsCount = result.notification?.new_finding_keys.length ?? 0

  // Active first, then severity (Do soon → When you can), then higher tier first.
  const sortedFindings = [...result.findings].sort((a, b) => {
    if (a.active !== b.active) return a.active ? -1 : 1
    const sev =
      DEEP_DIVE_SEVERITY_ORDER.indexOf(a.severity) - DEEP_DIVE_SEVERITY_ORDER.indexOf(b.severity)
    if (sev !== 0) return sev
    return (b.rating_percent ?? -1) - (a.rating_percent ?? -1)
  })
  const activeFindings = sortedFindings.filter((finding) => finding.active)
  const setAsideFindings = sortedFindings.filter((finding) => !finding.active)

  // Projection is a demoted what-if, never a peer stat — labelled inline as a scenario.
  const projectionWhatIf =
    result.current_combined == null
      ? ''
      : result.delta > 0
        ? ` — about ${result.delta} ${result.delta === 1 ? 'point' : 'points'} above your current ${result.current_combined}% in this what-if scenario`
        : result.delta < 0
          ? ` — about ${Math.abs(result.delta)} ${Math.abs(result.delta) === 1 ? 'point' : 'points'} below your current ${result.current_combined}% in this what-if scenario`
          : ` — the same as your current ${result.current_combined}%`

  return (
    <>
      {result.notification?.has_new_findings && (
        <div
          className="vo-card vo-accent flex items-start gap-3 p-4"
          style={hueStyle('teal') as CSSProperties}
          role="status"
          aria-live="polite"
        >
          <Sparkles size={17} className="mt-0.5 shrink-0" style={{ color: hueInk('teal') }} />
          <p className="text-sm leading-relaxed text-txt">
            We found {newFindingsCount} new {newFindingsCount === 1 ? 'item' : 'items'} worth reviewing since your last
            deep dive.
          </p>
        </div>
      )}

      <Panel
        hue={HUE}
        title="What the deep dive found"
        subtitle={result.generated_at ? `Last reviewed ${formatDate(result.generated_at)}` : 'Saved deep-dive result'}
        action={<DeepDiveRunButton running={running} onRun={onRun} />}
      >
        <div className="grid gap-px bg-line sm:grid-cols-3">
          <DeepDiveStat label="Ratings we checked" value={candidateCount} />
          <DeepDiveStat label="Worth a closer look" value={result.findings.length} />
          <DeepDiveStat label="Kept after overlap check" value={activeCount} />
        </div>
        <div className="border-t border-line p-4 sm:px-5">
          <p className="text-sm leading-relaxed text-muted">
            If every item below were granted as written, the §4.25 math would combine to about{' '}
            <span className="font-semibold tabular-nums text-txt">{result.projected_combined}%</span>
            {projectionWhatIf}. This is a planning estimate — only the VA decides your rating.
          </p>
          {running && (
            <p className="mt-3 flex items-center gap-2 text-xs leading-relaxed text-muted" role="status" aria-live="polite">
              <RefreshCw size={13} className="animate-spin" /> Re-checking your records — this takes about a minute.
              Your saved results stay up until the new ones are ready.
            </p>
          )}
          {runError && <DeepDiveInlineError message={runError} />}
        </div>
      </Panel>

      {result.findings.length === 0 ? (
        <Panel hue="sky">
          <p className="p-5 text-sm leading-relaxed text-muted">
            Nothing came up worth a closer look in this pass. An item only appears when your records show a signal and a
            matching card in the VA's rating schedule backs it up.
          </p>
        </Panel>
      ) : (
        <div className="space-y-4">
          {activeFindings.length > 0 && (
            <div className="space-y-3">
              <p className="text-micro font-semibold uppercase tracking-wide text-faint">Worth pursuing</p>
              {activeFindings.map((finding) => (
                <DeepDiveFindingCard
                  key={finding.key}
                  finding={finding}
                  candidate={candidateForFinding(result.candidates, finding)}
                  winnerTitle={winnerTitleForFinding(result.findings, finding)}
                />
              ))}
            </div>
          )}

          {setAsideFindings.length > 0 && (
            <details className="vo-card vo-accent overflow-hidden p-0" style={hueStyle('amber') as CSSProperties}>
              <summary className="flex cursor-pointer items-center gap-2 px-5 py-3.5 text-sm font-semibold text-txt">
                <Scale size={15} style={{ color: hueInk('amber') }} /> Set aside to avoid overlap ·{' '}
                {setAsideFindings.length}
              </summary>
              <div className="space-y-3 border-t border-line p-4 sm:p-5">
                <p className="text-xs leading-relaxed text-muted">
                  These overlap with something already counted above, so they're left out of the planning math above.
                  Nothing is removed — each card explains why it was set aside.
                </p>
                {setAsideFindings.map((finding) => (
                  <DeepDiveFindingCard
                    key={finding.key}
                    finding={finding}
                    candidate={candidateForFinding(result.candidates, finding)}
                    winnerTitle={winnerTitleForFinding(result.findings, finding)}
                  />
                ))}
              </div>
            </details>
          )}
        </div>
      )}
    </>
  )
}

function DeepDiveStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-surface p-4">
      <p className="text-micro font-semibold uppercase tracking-wide text-faint">{label}</p>
      <p className="mt-1 text-xl font-bold tabular-nums text-txt">{value}</p>
    </div>
  )
}

function candidateForFinding(candidates: CandidateRating[], finding: DeepDiveFinding): CandidateRating | undefined {
  const primaryDc = typeof finding.seed.primary_dc === 'string' ? finding.seed.primary_dc : null
  return candidates.find(
    (candidate) =>
      candidate.diagnostic_code === finding.diagnostic_code &&
      candidate.origin === finding.origin &&
      (primaryDc === null || candidate.primary_dc === primaryDc)
  )
}

function winnerTitleForFinding(findings: DeepDiveFinding[], finding: DeepDiveFinding): string | null {
  const winnerKey = finding.superseded_by ?? finding.excluded_by
  if (!winnerKey) return null
  return findings.find((candidate) => candidate.key === winnerKey)?.title ?? winnerKey
}

function DeepDiveFindingCard({
  finding,
  candidate,
  winnerTitle,
}: {
  finding: DeepDiveFinding
  candidate: CandidateRating | undefined
  winnerTitle: string | null
}) {
  // Hue carries SEVERITY (how soon to look at it), not the theory type. Set-aside
  // items stay amber to match their overlap framing.
  const hue: Hue = finding.active ? IMPACT_HUES[finding.severity] : 'amber'
  const regs = Array.from(new Set([...finding.regs, ...(finding.conflict_cfr ? [finding.conflict_cfr] : [])]))

  return (
    <OpportunityCard
      opportunity={{
        kind: finding.kind,
        title: finding.title,
        body: finding.body,
        reg: regs.join(' · '),
      }}
      hue={hue}
      icon={<ScanSearch size={16} />}
      badges={
        <>
          {finding.active && (
            <span className="vo-chip-hue" style={hueStyle(hue) as CSSProperties}>
              {IMPACT_LABELS[finding.severity]}
            </span>
          )}
          {finding.rating_percent != null && (
            <span className="vo-chip-hue" style={hueStyle('sky') as CSSProperties}>
              may support {finding.rating_percent}%
            </span>
          )}
          {finding.diagnostic_code && <span className="vo-chip">DC {finding.diagnostic_code}</span>}
          <span className="vo-chip">{DEEP_DIVE_ORIGIN_LABELS[finding.origin]}</span>
          {/* Phase 2b: a THEORY finding is a weighed opinion, not settled rules — show
              its VA register + confidence so it never reads as the deterministic floor. */}
          {finding.layer === 'theory' && finding.confidence_level && (
            <span
              className="vo-chip-hue"
              style={hueStyle(CONFIDENCE_LEVEL_HUES[finding.confidence_level]) as CSSProperties}
              title={`Confidence ${Math.round(finding.confidence * 100)}%`}
            >
              {CONFIDENCE_LEVEL_LABELS[finding.confidence_level]} · {Math.round(finding.confidence * 100)}%
            </span>
          )}
          {!finding.active && (
            <span className="vo-chip-hue" style={hueStyle('amber') as CSSProperties}>
              overlap to weigh
            </span>
          )}
        </>
      }
      bodyLabel="What this is and what your record shows"
      details={
        <DeepDiveFindingDetails
          finding={finding}
          candidate={candidate}
          winnerTitle={winnerTitle}
          hue={hue}
        />
      }
      action={<DeepDiveFindingAction finding={finding} hue={hue} />}
    />
  )
}

/** Every finding ends with a next step: the related VA form (when known, in the
 * TdiuCard form/reg style) and a consistent "take it to your VSO" CTA — never a
 * button that files or promises anything. */
function DeepDiveFindingAction({ finding, hue }: { finding: DeepDiveFinding; hue: Hue }) {
  const ink = hueInk(hue)
  return (
    <div className="mt-4">
      {finding.suggested_form && (
        <p className="mb-3 text-micro font-medium uppercase tracking-wide text-faint">
          Related VA form · {finding.suggested_form}
        </p>
      )}
      <a
        href="#support"
        className="inline-flex items-center gap-1.5 rounded-control px-3 py-1.5 text-sm font-semibold transition-colors"
        style={{ background: hueSoftVar(hue), color: ink }}
      >
        Bring this to your VSO <ArrowRight size={14} />
      </a>
    </div>
  )
}

function DeepDiveFindingDetails({
  finding,
  candidate,
  winnerTitle,
  hue,
}: {
  finding: DeepDiveFinding
  candidate: CandidateRating | undefined
  winnerTitle: string | null
  hue: Hue
}) {
  const conflict = finding.conflict_reason || finding.conflict_cfr || winnerTitle
  const structuredCitations = finding.citations ?? []
  const citationCount =
    finding.regs.length + finding.card_ids.length + finding.evidence_refs.length + structuredCitations.length

  return (
    <div className="mt-4 space-y-3">
      {candidate?.seed_signal && (
        <div className="rounded-control border border-line bg-surface2 p-3.5">
          <p className="text-micro font-semibold uppercase tracking-wide" style={{ color: hueLabel(hue) }}>
            Why it was checked
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{candidate.seed_signal}</p>
        </div>
      )}

      {finding.needs.length > 0 && (
        <div>
          <p className="text-micro font-semibold uppercase tracking-wide" style={{ color: hueLabel(hue) }}>
            What's still needed
          </p>
          <ul className="mt-1.5 space-y-1.5 text-sm text-muted">
            {finding.needs.map((need, index) => (
              <li key={`${index}-${need}`} className="flex items-start gap-2">
                <Circle size={8} className="mt-1.5 shrink-0 fill-current" style={{ color: hueInk(hue) }} />
                <span className="leading-relaxed">{need}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {!finding.active && conflict && (
        <div
          className="rounded-control border-l-[3px] px-3.5 py-3 text-xs leading-relaxed text-txt/85"
          style={{ borderColor: hueVar('amber'), background: hueSoftVar('amber') }}
        >
          <p className="font-semibold text-txt">How this overlap was handled</p>
          <p className="mt-1">
            For the planning projection, this lane was set aside
            {winnerTitle ? ` in favor of ${winnerTitle}` : ''}. {finding.conflict_reason}
            {finding.conflict_cfr ? ` (${finding.conflict_cfr})` : ''}
          </p>
        </div>
      )}

      <details className="rounded-control border border-line bg-surface2 px-3.5 py-2.5">
        <summary className="cursor-pointer text-xs font-semibold text-muted">
          Grounding citations · {citationCount}
        </summary>
        <div className="mt-2.5 space-y-2 text-xs text-faint">
          {finding.regs.length > 0 && (
            <p>
              <span className="font-semibold text-muted">Regulations:</span> {finding.regs.join(' · ')}
            </p>
          )}
          {finding.card_ids.length > 0 && (
            <p className="flex flex-wrap items-center gap-1.5">
              <span className="font-semibold text-muted">Rating cards:</span>
              {finding.card_ids.map((ref) => (
                <code key={ref} title={ref} className="rounded bg-surface px-1.5 py-0.5 text-faint">
                  {shortCitation(ref)}
                </code>
              ))}
            </p>
          )}
          {finding.evidence_refs.length > 0 && (
            <p className="flex flex-wrap items-center gap-1.5">
              <span className="font-semibold text-muted">Your record excerpts:</span>
              {finding.evidence_refs.map((ref) => (
                <code key={ref} title={ref} className="rounded bg-surface px-1.5 py-0.5 text-faint">
                  {shortCitation(ref)}
                </code>
              ))}
            </p>
          )}
          {structuredCitations.length > 0 && (
            <div className="flex flex-col gap-1">
              <span className="font-semibold text-muted">Sources:</span>
              {structuredCitations.map((c, i) => (
                <span key={`cite-${i}`} className="leading-relaxed">
                  · {citationLabel(c)}
                </span>
              ))}
            </div>
          )}
          {candidate?.source_ref && (
            <p>
              <span className="font-semibold text-muted">Seed source:</span> {candidate.source_ref}
            </p>
          )}
        </div>
      </details>
    </div>
  )
}

function shortCitation(ref: string): string {
  if (ref.length <= 18) return ref
  return `${ref.slice(0, 8)}…${ref.slice(-4)}`
}

/** Readable one-line label for a Phase 2b structured citation. The backend attaches
 * source pointers as loosely-shaped objects; prefer the most specific recognizable
 * field, then fall back to a compact JSON so nothing is silently dropped. */
function citationLabel(c: DeepDiveCitation): string {
  const parts = [c.cfr, c.card_id ? shortCitation(c.card_id) : undefined, c.ref, c.label]
    .filter((p): p is string => typeof p === 'string' && p.length > 0)
  if (parts.length > 0) {
    const kind = typeof c.kind === 'string' && c.kind ? `${c.kind}: ` : ''
    return `${kind}${parts.join(' · ')}`
  }
  if (typeof c.quote === 'string' && c.quote) {
    return `“${c.quote.length > 120 ? `${c.quote.slice(0, 117)}…` : c.quote}”`
  }
  try {
    return JSON.stringify(c)
  } catch {
    return 'source'
  }
}

/** TDIU (§4.16) — the opportunity to be PAID at 100% without a 100% rating. An
 * emerald "worth knowing" card: what it is, why it may fit this veteran, the
 * evidence it turns on, and the form. Educational — VA decides unemployability. */
function TdiuCard({ tdiu: t }: { tdiu: GamePlanTdiu }) {
  const hue: Hue = 'emerald'
  const ink = hueInk(hue)
  return (
    <div className="vo-card vo-accent p-0 overflow-hidden" style={hueStyle(hue) as CSSProperties}>
      <div
        className="flex items-center gap-1.5 px-5 py-2.5 text-micro font-bold uppercase tracking-wide"
        style={{ background: hueVar(hue), color: 'var(--surface)' }}
      >
        <Briefcase size={13} /> {t.eligible_schedular ? 'You may meet the TDIU threshold' : 'Worth knowing: TDIU'}
      </div>
      <div className="p-5">
        <h3 className="text-lg font-semibold text-txt">TDIU — 100% pay without a 100% rating</h3>
        <p className="mt-1 text-sm leading-relaxed text-txt/85">{t.what_it_is}</p>
        <div
          className="mt-4 rounded-control border-l-[3px] px-3.5 py-2.5 text-sm leading-relaxed text-txt/90"
          style={{ borderColor: hueVar(hue), background: hueSoftVar(hue) }}
        >
          {t.why}
        </div>
        {t.evidence.length > 0 && (
          <div className="mt-4">
            <p className="mb-1.5 text-micro font-semibold uppercase tracking-wide" style={{ color: hueLabel(hue) }}>
              What TDIU turns on
            </p>
            <ul className="space-y-1.5 text-sm text-txt">
              {t.evidence.map((e, i) => (
                <li key={i} className="flex gap-2.5">
                  <CheckCircle2 size={15} className="mt-0.5 shrink-0" style={{ color: ink }} />
                  <span className="leading-relaxed">{e}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="mt-4 text-sm leading-relaxed text-txt/85">{t.note}</p>
        <p className="mt-3 text-micro font-medium uppercase tracking-wide text-faint">
          {t.form} · {t.reg}
        </p>
        <Link
          to="/tdiu"
          className="mt-4 inline-flex items-center gap-1.5 rounded-control px-3 py-1.5 text-sm font-semibold transition-colors"
          style={{ background: hueSoftVar(hue), color: ink }}
        >
          Open the TDIU workspace <ArrowRight size={14} />
        </Link>
      </div>
    </div>
  )
}

/** The estimated combined rating — NEVER shown without its basis label. */
function EstimateBlock({ pathway: p, hue }: { pathway: GamePlanPathway; hue: Hue }) {
  const hasNumber = p.estimated_combined !== null
  return (
    <div className="mt-4 rounded-control border border-line bg-surface2 p-4" style={hueStyle(hue) as CSSProperties}>
      {hasNumber && (
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold tabular-nums" style={{ color: hueInk(hue) }}>
              {p.estimated_combined}%
            </span>
            <span
              className="rounded-full px-2 py-0.5 text-micro font-bold uppercase tracking-wide"
              style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
            >
              Estimate only
            </span>
          </div>
          <p className="text-micro font-semibold uppercase tracking-wide" style={{ color: hueLabel(hue) }}>
            Estimated combined rating
          </p>
        </div>
      )}
      <p className={hasNumber ? 'mt-2 text-xs leading-relaxed text-muted' : 'text-sm leading-relaxed text-muted'}>
        {p.estimated_combined_basis}
      </p>
    </div>
  )
}

/* ─────────────────────────────  5 · ACTIONS  ─────────────────────────────── */

function ActionRow({ action: a }: { action: GamePlanAction }) {
  const hue = IMPACT_HUES[a.impact]
  const body = (
    <div
      className="vo-card vo-accent flex items-start gap-3.5 p-4 transition-shadow duration-150 hover:shadow-md"
      style={hueStyle(hue) as CSSProperties}
    >
      <span
        className="mt-0.5 shrink-0 rounded-full px-2.5 py-1 text-micro font-bold uppercase tracking-wide"
        style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
      >
        {IMPACT_LABELS[a.impact]}
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-txt">{a.title}</p>
        <p className="mt-0.5 text-sm leading-relaxed text-muted">{a.why}</p>
        {a.condition_name && <p className="mt-0.5 text-xs text-faint">Related to {a.condition_name}</p>}
      </div>
      {a.link && <ArrowRight size={16} className="mt-1 shrink-0" style={{ color: hueInk(hue) }} />}
    </div>
  )
  return a.link ? (
    <Link to={a.link} className="block">
      {body}
    </Link>
  ) : (
    body
  )
}

/* ─────────────────────────────  6 · ROADMAP  ─────────────────────────────── */

const STEP_HUE: Record<GamePlanStep['state'], Hue> = {
  done: 'emerald',
  now: 'fuchsia',
  upcoming: 'sky',
}

function Roadmap({ steps }: { steps: GamePlanStep[] }) {
  return (
    <div className="vo-card vo-accent p-5 sm:p-6" style={hueStyle(HUE) as CSSProperties}>
      <ol className="relative space-y-5">
        {/* connective spine */}
        <span aria-hidden className="absolute bottom-3 left-[13px] top-3 w-px bg-line" />
        {steps.map((s) => (
          <RoadmapStep key={s.key} step={s} />
        ))}
      </ol>
    </div>
  )
}

function RoadmapStep({ step: s }: { step: GamePlanStep }) {
  const hue = STEP_HUE[s.state]
  const isNow = s.state === 'now'
  return (
    <li className="relative flex gap-4">
      <span
        aria-hidden
        className="relative z-10 mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full ring-4 ring-[var(--surface)]"
        style={{
          background: s.state === 'upcoming' ? 'var(--surface2)' : hueVar(hue),
          color: s.state === 'upcoming' ? 'var(--faint)' : 'var(--surface)',
        }}
      >
        {s.state === 'done' ? (
          <CheckCircle2 size={16} />
        ) : isNow ? (
          <span className="h-2.5 w-2.5 rounded-full bg-current" />
        ) : (
          <Circle size={14} />
        )}
      </span>
      <div className={isNow ? 'flex-1 pb-1' : 'flex-1 pb-1 opacity-95'}>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="font-semibold text-txt">{s.title}</h3>
          {isNow && (
            <span
              className="rounded-full px-2 py-0.5 text-micro font-bold uppercase tracking-wide"
              style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
            >
              You're here
            </span>
          )}
          {s.state === 'done' && (
            <span className="text-micro font-bold uppercase tracking-wide" style={{ color: hueInk('emerald') }}>
              Done
            </span>
          )}
        </div>
        <p className="mt-0.5 text-sm leading-relaxed text-muted">{s.body}</p>
      </div>
    </li>
  )
}

/* ─────────────────────────────  7 · SUPPORT  ─────────────────────────────── */

/** You're not alone. A free VSO files for you; the Veterans Crisis Line is one
 * tap away. This belongs on a page a struggling veteran actually reads. */
function SupportResources({ data }: { data: GamePlanOut }) {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="vo-card vo-accent p-5" style={hueStyle('teal') as CSSProperties}>
        <p className="flex items-center gap-2 font-semibold text-txt">
          <LifeBuoy size={17} style={{ color: hueInk('teal') }} /> Get free help filing
        </p>
        <p className="mt-1.5 text-sm leading-relaxed text-muted">{data.vso_referral}</p>
        <a
          href="https://www.va.gov/get-help-from-accredited-representative/"
          target="_blank"
          rel="noreferrer"
          className="mt-2.5 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
        >
          Find a VSO near you <ExternalLink size={13} />
        </a>
      </div>
      <div className="vo-card vo-accent p-5" style={hueStyle('rose') as CSSProperties}>
        <p className="flex items-center gap-2 font-semibold text-txt">
          <Phone size={17} style={{ color: hueInk('rose') }} /> Veterans Crisis Line
        </p>
        <p className="mt-1.5 text-sm leading-relaxed text-muted">
          If you're struggling, you're not alone and it's not weakness to reach out. Confidential support, 24/7 — you
          don't have to be enrolled in VA.
        </p>
        <p className="mt-2.5 text-sm font-semibold text-txt">
          Dial <a href="tel:988" className="text-brand hover:text-brand-hover">988</a> then press 1 · text{' '}
          <a href="sms:838255" className="text-brand hover:text-brand-hover">838255</a>
        </p>
      </div>
    </div>
  )
}

function SourceAndDisclaimer({ data }: { data: GamePlanOut }) {
  return (
    <Panel hue={HUE} title="What this is — and isn't" subtitle="Educational self-help, not legal or medical advice">
      <div className="space-y-3 p-5">
        <p className="flex items-start gap-2 text-sm leading-relaxed text-muted">
          <ShieldCheck size={15} className="mt-0.5 shrink-0" style={{ color: hueInk(HUE) }} />
          <span>{data.disclaimer}</span>
        </p>
        <div
          className="rounded-control border-l-2 px-3 py-2 text-xs italic leading-relaxed text-faint"
          style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
        >
          {data.source_note}
        </div>
      </div>
    </Panel>
  )
}

/** Prominent legal-lane note (shown on the empty state). */
function LegalLaneBanner() {
  return (
    <div
      className="vo-card vo-accent relative flex items-start gap-3.5 overflow-hidden p-5"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}
      >
        <ShieldCheck size={20} />
      </div>
      <div>
        <h2 className="text-sm font-semibold text-txt">
          Options to consider — not a prediction, and never filed for you
        </h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          This Claim Plan organizes what you've told Rating Raider into strategies you might consider. Any estimated
          combined rating is simple §4.25 math on the target ratings <em>you</em> entered — never a prediction or a
          promise of what VA will decide. You choose your path, and a VA-accredited VSO — VFW, DAV, The American Legion,
          or your state/county veterans office — helps you file it for free.
        </p>
      </div>
    </div>
  )
}

/** Short label for a VA disposition in the decision-status apply list. */
function decisionStatusLabel(status: string): string {
  if (status === 'service_connected') return 'service-connected'
  if (status === 'denied') return 'denied'
  if (status === 'pending') return 'pending'
  if (status === 'unknown') return 'unknown'
  return status.replace(/_/g, ' ')
}

/** Opt-in banner: formal decision letters can fill conditions still marked unknown.
 * Never auto-applies — veteran must click Apply. */
function DecisionStatusPanel({
  preview,
  applying,
  onApply,
}: {
  preview: DecisionStatusApplyOut
  applying: boolean
  onApply: () => void
}) {
  const hue: Hue = 'teal'
  const updates = preview.updates
  return (
    <div
      className="vo-card vo-accent p-5"
      style={hueStyle(hue) as CSSProperties}
      role="region"
      aria-label="Decision letter status updates"
    >
      <div className="flex items-start gap-3.5">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
        >
          <CheckCircle2 size={20} />
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <div>
            <h2 className="text-sm font-semibold text-txt">
              Decision letters can fill missing VA statuses
            </h2>
            <p className="mt-1 text-sm leading-relaxed text-muted">
              Your uploaded decision / claim letters already state a disposition for{' '}
              {updates.length === 1 ? 'this condition' : 'these conditions'} still marked unknown. Apply only if
              this matches what the letters say — you can edit any condition afterward.
            </p>
          </div>
          <ul className="space-y-1.5 text-sm text-txt/90">
            {updates.map((u) => {
              const key = u.condition_id ?? `${u.name}-${u.to_status}`
              const rating =
                u.set_current_rating != null ? ` · ${u.set_current_rating}%` : ''
              return (
                <li key={key} className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
                  <span className="font-medium text-txt">{u.name}</span>
                  <span className="text-muted">
                    {decisionStatusLabel(u.from_status)} → {decisionStatusLabel(u.to_status)}
                    {rating}
                  </span>
                  {u.decision_name ? (
                    <span className="text-xs text-faint">({u.decision_name})</span>
                  ) : null}
                </li>
              )
            })}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              className="vo-btn-primary text-sm"
              disabled={applying}
              onClick={onApply}
            >
              {applying ? <Spinner size={15} /> : <CheckCircle2 size={15} />}
              {applying ? 'Applying…' : 'Apply statuses from decision letters'}
            </button>
          </div>
          <p className="text-xs leading-relaxed text-muted">
            {preview.note?.trim() ||
              'Organizing what your formal decision letters already say — not a VA determination. Only conditions still marked unknown are updated; statuses you set yourself are kept.'}
          </p>
        </div>
      </div>
    </div>
  )
}
