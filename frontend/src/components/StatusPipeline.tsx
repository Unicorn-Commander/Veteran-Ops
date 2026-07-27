import { cx } from './ui'
import { hueInk, hueVar, STATUS_HUES } from '../lib/hues'
import { humanize } from '../lib/format'
import type { ConditionStatus } from '../types'

// Status pipeline: considering → gathering → ready → filed → decided.
// Shared by Conditions.tsx (compact, no labels) and ConditionDetail.tsx
// (larger, with a label under each step) via the `showLabels` prop.
const STATUS_ORDER: ConditionStatus[] = ['considering', 'gathering_evidence', 'ready_to_file', 'filed', 'decided']

export function StatusPipeline({
  status,
  compact = false,
  showLabels = false,
}: {
  status: ConditionStatus
  /** Smaller step dots + connectors — used in row/list contexts. */
  compact?: boolean
  /** Larger step dots with a label beneath each — used in the detail header. */
  showLabels?: boolean
}) {
  const idx = STATUS_ORDER.indexOf(status)
  return (
    <div
      className={cx('flex items-center', showLabels && 'flex-wrap gap-x-1 gap-y-2')}
      role="img"
      aria-label={`Status: ${humanize(status)}, step ${idx + 1} of ${STATUS_ORDER.length}`}
    >
      {STATUS_ORDER.map((s, i) => {
        const done = i < idx
        const active = i === idx
        const hueKey = STATUS_HUES[s] ?? 'sky'
        const hue = hueVar(hueKey)
        const ink = hueInk(hueKey)
        const dot = (
          <span
            className={cx(
              'flex shrink-0 items-center justify-center rounded-full border font-bold transition-colors',
              showLabels ? 'h-6 w-6 text-[11px]' : compact ? 'h-4 w-4 text-[9px]' : 'h-5 w-5 text-[10px]'
            )}
            style={{
              borderColor: active || done ? hue : 'var(--border)',
              background: active ? `color-mix(in srgb, ${hue} 18%, transparent)` : 'transparent',
              color: active || done ? ink : 'var(--faint)',
            }}
          >
            {done ? '✓' : i + 1}
          </span>
        )
        return (
          <div key={s} className="flex items-center">
            {showLabels ? (
              <div className="flex flex-col items-center gap-1">
                {dot}
                <span
                  className={cx('whitespace-nowrap text-[10px] font-medium', active ? 'text-txt' : 'text-faint')}
                  style={active ? { color: ink } : undefined}
                >
                  {humanize(s)}
                </span>
              </div>
            ) : (
              dot
            )}
            {i < STATUS_ORDER.length - 1 && (
              <span
                aria-hidden
                className={cx('h-px shrink-0', showLabels ? 'mb-4 w-4 sm:w-8' : compact ? 'w-2' : 'w-3 sm:w-4')}
                style={{ background: i < idx ? hue : 'var(--border)' }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
