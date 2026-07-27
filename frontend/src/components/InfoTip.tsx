import { Info } from 'lucide-react'
import { useId, type ReactNode } from 'react'

/** Shared bubble: absolutely positioned, hidden until the wrapping `.group` is
 * hovered OR contains keyboard focus (`group-focus-within`), so it's reachable
 * without a mouse. Motion is handled globally by the prefers-reduced-motion
 * rule in index.css, which collapses every transition to ~instant. */
function TipBubble({ id, side, children }: { id: string; side: 'top' | 'bottom'; children: ReactNode }) {
  return (
    <span
      role="tooltip"
      id={id}
      className={`pointer-events-none absolute left-1/2 z-50 w-max max-w-[15rem] -translate-x-1/2 whitespace-normal rounded-control border border-line bg-surface px-2.5 py-1.5 text-xs font-normal leading-snug text-txt opacity-0 shadow-pop transition-opacity duration-150 group-hover:opacity-100 group-focus-within:opacity-100 ${
        side === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5'
      }`}
    >
      {children}
    </span>
  )
}

/** Wrap any (non-interactive) content in a keyboard-reachable tooltip. The
 * wrapper is focusable and points at the bubble via `aria-describedby`, so a
 * screen reader announces the child's text followed by the description. Use for
 * badges, chips, and status dots that need an on-hover/-focus explanation. */
export function Tooltip({
  content,
  children,
  side = 'top',
  className = '',
}: {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'bottom'
  className?: string
}) {
  const id = useId()
  return (
    <span className={`group relative inline-flex ${className}`}>
      <span
        tabIndex={0}
        aria-describedby={id}
        className="inline-flex rounded-control focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        {children}
      </span>
      <TipBubble id={id} side={side}>
        {content}
      </TipBubble>
    </span>
  )
}

/** A small, focusable "i" affordance whose whole job is to explain a nearby
 * symbol or heading. The button carries the tip as both its accessible name
 * (`aria-label`) and its visible bubble, so mouse and keyboard users get the
 * same help. */
export function InfoTip({
  label,
  content,
  side = 'top',
  className = '',
}: {
  /** Accessible name for the button (a plain string). */
  label: string
  /** Rich visible bubble; defaults to `label`. */
  content?: ReactNode
  side?: 'top' | 'bottom'
  className?: string
}) {
  const id = useId()
  return (
    <span className={`group relative inline-flex ${className}`}>
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-line text-faint transition-colors hover:text-txt focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        <Info size={11} aria-hidden />
      </button>
      <TipBubble id={id} side={side}>
        {content ?? label}
      </TipBubble>
    </span>
  )
}
