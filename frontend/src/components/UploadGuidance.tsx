import { UploadCloud } from 'lucide-react'
import { useId, useState } from 'react'
import { documentsApi } from '../lib/api'
import type { DocTypeGuidance } from '../types'

/** Preferred display order — evidence a veteran most often holds first, "other"
 * last. Any doc type the backend adds that isn't listed here still renders
 * (appended in map order), so this never silently hides a type. */
const PREFERRED_ORDER = [
  'rating_decision',
  'decision_letter',
  'str',
  'service_record',
  'treatment_record',
  'dbq',
  'private_medical_opinion',
  'lay_statement',
  'other',
]

function orderedEntries(
  guidance: Record<string, DocTypeGuidance>,
): Array<[string, DocTypeGuidance]> {
  const keys = Object.keys(guidance)
  const ranked = keys.slice().sort((a, b) => {
    const ia = PREFERRED_ORDER.indexOf(a)
    const ib = PREFERRED_ORDER.indexOf(b)
    // unknown (un-ranked) keys go to the end, stable among themselves
    return (ia === -1 ? PREFERRED_ORDER.length : ia) - (ib === -1 ? PREFERRED_ORDER.length : ib)
  })
  return ranked.map((k) => [k, guidance[k]])
}

/** A calm, collapsible "What should I upload?" panel. Lazy-loads the backend's
 * plain-language guidance (GET /documents/upload-guidance) the first time the
 * veteran opens it — not on page load — then caches it. Educational self-help
 * only; it explains what each document type is and what commonly counts, never
 * what rating or outcome the veteran will get. Degrades silently if the
 * endpoint 404s on an older backend.
 *
 * Native <details> so it's keyboard-reachable and collapsed by default, matching
 * the <Legend> pattern used elsewhere on the page. */
export function UploadGuidance({ className = '' }: { className?: string }) {
  const id = useId()
  const [guidance, setGuidance] = useState<Record<string, DocTypeGuidance> | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

  async function loadOnce() {
    if (guidance || loading) return
    setLoading(true)
    setFailed(false)
    try {
      const res = await documentsApi.uploadGuidance()
      setGuidance(res.guidance)
    } catch {
      // Older backend without the endpoint, or a transient error — keep the
      // panel usable and let the veteran try again by re-opening.
      setFailed(true)
    } finally {
      setLoading(false)
    }
  }

  return (
    <details
      className={`overflow-hidden rounded-control border border-line bg-surface2 ${className}`}
      onToggle={(e) => {
        if ((e.currentTarget as HTMLDetailsElement).open) void loadOnce()
      }}
    >
      <summary
        aria-describedby={id}
        className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 text-xs font-semibold text-muted transition-colors hover:text-txt focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        <UploadCloud size={13} className="shrink-0" /> What should I upload?
      </summary>
      <div id={id} className="border-t border-line px-4 py-3.5">
        {loading && <p className="text-sm text-muted">Loading guidance…</p>}
        {failed && !loading && (
          <p className="text-sm text-muted">
            Couldn’t load upload guidance right now. Close and reopen this to try again — you
            can still upload anything you believe is relevant evidence for your claim.
          </p>
        )}
        {guidance && !loading && (
          <>
            <p className="mb-3 text-sm leading-snug text-muted">
              A quick guide to the kinds of documents that help a VA claim. Upload whatever
              you have — nothing here is required, and nothing you upload is filed with the VA.
            </p>
            <ul className="space-y-3.5">
              {orderedEntries(guidance).map(([key, g]) => (
                <li key={key} className="border-l-2 border-line pl-3">
                  <p className="text-sm font-semibold text-txt">{g.label}</p>
                  <p className="mt-0.5 text-sm leading-snug text-muted">{g.what_it_is}</p>
                  {g.what_to_upload.length > 0 && (
                    <ul className="mt-1.5 space-y-1">
                      {g.what_to_upload.map((ex, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-muted">
                          <span aria-hidden className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-faint" />
                          <span className="min-w-0 leading-snug">{ex}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-1.5 text-micro leading-snug text-faint">{g.why_it_helps}</p>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </details>
  )
}
