import { useEffect, type RefObject } from 'react'

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

/**
 * Trap keyboard focus inside `containerRef` while `active`. Built for modal
 * dialogs (disclaimer gate, ITF confirm, mobile nav) so keyboard + screen-reader
 * users can't Tab out into the app behind the overlay.
 *
 * On activate: remembers the previously-focused element, then moves focus into
 * the container — preferring an element marked `[data-autofocus]` (e.g. the
 * dialog heading with `tabIndex={-1}`), else the first focusable control, else
 * the container itself. Tab / Shift+Tab then cycle within the container.
 *
 * On deactivate / unmount: restores focus to the previously-focused element,
 * falling back to `<main>` if that element is gone.
 */
export function useFocusTrap(containerRef: RefObject<HTMLElement | null>, active = true) {
  useEffect(() => {
    if (!active) return
    const container = containerRef.current
    if (!container) return

    const previouslyFocused = document.activeElement as HTMLElement | null

    const focusables = () =>
      Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
        (el) => el.offsetParent !== null || el === document.activeElement
      )

    // Move focus in: dialog heading (data-autofocus) → first control → container.
    const autofocus = container.querySelector<HTMLElement>('[data-autofocus]')
    ;(autofocus ?? focusables()[0] ?? container).focus()

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Tab') return
      const items = focusables()
      if (items.length === 0) {
        // Nothing focusable inside — keep focus on the container itself.
        e.preventDefault()
        container.focus()
        return
      }
      const firstEl = items[0]
      const lastEl = items[items.length - 1]
      const activeEl = document.activeElement
      if (e.shiftKey) {
        if (activeEl === firstEl || !container.contains(activeEl)) {
          e.preventDefault()
          lastEl.focus()
        }
      } else if (activeEl === lastEl || !container.contains(activeEl)) {
        e.preventDefault()
        firstEl.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown, true)
    return () => {
      document.removeEventListener('keydown', onKeyDown, true)
      const restore =
        previouslyFocused && document.contains(previouslyFocused)
          ? previouslyFocused
          : document.querySelector<HTMLElement>('main')
      restore?.focus?.()
    }
  }, [active, containerRef])
}
