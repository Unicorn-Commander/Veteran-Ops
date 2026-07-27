import {
  Ban,
  ClipboardList,
  Copy,
  ExternalLink,
  HeartHandshake,
  Lightbulb,
  ListChecks,
  Printer,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ErrorBlock, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { buddyApi } from '../lib/api'
import { hueInk, hueLabel, hueStyle, hueSoftVar, hueVar, type Hue } from '../lib/hues'
import type {
  BuddyDraft,
  BuddyDraftInput,
  BuddyGuidance,
  BuddySituationBrief,
} from '../types'

// /buddy — WAVE5-SPEC F4. VA Form 21-10210 (Lay/Witness Statement) builder.
// A buddy statement is powerful LAY EVIDENCE (38 CFR §3.159(a)(2); Layno v.
// Brown) — but the WITNESS reviews it, edits it into their own words, and
// SIGNS it. Veteran-Ops never fabricates, never signs, never submits.
// Endpoint shapes reconciled against backend/app/routers/buddy.py (routers are
// truth). Follows the Records.tsx builder + RecordsPrintViews print pattern.

const HUE: Hue = 'orange'
export const BUDDY_DRAFT_KEY = 'vo_buddy_draft'

/** What the print view reads out of sessionStorage. */
export interface BuddyPrintState {
  draft: BuddyDraft
  inputs: BuddyDraftInput
}

export function Buddy() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { toast } = useToast()
  const { data: guidance, error: guidanceError } = useAsync(() => buddyApi.guidance())

  const [witnessName, setWitnessName] = useState('')
  const [relationship, setRelationship] = useState('')
  const [veteranName, setVeteranName] = useState('')
  const [condition, setCondition] = useState('')
  const [period, setPeriod] = useState('')
  const [observations, setObservations] = useState('')
  /** Prefill for SituationBriefSection from Claim Plan reclaim deep-links. */
  const [briefPrefill, setBriefPrefill] = useState<{
    condition?: string
    period?: string
    veteranName?: string
    themes?: string
    facts?: string
    open?: boolean
    autoGenerate?: boolean
  } | null>(null)

  const [draft, setDraft] = useState<BuddyDraft | null>(null)
  const [building, setBuilding] = useState(false)

  // Claim Plan reclaim links: /buddy?condition=…&brief=1&themes=…&period=…&veteran=…
  useEffect(() => {
    const cond = searchParams.get('condition')?.trim()
    const per = searchParams.get('period')?.trim()
    const vet =
      searchParams.get('veteran')?.trim() ||
      searchParams.get('veteran_name')?.trim()
    const themes = searchParams.get('themes')?.trim()
    const facts = searchParams.get('facts')?.trim()
    const brief = searchParams.get('brief') === '1'
    if (!cond && !brief && !per && !vet && !themes && !facts) return

    // Also prefill the main draft builder condition/period/veteran when present.
    if (cond) setCondition(cond)
    if (per) setPeriod(per)
    if (vet) setVeteranName(vet)

    if (brief || cond) {
      setBriefPrefill({
        condition: cond || undefined,
        period: per || undefined,
        veteranName: vet || undefined,
        themes: themes || undefined,
        facts: facts || undefined,
        open: brief,
        autoGenerate: Boolean(brief && cond),
      })
    }

    // Consume query so refresh doesn't re-apply over user edits.
    const next = new URLSearchParams(searchParams)
    for (const k of ['condition', 'period', 'veteran', 'veteran_name', 'themes', 'facts', 'brief']) {
      next.delete(k)
    }
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  const inputs: BuddyDraftInput | null = useMemo(() => {
    if (!witnessName.trim() || !relationship.trim() || !observations.trim()) return null
    return {
      witness_name: witnessName.trim(),
      witness_relationship: relationship.trim(),
      veteran_name: veteranName.trim() || null,
      condition: condition.trim() || null,
      observations: observations.trim(),
      period: period.trim() || null,
    }
  }, [witnessName, relationship, veteranName, condition, period, observations])

  // Debounced live preview: regenerate the draft as the required fields fill in.
  useEffect(() => {
    if (!inputs) {
      setDraft(null)
      return
    }
    let cancelled = false
    const timer = setTimeout(() => {
      setBuilding(true)
      buddyApi
        .draft(inputs)
        .then((d) => {
          if (!cancelled) setDraft(d)
        })
        .catch((err) => {
          if (!cancelled) toast(errorMessage(err), 'error')
        })
        .finally(() => {
          if (!cancelled) setBuilding(false)
        })
    }, 400)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [inputs, toast])

  const goToPrint = (e: FormEvent) => {
    e.preventDefault()
    if (!inputs) {
      toast('Fill in the witness name, relationship, and what they observed first.', 'error')
      return
    }
    if (!draft) {
      toast('Give the preview a moment to build, then try again.', 'error')
      return
    }
    const state: BuddyPrintState = { draft, inputs }
    sessionStorage.setItem(BUDDY_DRAFT_KEY, JSON.stringify(state))
    navigate('/buddy/print')
  }

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)

  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6" style={hueStyle(HUE) as CSSProperties}>
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          {guidance?.form ?? 'VA Form 21-10210'} · Lay/Witness statement
        </p>
        <h1 className="vo-page-title">Buddy statement builder</h1>
        <p className="vo-page-sub">
          A statement from someone who saw what you went through is powerful evidence VA must weigh. Rating Raider drafts
          it from your notes — then the witness reads it, puts it in their own words, and signs it.
        </p>
      </div>

      <LegalLaneBanner />

      {guidanceError && !guidance && <ErrorBlock message={guidanceError} />}
      {guidance && <GuidancePanel guidance={guidance} ink={ink} label={label} />}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        <Panel hue={HUE} title="Draft the statement" subtitle="Only what the witness personally saw — no guessing">
          <form onSubmit={goToPrint} className="space-y-4 p-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm">
                <span className="vo-label">Witness full name *</span>
                <input
                  className="vo-input"
                  value={witnessName}
                  onChange={(e) => setWitnessName(e.target.value)}
                  placeholder="e.g. Maria Vega"
                  required
                />
              </label>
              <label className="text-sm">
                <span className="vo-label">Relationship to you *</span>
                <input
                  className="vo-input"
                  value={relationship}
                  onChange={(e) => setRelationship(e.target.value)}
                  placeholder="e.g. spouse, squad leader, coworker"
                  required
                />
              </label>
              <label className="text-sm">
                <span className="vo-label">Veteran's name (optional)</span>
                <input
                  className="vo-input"
                  value={veteranName}
                  onChange={(e) => setVeteranName(e.target.value)}
                  placeholder="Your name, as the witness refers to you"
                />
              </label>
              <label className="text-sm">
                <span className="vo-label">Condition it's about (optional)</span>
                <input
                  className="vo-input"
                  value={condition}
                  onChange={(e) => setCondition(e.target.value)}
                  placeholder="e.g. PTSD, right knee, back pain"
                />
              </label>
              <label className="text-sm sm:col-span-2">
                <span className="vo-label">When / how often (optional)</span>
                <input
                  className="vo-input"
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                  placeholder="e.g. from 2019 to the present; about twice a week"
                />
              </label>
            </div>
            <label className="block text-sm">
              <span className="vo-label">What the witness personally observed *</span>
              <textarea
                className="vo-input min-h-[160px] resize-y leading-relaxed"
                value={observations}
                onChange={(e) => setObservations(e.target.value)}
                placeholder={
                  'Concrete, first-hand specifics — what they saw, heard, or experienced, with dates and examples. ' +
                  'e.g. "Since 2019 I\'ve seen him wake up screaming most nights and grip the railing on every set of stairs."'
                }
                required
              />
              <span className="mt-1 block text-xs text-faint">
                First-hand only. No diagnoses or opinions — just what the witness actually saw.
              </span>
            </label>

            <button type="submit" disabled={!inputs || !draft} className="vo-btn-primary">
              {building ? <Spinner size={16} className="text-white" /> : <Printer size={15} />}
              Print / save as PDF
            </button>
            {inputs && draft && !building && (
              <p className="flex items-center gap-1.5 text-xs text-faint">
                <Sparkles size={12} style={{ color: ink }} /> Opens a clean, print-ready page the witness signs.
              </p>
            )}
          </form>
        </Panel>

        <Panel hue={HUE} title="Live preview" subtitle="The witness edits this into their own words before signing">
          <div className="p-5">
            {draft ? (
              <div className="whitespace-pre-wrap rounded-control border border-line bg-surface2 p-5 text-sm leading-relaxed text-txt">
                {draft.statement_markdown}
              </div>
            ) : (
              <div className="flex min-h-[220px] flex-col items-center justify-center rounded-control border border-dashed border-line2 p-6 text-center">
                <ShieldCheck size={26} className="mb-2 text-faint" />
                <p className="text-sm text-muted">
                  Fill in the witness name, their relationship to you, and what they observed — the draft appears here as
                  you type.
                </p>
              </div>
            )}
            {draft && draft.guidance.length > 0 && (
              <div className="mt-4 rounded-control border p-4" style={{ borderColor: `color-mix(in srgb, ${hueVar(HUE)} 30%, var(--border))`, background: hueSoftVar(HUE) }}>
                <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                  <ListChecks size={13} /> Before the witness signs
                </p>
                <ul className="mt-2 space-y-1.5 text-xs text-muted">
                  {draft.guidance.map((g, i) => (
                    <li key={i} className="flex gap-2">
                      <span aria-hidden style={{ color: ink }}>•</span>
                      <span className="leading-relaxed">{g}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Panel>
      </div>

      <SituationBriefSection ink={ink} label={label} prefill={briefPrefill} />
    </div>
  )
}

/** Split comma / newline lists into trimmed non-empty tokens. */
function splitList(raw: string): string[] {
  return raw
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

/** Case-aware points-to-hit brief. Witness still owns the words and signs. */
function SituationBriefSection({
  ink,
  label,
  prefill,
}: {
  ink: string
  label: string
  prefill?: {
    condition?: string
    period?: string
    veteranName?: string
    themes?: string
    facts?: string
    open?: boolean
    autoGenerate?: boolean
  } | null
}) {
  const { toast } = useToast()
  const [condition, setCondition] = useState('')
  const [veteranName, setVeteranName] = useState('')
  const [period, setPeriod] = useState('')
  const [themesRaw, setThemesRaw] = useState('')
  const [factsRaw, setFactsRaw] = useState('')
  const [brief, setBrief] = useState<BuddySituationBrief | null>(null)
  const [loading, setLoading] = useState(false)
  const autoGenRef = useRef(false)

  const themeChips = useMemo(() => splitList(themesRaw), [themesRaw])

  // Apply Claim Plan reclaim deep-link once.
  useEffect(() => {
    if (!prefill) return
    if (prefill.condition) setCondition(prefill.condition)
    if (prefill.period) setPeriod(prefill.period)
    if (prefill.veteranName) setVeteranName(prefill.veteranName)
    if (prefill.themes) setThemesRaw(prefill.themes.replace(/\+/g, ' '))
    if (prefill.facts) setFactsRaw(prefill.facts.replace(/\+/g, ' '))
    if (prefill.open) {
      requestAnimationFrame(() => {
        document.getElementById('situation-brief')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      })
    }
  }, [prefill])

  // Single-shot auto-generate when deep-linked with condition + brief=1.
  useEffect(() => {
    if (!prefill?.autoGenerate || !prefill.condition || autoGenRef.current) return
    autoGenRef.current = true
    const cond = prefill.condition.trim()
    if (!cond) return
    setLoading(true)
    buddyApi
      .situationBrief({
        condition: cond,
        veteran_name: (prefill.veteranName || '').trim() || null,
        period: (prefill.period || '').trim() || null,
        themes: splitList((prefill.themes || '').replace(/\+/g, ' ')),
        known_facts: splitList((prefill.facts || '').replace(/\+/g, ' ')),
      })
      .then((b) => setBrief(b))
      .catch((err) => toast(errorMessage(err), 'error'))
      .finally(() => setLoading(false))
  }, [prefill, toast])

  const generate = (e: FormEvent) => {
    e.preventDefault()
    if (!condition.trim()) {
      toast('Enter the condition the statement is about.', 'error')
      return
    }
    setLoading(true)
    buddyApi
      .situationBrief({
        condition: condition.trim(),
        veteran_name: veteranName.trim() || null,
        period: period.trim() || null,
        themes: splitList(themesRaw),
        known_facts: splitList(factsRaw),
      })
      .then((b) => setBrief(b))
      .catch((err) => toast(errorMessage(err), 'error'))
      .finally(() => setLoading(false))
  }

  const copyAll = async () => {
    if (!brief) return
    const parts = [
      brief.starter_outline,
      '',
      '## Points to hit (first-hand only)',
      ...brief.hit_list.map((h, i) => `${i + 1}. ${h}`),
      '',
      '## Avoid',
      ...brief.avoid.map((a) => `• ${a}`),
      '',
      brief.disclaimer,
    ]
    const ok = await copyText(parts.join('\n'))
    toast(
      ok ? 'Brief copied — witness still owns the words and signs.' : 'Could not copy. Select the text manually.',
      ok ? 'success' : 'error',
    )
  }

  return (
    <div id="situation-brief" className="scroll-mt-24">
    <Panel
      hue={HUE}
      title="Situation brief"
      subtitle="Points to hit in the witness’s own words — not a finished statement"
      action={
        brief ? (
          <button type="button" onClick={() => void copyAll()} className="vo-btn-secondary text-xs">
            <Copy size={12} /> Copy all
          </button>
        ) : undefined
      }
    >
      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        <form onSubmit={generate} className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm sm:col-span-2">
              <span className="vo-label">Condition *</span>
              <input
                className="vo-input"
                value={condition}
                onChange={(e) => setCondition(e.target.value)}
                placeholder="e.g. PTSD, right knee, tinnitus"
                required
              />
            </label>
            <label className="text-sm">
              <span className="vo-label">Veteran’s name (optional)</span>
              <input
                className="vo-input"
                value={veteranName}
                onChange={(e) => setVeteranName(e.target.value)}
                placeholder="How the witness should refer to you"
              />
            </label>
            <label className="text-sm">
              <span className="vo-label">Period focus (optional)</span>
              <input
                className="vo-input"
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                placeholder="e.g. since 2019; about twice a week"
              />
            </label>
          </div>
          <label className="block text-sm">
            <span className="vo-label">Themes to cover (optional)</span>
            <input
              className="vo-input"
              value={themesRaw}
              onChange={(e) => setThemesRaw(e.target.value)}
              placeholder="Comma-separated — e.g. sleep, stairs, missed work"
            />
            {themeChips.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {themeChips.map((t) => (
                  <span key={t} className="vo-chip border-line bg-surface2 text-xs text-muted">
                    {t}
                  </span>
                ))}
              </div>
            )}
            <span className="mt-1 block text-xs text-faint">
              Leave blank for default first-hand themes (change after service, concrete examples, frequency, daily impact).
            </span>
          </label>
          <label className="block text-sm">
            <span className="vo-label">Known facts the witness may confirm (optional)</span>
            <textarea
              className="vo-input min-h-[80px] resize-y leading-relaxed"
              value={factsRaw}
              onChange={(e) => setFactsRaw(e.target.value)}
              placeholder={
                'One per line or comma-separated. Only if the witness personally saw it — e.g. "wakes screaming most nights," "needs railing on every staircase."'
              }
            />
            <span className="mt-1 block text-xs text-faint">
              Briefed as “only if you saw it — put it in your own words or drop it.” Never invents observations.
            </span>
          </label>
          <button type="submit" disabled={loading || !condition.trim()} className="vo-btn-primary">
            {loading ? <Spinner size={16} className="text-white" /> : <ClipboardList size={15} />}
            Generate situation brief
          </button>
          <p className="text-xs leading-relaxed text-faint">
            Legal lane: this is a checklist. The <strong className="font-semibold text-muted">witness</strong> writes,
            edits into their own words, and <strong className="font-semibold text-muted">signs</strong>. Rating Raider
            never signs or submits for anyone.
          </p>
        </form>

        <div>
          {brief ? (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
                  {brief.form} · {brief.condition}
                </p>
                <a
                  href={brief.form_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-brand hover:text-brand-hover"
                >
                  Official form <ExternalLink size={12} />
                </a>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                    <ListChecks size={13} /> Hit list
                  </p>
                  <button
                    type="button"
                    className="vo-btn-ghost text-[11px]"
                    onClick={() =>
                      void copyText(brief.hit_list.map((h, i) => `${i + 1}. ${h}`).join('\n')).then((ok) =>
                        toast(ok ? 'Hit list copied.' : 'Could not copy.', ok ? 'success' : 'error'),
                      )
                    }
                  >
                    <Copy size={11} /> Copy
                  </button>
                </div>
                <ol className="space-y-2 text-sm text-txt">
                  {brief.hit_list.map((h, i) => (
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
                </ol>
              </div>

              <div className="rounded-control border border-[color-mix(in_oklab,var(--danger)_30%,transparent)] bg-danger-soft p-4">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 text-xs font-semibold text-danger">
                    <Ban size={13} /> Avoid
                  </p>
                  <button
                    type="button"
                    className="vo-btn-ghost text-[11px]"
                    onClick={() =>
                      void copyText(brief.avoid.map((a) => `• ${a}`).join('\n')).then((ok) =>
                        toast(ok ? 'Avoid list copied.' : 'Could not copy.', ok ? 'success' : 'error'),
                      )
                    }
                  >
                    <Copy size={11} /> Copy
                  </button>
                </div>
                <ul className="space-y-1.5 text-xs text-muted">
                  {brief.avoid.map((a, i) => (
                    <li key={i} className="flex gap-2">
                      <span aria-hidden className="text-danger">
                        •
                      </span>
                      <span className="leading-relaxed">{a}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                    <Lightbulb size={13} /> Starter outline
                  </p>
                  <button
                    type="button"
                    className="vo-btn-ghost text-[11px]"
                    onClick={() =>
                      void copyText(brief.starter_outline).then((ok) =>
                        toast(ok ? 'Outline copied.' : 'Could not copy.', ok ? 'success' : 'error'),
                      )
                    }
                  >
                    <Copy size={11} /> Copy
                  </button>
                </div>
                <div className="whitespace-pre-wrap rounded-control border border-line bg-surface2 p-4 text-sm leading-relaxed text-txt">
                  {brief.starter_outline}
                </div>
              </div>

              <p className="text-xs italic leading-relaxed text-faint">{brief.disclaimer}</p>
            </div>
          ) : (
            <div className="flex min-h-[220px] flex-col items-center justify-center rounded-control border border-dashed border-line2 p-6 text-center">
              <ClipboardList size={26} className="mb-2 text-faint" />
              <p className="text-sm text-muted">
                Enter a condition and generate a first-hand hit list the witness can use while writing — then they edit
                and sign in their own words.
              </p>
            </div>
          )}
        </div>
      </div>
    </Panel>
    </div>
  )
}

/** Prominent legal-lane note: the witness signs it, you never submit it for
 * them, and a VSO can help for free. */
function LegalLaneBanner() {
  return (
    <div
      className="vo-card vo-accent relative flex items-start gap-3.5 overflow-hidden p-5"
      style={hueStyle('orange') as CSSProperties}
    >
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar('orange'), color: hueInk('orange') }}
      >
        <HeartHandshake size={20} />
      </div>
      <div>
        <h2 className="text-sm font-semibold text-txt">The witness signs it — you never submit it for them</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          This is a draft the witness reads, edits into their own words, and signs. It has to be first-hand and true —
          never exaggerated or invented. You (or a VA-accredited VSO) then attach it to your claim as evidence. A VSO —
          VFW, DAV, The American Legion, or your state/county veterans office — can help you file it for free.
        </p>
        <a
          href="https://www.va.gov/get-help-from-accredited-representative/"
          target="_blank"
          rel="noreferrer"
          className="mt-2.5 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
        >
          Find a VSO near you <ExternalLink size={13} />
        </a>
      </div>
    </div>
  )
}

function GuidancePanel({
  guidance,
  ink,
  label,
}: {
  guidance: BuddyGuidance
  ink: string
  label: string
}) {
  return (
    <Panel hue={HUE} title="What makes a strong statement" subtitle={`${guidance.form} — ${guidance.form_title}`}
      action={
        <a
          href={guidance.form_url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-xs font-semibold text-brand hover:text-brand-hover"
        >
          Official form <ExternalLink size={12} />
        </a>
      }
    >
      <div className="grid gap-5 p-5 sm:grid-cols-2">
        <div>
          <p className="mb-2.5 text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
            What to cover
          </p>
          <ul className="space-y-2 text-sm text-txt">
            {guidance.prompts.map((p, i) => (
              <li key={i} className="flex gap-2.5">
                <span
                  aria-hidden
                  className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                  style={{ background: hueSoftVar(HUE), color: ink }}
                >
                  {i + 1}
                </span>
                <span className="leading-relaxed">{p}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="mb-2.5 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
            <Lightbulb size={12} /> How to write it
          </p>
          <ul className="space-y-2 text-sm text-txt">
            {guidance.tips.map((t, i) => (
              <li key={i} className="flex gap-2.5">
                <span aria-hidden className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: ink }} />
                <span className="leading-relaxed">{t}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="mx-5 mb-5 rounded-control border-l-2 px-3 py-2 text-xs italic leading-relaxed text-faint" style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}>
        {guidance.disclaimer}
      </div>
    </Panel>
  )
}
