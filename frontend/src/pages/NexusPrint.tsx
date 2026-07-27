import { Link } from 'react-router-dom'
import { ErrorBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { NEXUS_DRAFT_KEY, type NexusPrintState } from './Nexus'
import type { NexusDraft, NexusDraftInput } from '../types'

// Standalone print view for the medical-nexus opinion TEMPLATE. Same pattern as
// BuddyPrint.tsx: no Shell chrome, one print button, refined letterhead
// document. The draft is handed over via sessionStorage (NEXUS_DRAFT_KEY) by
// pages/Nexus.tsx. Rating Raider never renders the medical opinion — the
// [PROVIDER TO COMPLETE] sections are the provider's to write and sign.

function readState(): NexusPrintState | null {
  try {
    const raw = sessionStorage.getItem(NEXUS_DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as NexusPrintState
    if (!parsed?.draft?.letter_markdown) return null
    return parsed
  } catch {
    return null
  }
}

/** Minimal inline renderer: **bold** and the rest as plain text (the backend
 * emits bold labels — no other inline markdown). */
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

/** True for a single-asterisk *italic instruction* line (not **bold**). */
function isItalicNote(text: string): boolean {
  return text.startsWith('*') && !text.startsWith('**') && text.endsWith('*') && text.length > 2
}

/** Render the deterministic nexus-letter markdown as a clean printed document.
 * The backend emits a fixed set of block types: H1 (title, rendered in the
 * header), ## headings (with [PROVIDER TO COMPLETE] callouts), *italic* provider
 * instructions, --- rules, and paragraphs with **bold** labels. */
function LetterBody({ draft, inputs }: { draft: NexusDraft; inputs: NexusDraftInput }) {
  // Split into blank-line-separated paragraphs so multi-line blocks stay whole.
  const paras = draft.letter_markdown.split(/\n{2,}/)
  const blocks: React.ReactNode[] = []

  paras.forEach((raw, i) => {
    const block = raw.trim()
    if (!block) return

    // H1 document title — rendered by the header instead; skip.
    if (block.startsWith('# ')) return

    // Horizontal rule between the letter and the signature block.
    if (block === '---') {
      blocks.push(<hr key={`hr-${i}`} className="mt-8 border-t border-line" />)
      return
    }

    // Section headings. [PROVIDER TO COMPLETE] sections get a clear accent so
    // the reader knows exactly what the provider must supply.
    if (block.startsWith('## ')) {
      const heading = block.slice(3).trim()
      const providerOwned = heading.includes('[PROVIDER TO COMPLETE]')
      if (providerOwned) {
        blocks.push(
          <p
            key={`h-${i}`}
            className="rr-sans mt-8 rounded-md border-2 border-dashed border-line2 bg-surface2 px-3 py-2 text-[13px] font-bold uppercase tracking-wide text-txt"
          >
            {heading}
          </p>,
        )
      } else {
        blocks.push(
          <p key={`h-${i}`} className="rr-rule-label mt-8 text-muted">
            {heading}
          </p>,
        )
      }
      return
    }

    // Italic provider instructions — muted, so they read as guidance not opinion.
    if (isItalicNote(block)) {
      blocks.push(
        <p key={`i-${i}`} className="rr-sans mt-3 text-[13px] italic leading-relaxed text-muted">
          {block.replace(/^\*+/, '').replace(/\*+$/, '').trim()}
        </p>,
      )
      return
    }

    // Ordinary paragraph — preserve internal line breaks (blank-fill lines).
    const lines = block.split('\n')
    blocks.push(
      <p key={`p-${i}`} className="mt-3 text-[15px] leading-relaxed text-txt">
        {lines.map((ln, k) => (
          <span key={k}>
            {renderInline(ln)}
            {k < lines.length - 1 && <br />}
          </span>
        ))}
      </p>,
    )
  })

  return (
    <div className="rr-doc">
      <PrintDocStyles />
      <Letterhead preparedFor={inputs.veteran_name || undefined} />
      <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">
        Medical Nexus Opinion Letter
      </h1>
      <p className="rr-sans mt-1.5 text-sm text-muted">
        A template to bring to your provider. The opinion and rationale — the [PROVIDER TO COMPLETE] sections — are the
        provider's to write and sign in their own clinical judgment. Rating Raider does not supply the medical opinion.
      </p>

      <section className="mt-7">{blocks}</section>

      {draft.guidance.length > 0 && (
        <section className="vo-no-print mt-8">
          <p className="rr-rule-label text-muted">Before you bring it to your provider</p>
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

export function NexusPrint() {
  const state = readState()
  if (!state) {
    return (
      <div data-section="records">
        <PrintShell backTo="/nexus" backLabel="Back to Nexus letter">
          <div className="mx-auto max-w-xl py-10">
            <ErrorBlock message="No nexus letter to show yet — open the Nexus letter builder and fill it in first." />
            <p className="mt-4 text-center text-sm text-muted">
              <Link to="/nexus" className="font-semibold text-brand hover:text-brand-hover">
                Open the Nexus letter builder
              </Link>
            </p>
          </div>
        </PrintShell>
      </div>
    )
  }
  return (
    <div data-section="records">
      <PrintShell backTo="/nexus" backLabel="Back to Nexus letter">
        <LetterBody draft={state.draft} inputs={state.inputs} />
      </PrintShell>
    </div>
  )
}
