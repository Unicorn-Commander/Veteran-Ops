import { Link } from 'react-router-dom'
import { ErrorBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { STATEMENT_DRAFT_KEY, type StatementPrintState } from './Statement'
import type { StatementDraft, StatementDraftInput } from '../types'

// Standalone print view for the personal statement (VA Form 21-4138). Same
// pattern as BuddyPrint.tsx: no Shell chrome, one print button, refined
// letterhead document. The draft is handed over via sessionStorage
// (STATEMENT_DRAFT_KEY) by pages/Statement.tsx. Rating Raider never submits —
// these are the VETERAN'S own words; they read this, sign it, and file it.

function readState(): StatementPrintState | null {
  try {
    const raw = sessionStorage.getItem(STATEMENT_DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StatementPrintState
    if (!parsed?.draft?.statement_markdown) return null
    return parsed
  } catch {
    return null
  }
}

/** Render the deterministic 21-4138 markdown as a clean printed document. The
 * backend emits a small, fixed set of block types (H1/H2/HR/paragraphs + a
 * bold-label signature line) — we style those, not a full markdown engine. */
function StatementBody({ draft, inputs }: { draft: StatementDraft; inputs: StatementDraftInput }) {
  const lines = draft.statement_markdown.split('\n')
  const blocks: React.ReactNode[] = []
  let para: string[] = []

  const flushPara = (key: string) => {
    if (para.length === 0) return
    const text = para.join(' ')
    blocks.push(
      <p key={key} className="mt-3 text-[15px] leading-relaxed text-txt">
        {renderInline(text)}
      </p>,
    )
    para = []
  }

  lines.forEach((raw, i) => {
    const line = raw.trimEnd()
    if (line.trim() === '') {
      flushPara(`p-${i}`)
      return
    }
    if (line.startsWith('# ')) {
      flushPara(`p-${i}`)
      // The H1 is the document title — rendered by the header instead; skip.
      return
    }
    if (line.startsWith('## ')) {
      flushPara(`p-${i}`)
      blocks.push(
        <p key={`h-${i}`} className="rr-rule-label mt-8 text-muted">
          {line.slice(3).trim()}
        </p>,
      )
      return
    }
    if (line.trim() === '---') {
      flushPara(`p-${i}`)
      blocks.push(<hr key={`hr-${i}`} className="mt-8 border-t border-line" />)
      return
    }
    para.push(line)
  })
  flushPara('p-final')

  return (
    <div className="rr-doc">
      <PrintDocStyles />
      <Letterhead preparedFor={inputs.veteran_name || undefined} />
      <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">
        {draft.form} — {draft.form_title}
      </h1>
      <p className="rr-sans mt-1.5 text-sm text-muted">
        Your own statement, formatted for you to review and sign. Rating Raider never rewords it and never submits it —
        you (or your VSO) file it with the claim.
      </p>

      <section className="mt-7">{blocks}</section>

      {draft.guidance.length > 0 && (
        <section className="vo-no-print mt-8">
          <p className="rr-rule-label text-muted">Before you sign</p>
          <ul className="rr-checklist mt-3 space-y-2 text-sm text-txt">
            {draft.guidance.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </section>
      )}

      <DisclaimerFooterBlock text={draft.disclaimer} />
    </div>
  )
}

/** Minimal inline renderer: **bold** and the rest as plain text (the backend
 * only ever emits bold labels — no other inline markdown). */
function renderInline(text: string): React.ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return (
        <strong key={i} className="font-semibold text-txt">
          {part.slice(2, -2)}
        </strong>
      )
    }
    return <span key={i}>{part}</span>
  })
}

export function StatementPrint() {
  const state = readState()
  if (!state) {
    return (
      <div data-section="records">
        <PrintShell backTo="/statement" backLabel="Back to Personal statement">
          <div className="mx-auto max-w-xl py-10">
            <ErrorBlock message="No statement to show yet — open the Personal statement builder and write it first." />
            <p className="mt-4 text-center text-sm text-muted">
              <Link to="/statement" className="font-semibold text-brand hover:text-brand-hover">
                Open the Personal statement builder
              </Link>
            </p>
          </div>
        </PrintShell>
      </div>
    )
  }
  return (
    <div data-section="records">
      <PrintShell backTo="/statement" backLabel="Back to Personal statement">
        <StatementBody draft={state.draft} inputs={state.inputs} />
      </PrintShell>
    </div>
  )
}
