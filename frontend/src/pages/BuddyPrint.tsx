import { Link } from 'react-router-dom'
import { ErrorBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { BUDDY_DRAFT_KEY, type BuddyPrintState } from './Buddy'
import type { BuddyDraft, BuddyDraftInput } from '../types'

// Standalone print view for the buddy/lay statement (VA Form 21-10210). Same
// pattern as RecordsPrintViews.tsx: no Shell chrome, one print button, refined
// letterhead document. The draft is handed over via sessionStorage
// (BUDDY_DRAFT_KEY) by pages/Buddy.tsx. Veteran-Ops never submits — the
// WITNESS reads this, edits it into their own words, and SIGNS it.

function readState(): BuddyPrintState | null {
  try {
    const raw = sessionStorage.getItem(BUDDY_DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as BuddyPrintState
    if (!parsed?.draft?.statement_markdown) return null
    return parsed
  } catch {
    return null
  }
}

/** Render the deterministic 21-10210 markdown as a clean printed document.
 * The backend emits a small, fixed set of block types (H1/H2/HR/paragraphs +
 * a bold-label signature line) — we style those, not a full markdown engine. */
function StatementBody({ draft, inputs }: { draft: BuddyDraft; inputs: BuddyDraftInput }) {
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
        A draft for the witness to review, put in their own words, and sign. Veteran-Ops never submits it — you (or
        your VSO) attach it to the claim as evidence.
      </p>

      <section className="mt-7">{blocks}</section>

      {draft.guidance.length > 0 && (
        <section className="vo-no-print mt-8">
          <p className="rr-rule-label text-muted">Before the witness signs</p>
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

export function BuddyPrint() {
  const state = readState()
  if (!state) {
    return (
      <div data-section="records">
        <PrintShell backTo="/buddy" backLabel="Back to Buddy statement">
          <div className="mx-auto max-w-xl py-10">
            <ErrorBlock message="No statement to show yet — open the Buddy statement builder and fill it in first." />
            <p className="mt-4 text-center text-sm text-muted">
              <Link to="/buddy" className="font-semibold text-brand hover:text-brand-hover">
                Open the Buddy statement builder
              </Link>
            </p>
          </div>
        </PrintShell>
      </div>
    )
  }
  return (
    <div data-section="records">
      <PrintShell backTo="/buddy" backLabel="Back to Buddy statement">
        <StatementBody draft={state.draft} inputs={state.inputs} />
      </PrintShell>
    </div>
  )
}
