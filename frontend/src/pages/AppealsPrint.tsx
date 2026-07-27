import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { ErrorBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { formatDate } from '../lib/format'
import type { AppealDraftContentionOut, AppealDraftOut, DecodeOption } from '../types'

// Standalone print view for a drafted decision-review response (Supplemental
// Claim / Higher-Level Review / Board Appeal). Same pattern as Form526Print.tsx:
// no Shell chrome, one print button, a refined-letterhead document. The draft is
// handed over via sessionStorage by pages/Appeals.tsx. This is a REVIEW draft —
// the veteran reads it, signs it, and files it themselves at VA.gov or hands it to
// a free VSO. Rating Raider never submits anything and never renders a medical
// opinion. The veteran's own words are reproduced VERBATIM.

/** Kept local to both files (Appeals.tsx defines the same string). */
const APPEAL_DRAFT_KEY = 'vo_appeal_draft'

function readDraft(): AppealDraftOut | null {
  try {
    const raw = sessionStorage.getItem(APPEAL_DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as AppealDraftOut
    if (!parsed?.lane_form || !Array.isArray(parsed.contentions)) return null
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

function DeadlineLine({ deadline }: { deadline: AppealDraftOut['deadline'] }) {
  if (!deadline || !deadline.deadline) {
    return (
      <p className="rr-sans mt-3 text-sm text-muted">
        Decision date not detected — confirm your one-year filing window against the decision letter itself.
      </p>
    )
  }
  const days = deadline.days_remaining
  return (
    <p className="rr-sans mt-3 text-sm text-txt">
      Filing within one year of the decision preserves your original effective date. That one-year window{' '}
      {deadline.expired ? 'closed' : 'ends'} on <strong>{formatDate(deadline.deadline)}</strong>
      {typeof days === 'number' && (deadline.expired ? ` (${Math.abs(days)} days ago)` : ` — ${days} days remaining`)}.
      Deadlines have exceptions; confirm yours with a VSO.
    </p>
  )
}

function ContentionBlock({ c, i }: { c: AppealDraftContentionOut; i: number }) {
  return (
    <div className="mt-5 border-t border-line pt-4 first:mt-3 first:border-t-0 first:pt-0">
      <h3 className="text-[17px] font-semibold text-txt">
        {i + 1}. {c.name}
        {c.diagnostic_code && <span className="rr-sans ml-2 text-xs text-muted">DC {c.diagnostic_code}</span>}
      </h3>

      {c.missing_element_plain.length > 0 && (
        <div className="mt-2">
          <p className="rr-sans text-[11px] uppercase tracking-wide text-faint">What VA said was missing</p>
          <ul className="rr-checklist mt-1 space-y-1 text-sm text-txt">
            {c.missing_element_plain.map((m, j) => (
              <li key={j}>{m}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-3">
        <p className="rr-sans text-[11px] uppercase tracking-wide text-faint">New &amp; relevant evidence</p>
        {c.new_and_relevant_evidence.length > 0 ? (
          <ul className="rr-checklist mt-1 space-y-1 text-sm text-txt">
            {c.new_and_relevant_evidence.map((e, j) => (
              <li key={j}>{e}</li>
            ))}
          </ul>
        ) : (
          <p className="rr-sans mt-0.5 text-sm italic text-faint">None attached to this contention.</p>
        )}
      </div>

      {c.veteran_statement && (
        <div className="mt-3">
          <p className="rr-sans text-[11px] uppercase tracking-wide text-faint">My statement (in my own words)</p>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-txt">{c.veteran_statement}</p>
        </div>
      )}

      <p className="rr-sans mt-3 text-sm italic text-muted">{c.what_this_addresses}</p>
    </div>
  )
}

function LaneGuidance({ lanes }: { lanes: DecodeOption[] }) {
  if (lanes.length === 0) return null
  return (
    <ul className="mt-3 space-y-3">
      {lanes.map((l) => (
        <li key={l.key}>
          <p className="text-sm font-semibold text-txt">{l.title}</p>
          <p className="rr-sans text-xs text-muted">
            <em>{l.when}</em> {l.detail}
          </p>
        </li>
      ))}
    </ul>
  )
}

function ResponseBody({ draft }: { draft: AppealDraftOut }) {
  return (
    <div className="rr-doc">
      <PrintDocStyles />
      <Letterhead />
      <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">{draft.heading}</h1>
      <p className="rr-sans mt-1.5 text-sm text-muted">
        A draft decision-review response assembled from what you selected — not a filed document. Review it, sign it, and
        file it yourself at VA.gov or hand it to a free VSO. Rating Raider never submits anything and never renders a
        medical opinion.
      </p>

      <Section>
        <SectionLabel n={1} title={`${draft.lane_title} — VA Form ${draft.lane_form}`} />
        <p className="mt-3 text-sm leading-relaxed text-txt">{draft.intro}</p>
      </Section>

      <Section>
        <SectionLabel n={2} title="Contentions" />
        {draft.contentions.length > 0 ? (
          draft.contentions.map((c, i) => <ContentionBlock key={i} c={c} i={i} />)
        ) : (
          <p className="rr-sans mt-3 text-sm text-muted">No contentions selected.</p>
        )}
      </Section>

      <Section>
        <SectionLabel n={3} title="Filing deadline" />
        <DeadlineLine deadline={draft.deadline} />
      </Section>

      <Section>
        <SectionLabel n={4} title="Your review options (educational)" />
        <LaneGuidance lanes={draft.lane_guidance} />
      </Section>

      <Section>
        <SectionLabel n={5} title="Attestation & signature" />
        <p className="mt-3 text-sm leading-relaxed text-txt">{draft.veteran_attestation}</p>
        <p className="rr-sans mt-4 whitespace-pre-wrap text-sm leading-relaxed text-txt">{draft.signature_block}</p>
      </Section>

      <Section>
        <SectionLabel n={6} title="Free help" />
        <p className="rr-sans mt-3 text-sm leading-relaxed text-muted">{draft.vso_referral}</p>
        <p className="rr-sans mt-2 text-xs italic leading-relaxed text-faint">{draft.source_note}</p>
      </Section>

      <DisclaimerFooterBlock text={draft.disclaimer} />
    </div>
  )
}

export function AppealsPrint() {
  const draft = readDraft()
  if (!draft) {
    return (
      <div data-section="insight">
        <PrintShell backTo="/appeals" backLabel="Back to Appeals">
          <div className="mx-auto max-w-xl py-10">
            <ErrorBlock message="No draft to show yet — open Appeal a denial and build your response first." />
            <p className="mt-4 text-center text-sm text-muted">
              <Link to="/appeals" className="font-semibold text-brand hover:text-brand-hover">
                Open Appeal a denial
              </Link>
            </p>
          </div>
        </PrintShell>
      </div>
    )
  }
  return (
    <div data-section="insight">
      <PrintShell backTo="/appeals" backLabel="Back to Appeals">
        <ResponseBody draft={draft} />
      </PrintShell>
    </div>
  )
}
