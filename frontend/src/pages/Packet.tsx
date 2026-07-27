import { ArrowLeft, Printer } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ErrorBlock, LoadingBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { useAsync } from '../hooks/useAsync'
import { packetApi } from '../lib/api'
import { formatDate, formatPercent, humanize } from '../lib/format'
import type { ContinuityCheckin, PacketEvidence, PacketEvidenceIndexItem } from '../types'

// Shared print-document styling (type system, checklist, letterhead,
// disclaimer footer) lives in ../components/PrintDoc.tsx — also used by
// RecordsPrintViews.tsx, the other standalone print artifact.

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-7">
      <p className="rr-rule-label text-muted">{title}</p>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function EvidenceLine({ e, showStatus }: { e: PacketEvidence; showStatus?: boolean }) {
  return (
    <li>
      {e.title}{' '}
      <span className="rr-sans text-xs text-faint">
        ({humanize(e.kind)}
        {showStatus ? ` · ${humanize(e.status)}` : ''}
        {e.source ? ` · ${e.source}` : ''})
      </span>
      {e.notes && <p className="rr-sans text-xs text-muted">{e.notes}</p>}
    </li>
  )
}

function PacketCitation({ citation }: { citation: PacketEvidenceIndexItem['citations'][number] }) {
  return (
    <li className={citation.selected ? 'rounded border border-brand bg-brand-soft/20 p-2.5' : 'rounded border border-line bg-surface2 p-2.5'}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="rr-sans text-xs font-semibold text-txt">
            {citation.source_title}
            {citation.page ? ` · p. ${citation.page}` : ''}
            {citation.selected ? ' · selected' : ''}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-txt">{citation.quote}</p>
          {citation.note && <p className="mt-1 text-xs text-muted">Note: {citation.note}</p>}
        </div>
      </div>
    </li>
  )
}

function checkinScores(c: ContinuityCheckin): string {
  const parts: string[] = []
  if (c.pain !== null && c.pain !== undefined && c.pain !== '') parts.push(`pain ${c.pain}`)
  if (c.mood !== null && c.mood !== undefined && c.mood !== '') parts.push(`mood ${c.mood}`)
  if (c.energy !== null && c.energy !== undefined && c.energy !== '') parts.push(`energy ${c.energy}`)
  return parts.join(' · ')
}

