/**
 * Single primary "continue" hero — always driven by resolveNextAction(claimProgress).
 */
import { ArrowRight, Loader2 } from 'lucide-react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import {
  buildClaimProgress,
  progressCounts,
  resolveNextAction,
  type ClaimProgressInput,
} from '../lib/claimProgress'
import { hueInk, hueSoftVar, hueStyle } from '../lib/hues'

const STEP_HUE: Record<string, 'violet' | 'amber' | 'emerald' | 'sky' | 'teal' | 'indigo'> = {
  profile: 'violet',
  records: 'amber',
  processing: 'amber',
  review: 'amber',
  case: 'emerald',
  analysis: 'sky',
  plan: 'teal',
  file: 'indigo',
  done: 'emerald',
}

export function ClaimContinue({
  input,
  subtitle,
}: {
  input: ClaimProgressInput
  /** Optional line under the product caption (e.g. journey stage). */
  subtitle?: string
}) {
  const action = resolveNextAction(input)
  const counts = progressCounts(input)
  const steps = buildClaimProgress(input)
  const hue = STEP_HUE[action.stepId] ?? 'violet'

  return (
    <section
      className="vo-card vo-accent p-5 sm:p-6"
      style={hueStyle(hue) as CSSProperties}
      aria-labelledby="claim-continue-title"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <p className="text-micro font-bold uppercase tracking-wide" style={{ color: hueInk(hue) }}>
            Your next step
            {subtitle ? ` · ${subtitle}` : ''}
          </p>
          <h2 id="claim-continue-title" className="mt-0.5 text-lg font-bold leading-snug text-txt">
            {action.title}
          </h2>
          <p className="mt-0.5 max-w-xl text-sm leading-relaxed text-muted">{action.detail}</p>
          <p className="mt-2 text-xs text-faint">
            Path progress: {counts.completed} of {counts.total} main steps
            <span className="mx-1.5 text-line" aria-hidden>
              ·
            </span>
            {counts.percent}%
          </p>
          {/* Mini track — stable order, done vs current */}
          <ol className="mt-3 flex flex-wrap gap-1.5" aria-label="Claim path steps">
            {steps.map((s) => (
              <li key={s.id}>
                <Link
                  to={s.route}
                  className="inline-flex min-h-8 items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold transition-colors"
                  style={
                    s.done
                      ? {
                          borderColor: 'transparent',
                          background: hueSoftVar('emerald'),
                          color: hueInk('emerald'),
                        }
                      : s.current
                        ? {
                            borderColor: 'var(--hue-violet)',
                            background: hueSoftVar('violet'),
                            color: hueInk('violet'),
                          }
                        : { borderColor: 'var(--border)', color: 'var(--muted)' }
                  }
                >
                  {s.done ? '✓ ' : s.current ? '→ ' : ''}
                  {s.label}
                </Link>
              </li>
            ))}
          </ol>
        </div>
        <div className="flex flex-col items-stretch gap-2 sm:items-end">
          <Link to={action.route} className="vo-btn-primary min-h-11 text-sm">
            {action.busy ? <Loader2 size={15} className="animate-spin" /> : null}
            {action.cta} <ArrowRight size={15} />
          </Link>
          <Link to="/journey" className="text-xs font-semibold text-muted hover:text-txt">
            Full journey map
          </Link>
        </div>
      </div>
    </section>
  )
}
