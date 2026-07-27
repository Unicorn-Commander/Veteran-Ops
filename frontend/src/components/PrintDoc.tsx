import { Wordmark } from './Brand'
import { DISCLAIMER_TEXT } from './Disclaimer'
import { formatDate } from '../lib/format'

// Shared print-document type system + checkbox-list styling for the
// standalone print artifacts (RecordsPrintViews.tsx, Packet.tsx). Scoped to
// `.rr-doc` so it can't leak into the rest of the app.
//
// Print typography note: index.css's @media print block flattens color to
// #111/#ccc — by design (see comment there) — so the "designed document"
// feel here comes from layout/rule-work/type scale, which survives that
// flattening on paper. The refined-serif treatment is page-local (no serif
// stack is registered in tailwind.config.js).
export function PrintDocStyles() {
  return (
    <style>{`
      .rr-doc {
        font-family: 'Iowan Old Style', 'Palatino Linotype', Palatino, Georgia, 'Times New Roman', serif;
      }
      .rr-doc .rr-sans { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
      .rr-doc .rr-rule-label {
        display: flex; align-items: center; gap: 0.75rem;
        font-family: Inter, ui-sans-serif, system-ui, sans-serif;
        font-size: 0.6875rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.09em;
      }
      .rr-doc .rr-rule-label::after { content: ''; flex: 1; height: 1px; background: var(--border); }
      .rr-doc .rr-checklist { list-style: none; margin-left: 0; padding-left: 0; }
      .rr-doc .rr-checklist li { position: relative; padding-left: 1.7em; }
      .rr-doc .rr-checklist li::before {
        content: ''; position: absolute; left: 0; top: 0.2em;
        width: 0.9em; height: 0.9em; border: 1.5px solid currentColor; border-radius: 3px; opacity: 0.55;
      }
      @media print {
        .rr-doc { font-family: Georgia, 'Times New Roman', serif; }
        .rr-doc section { break-inside: avoid; }
      }
    `}</style>
  )
}

/** Letterhead: the Rating Raider mark as a document header, generated
 * timestamp as a formal "prepared" line. */
export function Letterhead({ preparedFor }: { preparedFor?: string | null }) {
  return (
    <header className="rr-sans mb-8 flex items-start justify-between gap-6 border-b-2 border-line pb-5">
      <Wordmark size={34} />
      <div className="text-right">
        <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-faint">Prepared</p>
        <p className="mt-0.5 text-sm text-muted">{formatDate(new Date().toISOString())}</p>
        {preparedFor && <p className="mt-1 text-sm font-semibold text-txt">for {preparedFor}</p>}
      </div>
    </header>
  )
}

/** Standard "important notice" disclaimer footer for print artifacts. */
export function DisclaimerFooterBlock({ text }: { text?: string | null }) {
  return (
    <footer className="rr-sans mt-12 border-t border-line pt-5">
      <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-faint">Important notice</p>
      <p className="mx-0 mt-1.5 max-w-[70ch] text-xs italic leading-relaxed text-faint">{text || DISCLAIMER_TEXT}</p>
    </footer>
  )
}
