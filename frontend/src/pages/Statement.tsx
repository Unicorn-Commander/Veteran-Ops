import { ExternalLink, FileSignature, Lightbulb, ListChecks, Printer, ShieldCheck, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ErrorBlock, Panel, Spinner } from '../components/ui'
import { FilledFormPanel } from '../components/FilledFormPanel'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { statementApi } from '../lib/api'
import { hueInk, hueLabel, hueStyle, hueSoftVar, hueVar, type Hue } from '../lib/hues'
import type { StatementDraft, StatementDraftInput, StatementGuidance } from '../types'

// /statement — WAVE6-SPEC F3. VA Form 21-4138 (Statement in Support of Claim)
// builder. This is the veteran's OWN sworn statement — the narrative the
// records don't show (an in-service event/stressor, why records are missing,
// how the condition affects daily life). Rating Raider FORMATS the veteran's
// own words (verbatim) into a clean 21-4138-style page they review, sign, and
// submit. It never reworders, never fabricates, never signs, never files.
// Endpoint shapes reconciled against backend/app/routers/statement.py (routers
// are truth). Follows the Buddy.tsx builder + BuddyPrint print pattern.

const HUE: Hue = 'amber'
export const STATEMENT_DRAFT_KEY = 'vo_statement_draft'

/** What the print view reads out of sessionStorage. */
export interface StatementPrintState {
  draft: StatementDraft
  inputs: StatementDraftInput
}

