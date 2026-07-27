import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { ErrorBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { formatDate, formatPercent, humanize } from '../lib/format'
import { FORM526_KEY } from './Form526'
import type { Form526Contention, Form526Packet } from '../types'

// Standalone print view for the 21-526EZ application. Same pattern as
// RecordsPrintViews.tsx / BuddyPrint.tsx: no Shell chrome, one print button, a
// refined-letterhead document. The assembled packet is handed over via
// sessionStorage (FORM526_KEY) by pages/Form526.tsx. This is a REVIEW worksheet
// — the veteran reads it, signs it, and files it themselves at VA.gov or hands
// it to a free VSO. Rating Raider never submits anything.

function readPacket(): Form526Packet | null {
  try {
    const raw = sessionStorage.getItem(FORM526_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Form526Packet
    if (!parsed?.completeness) return null
    return parsed
  } catch {
    return null
  }
}

function s(v: unknown): string {
  return v === null || v === undefined ? '' : String(v)
}

function SectionLabel({ n, title }: { n: number; title: string }) {
  return (
    <p className="rr-rule-label text-muted">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface2 text-[10px] text-muted">
        {n}
      </span>
      {title}
    </p>
  )
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <p className="rr-sans text-[11px] uppercase tracking-wide text-faint">{label}</p>
      <p className="mt-0.5 min-h-[1.4em] border-b border-dotted border-line2 pb-1 text-sm text-txt">{value || ' '}</p>
    </div>
  )
}

function EvidenceLines({ items, label }: { items: Form526Contention['evidence_have']; label: string }) {
  if (items.length === 0) {
    return (
      <p className="rr-sans mt-0.5 text-xs text-muted">
        {label}: <span className="italic text-faint">none recorded</span>
      </p>
    )
  }
  return (
    <div className="mt-0.5">
      <p className="rr-sans text-[11px] uppercase tracking-wide text-faint">{label}</p>
      <ul className="rr-checklist mt-1 space-y-1 text-sm text-txt">
        {items.map((e, i) => (
          <li key={i}>
            {e.title} <span className="rr-sans text-xs text-faint">({humanize(e.kind)})</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ContentionBlock({ c, i }: { c: Form526Contention; i: number }) {
  return (
    <div className="mt-5 border-t border-line pt-4 first:mt-3 first:border-t-0 first:pt-0">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[17px] font-semibold text-txt">
          {i + 1}. {c.name}
        </h3>
        <span className="rr-sans text-xs uppercase tracking-wide text-muted">{humanize(c.claim_type)} claim</span>
      </div>
      <p className="rr-sans mt-1 text-sm text-muted">
        {c.diagnostic_code ? `DC ${c.diagnostic_code}` : 'No diagnostic code'}
        {c.current_rating !== null ? ` · Currently rated ${formatPercent(c.current_rating)}` : ''}
        {c.onset_date ? ` · Onset ${formatDate(c.onset_date)}` : ''}
        {c.secondary_to_name ? ` · Secondary to ${c.secondary_to_name}` : ''}
      </p>
      {c.in_service_event && (
        <p className="mt-2 text-sm text-txt">
          <strong>In-service event:</strong> {c.in_service_event}
        </p>
      )}
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        <EvidenceLines items={c.evidence_have} label="Evidence on hand" />
        <EvidenceLines items={c.evidence_needed} label="Still needed" />
      </div>
    </div>
  )
}

function Section({ children }: { children: ReactNode }) {
  return <section className="mt-8">{children}</section>
}

function ApplicationBody({ packet }: { packet: Form526Packet }) {
  const { veteran, service, contentions, itf, completeness } = packet
  return (
    <div className="rr-doc">
      <PrintDocStyles />
      <Letterhead preparedFor={veteran.name || undefined} />
      <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">
        VA Form 21-526EZ — Application for Disability Compensation
      </h1>
      <p className="rr-sans mt-1.5 text-sm text-muted">
        A review worksheet assembled from your own records — not the official fillable form. Review it, then file it
        yourself at VA.gov or hand it to a free VSO. Rating Raider never submits anything on your behalf.
      </p>

      <Section>
        <SectionLabel n={1} title="Veteran" />
        <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <Field label="Full name" value={veteran.name} />
          <Field label="Email" value={veteran.email} />
        </div>
      </Section>

      <Section>
        <SectionLabel n={2} title="Military service" />
        {service.periods.length > 0 ? (
          <table className="rr-sans mt-3 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase text-faint">
                <th className="py-1.5 pr-3 font-semibold">Branch</th>
                <th className="py-1.5 pr-3 font-semibold">Component</th>
                <th className="py-1.5 pr-3 font-semibold">Service dates</th>
                <th className="py-1.5 font-semibold">Discharge</th>
              </tr>
            </thead>
            <tbody>
              {service.periods.map((p, i) => (
                <tr key={i} className="border-b border-line">
                  <td className="py-2 pr-3 text-txt">{s(p.branch)}</td>
                  <td className="py-2 pr-3 text-txt">{s(p.component)}</td>
                  <td className="py-2 pr-3 text-txt">
                    {formatDate(s(p.start_date) || null)} – {formatDate(s(p.end_date) || null)}
                  </td>
                  <td className="py-2 text-txt">{s(p.discharge_character)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="rr-sans mt-3 text-sm text-muted">No service periods on file.</p>
        )}
        <p className="rr-sans mt-3 text-sm text-txt">
          <strong>Combat service:</strong> {service.combat ? 'Yes' : 'Not indicated'}
        </p>
        <p className="rr-sans mt-1 text-sm text-txt">
          <strong>Toxic / environmental exposures:</strong>{' '}
          {service.exposures.length > 0 ? service.exposures.join(', ') : 'None recorded'}
        </p>
      </Section>

      <Section>
        <SectionLabel n={3} title="Conditions claimed (contentions)" />
        <p className="rr-sans mb-1 mt-2 text-xs text-faint">
          {completeness.conditions} condition{completeness.conditions === 1 ? '' : 's'} · {completeness.with_evidence}{' '}
          with evidence on hand · {completeness.missing_evidence} still needing evidence
        </p>
        {contentions.length > 0 ? (
          contentions.map((c, i) => <ContentionBlock key={i} c={c} i={i} />)
        ) : (
          <p className="rr-sans mt-2 text-sm text-muted">No conditions added yet.</p>
        )}
      </Section>

      <Section>
        <SectionLabel n={4} title="Intent to File" />
        {itf ? (
          <p className="rr-sans mt-3 text-sm text-txt">
            {humanize(itf.type)} Intent to File — filed {formatDate(itf.filed_date)}, effective-date protection through{' '}
            {formatDate(itf.deadline)} ({itf.days_remaining} days remaining). File your full claim before the deadline.
          </p>
        ) : (
          <p className="rr-sans mt-3 text-sm text-muted">
            No active Intent to File on record. Filing an ITF first locks in your effective date (and back pay) for one
            year.
          </p>
        )}
      </Section>

      <section className="mt-10 grid grid-cols-2 gap-8">
        <div>
          <div className="h-9 border-b border-line2" />
          <p className="rr-sans mt-1.5 text-[11px] text-faint">
            Veteran signature — sign after you review this and transcribe it onto VA.gov (or hand it to your VSO)
          </p>
        </div>
        <div>
          <div className="h-9 border-b border-line2" />
          <p className="rr-sans mt-1.5 text-[11px] text-faint">Date</p>
        </div>
      </section>

      <DisclaimerFooterBlock text={packet.disclaimer} />
    </div>
  )
}

export function Form526Print() {
  const packet = readPacket()
  if (!packet) {
    return (
      <div data-section="records">
        <PrintShell backTo="/application" backLabel="Back to Application">
          <div className="mx-auto max-w-xl py-10">
            <ErrorBlock message="No application to show yet — open the Application builder and review it first." />
            <p className="mt-4 text-center text-sm text-muted">
              <Link to="/application" className="font-semibold text-brand hover:text-brand-hover">
                Open the Application builder
              </Link>
            </p>
          </div>
        </PrintShell>
      </div>
    )
  }
  return (
    <div data-section="records">
      <PrintShell backTo="/application" backLabel="Back to Application">
        <ApplicationBody packet={packet} />
      </PrintShell>
    </div>
  )
}