export function Packet() {
  const { id } = useParams<{ id: string }>()
  const { data: packet, loading, error, reload } = useAsync(() => packetApi.get(id!), [id])

  if (loading) return <LoadingBlock label="Building your packet…" />
  if (error || !packet) {
    return (
      <div className="p-6">
        <ErrorBlock message={error ?? 'Could not load this packet.'} onRetry={reload} />
        <Link to={`/conditions/${id}`} className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-brand">
          <ArrowLeft size={14} /> Back to condition
        </Link>
      </div>
    )
  }

  const { condition, dc_card } = packet
  const dc = condition.diagnostic_code ?? dc_card?.diagnostic_code

  return (
    <div data-section="records" className="min-h-screen bg-bg">
      {/* Screen-only controls — the packet body below stays print-neutral */}
      <div className="vo-no-print vo-section-band flex items-center justify-between border-b border-line px-4 py-3 sm:px-6">
        <Link to={`/conditions/${id}`} className="inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-txt">
          <ArrowLeft size={14} /> Back to condition
        </Link>
        <button onClick={() => window.print()} className="vo-btn-primary text-sm">
          <Printer size={14} /> Print
        </button>
      </div>

      <div className="vo-print-page mx-auto max-w-3xl px-6 py-10">
        <div className="rr-doc">
          <PrintDocStyles />

          <Letterhead preparedFor={packet.veteran.name} />

          <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">{condition.name}</h1>
          <p className="rr-sans mt-1.5 text-sm text-muted">
            {condition.body_system ? humanize(condition.body_system) : 'Body system not set'}
            {dc ? ` · DC ${dc}` : ''}
            {' · '}
            {humanize(condition.claim_type)} claim
            {' · '}
            {humanize(condition.status)}
            {condition.current_rating !== null ? ` · Currently rated ${formatPercent(condition.current_rating)}` : ''}
            {condition.onset_date ? ` · Onset ${formatDate(condition.onset_date)}` : ''}
          </p>

          {dc_card && (
            <Section title={`Rating criteria — ${dc_card.title}`}>
              {dc_card.tiers.length > 0 ? (
                <table className="rr-sans w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-line text-left text-[11px] uppercase text-faint">
                      <th className="py-1.5 pr-3 font-semibold">%</th>
                      <th className="py-1.5 font-semibold">Criteria</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dc_card.tiers.map((tier, i) => (
                      <tr key={i} className="border-b border-line align-top">
                        <td className="py-2 pr-3 font-semibold text-txt">{tier.percent}%</td>
                        <td className="py-2 text-txt">
                          {tier.criteria}
                          {tier.evidence_needed.length > 0 && (
                            <p className="mt-1 text-xs text-muted">
                              Evidence to show: {tier.evidence_needed.join('; ')}
                            </p>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="whitespace-pre-line text-sm text-txt">{dc_card.content}</p>
              )}
              <p className="rr-sans mt-2 text-xs text-faint">Source: {dc_card.source}</p>
            </Section>
          )}

          <Section title="Evidence on hand">
            {packet.evidence_have.length === 0 ? (
              <p className="rr-sans text-sm text-muted">None recorded yet.</p>
            ) : (
              <ul className="rr-checklist space-y-2 text-sm text-txt">
                {packet.evidence_have.map((e) => (
                  <EvidenceLine key={e.id} e={e} />
                ))}
              </ul>
            )}
          </Section>

          {packet.evidence_index && packet.evidence_index.length > 0 && (
            <Section title="Evidence index">
              <p className="rr-sans mb-2 text-sm text-muted">
                For each piece of evidence, this shows why it counts and the exact quote to find in your records.
              </p>
              <div className="space-y-3">
                {packet.evidence_index.map((item) => {
                  const selected = item.citations.find((c) => c.selected) ?? item.citations[0] ?? null
                  return (
                    <div key={item.id} className="rounded-control border border-line bg-surface2 p-3">
                      <p className="text-sm font-semibold text-txt">{item.title}</p>
                      <p className="rr-sans mt-0.5 text-xs text-faint">
                        {humanize(item.kind)}
                        {item.source ? ` · ${item.source}` : ''}
                        {item.document_id ? ' · linked to your records' : ''}
                      </p>
                      {item.rationale && (
                        <div className="mt-2 rounded-control border border-line bg-surface p-3">
                          <p className="rr-sans text-xs uppercase tracking-wide text-faint">
                            Why this counts
                          </p>
                          <p className="mt-1 text-sm font-medium text-txt">
                            {item.rationale.elements.length > 0 ? item.rationale.elements.join(' · ') : 'General support'}
                          </p>
                          <p className="mt-1 text-sm leading-relaxed text-txt">{item.rationale.why}</p>
                        </div>
                      )}
                      <div className="mt-2">
                        <p className="rr-sans text-xs uppercase tracking-wide text-faint">In your records</p>
                        {selected ? (
                          <ul className="mt-2 space-y-2">
                            <PacketCitation citation={selected} />
                            {item.citations.filter((c) => c !== selected).map((citation) => (
                              <PacketCitation key={`${citation.document_id}-${citation.chunk_index}-${citation.char_start}`} citation={citation} />
                            ))}
                          </ul>
                        ) : (
                          <p className="mt-1 text-sm text-muted">No matching quote found yet.</p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </Section>
          )}

          {packet.evidence_excerpts && packet.evidence_excerpts.length > 0 && (
            <Section title="In your records">
              <p className="rr-sans mb-2 text-sm text-muted">
                Passages from your own uploaded documents that mention this condition — quoted so you (or your VSO) can
                point the rater straight to the page. Your text, not an interpretation.
              </p>
              <ul className="space-y-2.5">
                {packet.evidence_excerpts.map((x, i) => (
                  <li key={`${x.document_id}-${x.chunk_index}-${i}`} className="border-l-2 border-line pl-3">
                    <p className="rr-sans text-xs text-faint">{x.source}</p>
                    <p className="whitespace-pre-wrap text-sm text-txt">{x.excerpt}</p>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="Still needed">
            {packet.evidence_missing.length === 0 ? (
              <p className="rr-sans text-sm text-muted">Nothing outstanding.</p>
            ) : (
              <ul className="rr-checklist space-y-2 text-sm text-txt">
                {packet.evidence_missing.map((e) => (
                  <EvidenceLine key={e.id} e={e} showStatus />
                ))}
              </ul>
            )}
          </Section>

          {packet.gaps.length > 0 && (
            <Section title="Evidence gaps to close">
              <ul className="list-disc space-y-1.5 pl-5 text-sm text-txt">
                {packet.gaps.map((gap, i) => (
                  <li key={i}>
                    <strong>{gap.label}</strong>
                    {gap.detail && <> — {gap.detail}</>}
                    {gap.source && <span className="rr-sans ml-1 text-xs text-faint">({gap.source})</span>}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {packet.continuity.length > 0 && (
            <Section title="Continuity of care (symptom check-ins)">
              <p className="rr-sans mb-2 text-sm text-muted">
                Symptom check-ins recorded in Glitter Mane that mention this condition — evidence of ongoing symptoms.
              </p>
              <table className="rr-sans w-full border-collapse text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-[11px] uppercase text-faint">
                    <th className="py-1.5 pr-3 font-semibold">Date</th>
                    <th className="py-1.5 pr-3 font-semibold">Scores</th>
                    <th className="py-1.5 font-semibold">Symptoms / notes</th>
                  </tr>
                </thead>
                <tbody>
                  {packet.continuity.map((c, i) => (
                    <tr key={c.id ?? i} className="border-b border-line align-top">
                      <td className="whitespace-nowrap py-2 pr-3 text-txt">{formatDate(c.created_at ?? null)}</td>
                      <td className="whitespace-nowrap py-2 pr-3 text-muted">{checkinScores(c) || '—'}</td>
                      <td className="py-2 text-txt">
                        {[c.symptoms, c.note].filter(Boolean).join(' — ') || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          )}

          {packet.lay_statement_prompts.length > 0 && (
            <Section title="Lay statement prompts">
              <p className="rr-sans mb-2 text-sm text-muted">
                Questions to help you (or someone who knew you in service) write a specific, dated, first-person statement.
              </p>
              <ul className="list-disc space-y-1 pl-5 text-sm text-txt">
                {packet.lay_statement_prompts.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </Section>
          )}

          {(condition.nexus_notes || condition.in_service_event) && (
            <Section title="Your notes">
              {condition.in_service_event && (
                <p className="text-sm text-txt"><strong>In-service event:</strong> {condition.in_service_event}</p>
              )}
              {condition.nexus_notes && (
                <p className="mt-1 text-sm text-txt"><strong>Nexus notes:</strong> {condition.nexus_notes}</p>
              )}
            </Section>
          )}

          {packet.dbq && (
            <Section title="Suggested DBQ">
              <p className="text-sm text-txt">{packet.dbq}</p>
              <p className="rr-sans mt-1 text-xs text-muted">
                Ask your provider to complete this Disability Benefits Questionnaire during your appointment.
              </p>
            </Section>
          )}

          <DisclaimerFooterBlock text={packet.disclaimer} />
        </div>
      </div>
    </div>
  )
}
