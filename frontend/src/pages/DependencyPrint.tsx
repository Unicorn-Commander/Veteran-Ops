import { Link } from 'react-router-dom'
import { ErrorBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { DEPENDENCY_WORKSHEET_KEY, type DependencyPrintState } from './Dependency'
import type { DependencyWorksheet } from '../types'

// Standalone print view for the dependency worksheet (VA Form 21-686c / 21-509).
// Same pattern as TdiuPrint.tsx: no Shell chrome, one print button, refined
// letterhead document. The worksheet is handed over via sessionStorage
// (DEPENDENCY_WORKSHEET_KEY) by pages/Dependency.tsx. Rating Raider never submits
// and never decides dependency — the veteran reads this, signs it, and files it.

function readState(): DependencyPrintState | null {
  try {
    const raw = sessionStorage.getItem(DEPENDENCY_WORKSHEET_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as DependencyPrintState
    if (!parsed?.worksheet?.worksheet_markdown) return null
    return parsed
  } catch {
    return null
  }
}

/** Render the deterministic worksheet markdown as a clean printed document. The
 * backend emits a small, fixed set of block types (H1/H2/HR/list/paragraphs +
 * bold labels) — we style those, not a full markdown engine. */
function DependencyBody({ worksheet, veteranName }: { worksheet: DependencyWorksheet; veteranName: string }) {
  const lines = worksheet.worksheet_markdown.split('\n')
  const blocks: React.ReactNode[] = []
  let para: string[] = []
  let list: string[] = []

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

  const flushList = (key: string) => {
    if (list.length === 0) return
    blocks.push(
      <ul key={key} className="mt-3 space-y-1.5 pl-5 text-[15px] leading-relaxed text-txt">
        {list.map((item, i) => (
          <li key={i} className="list-disc">
            {renderInline(item)}
          </li>
        ))}
      </ul>,
    )
    list = []
  }

  lines.forEach((raw, i) => {
    const line = raw.trimEnd()
    if (line.trim() === '') {
      flushPara(`p-${i}`)
      flushList(`l-${i}`)
      return
    }
    if (line.startsWith('# ')) {
      flushPara(`p-${i}`)
      flushList(`l-${i}`)
      // The H1 is the document title — rendered by the header instead; skip.
      return
    }
    if (line.startsWith('## ')) {
      flushPara(`p-${i}`)
      flushList(`l-${i}`)
      blocks.push(
        <p key={`h-${i}`} className="rr-rule-label mt-8 text-muted">
          {line.slice(3).trim()}
        </p>,
      )
      return
    }
    if (line.trim() === '---') {
      flushPara(`p-${i}`)
      flushList(`l-${i}`)
      blocks.push(<hr key={`hr-${i}`} className="mt-8 border-t border-line" />)
      return
    }
    if (line.startsWith('- ') || line.startsWith('* ')) {
      flushPara(`p-${i}`)
      list.push(line.slice(2).trim())
      return
    }
    flushList(`l-${i}`)
    para.push(line)
  })
  flushPara('p-final')
  flushList('l-final')

  return (
    <div className="rr-doc">
      <PrintDocStyles />
      <Letterhead preparedFor={veteranName || undefined} />
      <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">
        {worksheet.form} — {worksheet.form_title}
      </h1>
      <p className="rr-sans mt-1.5 text-sm text-muted">
        Your dependency change, organized for you to review and sign. Rating Raider never decides dependency and never
        submits this — you (or your VSO) file it with VA. VA makes the determination.
      </p>

      <section className="mt-7">{blocks}</section>

      {worksheet.guidance.length > 0 && (
        <section className="vo-no-print mt-8">
          <p className="rr-rule-label text-muted">Before you sign</p>
          <ul className="rr-checklist mt-3 space-y-2 text-sm text-txt">
            {worksheet.guidance.map((g, i) => (
              <li key={i}>{g}</li>
            ))}
          </ul>
        </section>
      )}

      <DisclaimerFooterBlock text={worksheet.disclaimer} />
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

export function DependencyPrint() {
  const state = readState()
  if (!state) {
    return (
      <div data-section="records">
        <PrintShell backTo="/dependency" backLabel="Back to dependents workspace">
          <div className="mx-auto max-w-xl py-10">
            <ErrorBlock message="No worksheet to show yet — open the dependents workspace and fill in your change first." />
            <p className="mt-4 text-center text-sm text-muted">
              <Link to="/dependency" className="font-semibold text-brand hover:text-brand-hover">
                Open the dependents workspace
              </Link>
            </p>
          </div>
        </PrintShell>
      </div>
    )
  }
  return (
    <div data-section="records">
      <PrintShell backTo="/dependency" backLabel="Back to dependents workspace">
        <DependencyBody worksheet={state.worksheet} veteranName={state.veteranName} />
      </PrintShell>
    </div>
  )
}
