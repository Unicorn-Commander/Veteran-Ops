import {
  ClipboardList,
  Copy,
  ExternalLink,
  FileSearch,
  Info,
  Lightbulb,
  ListChecks,
  Printer,
  ShieldAlert,
  Sparkles,
  Stethoscope,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Checkbox, ErrorBlock, Panel, Spinner } from '../components/ui'
import { FilledFormPanel } from '../components/FilledFormPanel'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { nexusApi } from '../lib/api'
import { hueInk, hueLabel, hueStyle, hueSoftVar, hueVar, type Hue } from '../lib/hues'
import type { NexusDraft, NexusDraftInput, NexusGuidance, NexusProviderBrief } from '../types'

// /nexus — WAVE6-SPEC F2. Medical-nexus opinion letter TEMPLATE builder.
// The nexus opinion ("at least as likely as not") is the linchpin of most VA
// claims — but it is a MEDICAL opinion only a qualified PROVIDER can render and
// sign. Rating Raider builds a template the veteran brings to their provider:
// the opinion sentence is a fill-in and the rationale is left blank for the
// provider. The app never writes, signs, or supplies the medical opinion.
// Shapes reconciled against backend/app/routers/nexus.py (routers are truth).
// Follows the Buddy.tsx builder + BuddyPrint.tsx print pattern.

const HUE: Hue = 'orange'
export const NEXUS_DRAFT_KEY = 'vo_nexus_draft'

type ClaimType = 'direct' | 'secondary'

/** What the print view reads out of sessionStorage. */
export interface NexusPrintState {
  draft: NexusDraft
  inputs: NexusDraftInput
}

