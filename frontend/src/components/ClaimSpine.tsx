/**
 * Auto spine — the claim workflow as sequential rings after records exist.
 * Complements Journey's full ring list with a tight "where you are → next".
 */
import { ArrowRight, Check, Circle } from 'lucide-react'
import { Link } from 'react-router-dom'
import { hueInk, hueSoftVar, hueStyle } from '../lib/hues'
import type { CSSProperties } from 'react'

export interface SpineStep {
  id: string
  label: string
  route: string
  done: boolean
  current?: boolean
}

export function ClaimSpine({
  steps,
  title = 'Your claim spine',
  className,
  dualUseRecords = true,
}: {
  steps: SpineStep[]
  title?: string
  className?: string
  /** When true (default), mention dual-use with Glitter Mane. When false, keep claim-only copy. */
  dualUseRecords?: boolean
}) {
  if (steps.length === 0) return null
  const next = steps.find((s) => !s.done) ?? steps[steps.length - 1]
  return (
    <div
      className={`vo-card vo-accent p-4 sm:p-5 ${className ?? ''}`}
      style={hueStyle('violet') as CSSProperties}
      role="navigation"
      aria-label={title}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-micro font-bold uppercase tracking-wide" style={{ color: hueInk('violet') }}>
            {title}
          </p>
          <p className="mt-0.5 text-sm text-muted">
            {dualUseRecords
              ? 'Records can serve both health (Glitter Mane) and claim evidence — confirm each step for the claim file.'
              : 'Confirm each step before it becomes claim-side fact. You stay in control of every item.'}
          </p>
        </div>
        {next && (
          <Link to={next.route} className="vo-btn-primary min-h-11 shrink-0 text-sm">
            {next.done ? 'Review' : 'Continue'}: {next.label} <ArrowRight size={14} />
          </Link>
        )}
      </div>
      <ol className="mt-4 flex flex-wrap gap-2">
        {steps.map((s, i) => (
          <li key={s.id}>
            <Link
              to={s.route}
              className="inline-flex min-h-10 items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors"
              style={
                s.done
                  ? {
                      borderColor: 'transparent',
                      background: hueSoftVar('emerald'),
                      color: hueInk('emerald'),
                    }
                  : s.current || s.id === next?.id
                    ? {
                        borderColor: 'var(--hue-violet)',
                        background: hueSoftVar('violet'),
                        color: hueInk('violet'),
                      }
                    : { borderColor: 'var(--border)', color: 'var(--muted)' }
              }
            >
              {s.done ? <Check size={12} /> : <Circle size={12} />}
              <span className="tabular-nums text-faint">{i + 1}.</span> {s.label}
            </Link>
          </li>
        ))}
      </ol>
    </div>
  )
}
