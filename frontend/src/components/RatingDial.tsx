import { useEffect, useState } from 'react'
import { AnimatedNumber } from './ui'

/**
 * Big animated ring showing the veteran's current combined VA rating.
 * Purely presentational — the number it renders always comes from either
 * the profile's stored current_combined_rating or the rating engine's
 * combined result; this component performs no rating math itself.
 *
 * Motion: the arc draws in with expo-out easing while the center number
 * ticks up in sync; a glow cap rides the end of the arc. Both collapse to
 * an instant render under prefers-reduced-motion.
 */
export function RatingDial({
  value,
  size = 200,
  label = 'Combined rating',
}: {
  value: number
  size?: number
  label?: string
}) {
  const [animated, setAnimated] = useState(0)
  const clamped = Math.max(0, Math.min(100, value))

  useEffect(() => {
    const id = requestAnimationFrame(() => setAnimated(clamped))
    return () => cancelAnimationFrame(id)
  }, [clamped])

  const stroke = Math.max(10, Math.round(size * 0.07))
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (animated / 100) * circumference

  // End-cap position (arc starts at 12 o'clock; svg is rotated -90°, so
  // compute in unrotated coords starting from the +x axis).
  const angle = (animated / 100) * 2 * Math.PI
  const capX = size / 2 + radius * Math.cos(angle)
  const capY = size / 2 + radius * Math.sin(angle)

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${label}: ${clamped} percent`}
    >
      {/* Subtle multi-hue conic sheen behind the ring — a static, blurred
          sweep of the aurora hues that gives the dial its jewel quality.
          Painted below the svg (svg is position:relative, later in tree). */}
      <div
        aria-hidden
        className="absolute rounded-full"
        style={{
          inset: '5%',
          background:
            'conic-gradient(from 220deg, var(--hue-violet), var(--hue-fuchsia), var(--hue-sky), var(--hue-teal), var(--hue-violet))',
          opacity: 0.16,
          filter: 'blur(16px)',
        }}
      />
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="relative -rotate-90">
        <defs>
          <linearGradient id="vo-dial-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="var(--hue-violet)" />
            <stop offset="55%" stopColor="var(--hue-fuchsia)" />
            <stop offset="100%" stopColor="var(--hue-teal)" />
          </linearGradient>
        </defs>
        {/* Track */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--border)"
          strokeWidth={stroke}
        />
        {/* Quarter tick marks on the track */}
        {[25, 50, 75].map((t) => {
          const a = (t / 100) * 2 * Math.PI
          const inner = radius - stroke / 2 + 1.5
          const outer = radius + stroke / 2 - 1.5
          return (
            <line
              key={t}
              x1={size / 2 + inner * Math.cos(a)}
              y1={size / 2 + inner * Math.sin(a)}
              x2={size / 2 + outer * Math.cos(a)}
              y2={size / 2 + outer * Math.sin(a)}
              stroke="var(--bg)"
              strokeOpacity={0.55}
              strokeWidth={2}
            />
          )
        })}
        {/* Soft under-glow of the arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="url(#vo-dial-gradient)"
          strokeWidth={stroke + 6}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          opacity={0.18}
          style={{ transition: 'stroke-dashoffset 1s cubic-bezier(0.16,1,0.3,1)', filter: 'blur(4px)' }}
        />
        {/* The arc */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="url(#vo-dial-gradient)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 1s cubic-bezier(0.16,1,0.3,1)' }}
        />
        {/* Glow cap riding the end of the arc */}
        {clamped > 0 && (
          <circle
            cx={capX}
            cy={capY}
            r={Math.max(3, stroke * 0.28)}
            fill="#fff"
            opacity={0.9}
            style={{
              transition: 'cx 1s cubic-bezier(0.16,1,0.3,1), cy 1s cubic-bezier(0.16,1,0.3,1)',
              filter: 'drop-shadow(0 0 6px var(--hue-fuchsia))',
            }}
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="vo-wordmark font-extrabold tabular-nums" style={{ fontSize: size * 0.22 }}>
          <AnimatedNumber value={clamped} duration={1000} />%
        </span>
        <span className="mt-1 text-center text-xs font-medium text-muted" style={{ maxWidth: size * 0.7 }}>
          {label}
        </span>
      </div>
    </div>
  )
}
