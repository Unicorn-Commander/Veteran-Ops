import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Download,
  ExternalLink,
  FileCheck,
  Loader2,
  PenLine,
  Printer,
  Rocket,
  ShieldCheck,
} from 'lucide-react'
import { type CSSProperties, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileReadyHandoff } from '../components/FileReadyHandoff'
import { EmptyState, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { ApiError, form526Api } from '../lib/api'
import { formatDate, formatPercent, humanize } from '../lib/format'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { Form526Contention, Form526EvidenceRef, Form526Packet } from '../types'

// /application — WAVE6-SPEC F1. VA Form 21-526EZ (Application for Disability
// Compensation), ASSEMBLED from the veteran's own data (profile, conditions,
// evidence, ITF). This is NOT the fillable government PDF — it's a review
// worksheet the veteran reads, signs, and files themselves at VA.gov or hands
// to a free VSO. Rating Raider never files anything. Endpoint shape reconciled
// against backend/app/routers/form526.py (routers are truth). Follows the
// Buddy.tsx builder + BuddyPrint sessionStorage handoff pattern.

const HUE: Hue = 'amber'
export const FORM526_KEY = 'vo_form526'

export function Form526() {
  const navigate = useNavigate()
  const { data, loading, error, reload } = useAsync(() => form526Api.get())

  if (loading) return <LoadingBlock label="Assembling your 21-526EZ application…" />
  if (error || !data) {
    return (
      <div className="p-6">
        <ErrorBlock message={error ?? 'Could not assemble your application.'} onRetry={reload} />
      </div>
    )
  }

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)
  const { veteran, service, contentions, itf } = data
  const hasConditions = contentions.length > 0

  const goToPrint = () => {
    sessionStorage.setItem(FORM526_KEY, JSON.stringify(data))
    navigate('/application/print')
  }

  return (
    <div
      data-section="records"
      className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          VA Form 21-526EZ · Application for Disability Compensation
        </p>
        <h1 className="vo-page-title">Application (21-526EZ)</h1>
        <p className="vo-page-sub">
          Your profile, conditions, evidence, and Intent to File — assembled into the shape of the 21-526EZ so you can
          review it in one place, then file it yourself at VA.gov or hand it to a free VSO.
        </p>
      </div>

      <LegalLaneBanner />

      {/* File-ready handoff at top when the veteran has contentions — score + VA.gov / VSO paths. */}
      {hasConditions && <FileReadyHandoff />}

      {!hasConditions ? (
        <Panel hue={HUE}>
          <EmptyState
            hue={HUE}
            icon={<FileCheck size={24} />}
            title="No conditions to apply for yet"
            description="Populate your case from uploaded records, or add conditions by hand — then they'll assemble into your 21-526EZ draft here."
            action={
              <div className="flex flex-wrap justify-center gap-2">
                <Link to="/build-case" className="vo-btn-primary">
                  Populate case from records
                </Link>
                <Link to="/conditions" className="vo-btn-secondary">
                  Add manually
                </Link>
              </div>
            }
          />
        </Panel>
      ) : (
        <>
          <AlmostDoneClimax onPrint={goToPrint} />

          <CompletenessBanner data={data} ink={ink} label={label} onPrint={goToPrint} />

          <PdfDownloadPanel ink={ink} label={label} />

          <Panel hue={HUE} title="Section I — Veteran" subtitle="Who this application is for">
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <ReviewField label="Full name" value={veteran.name} />
              <ReviewField label="Email" value={veteran.email} />
            </div>
          </Panel>

          <Panel hue={HUE} title="Section II — Military service" subtitle="From your veteran profile">
            <div className="p-5">
              {service.periods.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
                        <th className="py-2 pr-3 font-semibold">Branch</th>
                        <th className="py-2 pr-3 font-semibold">Component</th>
                        <th className="py-2 pr-3 font-semibold">Service dates</th>
                        <th className="py-2 font-semibold">Discharge</th>
                      </tr>
                    </thead>
                    <tbody>
                      {service.periods.map((p, i) => (
                        <tr key={i} className="border-b border-line align-top">
                          <td className="py-2 pr-3 text-txt">{str(p.branch)}</td>
                          <td className="py-2 pr-3 text-txt">{str(p.component)}</td>
                          <td className="py-2 pr-3 text-txt">
                            {formatDate(str(p.start_date) || null)} – {formatDate(str(p.end_date) || null)}
                          </td>
                          <td className="py-2 text-txt">{str(p.discharge_character)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-sm text-muted">
                  No service periods on file yet.{' '}
                  <Link to="/profile" className="font-semibold text-brand hover:text-brand-hover">
                    Add them in your profile
                  </Link>{' '}
                  so this section fills in.
                </p>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-2">
                {service.combat && (
                  <span className="vo-chip-hue" style={hueStyle('rose') as CSSProperties}>
                    Combat service
                  </span>
                )}
                {service.exposures.map((ex, i) => (
                  <span key={i} className="vo-chip-hue" style={hueStyle('lime') as CSSProperties}>
                    {ex}
                  </span>
                ))}
                {!service.combat && service.exposures.length === 0 && (
                  <p className="text-xs text-faint">No combat service or exposures recorded.</p>
                )}
              </div>
            </div>
          </Panel>

          <Panel
            hue={HUE}
            title="Section III — Conditions you're claiming"
            subtitle={`${contentions.length} contention${contentions.length === 1 ? '' : 's'}`}
          >
            <div className="space-y-4 p-5">
              {contentions.map((c, i) => (
                <ContentionCard key={i} c={c} ink={ink} label={label} />
              ))}
            </div>
          </Panel>

          <Panel hue={HUE} title="Intent to File" subtitle="Locks in your effective date for one year">
            <div className="p-5">
              {itf ? (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
                  <span className="font-semibold text-txt">{humanize(itf.type)} ITF</span>
                  <span className="text-muted">Filed {formatDate(itf.filed_date)}</span>
                  <span className="text-muted">Deadline {formatDate(itf.deadline)}</span>
                  <span
                    className="vo-chip-hue"
                    style={hueStyle(itf.days_remaining <= 60 ? 'rose' : 'emerald') as CSSProperties}
                  >
                    {itf.days_remaining} days remaining
                  </span>
                </div>
              ) : (
                <p className="text-sm text-muted">
                  No active Intent to File on record. An ITF locks in your effective date (and back pay) for one year —{' '}
                  <Link to="/itf" className="font-semibold text-brand hover:text-brand-hover">
                    add or track one here
                  </Link>
                  , or start it on VA.gov before you file the full claim.
                </p>
              )}
            </div>
          </Panel>

          <GuidancePanel data={data} ink={ink} />

          {/* Climax repeat at bottom so long reviews still end with a clear handoff. */}
          <AlmostDoneClimax onPrint={goToPrint} compact />
        </>
      )}
    </div>
  )
}

/** "You're almost done" climax — Review PDF → Download → Submit at VA.gov or VSO. */
function AlmostDoneClimax({ onPrint, compact = false }: { onPrint: () => void; compact?: boolean }) {
  const steps = [
    {
      n: 1,
      title: 'Review the PDF',
      body: 'Open the clean worksheet or pre-filled official form and check every field.',
    },
    {
      n: 2,
      title: 'Download & complete',
      body: 'Fill blanks (SSN, address, signature). Rating Raider never stores those.',
    },
    {
      n: 3,
      title: 'Submit at VA.gov or a VSO',
      body: 'You file — or a free accredited VSO files with you. We never e-file.',
    },
  ]

  return (
    <section
      aria-label="You're almost done"
      className="vo-card vo-accent overflow-hidden p-5 sm:p-6"
      style={hueStyle('emerald') as CSSProperties}
    >
      <div className="flex flex-wrap items-start gap-3.5">
        <span
          aria-hidden
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar('emerald'), color: hueInk('emerald') }}
        >
          <Rocket size={22} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="vo-caption mb-0.5" style={{ color: hueLabel('emerald') }}>
            Filing handoff
          </p>
          <h2 className="text-lg font-bold tracking-tight text-txt sm:text-xl">You&apos;re almost done</h2>
          <p className="mt-1 max-w-[70ch] text-sm leading-relaxed text-muted">
            Your application is assembled. Three steps left — then you (or a free VSO) submit. Rating Raider never
            files for you.
          </p>
        </div>
      </div>

      <ol className={`mt-5 grid gap-3 ${compact ? '' : 'sm:grid-cols-3'}`}>
        {steps.map((s) => (
          <li
            key={s.n}
            className="flex gap-3 rounded-control border border-line bg-surface2/80 px-3.5 py-3"
          >
            <span
              aria-hidden
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold"
              style={{ background: hueSoftVar('emerald'), color: hueInk('emerald') }}
            >
              {s.n}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-semibold text-txt">{s.title}</span>
              <span className="mt-0.5 block text-xs leading-relaxed text-muted">{s.body}</span>
            </span>
          </li>
        ))}
      </ol>

      <div className="mt-5 flex flex-wrap gap-2">
        <button type="button" onClick={onPrint} className="vo-btn-primary min-h-11 text-sm">
          <Printer size={15} /> Review PDF
        </button>
        <a
          href="#form526-pdf-download"
          className="vo-btn-secondary min-h-11 text-sm"
          onClick={(e) => {
            const el = document.getElementById('form526-pdf-download')
            if (el) {
              e.preventDefault()
              el.scrollIntoView({ behavior: 'smooth', block: 'start' })
            }
          }}
        >
          <Download size={15} /> Download draft
        </a>
        <a
          href="https://www.va.gov/disability/file-disability-claim-form-21-526ez/"
          target="_blank"
          rel="noreferrer"
          className="vo-btn-secondary min-h-11 text-sm"
        >
          Submit at VA.gov <ExternalLink size={13} />
        </a>
        <a
          href="https://www.va.gov/get-help-from-accredited-representative/"
          target="_blank"
          rel="noreferrer"
          className="vo-btn-ghost min-h-11 text-sm"
        >
          Find a VSO <ArrowRight size={13} />
        </a>
      </div>
    </section>
  )
}

/** Loosely-typed service-period values arrive as unknown — render safely. */
function str(v: unknown): string {
  return v === null || v === undefined ? '' : String(v)
}

function ReviewField({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-faint">{label}</p>
      <p className="mt-0.5 text-sm text-txt">{value || '—'}</p>
    </div>
  )
}

function CompletenessBanner({
  data,
  ink,
  label,
  onPrint,
}: {
  data: Form526Packet
  ink: string
  label: string
  onPrint: () => void
}) {
  const { conditions, with_evidence, missing_evidence } = data.completeness
  return (
    <div className="vo-card vo-accent p-5" style={hueStyle(HUE) as CSSProperties}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex flex-wrap gap-6">
          <Stat n={conditions} label="Conditions" ink={ink} labelColor={label} />
          <Stat n={with_evidence} label="With evidence" ink={hueInk('emerald')} labelColor={label} />
          <Stat n={missing_evidence} label="Missing evidence" ink={hueInk('rose')} labelColor={label} />
        </div>
        <button onClick={onPrint} className="vo-btn-primary shrink-0">
          <Printer size={15} /> Print / save as PDF
        </button>
      </div>
      {missing_evidence > 0 && (
        <p className="mt-3 flex items-start gap-2 text-sm text-muted">
          <AlertTriangle size={15} className="mt-0.5 shrink-0" style={{ color: hueInk('amber') }} />
          <span>
            {missing_evidence} condition{missing_evidence === 1 ? '' : 's'} still {missing_evidence === 1 ? 'has' : 'have'}
            {' '}no evidence on hand. You can file now and add evidence, but stronger evidence means a stronger claim.
          </span>
        </p>
      )}
    </div>
  )
}

function Stat({ n, label, ink, labelColor }: { n: number; label: string; ink: string; labelColor: string }) {
  return (
    <div>
      <p className="text-2xl font-bold tabular-nums" style={{ color: ink }}>
        {n}
      </p>
      <p className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: labelColor }}>
        {label}
      </p>
    </div>
  )
}

// Mirrors backend/app/pdf/form526_fill.py AUTO_FILLED / YOU_COMPLETE (static copy).
const PDF_AUTO_FILLED = [
  'Your name and email',
  'Service dates (from your profile)',
  'Standard claim process',
  "Each condition you're claiming and how it relates to your service",
]
const PDF_YOU_COMPLETE = [
  'Social Security number and VA file number',
  'Date of birth',
  'Mailing address and phone',
  'Remaining service details (branch, separation, reserve/guard)',
  'Treatment facilities and direct-deposit information',
  'Your signature and date',
]

/** Downloads the OFFICIAL fillable 21-526EZ (JAN 2026), pre-filled with the
 * high-confidence data and streamed as a DRAFT. Honest about what's filled vs. what
 * the veteran must still complete and sign — never presented as "done". */
function PdfDownloadPanel({ ink, label }: { ink: string; label: string }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const download = async () => {
    setBusy(true)
    setErr(null)
    try {
      await form526Api.downloadPdf()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not generate the PDF. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div id="form526-pdf-download">
      <Panel
        hue={HUE}
        title="Download the pre-filled official form"
        subtitle="VA Form 21-526EZ · JAN 2026 edition (OMB 2900-0747)"
      >
        <div className="p-5">
          <p className="text-sm leading-relaxed text-muted">
            This is the <strong className="text-txt">actual government PDF</strong>, pre-filled with the data we hold with
            confidence. It downloads as a <strong className="text-txt">draft</strong> — review every field, complete the
            blanks, and sign it before you file. Rating Raider never files it for you.
          </p>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div className="rounded-control border border-line bg-surface2 p-4">
              <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: hueInk('emerald') }}>
                <CheckCircle2 size={14} /> We fill this in
              </p>
              <ul className="space-y-1.5 text-sm text-txt">
                {PDF_AUTO_FILLED.map((t, i) => (
                  <li key={i} className="flex gap-2">
                    <CheckCircle2 size={14} className="mt-0.5 shrink-0" style={{ color: hueInk('emerald') }} />
                    <span>{t}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-control border border-line bg-surface2 p-4">
              <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: ink }}>
                <PenLine size={14} /> You complete &amp; sign
              </p>
              <ul className="space-y-1.5 text-sm text-txt">
                {PDF_YOU_COMPLETE.map((t, i) => (
                  <li key={i} className="flex gap-2">
                    <PenLine size={14} className="mt-0.5 shrink-0" style={{ color: ink }} />
                    <span>{t}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="mt-4 flex flex-col items-start gap-2">
            <button onClick={download} disabled={busy} className="vo-btn-primary">
              {busy ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
              {busy ? 'Preparing your PDF…' : 'Download pre-filled 21-526EZ (draft)'}
            </button>
            {err && <p className="text-xs font-medium" style={{ color: hueInk('rose') }}>{err}</p>}
            <p className="text-xs text-faint" style={{ color: label }}>
              We never store or fill your SSN, date of birth, or address — those stay with you.
            </p>
          </div>
        </div>
      </Panel>
    </div>
  )
}

function ContentionCard({ c, ink, label }: { c: Form526Contention; ink: string; label: string }) {
  return (
    <div className="rounded-control border border-line bg-surface2 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-base font-semibold text-txt">{c.name}</h3>
        <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: label }}>
          {humanize(c.claim_type)} claim
        </span>
      </div>
      <p className="mt-1 text-xs text-muted">
        {c.diagnostic_code ? `DC ${c.diagnostic_code}` : 'No diagnostic code'}
        {c.current_rating !== null ? ` · Currently rated ${formatPercent(c.current_rating)}` : ''}
        {c.onset_date ? ` · Onset ${formatDate(c.onset_date)}` : ''}
        {c.secondary_to_name ? ` · Secondary to ${c.secondary_to_name}` : ''}
      </p>
      {c.in_service_event && (
        <p className="mt-2 text-sm text-txt">
          <span className="font-semibold">In-service event: </span>
          {c.in_service_event}
        </p>
      )}
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <EvidenceList title="Evidence on hand" items={c.evidence_have} ink={hueInk('emerald')} empty="None recorded yet." />
        <EvidenceList title="Still needed" items={c.evidence_needed} ink={ink} empty="Nothing outstanding." />
      </div>
    </div>
  )
}

function EvidenceList({
  title,
  items,
  ink,
  empty,
}: {
  title: string
  items: Form526EvidenceRef[]
  ink: string
  empty: string
}) {
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide" style={{ color: ink }}>
        {title}
      </p>
      {items.length === 0 ? (
        <p className="text-xs text-faint">{empty}</p>
      ) : (
        <ul className="space-y-1.5 text-sm text-txt">
          {items.map((e, i) => (
            <li key={i} className="flex gap-2">
              <CheckCircle2 size={14} className="mt-0.5 shrink-0" style={{ color: ink }} />
              <span>
                {e.title} <span className="text-xs text-faint">({humanize(e.kind)})</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function GuidancePanel({ data, ink }: { data: Form526Packet; ink: string }) {
  return (
    <Panel hue={HUE} title="How to file this" subtitle="You file it — Rating Raider never does">
      <div className="p-5">
        <ol className="space-y-2.5 text-sm text-txt">
          {data.guidance.map((g, i) => (
            <li key={i} className="flex gap-2.5">
              <span
                aria-hidden
                className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                style={{ background: hueSoftVar(HUE), color: ink }}
              >
                {i + 1}
              </span>
              <span className="leading-relaxed">{g}</span>
            </li>
          ))}
        </ol>
        <div
          className="mt-4 rounded-control border-l-2 px-3 py-2 text-xs italic leading-relaxed text-faint"
          style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
        >
          {data.source_note}
        </div>
        <p className="mt-3 text-xs italic leading-relaxed text-faint">{data.disclaimer}</p>
      </div>
    </Panel>
  )
}

/** Prominent legal-lane note: this is never filed for you; a VSO files for free. */
function LegalLaneBanner() {
  return (
    <div className="vo-card vo-accent relative flex items-start gap-3.5 overflow-hidden p-5" style={hueStyle(HUE) as CSSProperties}>
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}
      >
        <ShieldCheck size={20} />
      </div>
      <div>
        <h2 className="text-sm font-semibold text-txt">Prepared for your review and signature — never filed for you</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          This is your own data assembled into VA Form 21-526EZ so you can review it in one place — as a clean worksheet
          and as the pre-filled official PDF below. Rating Raider never submits anything. You file it yourself at VA.gov,
          or a VA-accredited VSO — VFW, DAV, The American Legion, or your state/county veterans office — files it with you
          for free.
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
