interface LogoProps {
  size?: number
  className?: string
}

/** The Rating Raider mark — the CWO's unicorn mascot. */
export function Logo({ size = 36, className = '' }: LogoProps) {
  return (
    <span
      className={`vo-logo-tile inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full shadow-sm ${className}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      <img
        src="/logo-mark.png"
        alt=""
        width={Math.round(size * 0.82)}
        height={Math.round(size * 0.82)}
        className="object-contain"
        draggable={false}
      />
    </span>
  )
}

interface WordmarkProps {
  size?: number
  withTagline?: boolean
  className?: string
}

/** App chrome wordmark. Per docs/BRANDING.md the product/app/platform name is
 * **Veteran-Ops**; **Rating Raider** is the in-product agent and stays scoped to
 * the agent surface (/raider, "Ask Raider", agent tools and thinking states). */
export function Wordmark({ size = 36, withTagline = false, className = '' }: WordmarkProps) {
  return (
    <div className={`flex items-center gap-2.5 ${className}`}>
      <Logo size={size} />
      <div className="leading-tight">
        <div className="flex items-baseline gap-1">
          <span
            className="vo-wordmark font-bold tracking-tight"
            style={{ fontSize: Math.round(size * 0.5) }}
          >
            Veteran-Ops
          </span>
        </div>
        {withTagline && (
          <span className="text-xs font-medium text-muted">Organize your VA claim</span>
        )}
      </div>
    </div>
  )
}
