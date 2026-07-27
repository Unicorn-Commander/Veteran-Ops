import { ExternalLink } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { ErrorBlock, LoadingBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { useAsync } from '../hooks/useAsync'
import { recordsApi } from '../lib/api'
import { formatDate } from '../lib/format'
import type { RecordsPrefill } from '../types'

// Standalone print views (same pattern as Packet.tsx: no Shell chrome, one
// print button). SF-180 and 20-10206 are worksheets only — a veteran copies
// the info onto the official form (or hands the worksheet to a VSO). Rating
// Raider never submits anything on the veteran's behalf.
//
// Shapes reconciled against the real backend/app/routers/records.py +
// schemas.RecordsPrefillOut: the response is {form, form_title, form_url,
// prefill: {...}, guidance: string[], note} — guidance is the step-by-step
// the backend authored, not something this page invents.
//
// Shared print-document styling (type system, checklist, letterhead,
// disclaimer footer) lives in ../components/PrintDoc.tsx — also used by
// Packet.tsx, the other standalone print artifact.

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <p className="rr-sans text-[11px] uppercase tracking-wide text-faint">{label}</p>
      <p className="mt-0.5 min-h-[1.4em] border-b border-dotted border-line2 pb-1 text-sm text-txt">
        {value || ' '}
      </p>
    </div>
  )
}

function SectionLabel({ n, title }: { n: number; title: string }) {
  return (
    <p className="rr-rule-label text-muted">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface2 text-[10px] text-muted">{n}</span>
      {title}
    </p>
  )
}

