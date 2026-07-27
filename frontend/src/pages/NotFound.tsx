import { Compass, Home, LifeBuoy } from 'lucide-react'
import { Link } from 'react-router-dom'

/**
 * Friendly 404 — silent redirect-to-home used to erase context; this keeps
 * the veteran oriented with clear next moves.
 */
export function NotFound() {
  return (
    <div data-section="home" className="vo-page mx-auto w-full max-w-lg space-y-6 p-4 pb-16 sm:p-6">
      <div className="vo-section-band text-center">
        <p className="vo-caption mb-1">Page not found</p>
        <h1 className="vo-page-title">That page isn’t here</h1>
        <p className="vo-page-sub mx-auto max-w-md">
          The link may be old, or the page moved. Nothing is wrong with your claim data — pick a place to continue.
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-center gap-2">
        <Link to="/" className="vo-btn-primary min-h-11 text-sm">
          <Home size={15} /> Home
        </Link>
        <Link to="/journey" className="vo-btn-secondary min-h-11 text-sm">
          <Compass size={15} /> Rings & journey
        </Link>
        <Link to="/help" className="vo-btn-secondary min-h-11 text-sm">
          <LifeBuoy size={15} /> Help
        </Link>
      </div>
      <p className="text-center text-xs text-faint">
        Looking for a tool? Open <strong className="font-semibold text-muted">More</strong> in the nav, or ask Raider.
      </p>
    </div>
  )
}
