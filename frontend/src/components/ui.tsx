import type { CSSProperties, InputHTMLAttributes, ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import { AlertCircle, RefreshCw } from 'lucide-react'
import { hueStyle, hueVar, type Hue } from '../lib/hues'

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

export function Spinner({ size = 18, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      className={cx('animate-spin', className)}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-16 text-muted" role="status" aria-live="polite">
      <Spinner />
      <span className="text-sm">{label}</span>
    </div>
  )
}

export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  const dangerInk = 'color-mix(in srgb, var(--danger) var(--mix-ink, 92%), var(--txt))'
  return (
    <div
      className="animate-pop-in flex flex-col items-center justify-center gap-3 rounded-2xl border border-[color-mix(in_oklab,var(--danger)_40%,transparent)] bg-danger-soft px-6 py-12 text-center"
      role="alert"
    >
      <AlertCircle size={26} aria-hidden="true" style={{ color: dangerInk }} />
      <p className="max-w-sm text-sm" style={{ color: dangerInk }}>{message}</p>
      {onRetry && (
        <button type="button" onClick={onRetry} className="vo-btn-secondary mt-1">
          <RefreshCw size={15} />
          Try again
        </button>
      )}
    </div>
  )
}

/** Shared spring checkbox — the styled .vo-check input with a label slot.
 * Whole row is the hit target (≥40px). Use everywhere a checkbox appears. */
export function Checkbox({
  label,
  description,
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: ReactNode
  description?: ReactNode
  className?: string
}) {
  return (
    <label
      className={cx(
        'group flex min-h-[2.5rem] cursor-pointer items-start gap-3 rounded-control border border-line bg-surface2 p-3.5 text-sm transition-colors duration-150 hover:border-line2',
        props.disabled && 'cursor-not-allowed opacity-60',
        className
      )}
    >
      <input type="checkbox" className="vo-check mt-0.5" {...props} />
      <span className="min-w-0">
        <span className="font-medium text-txt">{label}</span>
        {description && <span className="mt-0.5 block text-xs leading-relaxed text-muted">{description}</span>}
      </span>
    </label>
  )
}

/** Number that ticks up (or down) to its value with expo-out easing.
 * Respects prefers-reduced-motion (renders instantly). Purely visual —
 * always pass the real, already-computed value. */
export function AnimatedNumber({
  value,
  duration = 900,
  format = (n: number) => String(Math.round(n)),
  className,
}: {
  value: number
  duration?: number
  format?: (n: number) => string
  className?: string
}) {
  const [display, setDisplay] = useState(value)
  const fromRef = useRef(value)
  const mounted = useRef(false)

  useEffect(() => {
    if (!mounted.current) {
      // First paint animates from 0 so dashboards "count in".
      mounted.current = true
      fromRef.current = 0
    }
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const from = fromRef.current
    if (reduce || from === value) {
      fromRef.current = value
      setDisplay(value)
      return
    }
    let raf = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 4) // expo-ish out
      setDisplay(from + (value - from) * eased)
      if (t < 1) raf = requestAnimationFrame(tick)
      else fromRef.current = value
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value, duration])

  return (
    <span className={cx('tabular-nums', className)}>
      {format(display)}
    </span>
  )
}

/** On-brand empty-state illustration: aurora-gradient orbit rings with a
 * sprinkle of hue stars around the icon. Pass any lucide icon as children. */
