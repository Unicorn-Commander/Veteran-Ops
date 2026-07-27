import {
  ArrowRight,
  CheckCircle2,
  Info,
  Landmark,
  ListChecks,
  Medal,
  Search,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { useState, type CSSProperties, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Checkbox, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { correctionsApi } from '../lib/api'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { RankAnalysisIn, RankAnalysisOut, RankFinding, RankSelection, RankStrength } from '../types'

// /rank — Officer rank / promotion correction. A missed or never-carried-out
// officer promotion (an officer who stayed a 2LT/1LT longer than the record shows
// promotion should have issued) may be correctable through the military records-
// correction board — NOT the VA. This NEVER promises a promotion: every line stays
// hedged ("may be correctable", the board decides). The backend enforces this in
// its strings; the UI renders them and adds none of its own. Mirrors the Dependency
// / Tdiu guidance+form builder pattern. From here, a strong/moderate finding routes
// the veteran to the Corrections page to prepare the DD Form 149 packet.

const HUE: Hue = 'orange'

/** Strength-badge identity. `weak` is deliberately a neutral slate/gray (no hue)
 * so it reads as "possible, not promising"; the others map to the section hue
 * family per the spec (strong=emerald, moderate=amber, needs_dates=sky/blue). */
const STRENGTH_META: Record<RankStrength, { hue: Hue | null; label: string }> = {
  strong: { hue: 'emerald', label: 'Strong basis' },
  moderate: { hue: 'amber', label: 'Moderate basis' },
  weak: { hue: null, label: 'Weak basis' },
  needs_dates: { hue: 'sky', label: 'Needs dates' },
}

const SELECTION_OPTIONS: { value: 'none' | RankSelection; label: string }[] = [
  { value: 'none', label: 'No / not sure' },
  { value: '1lt', label: 'Yes — for First Lieutenant (1LT)' },
  { value: 'capt', label: 'Yes — for Captain (CPT)' },
]

export function Rank() {
  const { toast } = useToast()
  const { data: guidance, error: guidanceError, loading } = useAsync(() => correctionsApi.rankGuidance())

  const [commissionDate, setCommissionDate] = useState('')
  const [dateOfRank2lt, setDateOfRank2lt] = useState('')
  const [promotedTo1lt, setPromotedTo1lt] = useState(false)
  const [dateOfRank1lt, setDateOfRank1lt] = useState('')
  const [promotedToCapt, setPromotedToCapt] = useState(false)
  const [separationDate, setSeparationDate] = useState('')
  const [medicallyRetired, setMedicallyRetired] = useState(false)
  const [selectedForPromotion, setSelectedForPromotion] = useState<'none' | RankSelection>('none')
  const [completedCcc, setCompletedCcc] = useState(false)
  const [branch, setBranch] = useState('Army')

  const [result, setResult] = useState<RankAnalysisOut | null>(null)
  const [analyzing, setAnalyzing] = useState(false)

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)

  const buildBody = (): RankAnalysisIn => {
    const body: RankAnalysisIn = {
      promoted_to_1lt: promotedTo1lt,
      promoted_to_capt: promotedToCapt,
      medically_retired: medicallyRetired,
      selected_for_promotion: selectedForPromotion === 'none' ? null : selectedForPromotion,
      completed_captains_career_course: completedCcc,
      branch: branch.trim() || 'Army',
    }
    if (commissionDate.trim()) body.commission_date = commissionDate.trim()
    if (dateOfRank2lt.trim()) body.date_of_rank_2lt = dateOfRank2lt.trim()
    if (dateOfRank1lt.trim()) body.date_of_rank_1lt = dateOfRank1lt.trim()
    if (separationDate.trim()) body.separation_date = separationDate.trim()
    return body
  }

  const analyze = async (e: FormEvent) => {
    e.preventDefault()
    setAnalyzing(true)
    try {
      const out = await correctionsApi.rankAnalyze(buildBody())
      setResult(out)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setAnalyzing(false)
    }
  }

  const hasActionable = result?.findings.some((f) => f.strength === 'strong' || f.strength === 'moderate')

  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6" style={hueStyle(HUE) as CSSProperties}>
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          Records &amp; corrections · Officer promotions
        </p>
        <h1 className="vo-page-title">Officer rank / promotion correction</h1>
        <p className="vo-page-sub max-w-[70ch]">
          If you were an officer who stayed the same grade longer than your record suggests a promotion should have
          issued — a missed or never-carried-out promotion — that <strong className="text-txt">may be correctable</strong>{' '}
          through your service's military records-correction board, not the VA. Tell it the dates and it will show you
          what a board would look at. This never promises a promotion — the board decides.
        </p>
      </div>

      {loading && !guidance && <LoadingBlock label="Loading rank-correction guidance…" />}
      {guidanceError && !guidance && <ErrorBlock message={guidanceError} />}

      {guidance && (
        <>
          <Panel hue={HUE} title="What this is" subtitle="Officer promotion corrections, in plain terms">
            <div className="p-5">
              <p className="text-sm leading-relaxed text-txt/90">{guidance.what_it_is}</p>
            </div>
          </Panel>

          {guidance.how_it_works.length > 0 && (
            <Panel hue={HUE} title="How it works" subtitle="The path a promotion correction takes">
              <div className="p-5">
                <ul className="space-y-2.5 text-sm text-txt">
                  {guidance.how_it_works.map((h, i) => (
                    <li key={i} className="flex gap-2.5">
                      <span
                        aria-hidden
                        className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                        style={{ background: hueSoftVar(HUE), color: ink }}
                      >
                        {i + 1}
                      </span>
                      <span className="leading-relaxed">{h}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Panel>
          )}

          {guidance.thresholds.length > 0 && (
            <Panel hue={HUE} title="What a board looks at" subtitle="The things that carry the most weight">
              <div className="p-5">
                <ul className="space-y-2.5 text-sm text-txt">
                  {guidance.thresholds.map((t, i) => (
                    <li key={i} className="flex gap-2.5">
                      <CheckCircle2 size={16} className="mt-0.5 shrink-0" style={{ color: ink }} />
                      <span className="leading-relaxed">{t}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Panel>
          )}

          <Panel
            hue={HUE}
            title="Your service facts"
            subtitle="Fill in what you can — dates help, but a partial answer still works"
          >
            <form onSubmit={analyze} className="space-y-5 p-5">
              {guidance.prompts.length > 0 && (
                <div
                  className="rounded-control border p-4"
                  style={{ borderColor: `color-mix(in srgb, ${hueVar(HUE)} 30%, var(--border))`, background: hueSoftVar(HUE) }}
                >
                  <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                    <ListChecks size={13} /> What to have on hand
                  </p>
                  <ul className="mt-2 space-y-1.5 text-xs text-muted">
                    {guidance.prompts.map((p, i) => (
                      <li key={i} className="flex gap-2">
                        <span aria-hidden style={{ color: ink }}>•</span>
                        <span className="leading-relaxed">{p}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">
                  <span className="vo-label">Date you were commissioned</span>
                  <input
                    type="date"
                    className="vo-input"
                    value={commissionDate}
                    onChange={(e) => setCommissionDate(e.target.value)}
                  />
                </label>
                <label className="text-sm">
                  <span className="vo-label">Date of rank — Second Lieutenant (2LT)</span>
                  <input
                    type="date"
                    className="vo-input"
                    value={dateOfRank2lt}
                    onChange={(e) => setDateOfRank2lt(e.target.value)}
                  />
                </label>
                <label className="text-sm">
                  <span className="vo-label">Branch</span>
                  <input
                    className="vo-input"
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    placeholder="e.g. Army"
                  />
                </label>
                <label className="text-sm">
                  <span className="vo-label">Date you separated or retired</span>
                  <input
                    type="date"
                    className="vo-input"
                    value={separationDate}
                    onChange={(e) => setSeparationDate(e.target.value)}
                  />
                </label>
              </div>

              <div className="space-y-3 rounded-control border border-line bg-surface2 p-4">
                <span className="text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
                  Promotions
                </span>
                <Checkbox
                  checked={promotedTo1lt}
                  onChange={() => setPromotedTo1lt(!promotedTo1lt)}
                  label="I was promoted to First Lieutenant (1LT)"
                  description="Officers are normally promoted from 2LT to 1LT after a set time in grade."
                />
                {promotedTo1lt && (
                  <label className="block text-sm sm:max-w-xs">
                    <span className="vo-label">Date of rank — First Lieutenant (1LT)</span>
                    <input
                      type="date"
                      className="vo-input"
                      value={dateOfRank1lt}
                      onChange={(e) => setDateOfRank1lt(e.target.value)}
                    />
                  </label>
                )}
                <Checkbox
                  checked={promotedToCapt}
                  onChange={() => setPromotedToCapt(!promotedToCapt)}
                  label="I was promoted to Captain (CPT)"
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">
                  <span className="vo-label">Were you selected for a promotion that was never carried out?</span>
                  <select
                    className="vo-input"
                    value={selectedForPromotion}
                    onChange={(e) => setSelectedForPromotion(e.target.value as 'none' | RankSelection)}
                  >
                    {SELECTION_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <div className="space-y-3 rounded-control border border-line bg-surface2 p-4">
                <Checkbox
                  checked={completedCcc}
                  onChange={() => setCompletedCcc(!completedCcc)}
                  label="I completed the Captain's Career Course"
                  description="A professional-education milestone tied to promotion to Captain."
                />
                <Checkbox
                  checked={medicallyRetired}
                  onChange={() => setMedicallyRetired(!medicallyRetired)}
                  label="I was medically retired"
                  description="The grade you retired at can matter for retired pay — see the note below."
                />
              </div>

              <button type="submit" disabled={analyzing} className="vo-btn-primary">
                {analyzing ? <Spinner size={16} className="text-white" /> : <Search size={15} />}
                Check for a promotion correction
              </button>
              <p className="flex items-center gap-1.5 text-xs text-faint">
                <Sparkles size={12} style={{ color: ink }} /> This looks at what a board would consider — it never
                promises a promotion. The board decides.
              </p>
            </form>
          </Panel>

          {result && (
            <RankResult result={result} hasActionable={!!hasActionable} ink={ink} label={label} />
          )}

          <div
            className="rounded-control border-l-2 px-4 py-3 text-xs leading-relaxed"
            style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
          >
            <p className="italic text-muted">{guidance.disclaimer}</p>
          </div>
        </>
      )}
    </div>
  )
}

/** The analysis result — overall summary, one card per grade-to-grade finding
 * (each strength-badged), the retired-grade note, the human checklist, an
 * optional non-Army note, the board/form, a route onward to the packet builder
 * when something is actionable, and the referrals + disclaimer footer. */
function RankResult({
  result,
  hasActionable,
  ink,
  label,
}: {
  result: RankAnalysisOut
  hasActionable: boolean
  ink: string
  label: string
}) {
  return (
    <Panel hue={HUE} title="What a board would look at" subtitle="Hedged findings — the board decides, not this tool">
      <div className="space-y-4 p-5">
        {result.overall && (
          <div
            className="rounded-control border p-4"
            style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
          >
            <p className="flex items-start gap-2 text-sm leading-relaxed text-txt">
              <Info size={15} className="mt-0.5 shrink-0" style={{ color: ink }} />
              <span>{result.overall}</span>
            </p>
          </div>
        )}

        {result.findings.length > 0 && (
          <div className="space-y-3">
            {result.findings.map((f, i) => (
              <FindingCard key={i} finding={f} />
            ))}
          </div>
        )}

        {result.retired_grade_note && (
          <div
            className="flex items-start gap-2.5 rounded-control border-l-2 px-3.5 py-3 text-sm leading-relaxed text-muted"
            style={{ borderColor: hueVar('violet'), background: hueSoftVar('violet') }}
          >
            <ShieldCheck size={15} className="mt-0.5 shrink-0" style={{ color: hueInk('violet') }} />
            <span>{result.retired_grade_note}</span>
          </div>
        )}

        {result.human_checklist.length > 0 && (
          <div>
            <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: label }}>
              <ListChecks size={12} /> Before you go to a board
            </p>
            <ul className="space-y-2 text-sm text-txt">
              {result.human_checklist.map((c, i) => (
                <li key={i} className="flex gap-2.5">
                  <CheckCircle2 size={16} className="mt-0.5 shrink-0" style={{ color: ink }} />
                  <span className="leading-relaxed">{c}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {result.non_army_note && (
          <p className="flex items-start gap-2 text-sm leading-relaxed text-muted">
            <Info size={14} className="mt-0.5 shrink-0" style={{ color: ink }} />
            <span>{result.non_army_note}</span>
          </p>
        )}

        {(result.board || result.form || result.form_title) && (
          <div
            className="rounded-control border p-4"
            style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
          >
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: label }}>
              <Landmark size={12} /> Where this goes
            </p>
            {result.board && <p className="mt-0.5 text-lg font-bold text-txt">{result.board}</p>}
            {(result.form || result.form_title) && (
              <p className="mt-1.5 flex flex-wrap items-baseline gap-2 text-sm text-txt">
                {result.form && (
                  <span
                    className="rounded-md border px-2 py-0.5 font-mono text-xs font-bold"
                    style={{ borderColor: hueVar(HUE), color: ink }}
                  >
                    {result.form}
                  </span>
                )}
                {result.form_title && <span className="text-muted">{result.form_title}</span>}
              </p>
            )}
          </div>
        )}

        {hasActionable && (
          <div
            className="flex flex-col items-start gap-2 rounded-control border p-4"
            style={{ borderColor: hueVar('emerald'), background: hueSoftVar('emerald') }}
          >
            <p className="text-sm font-semibold text-txt">Ready to prepare the application?</p>
            <p className="text-sm leading-relaxed text-muted">
              There may be a basis here worth putting to a board. The Corrections page builds the DD Form 149 packet you
              review, sign, and file — this tool never files anything and never promises the outcome.
            </p>
            <Link to="/corrections" className="vo-btn-primary mt-1">
              Prepare the correction packet <ArrowRight size={15} />
            </Link>
          </div>
        )}

        {/* Referrals + disclaimer — surfaced on every result. */}
        <div className="space-y-2 border-t border-line pt-4">
          {result.vso_referral && <p className="text-sm leading-relaxed text-muted">{result.vso_referral}</p>}
          {result.legal_aid_referral && <p className="text-sm leading-relaxed text-muted">{result.legal_aid_referral}</p>}
          {result.disclaimer && <p className="text-xs italic leading-relaxed text-faint">{result.disclaimer}</p>}
        </div>
      </div>
    </Panel>
  )
}

/** One grade-to-grade finding, with a strength badge. */
function FindingCard({ finding }: { finding: RankFinding }) {
  const meta = STRENGTH_META[finding.strength]
  const badgeStyle: CSSProperties = meta.hue
    ? { background: hueSoftVar(meta.hue), color: hueInk(meta.hue) }
    : { background: 'var(--surface2)', color: 'var(--muted)' }
  return (
    <article className="rounded-control border border-line bg-surface2 p-4">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-txt">
          <Medal size={15} style={{ color: meta.hue ? hueInk(meta.hue) : 'var(--muted)' }} />
          {finding.grade_from} <ArrowRight size={13} className="text-faint" /> {finding.grade_to}
        </p>
        <span className="rounded-full px-2 py-0.5 text-micro font-bold uppercase tracking-wide" style={badgeStyle}>
          {meta.label}
        </span>
      </div>
      {finding.headline && <p className="text-sm font-medium text-txt">{finding.headline}</p>}
      {finding.reasoning && <p className="mt-1.5 text-sm leading-relaxed text-muted">{finding.reasoning}</p>}
      {finding.what_to_request && (
        <p className="mt-2.5 flex items-start gap-2 rounded-control border-l-2 border-line bg-surface px-3 py-2 text-sm leading-relaxed text-txt">
          <ListChecks size={14} className="mt-0.5 shrink-0 text-faint" />
          <span>
            <span className="font-semibold">What to request:</span> {finding.what_to_request}
          </span>
        </p>
      )}
    </article>
  )
}
