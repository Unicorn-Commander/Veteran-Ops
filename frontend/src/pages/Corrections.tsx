import {
  AlertTriangle,
  Check,
  ExternalLink,
  Gavel,
  Info,
  Landmark,
  Lightbulb,
  ListChecks,
  Medal,
  Plus,
  Printer,
  Quote,
  Scale,
  ScrollText,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Checkbox, EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { checklistApi, correctionsApi, kbApi } from '../lib/api'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type {
  CorrectionGoal,
  CorrectionRequestedItem,
  CorrectionRouteResult,
  CorrectionSituationInput,
  KbCard,
  LiberalTrigger,
} from '../types'

// /corrections — WAVE10 Track. Military records CORRECTION is a DIFFERENT legal
// process from VA disability claims (you file with a MILITARY board — DRB / BCMR /
// PDBR — NOT the VA). This page pairs an interactive router+packet wizard with the
// existing educational KB cards (card_type "process", body_system "corrections").
//
// This is sensitive territory: discharge upgrades and MST. Rating Raider is
// educational self-help ONLY. It never files, never gives legal advice, and never
// promises an outcome. The veteran's own words pass through VERBATIM. Every result
// surfaces the disclaimer, the VSO referral, and — prominently for discharge
// upgrades — the free veterans-law-clinic (legal-aid) referral. Follows the
// Appeals.tsx / Form526.tsx pattern: situation form → API → print handoff.

const HUE: Hue = 'orange'
/** What the print view reads out of sessionStorage (kept local to both files). */
export const CORRECTION_PACKET_KEY = 'vo_correction_packet'

/** Rotating accent so a long stack of process cards doesn't read as one
 * monochrome wall — each card in the list gets the next hue in the cycle. */
const CARD_HUE_CYCLE: Hue[] = ['amber', 'orange', 'rose', 'pink']

/** The five things a veteran might be trying to correct. Discharge-related goals
 * (upgrade / narrative reason / RE code) reveal the discharge follow-ups; the
 * medical-rating goal reveals the PDBR follow-ups. */
const GOALS: { key: CorrectionGoal; label: string; help: string; discharge: boolean }[] = [
  {
    key: 'discharge_upgrade',
    label: 'Upgrade my discharge characterization',
    help: 'e.g. Other Than Honorable → General or Honorable',
    discharge: true,
  },
  {
    key: 'narrative_reason',
    label: 'Change the narrative reason for separation',
    help: 'The stated reason on your DD-214 (e.g. misconduct, personality disorder)',
    discharge: true,
  },
  {
    key: 're_code',
    label: 'Change my reentry (RE) code',
    help: 'The code that affects whether you can re-enlist',
    discharge: true,
  },
  {
    key: 'records_error',
    label: 'Fix an error in my military records',
    help: 'Wrong dates, awards, name, or other DD-214 / record errors',
    discharge: false,
  },
  {
    key: 'medical_rating',
    label: 'Correct a low medical-separation rating',
    help: 'A DoD disability rating you believe was too low when you were separated',
    discharge: false,
  },
]

const TRIGGERS: { key: LiberalTrigger; label: string }[] = [
  { key: 'ptsd', label: 'PTSD' },
  { key: 'tbi', label: 'TBI (traumatic brain injury)' },
  { key: 'mental_health', label: 'Other mental health condition' },
  { key: 'mst', label: 'Military sexual trauma (MST)' },
]

const DISCHARGE_CHARS: { value: string; label: string }[] = [
  { value: '', label: 'Select…' },
  { value: 'honorable', label: 'Honorable' },
  { value: 'general', label: 'General (Under Honorable Conditions)' },
  { value: 'other_than_honorable', label: 'Other Than Honorable (OTH)' },
  { value: 'bad_conduct', label: 'Bad Conduct Discharge' },
  { value: 'dishonorable', label: 'Dishonorable' },
  { value: 'uncharacterized', label: 'Uncharacterized / Entry-Level' },
]

interface WizardState {
  goals: Set<CorrectionGoal>
  years_since_separation: string
  general_court_martial: boolean
  drb_denied: boolean
  related_to: Set<LiberalTrigger>
  medically_separated_2001_2009: boolean
  dod_rating_20_or_less: boolean
  discharge_char: string
}

const EMPTY_WIZARD: WizardState = {
  goals: new Set(),
  years_since_separation: '',
  general_court_martial: false,
  drb_denied: false,
  related_to: new Set(),
  medically_separated_2001_2009: false,
  dod_rating_20_or_less: false,
  discharge_char: '',
}

function toggleInSet<T>(set: Set<T>, key: T): Set<T> {
  const next = new Set(set)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  return next
}

function buildSituation(w: WizardState): CorrectionSituationInput | null {
  if (w.goals.size === 0) return null
  const goals = [...w.goals]
  const isDischarge = goals.some((g) => GOALS.find((x) => x.key === g)?.discharge)
  const isMedical = w.goals.has('medical_rating')
  const years = w.years_since_separation.trim()
  const situation: CorrectionSituationInput = { goals }
  if (isDischarge) {
    if (years !== '' && !Number.isNaN(Number(years))) situation.years_since_separation = Number(years)
    situation.general_court_martial = w.general_court_martial
    situation.drb_denied = w.drb_denied
    if (w.related_to.size > 0) situation.related_to = [...w.related_to]
    if (w.discharge_char) situation.discharge_char = w.discharge_char
  }
  if (isMedical) {
    situation.medically_separated_2001_2009 = w.medically_separated_2001_2009
    situation.dod_rating_20_or_less = w.dod_rating_20_or_less
  }
  return situation
}

export function Corrections() {
  const navigate = useNavigate()
  const { toast } = useToast()

  // Educational KB cards (unchanged from the original page).
  const cardsAsync = useAsync(() => kbApi.cards({ type: 'process', body_system: 'corrections' }))
  const cards = cardsAsync.data ?? []
  const [addedIds, setAddedIds] = useState<Set<string>>(new Set())

  // Wizard state.
  const [w, setW] = useState<WizardState>(EMPTY_WIZARD)
  const [routeResult, setRouteResult] = useState<CorrectionRouteResult | null>(null)
  const [routeLoading, setRouteLoading] = useState(false)
  const [routeError, setRouteError] = useState<string | null>(null)

  // Packet builder state.
  const [applicantName, setApplicantName] = useState('')
  const [corrections, setCorrections] = useState<CorrectionRequestedItem[]>([{ field: '', current: '', requested: '' }])
  const [statement, setStatement] = useState('')
  const [building, setBuilding] = useState(false)

  const dischargeSelected = useMemo(
    () => [...w.goals].some((g) => GOALS.find((x) => x.key === g)?.discharge),
    [w.goals],
  )
  const medicalSelected = w.goals.has('medical_rating')

  const situation = useMemo(() => buildSituation(w), [w])
  const situationKey = situation ? JSON.stringify(situation) : ''

  // Live routing, debounced — recompute the board recommendation whenever the
  // situation changes. Clears out when no goal is selected.
  useEffect(() => {
    if (!situation) {
      setRouteResult(null)
      setRouteError(null)
      setRouteLoading(false)
      return
    }
    let cancelled = false
    setRouteLoading(true)
    const t = setTimeout(async () => {
      try {
        const result = await correctionsApi.route(situation)
        if (!cancelled) {
          setRouteResult(result)
          setRouteError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setRouteResult(null)
          setRouteError(errorMessage(err))
        }
      } finally {
        if (!cancelled) setRouteLoading(false)
      }
    }, 450)
    return () => {
      cancelled = true
      clearTimeout(t)
    }
    // situationKey is the serialized dependency; situation is stable within it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [situationKey])

  const patch = (p: Partial<WizardState>) => setW((prev) => ({ ...prev, ...p }))

  const toggleGoal = (g: CorrectionGoal) => setW((prev) => ({ ...prev, goals: toggleInSet(prev.goals, g) }))
  const toggleTrigger = (t: LiberalTrigger) => setW((prev) => ({ ...prev, related_to: toggleInSet(prev.related_to, t) }))

  const setCorrectionAt = (i: number, field: keyof CorrectionRequestedItem, value: string) =>
    setCorrections((rows) => rows.map((r, j) => (i === j ? { ...r, [field]: value } : r)))
  const addCorrectionRow = () => setCorrections((rows) => [...rows, { field: '', current: '', requested: '' }])
  const removeCorrectionRow = (i: number) =>
    setCorrections((rows) => (rows.length === 1 ? rows : rows.filter((_, j) => j !== i)))

  const addToChecklist = async (card: KbCard) => {
    try {
      await checklistApi.create({ text: `Review: ${card.title}`, category: 'corrections' })
      setAddedIds((prev) => new Set(prev).add(card.id))
      toast('Added to your checklist.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const buildPacket = async () => {
    if (!situation) {
      toast('Pick what you want to correct first.', 'error')
      return
    }
    const cleaned = corrections
      .map((r) => ({
        field: r.field.trim(),
        current: (r.current ?? '').trim() || null,
        requested: (r.requested ?? '').trim() || null,
      }))
      .filter((r) => r.field.length > 0)
    setBuilding(true)
    try {
      const packet = await correctionsApi.draft({
        situation,
        applicant_name: applicantName.trim() || null,
        corrections_requested: cleaned.length > 0 ? cleaned : undefined,
        veteran_statement: statement.trim() || null,
      })
      sessionStorage.setItem(CORRECTION_PACKET_KEY, JSON.stringify(packet))
      navigate('/corrections/print')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBuilding(false)
    }
  }

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)

  return (
    <div
      data-section="records"
      className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          Records &amp; corrections
        </p>
        <h1 className="vo-page-title">Fix your military record</h1>
        <p className="vo-page-sub max-w-[70ch] leading-relaxed">
          Discharge upgrades, DD-214 errors, and low medical-separation ratings go through your{' '}
          <strong className="text-txt">military department's review board</strong> — the DRB, BCMR/BCNR, or PDBR — not
          the VA. Tell Rating Raider what you're trying to fix and it will point you to the right board and form, then
          help you prepare an application to review and sign.
        </p>
      </div>

      {/* Discoverability: officers who stayed the same grade too long may have a
          separate promotion-correction basis — point them to /rank. Hedged copy. */}
      <Link
        to="/rank"
        className="group flex items-center gap-2.5 rounded-control border-l-2 px-4 py-3 text-sm no-underline transition-colors"
        style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
      >
        <Medal size={16} className="shrink-0" style={{ color: ink }} />
        <span className="text-txt">
          Were you an officer who stayed the same rank too long?{' '}
          <span className="font-semibold text-brand group-hover:text-brand-hover">
            Check for a promotion correction →
          </span>
        </span>
      </Link>

      <LegalLaneBanner />

      {/* 3 — Situation form */}
      <Panel hue={HUE} title="What are you trying to correct?" subtitle="Pick everything that applies">
        <div className="space-y-3 p-5">
          <fieldset>
            <legend className="sr-only">What are you trying to correct?</legend>
            <div className="space-y-2">
              {GOALS.map((g) => (
                <Checkbox
                  key={g.key}
                  checked={w.goals.has(g.key)}
                  onChange={() => toggleGoal(g.key)}
                  label={g.label}
                  description={g.help}
                />
              ))}
            </div>
          </fieldset>

          {dischargeSelected && (
            <div
              className="mt-2 space-y-4 rounded-control border p-4"
              style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
            >
              <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: label }}>
                <Scale size={12} /> A few details about the discharge
              </p>

              <label className="block text-sm">
                <span className="vo-label">Years since you separated</span>
                <input
                  type="number"
                  min={0}
                  inputMode="numeric"
                  className="vo-input max-w-[10rem]"
                  value={w.years_since_separation}
                  onChange={(e) => patch({ years_since_separation: e.target.value })}
                  aria-label="Years since you separated from service"
                  placeholder="e.g. 8"
                />
                <span className="mt-1 block text-xs text-faint">
                  The DRB generally reviews discharges within 15 years; after that it's the BCMR/BCNR. This just helps
                  point you to the right board.
                </span>
              </label>

              <Checkbox
                checked={w.general_court_martial}
                onChange={() => patch({ general_court_martial: !w.general_court_martial })}
                label="My discharge was the result of a general court-martial"
                description="General court-martial discharges follow a different review path."
              />

              <Checkbox
                checked={w.drb_denied}
                onChange={() => patch({ drb_denied: !w.drb_denied })}
                label="A Discharge Review Board (DRB) already denied me"
                description="If the DRB already said no, the BCMR/BCNR may be your next step."
              />

              <fieldset>
                <legend className="vo-label mb-1.5">Is this connected to any of these? (optional)</legend>
                <p className="mb-2 text-xs text-muted">
                  Boards give <em>liberal consideration</em> to discharges tied to these — it can change the outcome, so
                  it's worth noting if it applies to you.
                </p>
                <div className="grid gap-2 sm:grid-cols-2">
                  {TRIGGERS.map((t) => (
                    <Checkbox
                      key={t.key}
                      checked={w.related_to.has(t.key)}
                      onChange={() => toggleTrigger(t.key)}
                      label={t.label}
                    />
                  ))}
                </div>
              </fieldset>

              <label className="block text-sm">
                <span className="vo-label">Current discharge characterization</span>
                <select
                  className="vo-input"
                  value={w.discharge_char}
                  onChange={(e) => patch({ discharge_char: e.target.value })}
                  aria-label="Current discharge characterization"
                >
                  {DISCHARGE_CHARS.map((d) => (
                    <option key={d.value} value={d.value}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}

          {medicalSelected && (
            <div
              className="mt-2 space-y-3 rounded-control border p-4"
              style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
            >
              <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: label }}>
                <Landmark size={12} /> About your medical separation
              </p>
              <Checkbox
                checked={w.medically_separated_2001_2009}
                onChange={() => patch({ medically_separated_2001_2009: !w.medically_separated_2001_2009 })}
                label="I was medically separated between 2001 and 2009"
                description="The Physical Disability Board of Review (PDBR) reviews ratings from this window."
              />
              <Checkbox
                checked={w.dod_rating_20_or_less}
                onChange={() => patch({ dod_rating_20_or_less: !w.dod_rating_20_or_less })}
                label="My DoD disability rating was 20% or less"
                description="A low separation rating (vs. medical retirement at 30%+) is what the PDBR looks at."
              />
            </div>
          )}
        </div>
      </Panel>

      {/* 4 — Recommendation panel */}
      <RecommendationPanel
        hasGoals={w.goals.size > 0}
        loading={routeLoading}
        error={routeError}
        result={routeResult}
        dischargeSelected={dischargeSelected}
        ink={ink}
        label={label}
      />

      {/* 5 — Build the packet */}
      {routeResult?.routed && (
        <Panel
          hue={HUE}
          title="Prepare your application to review &amp; sign"
          subtitle="Rating Raider assembles it — you review, sign, and file it with the board"
        >
          <div className="space-y-5 p-5">
            <label className="block text-sm">
              <span className="vo-label">Your full name (optional)</span>
              <input
                className="vo-input"
                value={applicantName}
                onChange={(e) => setApplicantName(e.target.value)}
                aria-label="Your full name"
                placeholder="As it should appear on the application"
              />
            </label>

            <div>
              <p className="vo-label mb-1">What should be corrected?</p>
              <p className="mb-2 text-xs text-muted">
                List each item you want the board to fix — what your record says now, and what it should say.
              </p>
              <div className="space-y-3">
                {corrections.map((row, i) => (
                  <div key={i} className="rounded-control border border-line bg-surface2 p-3">
                    <div className="grid gap-2 sm:grid-cols-3">
                      <label className="block text-sm sm:col-span-3">
                        <span className="sr-only">Field or item to correct (row {i + 1})</span>
                        <input
                          className="vo-input"
                          value={row.field}
                          onChange={(e) => setCorrectionAt(i, 'field', e.target.value)}
                          aria-label={`Field or item to correct, row ${i + 1}`}
                          placeholder="Field / item (e.g. Narrative reason for separation)"
                        />
                      </label>
                      <label className="block text-sm">
                        <span className="sr-only">Current value (row {i + 1})</span>
                        <input
                          className="vo-input"
                          value={row.current ?? ''}
                          onChange={(e) => setCorrectionAt(i, 'current', e.target.value)}
                          aria-label={`Current value, row ${i + 1}`}
                          placeholder="Currently reads…"
                        />
                      </label>
                      <label className="block text-sm">
                        <span className="sr-only">Requested value (row {i + 1})</span>
                        <input
                          className="vo-input"
                          value={row.requested ?? ''}
                          onChange={(e) => setCorrectionAt(i, 'requested', e.target.value)}
                          aria-label={`Requested value, row ${i + 1}`}
                          placeholder="Should read…"
                        />
                      </label>
                      <div className="flex items-center justify-end sm:col-span-1 sm:col-start-3">
                        <button
                          type="button"
                          onClick={() => removeCorrectionRow(i)}
                          disabled={corrections.length === 1}
                          className="vo-btn border border-line bg-surface text-xs text-muted hover:border-line2 disabled:opacity-40"
                          aria-label={`Remove correction row ${i + 1}`}
                        >
                          <Trash2 size={13} /> Remove
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <button
                type="button"
                onClick={addCorrectionRow}
                className="vo-btn mt-2 border border-line bg-surface2 text-xs text-txt hover:border-line2"
              >
                <Plus size={13} /> Add another correction
              </button>
            </div>

            <label className="block text-sm">
              <span className="vo-label">Your statement — in your own words</span>
              <textarea
                className="vo-input min-h-[160px] resize-y leading-relaxed"
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
                aria-label="Your statement, in your own words"
                placeholder={
                  'Tell the board, in your own words, what happened and why the record should be corrected — the error ' +
                  'or injustice, the circumstances, and how it has affected you. This goes onto the application exactly ' +
                  'as you write it.'
                }
              />
              <span className="mt-1 flex items-start gap-1.5 text-xs text-faint">
                <Info size={12} className="mt-0.5 shrink-0" />
                Your words go in <strong className="not-italic">verbatim</strong> — never rewritten, softened, or
                summarized. Keep it true and first-hand.
              </span>
            </label>

            <div className="flex flex-col items-center gap-2 pt-1">
              <button onClick={buildPacket} disabled={building} className="vo-btn-primary">
                {building ? <Spinner size={16} className="text-white" /> : <Printer size={16} />}
                Build my application to review &amp; sign
              </button>
              <p className="text-xs text-faint">
                Opens a clean, letterhead draft. You review it, sign it, and file it with the board — Veteran-Ops
                never files anything.
              </p>
            </div>
          </div>
        </Panel>
      )}

      {/* 6 — Educational KB cards (kept) */}
      <div className="pt-2">
        <div className="mb-3">
          <h2 className="text-heading text-txt">Learn how corrections work</h2>
          <p className="text-sm text-muted">
            Background on DRB discharge review, BCMR/BCNR, liberal consideration, and how corrections issue.
          </p>
        </div>
        {cardsAsync.loading ? (
          <LoadingBlock label="Loading corrections guide…" />
        ) : cardsAsync.error ? (
          <ErrorBlock message={cardsAsync.error} onRetry={cardsAsync.reload} />
        ) : cards.length === 0 ? (
          <EmptyState
            icon={<ScrollText size={20} />}
            title="Corrections guide coming soon"
            description="This guide (DRB discharge review, BCMR/BCNR, liberal consideration, and how corrections issue) is being written. Check back soon, or ask a VSO in the meantime."
          />
        ) : (
          <>
            <SectionNav
              items={cards.map((card, i) => {
                const { headline } = splitFormNumber(card.title)
                return { id: `corr-${card.id}`, label: headline, hue: CARD_HUE_CYCLE[i % CARD_HUE_CYCLE.length] }
              })}
            />
            <div className="mt-3 space-y-4">
              {cards.map((card, i) => {
                const { code, headline } = splitFormNumber(card.title)
                const added = addedIds.has(card.id)
                const hue = CARD_HUE_CYCLE[i % CARD_HUE_CYCLE.length]
                return (
                  <article
                    key={card.id}
                    id={`corr-${card.id}`}
                    className="vo-panel vo-accent scroll-mt-24 overflow-hidden"
                    style={hueStyle(hue) as CSSProperties}
                  >
                    <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
                      <div className="flex min-w-0 items-center gap-2.5">
                        {code && (
                          <span
                            className="shrink-0 rounded-md border px-2 py-1 font-mono text-xs font-bold tracking-wide"
                            style={{
                              borderColor: `color-mix(in srgb, ${hueVar(hue)} 40%, transparent)`,
                              background: hueSoftVar(hue),
                              color: hueInk(hue),
                            }}
                          >
                            {code}
                          </span>
                        )}
                        <h2 className="truncate text-[15px] font-semibold text-txt">{headline}</h2>
                      </div>
                      <button
                        onClick={() => void addToChecklist(card)}
                        disabled={added}
                        className={`vo-btn text-xs transition-all ${
                          added
                            ? 'border border-success/40 bg-h-emerald-soft text-success'
                            : 'border border-line bg-surface2 text-txt hover:border-line2'
                        }`}
                      >
                        {added ? <Check size={13} /> : <ListChecks size={13} />}
                        {added ? 'Added to checklist' : 'Add to checklist'}
                      </button>
                    </header>
                    <div
                      className="vo-prose max-w-[70ch] p-5"
                      dangerouslySetInnerHTML={{ __html: renderContent(card.content) }}
                    />
                    {card.source && (
                      <footer className="flex items-center gap-1.5 border-t border-line px-5 py-3">
                        <Quote size={11} className="shrink-0 text-faint" />
                        <span className="vo-chip border-none bg-transparent px-0 py-0 text-faint">{card.source}</span>
                      </footer>
                    )}
                  </article>
                )
              })}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/** Recommendation panel — which military board + form fits the situation, with
 * the liberal-consideration (MST/PTSD) path highlighted, deadline caveats, and
 * the disclaimer + VSO + legal-aid referrals surfaced on every result. */
function RecommendationPanel({
  hasGoals,
  loading,
  error,
  result,
  dischargeSelected,
  ink,
  label,
}: {
  hasGoals: boolean
  loading: boolean
  error: string | null
  result: CorrectionRouteResult | null
  dischargeSelected: boolean
  ink: string
  label: string
}) {
  if (!hasGoals) {
    return (
      <Panel hue={HUE}>
        <EmptyState
          hue={HUE}
          icon={<Landmark size={22} />}
          title="Pick what you want to correct"
          description="Choose one or more items above and Rating Raider will point you to the right military review board and application form."
        />
      </Panel>
    )
  }
  if (error) {
    return (
      <div className="p-1">
        <ErrorBlock message={error} />
      </div>
    )
  }
  if (loading && !result) {
    return <LoadingBlock label="Finding the right board for you…" />
  }
  if (!result) return null

  return (
    <Panel
      hue={HUE}
      title="Where this goes"
      subtitle={result.routed ? 'The board and form that fit your situation' : 'A little more to narrow it down'}
    >
      <div className="space-y-4 p-5">
        {result.routed ? (
          <>
            <div
              className="rounded-control border p-4"
              style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
            >
              <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: label }}>
                File with
              </p>
              <p className="mt-0.5 text-lg font-bold text-txt">{result.board_full ?? result.board}</p>
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

            {result.why && <p className="text-sm leading-relaxed text-txt">{result.why}</p>}

            {result.liberal_consideration?.applies && result.liberal_consideration.note && (
              <div
                className="flex items-start gap-2.5 rounded-control border p-4"
                style={{ borderColor: hueVar('violet'), background: hueSoftVar('violet') }}
              >
                <Lightbulb size={16} className="mt-0.5 shrink-0" style={{ color: hueInk('violet') }} />
                <div>
                  <p className="text-sm font-semibold text-txt">Liberal consideration may apply to you</p>
                  <p className="mt-1 text-sm leading-relaxed text-muted">{result.liberal_consideration.note}</p>
                </div>
              </div>
            )}

            {result.character_of_discharge_note && (
              <p className="flex items-start gap-2 text-sm text-muted">
                <Info size={14} className="mt-0.5 shrink-0" style={{ color: ink }} />
                <span>{result.character_of_discharge_note}</span>
              </p>
            )}

            {result.deadline_note && (
              <p className="flex items-start gap-2 text-sm text-txt">
                <AlertTriangle size={14} className="mt-0.5 shrink-0" style={{ color: ink }} />
                <span>{result.deadline_note}</span>
              </p>
            )}

            {result.warnings?.length > 0 && (
              <ul className="space-y-2">
                {result.warnings.map((wn, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 rounded-control border p-3 text-sm text-txt"
                    style={{ borderColor: hueVar('rose'), background: hueSoftVar('rose') }}
                  >
                    <AlertTriangle size={14} className="mt-0.5 shrink-0" style={{ color: hueInk('rose') }} />
                    <span>{wn}</span>
                  </li>
                ))}
              </ul>
            )}

            {result.also_consider?.length > 0 && (
              <div>
                <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: label }}>
                  You may also consider
                </p>
                <ul className="space-y-2">
                  {result.also_consider.map((a, i) => (
                    <li key={i} className="rounded-control border border-line bg-surface2 p-3 text-sm">
                      <span className="font-semibold text-txt">{a.board}</span>
                      {a.form && <span className="ml-1.5 font-mono text-xs text-muted">{a.form}</span>}
                      {a.when && <span className="mt-0.5 block text-xs text-muted">{a.when}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <p className="flex items-start gap-2 text-sm leading-relaxed text-muted">
            <Info size={15} className="mt-0.5 shrink-0" style={{ color: ink }} />
            <span>{result.why || 'Tell us a bit more about what you want to correct so we can point you to the right board.'}</span>
          </p>
        )}

        {/* Referrals — surfaced on EVERY result. Legal aid is elevated for
            discharge-upgrade paths (free veterans law clinics). */}
        <div className="space-y-3 border-t border-line pt-4">
          {dischargeSelected && result.legal_aid_referral && (
            <div
              className="flex items-start gap-2.5 rounded-control border p-4"
              style={{ borderColor: hueVar('emerald'), background: hueSoftVar('emerald') }}
            >
              <Scale size={16} className="mt-0.5 shrink-0" style={{ color: hueInk('emerald') }} />
              <div>
                <p className="text-sm font-semibold text-txt">Free legal help for discharge upgrades</p>
                <p className="mt-1 text-sm leading-relaxed text-muted">{result.legal_aid_referral}</p>
              </div>
            </div>
          )}
          {!dischargeSelected && result.legal_aid_referral && (
            <p className="text-sm leading-relaxed text-muted">{result.legal_aid_referral}</p>
          )}
          {result.vso_referral && <p className="text-sm leading-relaxed text-muted">{result.vso_referral}</p>}
          {result.source && (
            <p className="flex items-center gap-1.5 text-xs text-faint">
              <Quote size={11} className="shrink-0" /> {result.source}
            </p>
          )}
          {result.disclaimer && <p className="text-xs italic leading-relaxed text-faint">{result.disclaimer}</p>}
        </div>
      </div>
    </Panel>
  )
}

/** Prominent legal-lane note for this sensitive lane (discharge upgrades, MST):
 * educational self-help only, you file with a MILITARY board (not the VA), and
 * free veterans-law clinics take discharge-upgrade cases at no cost. */
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
        <Gavel size={20} />
      </div>
      <div>
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-txt">
          <ShieldCheck size={15} style={{ color: hueInk(HUE) }} /> Educational self-help — you file with a military
          board, not the VA
        </h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          Veteran-Ops is educational self-help software — not a lawyer, not a VA-accredited representative. It does
          not give legal advice, file anything for you, or promise an outcome. A records correction or discharge upgrade
          is decided by your <strong className="text-txt">military department's review board</strong> (DRB, BCMR/BCNR,
          or PDBR) — not the VA. It assembles an application from what you tell it, in your own words, for you to review
          and sign.
        </p>
        <p className="mt-2 flex items-start gap-1.5 text-sm leading-relaxed text-txt">
          <Scale size={14} className="mt-0.5 shrink-0" style={{ color: hueInk(HUE) }} />
          <span>
            <strong>Discharge upgrades can be hard to win on your own.</strong> Free veterans law clinics and
            accredited VSOs take these cases at no cost — talk to one before you file.
          </span>
        </p>
        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1.5">
          <a
            href="https://www.va.gov/get-help-from-accredited-representative/"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
          >
            Find a VSO near you <ExternalLink size={13} />
          </a>
          <a
            href="https://www.va.gov/ogc/apps/accreditation/index.asp"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
          >
            Find free veterans legal help <ExternalLink size={13} />
          </a>
        </div>
        <p className="mt-2 flex items-start gap-1.5 text-xs text-faint">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" /> If your case involves MST or a mental-health
          condition, boards give it liberal consideration — a VSO or clinic can help you make that case.
        </p>
      </div>
    </div>
  )
}

/** Slim sticky anchor-nav — one chip per process card below, hued to match
 * (targets carry scroll-mt-24 to clear the shared Shell topbar). */
function SectionNav({ items }: { items: { id: string; label: string; hue: Hue }[] }) {
  return (
    <nav
      aria-label="Jump to section"
      className="vo-no-print sticky top-16 z-30 -mx-1 flex flex-wrap gap-1.5 rounded-full border border-line bg-surface/90 px-2 py-1.5 backdrop-blur"
    >
      {items.map((it) => (
        <a key={it.id} href={`#${it.id}`} className="vo-chip-hue no-underline" style={hueStyle(it.hue) as CSSProperties}>
          {it.label}
        </a>
      ))}
    </nav>
  )
}

/** KB card titles are often authored as "DD-149: Application for Correction of
 * Military Record" — pull the form number out as a badge and keep the rest as
 * the headline. Falls back to the plain title if no code is found. */
function splitFormNumber(title: string): { code: string | null; headline: string } {
  const m = title.match(/^\s*((?:DD|VA)[\s-]?(?:Form\s*)?\d[\w-]*)\s*[:\-–—]\s*(.+)$/i)
  if (!m) return { code: null, headline: title }
  return { code: m[1].toUpperCase().replace(/\s+/g, ' '), headline: m[2].trim() }
}

/** Same defensive markdown-ish renderer as Filing.tsx — no markdown dependency. */
function renderContent(content: string): string {
  const escaped = content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return escaped
    .split(/\n{2,}/)
    .map((p) => `<p>${p.replace(/\n/g, '<br/>')}</p>`)
    .join('')
}