function EmptyArt({ hue = 'violet', icon }: { hue?: Hue; icon?: ReactNode }) {
  const h = hueVar(hue)
  return (
    <div className="relative h-24 w-24" aria-hidden="true">
      <svg viewBox="0 0 96 96" className="absolute inset-0 h-full w-full">
        <defs>
          <linearGradient id="vo-empty-ring" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--hue-violet)" />
            <stop offset="55%" stopColor="var(--hue-fuchsia)" />
            <stop offset="100%" stopColor="var(--hue-teal)" />
          </linearGradient>
        </defs>
        {/* orbit rings */}
        <circle cx="48" cy="48" r="43" fill="none" stroke="url(#vo-empty-ring)" strokeOpacity="0.35" strokeWidth="1.5" strokeDasharray="3 7" strokeLinecap="round" />
        <circle cx="48" cy="48" r="31" fill="none" stroke={h} strokeOpacity="0.25" strokeWidth="1.5" />
        {/* soft center */}
        <circle cx="48" cy="48" r="21" fill={h} fillOpacity="0.12" />
        {/* orbit satellites */}
        <circle cx="48" cy="5" r="3" fill={h} fillOpacity="0.9" />
        <circle cx="83" cy="66" r="2.4" fill="var(--hue-teal)" fillOpacity="0.8" />
        <circle cx="14" cy="70" r="2" fill="var(--hue-fuchsia)" fillOpacity="0.8" />
        {/* four-point stars */}
        <path d="M78 22 l1.6 4 4 1.6 -4 1.6 -1.6 4 -1.6 -4 -4 -1.6 4 -1.6 z" fill={h} fillOpacity="0.55" />
        <path d="M17 30 l1.2 3 3 1.2 -3 1.2 -1.2 3 -1.2 -3 -3 -1.2 3 -1.2 z" fill="var(--hue-teal)" fillOpacity="0.5" />
      </svg>
      <div
        className="absolute inset-0 flex items-center justify-center"
        style={{ color: h }}
      >
        {icon}
      </div>
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  hue = 'violet',
}: {
  icon?: ReactNode
  title: string
  description?: string
  action?: ReactNode
  /** Identity hue for the illustration — match the surrounding panel. */
  hue?: Hue
}) {
  return (
    <div className="animate-pop-in flex flex-col items-center justify-center gap-4 rounded-2xl border border-dashed border-line bg-surface/50 px-6 py-12 text-center">
      <EmptyArt hue={hue} icon={icon} />
      <div>
        <h3 className="text-heading text-txt">{title}</h3>
        {description && <p className="mx-auto mt-1.5 max-w-sm text-sm leading-relaxed text-muted">{description}</p>}
      </div>
      {action}
    </div>
  )
}

type Tone = 'neutral' | 'primary' | 'accent' | 'success' | 'warning' | 'danger'

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: Tone }) {
  const tones: Record<Tone, string> = {
    neutral: 'border-line bg-surface2 text-muted',
    primary: 'border-brand/40 bg-brand-soft text-brand',
    accent: 'border-h-teal bg-h-teal-soft text-h-teal',
    success: 'border-success/40 bg-h-emerald-soft text-success',
    warning: 'border-warn/40 bg-h-amber-soft text-warn',
    danger: 'border-[color-mix(in_oklab,var(--danger)_40%,transparent)] bg-danger-soft text-danger',
  }
  return <span className={cx('vo-chip', tones[tone])}>{children}</span>
}

/** Hue chip: identity-colored badge (claim type, evidence status, program). */
export function HueBadge({ hue, children }: { hue: Hue; children: ReactNode }) {
  return (
    <span className="vo-chip-hue" style={hueStyle(hue) as CSSProperties}>
      {children}
    </span>
  )
}

export function Panel({
  title,
  subtitle,
  action,
  children,
  className,
  bodyClassName,
  hue,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
  bodyClassName?: string
  hue?: Hue
}) {
  return (
    // Always vo-accent: with no explicit hue the hairline reads the inherited
    // --hue, i.e. the page's section hue (section-identity contract) — so
    // every panel quietly carries its section's color unless overridden.
    <section
      className={cx('vo-panel vo-accent flex flex-col overflow-hidden', className)}
      style={hue ? (hueStyle(hue) as CSSProperties) : undefined}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <div className="flex min-w-0 items-center gap-2.5">
            {hue && (
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: hueVar(hue), boxShadow: `0 0 8px ${hueVar(hue)}` }}
              />
            )}
            <div className="min-w-0">
              {title && <h2 className="truncate text-heading text-txt">{title}</h2>}
              {subtitle && <p className="truncate text-xs text-muted">{subtitle}</p>}
            </div>
          </div>
          {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={cx('flex-1', bodyClassName)}>{children}</div>
    </section>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx('vo-skel h-4 w-full', className)} aria-hidden />
}
