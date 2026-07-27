import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { ErrorBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { formatDate } from '../lib/format'
import { CORRECTION_PACKET_KEY } from './Corrections'
import type { CorrectionPacket } from '../types'

// Standalone print view for a military-records correction application packet.
// Same pattern as Form526Print.tsx / AppealsPrint.tsx: no Shell chrome, one print
// button, a refined-letterhead document. The packet is handed over via
// sessionStorage (CORRECTION_PACKET_KEY) by pages/Corrections.tsx. This is a
// REVIEW draft — the veteran reads it, signs it, and files it themselves with the
// MILITARY review board (DRB / BCMR/BCNR / PDBR), not the VA. Veteran-Ops never
// files anything, never gives legal advice, and never promises an outcome. The
// veteran's own words are reproduced VERBATIM.

function readPacket(): CorrectionPacket | null {
  try {
    const raw = sessionStorage.getItem(CORRECTION_PACKET_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as CorrectionPacket
    if (!parsed?.route || !parsed.heading) return null
    return parsed
  } catch {
    return null
  }
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

function Section({ children }: { children: ReactNode }) {
  return <section className="mt-8">{children}</section>
}

function CorrectionBody({ packet }: { packet: CorrectionPacket }) {
  const { route } = packet
  return (
    <div className="rr-doc">
      <PrintDocStyles />
      <Letterhead preparedFor={packet.applicant_name || undefined} />
      <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">{packet.heading}</h1>
      <p className="rr-sans mt-1.5 text-sm text-muted">
        A draft records-correction application assembled from what you told us — not a filed document. Review it, sign
        it, and file it yourself with the military review board (not the VA), or hand it to a free VSO or veterans law
        clinic. Veteran-Ops never submits anything, never gives legal advice, and never promises an outcome.
      </p>

      <Section>
        <SectionLabel n={1} title="Where this is filed" />
        <p className="mt-3 text-sm leading-relaxed text-txt">
          <strong>{route.board_full ?? route.board ?? 'Military review board'}</strong>
          {route.form && (
            <>
              {' '}
              — <span className="rr-sans">{route.form}</span>
              {route.form_title ? `, ${route.form_title}` : ''}
            </>
          )}
          .
        </p>
        {route.why && <p className="rr-sans mt-2 text-sm leading-relaxed text-muted">{route.why}</p>}
        {route.deadline_note && <p className="rr-sans mt-2 text-sm text-txt">{route.deadline_note}</p>}
        {route.character_of_discharge_note && (
          <p className="rr-sans mt-2 text-sm text-muted">{route.character_of_discharge_note}</p>
        )}
        {route.liberal_consideration?.applies && route.liberal_consideration.note && (
          <p className="rr-sans mt-2 text-sm text-txt">
            <strong>Liberal consideration:</strong> {route.liberal_consideration.note}
          </p>
        )}
      </Section>

      <Section>
        <SectionLabel n={2} title="Corrections requested" />
        {packet.corrections_requested.length > 0 ? (
          <table className="rr-sans mt-3 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase text-faint">
                <th className="py-1.5 pr-3 font-semibold">Field / item</th>
                <th className="py-1.5 pr-3 font-semibold">Currently reads</th>
                <th className="py-1.5 font-semibold">Should read</th>
              </tr>
            </thead>
            <tbody>
              {packet.corrections_requested.map((c, i) => (
                <tr key={i} className="border-b border-line align-top">
                  <td className="py-2 pr-3 font-medium text-txt">{c.field}</td>
                  <td className="py-2 pr-3 text-txt">{c.current || '—'}</td>
                  <td className="py-2 text-txt">{c.requested || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="rr-sans mt-3 text-sm text-muted">No specific corrections itemized.</p>
        )}
      </Section>

      <Section>
        <SectionLabel n={3} title="Statement of error or injustice" />
        <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-txt">
          {packet.statement_of_error_or_injustice}
        </p>
        {packet.veteran_statement && (
          <div className="mt-4">
            <p className="rr-sans text-[11px] uppercase tracking-wide text-faint">My statement (in my own words)</p>
            <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-txt">{packet.veteran_statement}</p>
          </div>
        )}
      </Section>

      <Section>
        <SectionLabel n={4} title="Evidence to attach" />
        {packet.evidence_checklist.length > 0 ? (
          <ul className="rr-checklist mt-3 space-y-2 text-sm text-txt">
            {packet.evidence_checklist.map((e, i) => (
              <li key={i}>
                <span className="font-medium">{e.item}</span>
                {e.why && <span className="rr-sans block text-xs text-muted">{e.why}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="rr-sans mt-3 text-sm text-muted">No evidence items listed.</p>
        )}
      </Section>

      <Section>
        <SectionLabel n={5} title="How to file this" />
        {packet.instructions.length > 0 ? (
          <ol className="mt-3 space-y-2 text-sm text-txt">
            {packet.instructions.map((step, i) => (
              <li key={i} className="flex gap-2.5">
                <span className="rr-sans mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface2 text-[11px] text-muted">
                  {i + 1}
                </span>
                <span className="leading-relaxed">{step}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="rr-sans mt-3 text-sm text-muted">No filing steps provided.</p>
        )}
      </Section>

      <Section>
        <SectionLabel n={6} title="Attestation & signature" />
        <p className="mt-3 text-sm leading-relaxed text-txt">{packet.attestation}</p>
        <p className="rr-sans mt-4 whitespace-pre-wrap text-sm leading-relaxed text-txt">{packet.signature_block}</p>
      </Section>

      <Section>
        <SectionLabel n={7} title="Free help" />
        {route.legal_aid_referral && (
          <p className="rr-sans mt-3 text-sm leading-relaxed text-txt">{route.legal_aid_referral}</p>
        )}
        {route.vso_referral && <p className="rr-sans mt-2 text-sm leading-relaxed text-muted">{route.vso_referral}</p>}
        {packet.source_note && (
          <p className="rr-sans mt-2 text-xs italic leading-relaxed text-faint">{packet.source_note}</p>
        )}
        {packet.prepared_on && (
          <p className="rr-sans mt-2 text-xs text-faint">Prepared {formatDate(packet.prepared_on)}.</p>
        )}
      </Section>

      <DisclaimerFooterBlock text={packet.disclaimer} />
    </div>
  )
}

export function CorrectionsPrint() {
  const packet = readPacket()
  if (!packet) {
    return (
      <div data-section="records">
        <PrintShell backTo="/corrections" backLabel="Back to Corrections">
          <div className="mx-auto max-w-xl py-10">
            <ErrorBlock message="No application to show yet — open Fix your military record and build your application first." />
            <p className="mt-4 text-center text-sm text-muted">
              <Link to="/corrections" className="font-semibold text-brand hover:text-brand-hover">
                Open Fix your military record
              </Link>
            </p>
          </div>
        </PrintShell>
      </div>
    )
  }
  return (
    <div data-section="records">
      <PrintShell backTo="/corrections" backLabel="Back to Corrections">
        <CorrectionBody packet={packet} />
      </PrintShell>
    </div>
  )
}
