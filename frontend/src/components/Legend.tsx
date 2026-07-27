import { KeyRound } from 'lucide-react'
import { useId, type ReactNode } from 'react'

/** One row of a legend: the exact symbol the veteran sees on the page (a
 * HueBadge, a flag, a status chip) paired with a short plain-language meaning. */
export interface LegendItem {
  /** The symbol as it appears on the page — pass the real badge/chip so the key
   * matches what's rendered, not an approximation of it. */
  badge: ReactNode
  desc: string
}

export interface LegendGroup {
  label: string
  items: LegendItem[]
}

/** A calm, collapsible "what do these symbols mean?" key. Renders as a native
 * <details> so it's keyboard-reachable and collapsed by default — it stays out
 * of the way until a veteran wants it. Place it where the symbols cluster
 * (Documents, Analysis Center). */
export function Legend({
  title = 'What these symbols mean',
  groups,
  className = '',
}: {
  title?: string
  groups: LegendGroup[]
  className?: string
}) {
  const id = useId()
  return (
    <details className={`overflow-hidden rounded-control border border-line bg-surface2 ${className}`}>
      <summary
        aria-describedby={id}
        className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-xs font-semibold text-muted transition-colors hover:text-txt focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        <KeyRound size={13} className="shrink-0" /> {title}
      </summary>
      <div id={id} className="space-y-4 border-t border-line px-4 py-3.5">
        {groups.map((g) => (
          <div key={g.label}>
            <p className="mb-1.5 text-micro font-semibold uppercase tracking-wide text-faint">{g.label}</p>
            <ul className="grid gap-x-5 gap-y-2 sm:grid-cols-2">
              {g.items.map((it, i) => (
                <li key={i} className="flex items-start gap-2.5 text-sm">
                  <span className="mt-0.5 shrink-0">{it.badge}</span>
                  <span className="min-w-0 leading-snug text-muted">{it.desc}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </details>
  )
}