export function Statement() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data: guidance, error: guidanceError } = useAsync(() => statementApi.guidance())

  const [veteranName, setVeteranName] = useState('')
  const [topic, setTopic] = useState('')
  const [condition, setCondition] = useState('')
  const [period, setPeriod] = useState('')
  const [statement, setStatement] = useState('')

  const [draft, setDraft] = useState<StatementDraft | null>(null)
  const [building, setBuilding] = useState(false)

  // Assisted drafting — proposes a first-person draft from the veteran's OWN recorded
  // facts + condition prompts; fills the editable textarea so they revise + adopt + attest.
  const [assisting, setAssisting] = useState(false)
  const [prompts, setPrompts] = useState<string[]>([])
  const [attestation, setAttestation] = useState('')

  const runAssist = async () => {
    setAssisting(true)
    try {
      const res = await statementApi.assist({ condition: condition.trim() || topic.trim() || null })
      setPrompts(res.prompts)
      setAttestation(res.attestation)
      if (res.draft) {
        setStatement((cur) => (cur.trim() ? cur : res.draft))
        toast('Draft built from your records — now make it yours: edit every line.', 'success')
      } else if (res.has_facts === false) {
        toast('Log some symptoms or add your in-service event first, then I can draft from them.', 'info')
      }
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setAssisting(false)
    }
  }

  const inputs: StatementDraftInput | null = useMemo(() => {
    if (!topic.trim() || !statement.trim()) return null
    return {
      veteran_name: veteranName.trim() || null,
      condition: condition.trim() || null,
      topic: topic.trim(),
      statement: statement.trim(),
      period: period.trim() || null,
    }
  }, [veteranName, topic, condition, period, statement])

  // Debounced live preview: regenerate the draft as the required fields fill in.
  useEffect(() => {
    if (!inputs) {
      setDraft(null)
      return
    }
    let cancelled = false
    const timer = setTimeout(() => {
      setBuilding(true)
      statementApi
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
      toast('Add what the statement is about and write your account first.', 'error')
      return
    }
    if (!draft) {
      toast('Give the preview a moment to build, then try again.', 'error')
      return
    }
    const state: StatementPrintState = { draft, inputs }
    sessionStorage.setItem(STATEMENT_DRAFT_KEY, JSON.stringify(state))
    navigate('/statement/print')
  }

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)

  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6" style={hueStyle(HUE) as CSSProperties}>
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          {guidance?.form ?? 'VA Form 21-4138'} · Statement in Support of Claim
        </p>
        <h1 className="vo-page-title">Personal statement builder</h1>
        <p className="vo-page-sub">
          Your own account, in your own words — the in-service event or stressor, why records may be missing, and how
          the condition affects your work and daily life. Rating Raider formats exactly what you write into a clean
          21-4138 page for you to read, sign, and submit.
        </p>
      </div>

      <LegalLaneBanner />

      {guidanceError && !guidance && <ErrorBlock message={guidanceError} />}
      {guidance && <GuidancePanel guidance={guidance} ink={ink} label={label} />}

      <FilledFormPanel
        formId="21-4138"
        hue={HUE}
        title="Download the pre-filled 21-4138 (write, review & sign)"
      />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        <Panel hue={HUE} title="Write your statement" subtitle="Your own words — true, specific, first-person">
          <form onSubmit={goToPrint} className="space-y-4 p-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm sm:col-span-2">
                <span className="vo-label">What is this statement about? *</span>
                <input
                  className="vo-input"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="e.g. the 2004 convoy attack and my PTSD; my knee injury and missing records"
                  required
                />
              </label>
              <label className="text-sm">
                <span className="vo-label">Your name (optional)</span>
                <input
                  className="vo-input"
                  value={veteranName}
                  onChange={(e) => setVeteranName(e.target.value)}
                  placeholder="As it should appear on the statement"
                />
              </label>
              <label className="text-sm">
                <span className="vo-label">Condition it's about (optional)</span>
                <input
                  className="vo-input"
                  value={condition}
                  onChange={(e) => setCondition(e.target.value)}
                  placeholder="e.g. PTSD, right knee, tinnitus"
                />
              </label>
              <label className="text-sm sm:col-span-2">
                <span className="vo-label">Time period it covers (optional)</span>
                <input
                  className="vo-input"
                  value={period}
                  onChange={(e) => setPeriod(e.target.value)}
                  placeholder="e.g. March 2004 to the present"
                />
              </label>
            </div>
            {/* Assisted drafting — proposes a draft from the veteran's own records; they revise + adopt. */}
            <div className="rounded-control border border-line bg-surface2 p-3.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm font-semibold text-txt">Not sure how to start?</p>
                <button
                  type="button"
                  onClick={() => void runAssist()}
                  disabled={assisting}
                  className="vo-btn-secondary text-sm"
                >
                  {assisting ? <Spinner size={15} /> : <Sparkles size={14} style={{ color: ink }} />}
                  Draft from my records
                </button>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted">
                I'll assemble a first-person draft from what you've already recorded (your logged symptoms and
                in-service event) — then you make it yours: edit every line, add what only you know, and keep only what's
                true.
              </p>
              {prompts.length > 0 && (
                <div className="mt-3">
                  <p className="text-micro font-semibold uppercase tracking-wide text-faint">Things you may want to describe</p>
                  <ul className="mt-1.5 space-y-1">
                    {prompts.map((p, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm leading-snug text-txt/85">
                        <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: ink }} />
                        <span>{p}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {attestation && (
                <p className="mt-3 flex items-start gap-1.5 rounded-control border-l-[3px] px-3 py-2 text-xs leading-relaxed text-txt/85"
                  style={{ borderColor: ink, background: 'var(--surface)' }}>
                  <ShieldCheck size={13} className="mt-0.5 shrink-0" style={{ color: ink }} />
                  {attestation}
                </p>
              )}
            </div>

            <label className="block text-sm">
              <span className="vo-label">Your statement *</span>
              <textarea
                className="vo-input min-h-[200px] resize-y leading-relaxed"
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
                placeholder={
                  'Write it in your own words, in the first person. Cover the specific event or stressor with dates and ' +
                  'places, what you experienced, why records may be missing, and how it affects your work and daily life. ' +
                  'e.g. "In March 2004, outside Camp Victory, our convoy hit an IED. I was never treated on paper because ' +
                  'we kept moving. Since then I wake three or four nights a week and can\'t hold a job with early shifts."'
                }
                required
              />
              <span className="mt-1 block text-xs text-faint">
                Your words go through exactly as you write them — nothing is reworded or added. Be specific, and only
                include what's true and first-hand.
              </span>
            </label>

            <button type="submit" disabled={!inputs || !draft} className="vo-btn-primary">
              {building ? <Spinner size={16} className="text-white" /> : <Printer size={15} />}
              Print / save as PDF
            </button>
            {inputs && draft && !building && (
              <p className="flex items-center gap-1.5 text-xs text-faint">
                <Sparkles size={12} style={{ color: ink }} /> Opens a clean, print-ready page you sign and date.
              </p>
            )}
          </form>
        </Panel>

        <Panel hue={HUE} title="Live preview" subtitle="Read every line, then sign and date it yourself">
          <div className="p-5">
            {draft ? (
              <div className="whitespace-pre-wrap rounded-control border border-line bg-surface2 p-5 text-sm leading-relaxed text-txt">
                {draft.statement_markdown}
              </div>
            ) : (
              <div className="flex min-h-[220px] flex-col items-center justify-center rounded-control border border-dashed border-line2 p-6 text-center">
                <ShieldCheck size={26} className="mb-2 text-faint" />
                <p className="text-sm text-muted">
                  Add what the statement is about and write your account — the draft appears here as you type.
                </p>
              </div>
            )}
            {draft && draft.guidance.length > 0 && (
              <div className="mt-4 rounded-control border p-4" style={{ borderColor: `color-mix(in srgb, ${hueVar(HUE)} 30%, var(--border))`, background: hueSoftVar(HUE) }}>
                <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                  <ListChecks size={13} /> Before you sign
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
    </div>
  )
}

/** Prominent legal-lane note: these are your own words, you sign it, the app
 * never files it — and a VSO can help for free. */
function LegalLaneBanner() {
  return (
    <div
      className="vo-card vo-accent relative flex items-start gap-3.5 overflow-hidden p-5"
      style={hueStyle('amber') as CSSProperties}
    >
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar('amber'), color: hueInk('amber') }}
      >
        <FileSignature size={20} />
      </div>
      <div>
        <h2 className="text-sm font-semibold text-txt">These are your own words — you sign it, and the app never files it</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          A Statement in Support of Claim is your own sworn account. Rating Raider formats exactly what you write —
          it never rewords, adds, or invents anything. Read every line, make sure it's all true and first-hand, then
          sign and date it and submit it with your claim. A VA-accredited VSO — VFW, DAV, The American Legion, or your
          state/county veterans office — can help you file it for free.
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
  guidance: StatementGuidance
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