export function Nexus() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { toast } = useToast()
  const { data: guidance, error: guidanceError } = useAsync(() => nexusApi.guidance())

  const [condition, setCondition] = useState('')
  const [diagnosticCode, setDiagnosticCode] = useState('')
  const [claimType, setClaimType] = useState<ClaimType>('direct')
  const [veteranName, setVeteranName] = useState('')
  const [inServiceEvent, setInServiceEvent] = useState('')
  const [secondaryTo, setSecondaryTo] = useState('')
  const [clinicalSummary, setClinicalSummary] = useState('')
  /** Prefill for ProviderBriefSection from Claim Plan reclaim deep-links. */
  const [briefPrefill, setBriefPrefill] = useState<{
    condition?: string
    claimType?: ClaimType
    secondaryTo?: string
    diagnosticCode?: string
    priorDenial?: string
    open?: boolean
  } | null>(null)

  const [draft, setDraft] = useState<NexusDraft | null>(null)
  const [building, setBuilding] = useState(false)

  // Claim Plan reclaim links: /nexus?condition=…&claim_type=secondary&secondary_to=…&brief=1
  useEffect(() => {
    const cond = searchParams.get('condition')?.trim()
    const ct = searchParams.get('claim_type')
    const sec = searchParams.get('secondary_to')?.trim()
    const dc = searchParams.get('diagnostic_code')?.trim()
    const brief = searchParams.get('brief') === '1'
    const prior = searchParams.get('prior_denial') === '1'
    if (!cond && !brief && !sec) return

    if (cond) setCondition(cond)
    if (ct === 'secondary' || ct === 'direct') setClaimType(ct)
    if (sec) setSecondaryTo(sec)
    if (dc) setDiagnosticCode(dc)

    if (brief || cond) {
      setBriefPrefill({
        condition: cond || undefined,
        claimType: ct === 'secondary' || ct === 'direct' ? ct : undefined,
        secondaryTo: sec || undefined,
        diagnosticCode: dc || undefined,
        priorDenial: prior
          ? 'Previously denied — consider a new secondary theory with a medical nexus opinion (Supplemental Claim path). Confirm with a VSO.'
          : undefined,
        open: brief,
      })
    }

    // Consume query so refresh doesn't re-apply over user edits.
    const next = new URLSearchParams(searchParams)
    for (const k of ['condition', 'claim_type', 'secondary_to', 'diagnostic_code', 'brief', 'prior_denial']) {
      next.delete(k)
    }
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  const inputs: NexusDraftInput | null = useMemo(() => {
    if (!condition.trim()) return null
    return {
      condition: condition.trim(),
      diagnostic_code: diagnosticCode.trim() || null,
      claim_type: claimType,
      veteran_name: veteranName.trim() || null,
      in_service_event: inServiceEvent.trim() || null,
      secondary_to: claimType === 'secondary' ? secondaryTo.trim() || null : null,
      clinical_summary: clinicalSummary.trim() || null,
    }
  }, [condition, diagnosticCode, claimType, veteranName, inServiceEvent, secondaryTo, clinicalSummary])

  // Debounced live preview: regenerate the template as the fields fill in.
  useEffect(() => {
    if (!inputs) {
      setDraft(null)
      return
    }
    let cancelled = false
    const timer = setTimeout(() => {
      setBuilding(true)
      nexusApi
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
      toast('Enter the condition first — that is the one required field.', 'error')
      return
    }
    if (!draft) {
      toast('Give the preview a moment to build, then try again.', 'error')
      return
    }
    const state: NexusPrintState = { draft, inputs }
    sessionStorage.setItem(NEXUS_DRAFT_KEY, JSON.stringify(state))
    navigate('/nexus/print')
  }

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)

  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6" style={hueStyle(HUE) as CSSProperties}>
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          Nexus letter · 38 CFR §3.303 / §3.310
        </p>
        <h1 className="vo-page-title">Nexus letter builder</h1>
        <p className="vo-page-sub">
          The medical link between your condition and your service — "at least as likely as not" — is the linchpin of
          most claims. Rating Raider builds a clean template you bring to your provider, who writes the opinion and signs
          it.
        </p>
      </div>

      <LegalLaneBanner />

      {guidanceError && !guidance && <ErrorBlock message={guidanceError} />}
      {guidance && <GuidancePanel guidance={guidance} ink={ink} label={label} />}

      <FilledFormPanel
        formId="21-4142"
        hue={HUE}
        title="Authorize VA to collect your medical records — pre-filled 21-4142 (review & sign)"
      />

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        <Panel hue={HUE} title="Build the template" subtitle="For your provider to complete and sign — not a medical opinion">
          <form onSubmit={goToPrint} className="space-y-4 p-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="text-sm sm:col-span-2">
                <span className="vo-label">Condition *</span>
                <input
                  className="vo-input"
                  value={condition}
                  onChange={(e) => setCondition(e.target.value)}
                  placeholder="e.g. tinnitus, PTSD, lumbar strain"
                  required
                />
              </label>
              <label className="text-sm">
                <span className="vo-label">Diagnostic code (optional)</span>
                <input
                  className="vo-input"
                  value={diagnosticCode}
                  onChange={(e) => setDiagnosticCode(e.target.value)}
                  placeholder="e.g. 6260"
                />
              </label>
              <label className="text-sm">
                <span className="vo-label">Claim type</span>
                <select className="vo-input" value={claimType} onChange={(e) => setClaimType(e.target.value as ClaimType)}>
                  <option value="direct">Direct — related to service (§3.303)</option>
                  <option value="secondary">Secondary — caused/aggravated by a rated condition (§3.310)</option>
                </select>
              </label>
              {claimType === 'secondary' && (
                <label className="text-sm sm:col-span-2">
                  <span className="vo-label">Secondary to which service-connected condition? *</span>
                  <input
                    className="vo-input"
                    value={secondaryTo}
                    onChange={(e) => setSecondaryTo(e.target.value)}
                    placeholder="e.g. service-connected lumbar strain"
                  />
                  <span className="mt-1 block text-xs text-faint">
                    The already-rated condition your provider will link this new one to.
                  </span>
                </label>
              )}
              <label className="text-sm sm:col-span-2">
                <span className="vo-label">Your name (optional)</span>
                <input
                  className="vo-input"
                  value={veteranName}
                  onChange={(e) => setVeteranName(e.target.value)}
                  placeholder="As it should appear on the letter"
                />
              </label>
            </div>
            <label className="block text-sm">
              <span className="vo-label">In-service event or exposure (optional)</span>
              <textarea
                className="vo-input min-h-[80px] resize-y leading-relaxed"
                value={inServiceEvent}
                onChange={(e) => setInServiceEvent(e.target.value)}
                placeholder={'e.g. "Repeated exposure to artillery fire without hearing protection, 2007–2009."'}
              />
            </label>
            <label className="block text-sm">
              <span className="vo-label">Background for your provider (optional)</span>
              <textarea
                className="vo-input min-h-[100px] resize-y leading-relaxed"
                value={clinicalSummary}
                onChange={(e) => setClinicalSummary(e.target.value)}
                placeholder={
                  'Context to help your provider — symptoms, timeline, treatment history. This is your background, NOT a medical opinion.'
                }
              />
              <span className="mt-1 block text-xs text-faint">
                Appears as veteran-provided background. The medical opinion and rationale are your provider's to write.
              </span>
            </label>

            <button type="submit" disabled={!inputs || !draft} className="vo-btn-primary">
              {building ? <Spinner size={16} className="text-white" /> : <Printer size={15} />}
              Print / save as PDF
            </button>
            {inputs && draft && !building && (
              <p className="flex items-center gap-1.5 text-xs text-faint">
                <Sparkles size={12} style={{ color: ink }} /> Opens a clean, print-ready template to bring to your provider.
              </p>
            )}
          </form>
        </Panel>

        <Panel hue={HUE} title="Live preview" subtitle="Your provider completes the opinion and rationale, then signs">
          <div className="p-5">
            {draft ? (
              <div className="whitespace-pre-wrap rounded-control border border-line bg-surface2 p-5 text-sm leading-relaxed text-txt">
                {draft.letter_markdown}
              </div>
            ) : (
              <div className="flex min-h-[220px] flex-col items-center justify-center rounded-control border border-dashed border-line2 p-6 text-center">
                <Stethoscope size={26} className="mb-2 text-faint" />
                <p className="text-sm text-muted">
                  Enter the condition — the template appears here as you type. The opinion line and rationale are left for
                  your provider to complete.
                </p>
              </div>
            )}
            {draft && draft.guidance.length > 0 && (
              <div className="mt-4 rounded-control border p-4" style={{ borderColor: `color-mix(in srgb, ${hueVar(HUE)} 30%, var(--border))`, background: hueSoftVar(HUE) }}>
                <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                  <ListChecks size={13} /> Before you bring it to your provider
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

      <ProviderBriefSection ink={ink} label={label} prefill={briefPrefill} />
    </div>
  )
}

/** Known missing-element keys the backend maps to plain language. */
const MISSING_ELEMENT_OPTIONS: Array<{ key: string; label: string }> = [
  { key: 'current_disability', label: 'Current diagnosis' },
  { key: 'in_service_event', label: 'In-service event / exposure' },
  { key: 'nexus', label: 'Medical nexus link' },
  { key: 'continuity', label: 'Continuity / chronicity' },
  { key: 'secondary_link', label: 'Secondary causal / aggravation link' },
]

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

/** Provider-facing brief: what was missing + blank opinion scaffold. Clinician signs. */
function ProviderBriefSection({
  ink,
  label,
  prefill,
}: {
  ink: string
  label: string
  prefill?: {
    condition?: string
    claimType?: ClaimType
    secondaryTo?: string
    diagnosticCode?: string
    priorDenial?: string
    open?: boolean
  } | null
}) {
  const { toast } = useToast()
  const [condition, setCondition] = useState('')
  const [claimType, setClaimType] = useState<ClaimType>('direct')
  const [secondaryTo, setSecondaryTo] = useState('')
  const [diagnosticCode, setDiagnosticCode] = useState('')
  const [priorDenial, setPriorDenial] = useState('')
  const [missing, setMissing] = useState<string[]>([])
  const [recordsRaw, setRecordsRaw] = useState('')
  const [brief, setBrief] = useState<NexusProviderBrief | null>(null)
  const [loading, setLoading] = useState(false)
  const autoGenRef = useRef(false)

  // Apply Claim Plan reclaim deep-link once.
  useEffect(() => {
    if (!prefill) return
    if (prefill.condition) setCondition(prefill.condition)
    if (prefill.claimType) setClaimType(prefill.claimType)
    if (prefill.secondaryTo) setSecondaryTo(prefill.secondaryTo)
    if (prefill.diagnosticCode) setDiagnosticCode(prefill.diagnosticCode)
    if (prefill.priorDenial) {
      setPriorDenial(prefill.priorDenial)
      setMissing((m) =>
        m.includes('nexus') && m.includes('secondary_link')
          ? m
          : Array.from(new Set([...m, 'nexus', 'secondary_link'])),
      )
    }
    if (prefill.open) {
      // Scroll after paint so the panel is on-screen.
      requestAnimationFrame(() => {
        document.getElementById('provider-brief')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      })
    }
  }, [prefill])

  // Single-shot auto-generate when deep-linked with open + condition (provider still signs).
  useEffect(() => {
    if (!prefill?.open || !prefill.condition || autoGenRef.current) return
    autoGenRef.current = true
    const cond = prefill.condition.trim()
    if (!cond) return
    const ct: ClaimType = prefill.claimType === 'secondary' || prefill.claimType === 'direct' ? prefill.claimType : 'direct'
    const missingKeys =
      prefill.priorDenial
        ? Array.from(new Set(['nexus', 'secondary_link']))
        : []
    setLoading(true)
    nexusApi
      .providerBrief({
        condition: cond,
        claim_type: ct,
        secondary_to: ct === 'secondary' ? (prefill.secondaryTo || '').trim() || null : null,
        diagnostic_code: (prefill.diagnosticCode || '').trim() || null,
        prior_denial_notes: (prefill.priorDenial || '').trim() || null,
        missing_elements: missingKeys,
        records_to_review: [],
      })
      .then((b) => setBrief(b))
      .catch((err) => toast(errorMessage(err), 'error'))
      .finally(() => setLoading(false))
  }, [prefill, toast])

  const toggleMissing = (key: string) => {
    setMissing((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
  }

  const generate = (e: FormEvent) => {
    e.preventDefault()
    if (!condition.trim()) {
      toast('Enter the condition for the provider brief.', 'error')
      return
    }
    setLoading(true)
    nexusApi
      .providerBrief({
        condition: condition.trim(),
        claim_type: claimType,
        secondary_to: claimType === 'secondary' ? secondaryTo.trim() || null : null,
        diagnostic_code: diagnosticCode.trim() || null,
        prior_denial_notes: priorDenial.trim() || null,
        missing_elements: missing,
        records_to_review: splitList(recordsRaw),
      })
      .then((b) => setBrief(b))
      .catch((err) => toast(errorMessage(err), 'error'))
      .finally(() => setLoading(false))
  }

  const copyAll = async () => {
    if (!brief) return
    const parts = [
      brief.title,
      '',
      '## What was missing',
      ...brief.what_was_missing.map((w, i) => `${i + 1}. ${w}`),
      '',
      '## Records to review',
      ...brief.records_to_review.map((r) => `• ${r}`),
      '',
      brief.opinion_scaffold,
      '',
      brief.blank_rationale_prompt,
      '',
      brief.disclaimer,
    ]
    const ok = await copyText(parts.join('\n'))
    toast(
      ok
        ? 'Provider brief copied — clinician completes the opinion and signs.'
        : 'Could not copy. Select the text manually.',
      ok ? 'success' : 'error',
    )
  }

  return (
    <div id="provider-brief" className="scroll-mt-24">
    <Panel
      hue={HUE}
      title="Provider brief"
      subtitle="What was missing historically + blank opinion scaffold — provider completes and signs"
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
                placeholder="e.g. tinnitus, PTSD, lumbar strain"
                required
              />
            </label>
            <label className="text-sm">
              <span className="vo-label">Claim type</span>
              <select
                className="vo-input"
                value={claimType}
                onChange={(e) => setClaimType(e.target.value as ClaimType)}
              >
                <option value="direct">Direct — related to service (§3.303)</option>
                <option value="secondary">Secondary — caused/aggravated by a rated condition (§3.310)</option>
              </select>
            </label>
            <label className="text-sm">
              <span className="vo-label">Diagnostic code (optional)</span>
              <input
                className="vo-input"
                value={diagnosticCode}
                onChange={(e) => setDiagnosticCode(e.target.value)}
                placeholder="e.g. 6260"
              />
            </label>
            {claimType === 'secondary' && (
              <label className="text-sm sm:col-span-2">
                <span className="vo-label">Secondary to (service-connected primary)</span>
                <input
                  className="vo-input"
                  value={secondaryTo}
                  onChange={(e) => setSecondaryTo(e.target.value)}
                  placeholder="e.g. service-connected lumbar strain"
                />
              </label>
            )}
          </div>

          <label className="block text-sm">
            <span className="vo-label">Prior denial notes (optional)</span>
            <textarea
              className="vo-input min-h-[72px] resize-y leading-relaxed"
              value={priorDenial}
              onChange={(e) => setPriorDenial(e.target.value)}
              placeholder='e.g. "Denied for lack of nexus; examiner said condition existed prior to service."'
            />
            <span className="mt-1 block text-xs text-faint">
              If present, the brief asks the provider to address that rationale explicitly.
            </span>
          </label>

          <fieldset>
            <legend className="vo-label mb-2">What was historically missing (optional)</legend>
            <div className="space-y-2">
              {MISSING_ELEMENT_OPTIONS.map((opt) => (
                <Checkbox
                  key={opt.key}
                  label={opt.label}
                  checked={missing.includes(opt.key)}
                  onChange={() => toggleMissing(opt.key)}
                />
              ))}
            </div>
            <p className="mt-1.5 text-xs text-faint">
              Leave unchecked for default elements based on claim type (diagnosis + nexus / secondary link + ≥50% rationale).
            </p>
          </fieldset>

          <label className="block text-sm">
            <span className="vo-label">Records for the provider to review (optional)</span>
            <textarea
              className="vo-input min-h-[72px] resize-y leading-relaxed"
              value={recordsRaw}
              onChange={(e) => setRecordsRaw(e.target.value)}
              placeholder="One per line — e.g. STRs 2007–2009, prior rating decision, private MRI 2022"
            />
            <span className="mt-1 block text-xs text-faint">
              Blank uses a standard pack (STRs, prior decisions, current notes, private records).
            </span>
          </label>

          <button type="submit" disabled={loading || !condition.trim()} className="vo-btn-primary">
            {loading ? <Spinner size={16} className="text-white" /> : <FileSearch size={15} />}
            Generate provider brief
          </button>
          <p className="text-xs leading-relaxed text-faint">
            Legal lane: this is a scaffold for your <strong className="font-semibold text-muted">treating provider</strong>.
            Only they write the medical opinion and <strong className="font-semibold text-muted">sign</strong>. Rating
            Raider never supplies the opinion.
          </p>
        </form>

        <div>
          {brief ? (
            <div className="space-y-4">
              <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
                {brief.title}
              </p>

              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                    <ListChecks size={13} /> What was missing
                  </p>
                  <button
                    type="button"
                    className="vo-btn-ghost text-[11px]"
                    onClick={() =>
                      void copyText(brief.what_was_missing.map((w, i) => `${i + 1}. ${w}`).join('\n')).then((ok) =>
                        toast(ok ? 'Missing list copied.' : 'Could not copy.', ok ? 'success' : 'error'),
                      )
                    }
                  >
                    <Copy size={11} /> Copy
                  </button>
                </div>
                <ol className="space-y-2 text-sm text-txt">
                  {brief.what_was_missing.map((w, i) => (
                    <li key={i} className="flex gap-2.5">
                      <span
                        aria-hidden
                        className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                        style={{ background: hueSoftVar(HUE), color: ink }}
                      >
                        {i + 1}
                      </span>
                      <span className="leading-relaxed">{w}</span>
                    </li>
                  ))}
                </ol>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                    <ClipboardList size={13} /> Records to review
                  </p>
                  <button
                    type="button"
                    className="vo-btn-ghost text-[11px]"
                    onClick={() =>
                      void copyText(brief.records_to_review.map((r) => `• ${r}`).join('\n')).then((ok) =>
                        toast(ok ? 'Records list copied.' : 'Could not copy.', ok ? 'success' : 'error'),
                      )
                    }
                  >
                    <Copy size={11} /> Copy
                  </button>
                </div>
                <ul className="space-y-1.5 text-sm text-txt">
                  {brief.records_to_review.map((r, i) => (
                    <li key={i} className="flex gap-2">
                      <span aria-hidden style={{ color: ink }}>
                        •
                      </span>
                      <span className="leading-relaxed">{r}</span>
                    </li>
                  ))}
                </ul>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                    <Stethoscope size={13} /> Opinion scaffold
                  </p>
                  <button
                    type="button"
                    className="vo-btn-ghost text-[11px]"
                    onClick={() =>
                      void copyText(brief.opinion_scaffold).then((ok) =>
                        toast(ok ? 'Scaffold copied.' : 'Could not copy.', ok ? 'success' : 'error'),
                      )
                    }
                  >
                    <Copy size={11} /> Copy
                  </button>
                </div>
                <div className="whitespace-pre-wrap rounded-control border border-line bg-surface2 p-4 text-sm leading-relaxed text-txt">
                  {brief.opinion_scaffold}
                </div>
              </div>

              <div
                className="rounded-control border p-4"
                style={{
                  borderColor: `color-mix(in srgb, ${hueVar(HUE)} 30%, var(--border))`,
                  background: hueSoftVar(HUE),
                }}
              >
                <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                  <ShieldAlert size={13} /> Blank rationale — provider only
                </p>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">{brief.blank_rationale_prompt}</p>
              </div>

              <p className="text-xs italic leading-relaxed text-faint">{brief.disclaimer}</p>
            </div>
          ) : (
            <div className="flex min-h-[220px] flex-col items-center justify-center rounded-control border border-dashed border-line2 p-6 text-center">
              <FileSearch size={26} className="mb-2 text-faint" />
              <p className="text-sm text-muted">
                Enter a condition and generate a provider-facing brief: historical gaps, records to review, and a blank
                opinion scaffold. Your provider completes and signs the medical opinion.
              </p>
            </div>
          )}
        </div>
      </div>
    </Panel>
    </div>
  )
}

/** Prominent legal-lane note: this is a template FOR your provider — it is not a
 * medical opinion, and Veteran-Ops cannot supply the opinion. */
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
        <ShieldAlert size={20} />
      </div>
      <div>
        <h2 className="text-sm font-semibold text-txt">This is a template for YOUR provider to complete and sign</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          A nexus opinion is a <strong className="font-semibold text-txt">medical opinion</strong> — only a qualified
          treating provider can render it and sign it. Veteran-Ops cannot and does not supply the medical opinion. This
          builder produces a scaffold: the "at least as likely as not" opinion sentence is a fill-in, and the rationale is
          left <strong className="font-semibold text-txt">blank</strong> for your provider to write in their own clinical
          judgment. You (or a free VA-accredited VSO) then submit the signed letter as evidence.
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
  guidance: NexusGuidance
  ink: string
  label: string
}) {
  return (
    <Panel hue={HUE} title="What a strong nexus opinion covers" subtitle="What it is · why it decides claims">
      <div className="grid gap-4 p-5 sm:grid-cols-2">
        <div className="rounded-control border border-line bg-surface2 p-4">
          <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
            <Info size={12} /> What it is
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">{guidance.what_it_is}</p>
        </div>
        <div className="rounded-control border border-line bg-surface2 p-4">
          <p className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
            <Sparkles size={12} /> Why it matters
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">{guidance.why_it_matters}</p>
        </div>
      </div>
      <div className="grid gap-5 px-5 pb-5 sm:grid-cols-2">
        <div>
          <p className="mb-2.5 text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
            What the provider's opinion should cover
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
            <Lightbulb size={12} /> What wins it
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