function VeteranInfoBlock({ data }: { data: RecordsPrefill }) {
  const { prefill } = data
  const periods = prefill.service_periods ?? []
  return (
    <section className="mt-7">
      <SectionLabel n={1} title="Veteran identifying information" />
      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
        <Field label="Full name" value={prefill.full_name} />
        <Field label="Social Security Number" value={undefined} />
        <Field label="Date of birth" value={undefined} />
        <Field label="State of residence" value={prefill.state} />
      </div>

      {periods.length > 0 ? (
        <table className="rr-sans mt-4 w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left text-[11px] uppercase text-faint">
              <th className="py-1.5 pr-3 font-semibold">Branch</th>
              <th className="py-1.5 pr-3 font-semibold">Component</th>
              <th className="py-1.5 pr-3 font-semibold">Service dates</th>
              <th className="py-1.5 font-semibold">Discharge character</th>
            </tr>
          </thead>
          <tbody>
            {periods.map((p, i) => (
              <tr key={i} className="border-b border-line">
                <td className="py-2 pr-3 text-txt">{p.branch}</td>
                <td className="py-2 pr-3 text-txt">{p.component}</td>
                <td className="py-2 pr-3 text-txt">
                  {formatDate(p.start_date)} – {formatDate(p.end_date)}
                </td>
                <td className="py-2 text-txt">{p.discharge_character}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="rr-sans mt-3 text-sm text-muted">
          No service periods on file yet — add them in your Profile so this worksheet prefills, or write them in by
          hand below.
        </p>
      )}
    </section>
  )
}

function MailingAddressBlock() {
  return (
    <section className="mt-7">
      <SectionLabel n={2} title="Your current mailing address" />
      <div className="mt-4 space-y-4">
        <div className="h-6 border-b border-dotted border-line2" />
        <div className="h-6 border-b border-dotted border-line2" />
        <div className="h-6 border-b border-dotted border-line2" />
      </div>
    </section>
  )
}

function RecordsRequestedBlock({ data }: { data: RecordsPrefill }) {
  const items = data.prefill.records_requested ?? []
  if (items.length === 0) return null
  return (
    <section className="mt-7">
      <SectionLabel n={3} title="What you're requesting" />
      <ul className="rr-checklist mt-3 space-y-2 text-sm text-txt">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </section>
  )
}

function GuidanceBlock({ data }: { data: RecordsPrefill }) {
  if (data.guidance.length === 0) return null
  return (
    <section className="mt-7">
      <p className="rr-rule-label text-muted">How to submit this</p>
      <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-txt">
        {data.guidance.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </section>
  )
}

function SignatureBlock() {
  return (
    <section className="mt-10 grid grid-cols-2 gap-8">
      <div>
        <div className="h-9 border-b border-line2" />
        <p className="rr-sans mt-1.5 text-[11px] text-faint">Veteran signature — sign after you review and copy this onto the official form</p>
      </div>
      <div>
        <div className="h-9 border-b border-line2" />
        <p className="rr-sans mt-1.5 text-[11px] text-faint">Date</p>
      </div>
    </section>
  )
}

function WorksheetHeader({ data }: { data: RecordsPrefill }) {
  return (
    <>
      <Letterhead preparedFor={data.prefill.full_name} />
      <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">{data.form} — {data.form_title}</h1>
      <p className="rr-sans mt-1.5 text-sm text-muted">
        This is a preparation worksheet, not the official form. {data.note}
      </p>
      <a
        href={data.form_url}
        target="_blank"
        rel="noreferrer"
        className="vo-no-print rr-sans mt-2.5 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
      >
        Get the official form <ExternalLink size={13} />
      </a>
    </>
  )
}

function WorksheetBody({ data }: { data: RecordsPrefill }) {
  return (
    <div className="rr-doc">
      <PrintDocStyles />
      <WorksheetHeader data={data} />
      <VeteranInfoBlock data={data} />
      <MailingAddressBlock />
      <RecordsRequestedBlock data={data} />
      <GuidanceBlock data={data} />
      <SignatureBlock />
      <DisclaimerFooterBlock />
    </div>
  )
}

export function Sf180Print() {
  const { data, loading, error, reload } = useAsync(() => recordsApi.sf180())
  if (loading) return <LoadingBlock label="Building your SF-180 worksheet…" />
  if (error || !data) {
    return (
      <div className="p-6">
        <ErrorBlock message={error ?? 'Could not load this worksheet.'} onRetry={reload} />
      </div>
    )
  }
  return (
    <div data-section="records">
      <PrintShell backTo="/records" backLabel="Back to Records">
        <WorksheetBody data={data} />
      </PrintShell>
    </div>
  )
}

export function Va2010206Print() {
  const { data, loading, error, reload } = useAsync(() => recordsApi.va20_10206())
  if (loading) return <LoadingBlock label="Building your VA 20-10206 worksheet…" />
  if (error || !data) {
    return (
      <div className="p-6">
        <ErrorBlock message={error ?? 'Could not load this worksheet.'} onRetry={reload} />
      </div>
    )
  }
  return (
    <div data-section="records">
      <PrintShell backTo="/records" backLabel="Back to Records">
        <WorksheetBody data={data} />
      </PrintShell>
    </div>
  )
}

interface RequestLetterPrintState {
  letter: string
  providerName: string
}

export function RequestLetterPrint() {
  const location = useLocation()
  const state = location.state as RequestLetterPrintState | null
  if (!state?.letter) {
    return (
      <div className="p-6">
        <ErrorBlock message="No letter to show — generate one from the Records page first." />
      </div>
    )
  }
  return (
    <div data-section="records">
      <PrintShell backTo="/records" backLabel="Back to Records">
        <div className="rr-doc">
          <PrintDocStyles />
          <Letterhead />
          <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">
            Records request letter — {state.providerName}
          </h1>
          <p className="rr-sans mt-1.5 text-sm text-muted">
            Review, sign, and mail (or hand-deliver) this yourself — Rating Raider prepared it for your signature only.
          </p>
          <div className="mt-7 whitespace-pre-wrap rounded-control border border-line bg-surface2 p-6 text-sm leading-relaxed text-txt">
            {state.letter}
          </div>
          <DisclaimerFooterBlock />
        </div>
      </PrintShell>
    </div>
  )
}
