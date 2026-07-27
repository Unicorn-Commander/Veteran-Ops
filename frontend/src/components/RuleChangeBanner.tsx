import { AlertTriangle, Clock, ExternalLink } from 'lucide-react'
import type { CSSProperties } from 'react'
import { ruleChangeForDc } from '../lib/ruleChanges'
import { formatDate } from '../lib/format'
import { hueStyle } from '../lib/hues'
import { cx } from './ui'

/**
 * Surfaces a VA rating-rule change relevant to a diagnostic code — a FINAL rule
 * that already changed the criteria (amber, "changed"), or a PROPOSED rewrite that
 * is not final (sky, "proposed"). Legal lane: states what the rule says + its date
 * + source; for proposed rules it never claims the change is certain or predicts an
 * effect. Renders nothing when the diagnostic code has no curated note.
 */
export function RuleChangeBanner({
  diagnosticCode,
  className,
}: {
  diagnosticCode: string | null | undefined
  className?: string
}) {
  const note = ruleChangeForDc(diagnosticCode)
  if (!note) return null

  const changed = note.status === 'changed'
  const Icon = changed ? AlertTriangle : Clock
  return (
    <div
      className={cx(
        'vo-accent rounded-control border border-line bg-surface2 px-3.5 py-3 text-sm',
        className
      )}
      style={hueStyle(changed ? 'amber' : 'sky') as CSSProperties}
      role="note"
    >
      <div className="flex items-start gap-2.5">
        <Icon size={16} className={cx('mt-0.5 shrink-0', changed ? 'text-warn' : 'text-muted')} aria-hidden="true" />
        <div className="min-w-0">
          <p className="font-medium text-txt">
            {note.title}
            <span className="ml-1.5 text-xs font-normal text-muted">
              {changed ? 'effective' : 'proposed'} {formatDate(`${note.date}T00:00:00`)}
            </span>
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{note.summary}</p>
          <p className="mt-1.5 text-xs leading-relaxed text-txt">{note.actionHint}</p>
          <a
            href={note.sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="mt-1.5 inline-flex min-h-10 items-center gap-1 rounded-control px-1 text-xs font-semibold text-brand hover:text-brand-hover"
          >
            Read the official rule <ExternalLink size={12} aria-hidden="true" />
            <span className="sr-only"> (opens in a new tab)</span>
          </a>
        </div>
      </div>
    </div>
  )
}
