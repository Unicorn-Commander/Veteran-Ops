import { useEffect, useRef } from 'react'
import { useLocation } from 'react-router-dom'

/**
 * Accessibility for client-side navigation: on every route change, set the
 * document title to `"${pageTitle} — Rating Raider"` and move focus to the
 * `<main id="main-content">` region. Screen-reader users then hear the new page
 * (title + focused landmark) instead of nothing, and keyboard focus lands at the
 * top of the fresh content rather than lingering on the old link.
 *
 * Skips the initial mount so we don't steal focus on first paint.
 */
export function useRouteFocus(pageTitle: string) {
  const { pathname } = useLocation()
  // Skip the initial mount: don't steal focus on first paint (the first-run
  // disclaimer gate owns focus then).
  const firstRun = useRef(true)

  useEffect(() => {
    document.title = `${pageTitle} — Rating Raider`
  }, [pageTitle])

  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false
      return
    }
    // Defer until the routed content has rendered.
    const id = window.requestAnimationFrame(() => {
      const main = document.getElementById('main-content')
      main?.focus()
    })
    return () => window.cancelAnimationFrame(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname])
}
