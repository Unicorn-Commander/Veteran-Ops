import {
  ArrowRight,
  CheckCircle2,
  ClipboardPaste,
  Landmark,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { EmptyState, ErrorBlock, HueBadge, LoadingBlock, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage } from '../hooks/useAsync'
import { vaApi } from '../lib/api'
import { humanize } from '../lib/format'
import { hueInk, hueStyle, VA_STATUS_BADGES, VA_STATUS_HUES, type Hue } from '../lib/hues'
import type { VaDisposition, VaImportData, VaReconcileCondition, VaReconcileResult } from '../types'

// /va-import — reconcile the veteran's OWN VA rating/claim data into the app.
// The data arrives either in the URL hash (#data=<encodeURIComponent(JSON)>,
// opened by the VA Connect browser extension after it reads VA.gov) or is
// pasted into the box. We PREVIEW the changes as a dry-run, then apply on
// confirmation. Legal lane: this only organizes what the veteran's own VA
// record says — it files nothing, predicts nothing, and a free VSO can help.

const DISPOSITIONS: readonly VaDisposition[] = ['service_connected', 'denied', 'pending']

/** Coerce an untrusted disposition value to a known one (default: pending). */
function normDisposition(value: unknown): VaDisposition {
  return typeof value === 'string' && (DISPOSITIONS as readonly string[]).includes(value)
    ? (value as VaDisposition)
    : 'pending'
}

/** Best-effort number-or-null (accepts numeric strings like "60"). */
function numOrNull(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const n = Number(value)
    if (Number.isFinite(n)) return n
  }
  return null
}

function strOrNull(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null
}

/** Validate + normalize an untrusted parsed object into VaImportData, throwing
 * a friendly error on a shape we can't use. Defensive: the payload comes from a
 * separately-built extension or a hand-paste, so nothing is trusted. */
function normalizeVaData(input: unknown): VaImportData {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new Error("That doesn't look like VA data — expected an object with a “conditions” list.")
  }
  const obj = input as Record<string, unknown>
  const rawConditions = obj.conditions
  if (!Array.isArray(rawConditions)) {
    throw new Error('That data is missing a “conditions” list. Copy the whole export from VA Connect and try again.')
  }
  const conditions: VaReconcileCondition[] = rawConditions
    .filter((c): c is Record<string, unknown> => !!c && typeof c === 'object')
    .map((c) => ({
      name: typeof c.name === 'string' ? c.name.trim() : '',
      percent: numOrNull(c.percent),
      effective_date: strOrNull(c.effective_date),
      disposition: normDisposition(c.disposition),
    }))
    .filter((c) => c.name !== '')
  if (conditions.length === 0) {
    throw new Error('No conditions were found in that data. Make sure you copied your full VA record.')
  }
  return { combined_rating: numOrNull(obj.combined_rating), conditions }
}

/** Pull VA data out of `#data=<encodeURIComponent(JSON)>`, or null when absent.
 * Throws (via normalizeVaData) on a present-but-invalid payload. */
function readHashData(): VaImportData | null {
  const hash = window.location.hash || ''
  const marker = '#data='
  if (!hash.startsWith(marker)) return null
  const encoded = hash.slice(marker.length)
  if (!encoded) return null
  return normalizeVaData(JSON.parse(decodeURIComponent(encoded)))
}

export function VaImport() {
  const { toast } = useToast()
  const navigate = useNavigate()

  const [data, setData] = useState<VaImportData | null>(null)
  const [parseError, setParseError] = useState<string | null>(null)
  const [pasteText, setPasteText] = useState('')

  const [createNew, setCreateNew] = useState(false)
  const [preview, setPreview] = useState<VaReconcileResult | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)

  // On mount: try the URL hash. If it carried data, use it and scrub the hash
  // from the address bar (the record is now in memory — no need to leave the
  // veteran's ratings sitting in the URL). Nothing here is ever sent anywhere
  // but our own /va/reconcile.
  useEffect(() => {
    try {
      const fromHash = readHashData()
      if (fromHash) {
        setData(fromHash)
        window.history.replaceState(null, '', window.location.pathname + window.location.search)
      }
    } catch (e) {
      setParseError(errorMessage(e))
      window.history.replaceState(null, '', window.location.pathname + window.location.search)
    }
  }, [])

  // Preview (dry-run) whenever the data loads or the "add these" toggle flips.
  useEffect(() => {
    if (!data) {
      setPreview(null)
      return
    }
    let active = true
    setPreviewLoading(true)
    setPreviewError(null)
    vaApi
      .reconcile({ ...data, create_new: createNew, apply: false })
      .then((res) => {
        if (active) setPreview(res)
      })
      .catch((e) => {
        if (active) setPreviewError(errorMessage(e))
      })
      .finally(() => {
        if (active) setPreviewLoading(false)
      })
    return () => {
      active = false
    }
  }, [data, createNew])

  const loadFromPaste = useCallback(() => {
    setParseError(null)
    try {
      setData(normalizeVaData(JSON.parse(pasteText)))
    } catch (e) {
      // A JSON.parse SyntaxError isn't friendly — translate it.
      setParseError(
        e instanceof SyntaxError
          ? "That isn't valid data. Paste the exact export from the VA Connect extension."
          : errorMessage(e),
      )
    }
  }, [pasteText])

  const startOver = () => {
    setData(null)
    setPreview(null)
    setPreviewError(null)
    setParseError(null)
    setPasteText('')
    setCreateNew(false)
  }

  const changedCount = useMemo(
    () => (preview?.matched ?? []).filter((m) => m.changed).length,
    [preview],
  )
  const willCreate = createNew ? (preview?.unmatched.length ?? 0) : 0
  const hasChanges = changedCount > 0 || preview?.combined_rating != null || willCreate > 0

  const apply = async () => {
    if (!data) return
    setApplying(true)
    try {
      const res = await vaApi.reconcile({ ...data, create_new: createNew, apply: true })
      const n = res.matched.filter((m) => m.changed).length + res.unmatched.filter((u) => u.created).length
      toast(
        `Updated ${n} condition${n === 1 ? '' : 's'}` +
          (res.combined_rating != null ? `, set your combined rating to ${res.combined_rating}%` : '') +
          '.',
        'success',
      )
      navigate('/strategy')
    } catch (e) {
      toast(errorMessage(e), 'error')
      setApplying(false)
    }
  }

  return (
    <div data-section="settings" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">From your VA record</p>
        <h1 className="vo-page-title">Import from VA</h1>
        <p className="vo-page-sub">
          Bring in what your VA.gov record says — your combined rating and each condition's disposition — and line it
          up against the conditions you're tracking here. You'll see exactly what would change before anything does.
          This just organizes what your record already says; it files nothing, predicts nothing, and a free{' '}
          <a
            href="https://www.va.gov/vso/"
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-brand hover:text-brand-hover"
          >
            accredited VSO
          </a>{' '}
          can help you decide what to do next.
        </p>
      </div>

      {!data ? (
        // ── No data yet: paste box + how-to ──────────────────────────────────
        <Panel hue="violet" title="Paste your VA data" subtitle="Or open this page from the VA Connect extension">
          <div className="space-y-4 p-5">
            <div className="flex items-start gap-2.5 rounded-control border border-line bg-surface2 px-4 py-3.5 text-sm text-muted">
              <Landmark size={16} className="mt-0.5 shrink-0" style={{ color: hueInk('violet') }} />
              <p className="leading-relaxed">
                The easiest way is the{' '}
                <span className="font-semibold text-txt">VA Connect</span> browser extension: sign in at VA.gov, and it
                opens this page with your record already loaded. No extension? Paste the JSON export below instead.
                Your data only travels to Rating Raider — nowhere else.
              </p>
            </div>

            <div>
              <label htmlFor="va-paste" className="vo-label-micro mb-1.5 block">
                VA data (JSON)
              </label>
              <textarea
                id="va-paste"
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                placeholder='{ "combined_rating": 60, "conditions": [ { "name": "Tinnitus", "percent": 10, "effective_date": "2021-03-01", "disposition": "service_connected" } ] }'
                className="vo-input min-h-[160px] resize-y font-mono text-xs leading-relaxed"
                spellCheck={false}
              />
            </div>

            {parseError && (
              <div
                className="flex items-start gap-2.5 rounded-control border px-4 py-3 text-sm"
                style={{
                  borderColor: 'color-mix(in srgb, var(--danger) 40%, transparent)',
                  background: 'var(--danger-soft)',
                }}
              >
                <TriangleAlert size={16} className="mt-0.5 shrink-0 text-danger" />
                <p className="text-danger">{parseError}</p>
              </div>
            )}

            <button
              onClick={loadFromPaste}
              disabled={pasteText.trim() === ''}
              className="vo-btn-primary"
            >
              <ClipboardPaste size={15} />
              Preview these changes
            </button>
          </div>
        </Panel>
      ) : previewLoading && !preview ? (
        <LoadingBlock label="Lining up your VA record…" />
      ) : previewError ? (
        <ErrorBlock message={previewError} onRetry={() => setData({ ...data })} />
      ) : preview ? (
        // ── Data loaded: preview + apply ─────────────────────────────────────
        <>
          {/* Profile change: combined rating */}
          <Panel hue="emerald" title="Your combined rating" subtitle="What this import would set on your profile">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 p-5">
              {preview.combined_rating != null ? (
                <div className="flex items-baseline gap-2">
                  <span className="text-sm text-muted">Combined rating</span>
                  <ArrowRight size={16} className="text-muted" />
                  <span className="text-3xl font-bold tabular-nums" style={{ color: hueInk('emerald') }}>
                    {preview.combined_rating}%
                  </span>
                </div>
              ) : (
                <p className="flex items-center gap-2 text-sm text-muted">
                  <CheckCircle2 size={15} className="text-success" />
                  No combined-rating change — your profile already matches.
                </p>
              )}
            </div>
          </Panel>

          {/* Matched conditions */}
          <Panel
            hue="violet"
            title="Matched to your conditions"
            subtitle={
              preview.matched.length > 0
                ? `${changedCount} of ${preview.matched.length} would change`
                : 'None of your conditions matched this record'
            }
          >
            <div className="p-5">
              {preview.matched.length === 0 ? (
                <p className="text-sm text-muted">
                  None of the VA conditions matched a condition on your list. If you expected a match, the names may
                  differ — you can add them below instead.
                </p>
              ) : (
                <ul className="space-y-2">
                  {preview.matched.map((m) => {
                    const hue: Hue = VA_STATUS_HUES[m.set_va_status] ?? 'sky'
                    const label = VA_STATUS_BADGES[m.set_va_status] ?? humanize(m.set_va_status)
                    return (
                      <li
                        key={m.condition_id}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-control border border-line bg-surface2 px-4 py-3 text-sm"
                      >
                        <span className="font-semibold text-txt">{m.condition_name}</span>
                        {m.va_name && m.va_name.toLowerCase() !== m.condition_name.toLowerCase() && (
                          <span className="text-micro text-faint">VA: {m.va_name}</span>
                        )}
                        <span className="ml-auto flex items-center gap-2">
                          <ArrowRight size={14} className="text-muted" />
                          <HueBadge hue={hue}>{label}</HueBadge>
                          {m.set_current_rating != null && (
                            <span className="font-semibold tabular-nums text-txt">{m.set_current_rating}%</span>
                          )}
                          {m.changed ? (
                            <HueBadge hue="amber">Changed</HueBadge>
                          ) : (
                            <span className="text-micro text-faint">no change</span>
                          )}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </Panel>

          {/* Unmatched VA conditions */}
          {preview.unmatched.length > 0 && (
            <Panel
              hue="teal"
              title="Not in your list yet"
              subtitle={`${preview.unmatched.length} VA condition${preview.unmatched.length === 1 ? '' : 's'} you're not tracking here`}
            >
              <div className="space-y-4 p-5">
                <ul className="space-y-2">
                  {preview.unmatched.map((u, i) => {
                    const hue: Hue = VA_STATUS_HUES[u.disposition] ?? 'sky'
                    const label = VA_STATUS_BADGES[u.disposition] ?? humanize(u.disposition)
                    return (
                      <li
                        key={`${u.name}-${i}`}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-control border border-line bg-surface2 px-4 py-3 text-sm"
                      >
                        <span className="font-semibold text-txt">{u.name}</span>
                        <span className="ml-auto flex items-center gap-2">
                          <HueBadge hue={hue}>{label}</HueBadge>
                          {u.percent != null && (
                            <span className="font-semibold tabular-nums text-txt">{u.percent}%</span>
                          )}
                        </span>
                      </li>
                    )
                  })}
                </ul>

                <label
                  className="group flex min-h-[2.5rem] cursor-pointer items-start gap-3 rounded-control border border-line bg-surface2 p-3.5 text-sm transition-colors duration-150 hover:border-line2"
                  style={hueStyle('teal') as CSSProperties}
                >
                  <input
                    type="checkbox"
                    className="vo-check mt-0.5"
                    checked={createNew}
                    onChange={(e) => setCreateNew(e.target.checked)}
                  />
                  <span className="min-w-0">
                    <span className="font-medium text-txt">Also add these to my conditions</span>
                    <span className="mt-0.5 block text-xs leading-relaxed text-muted">
                      Adds the {preview.unmatched.length} condition{preview.unmatched.length === 1 ? '' : 's'} above to
                      your list with their VA disposition, so they're part of your Claim Plan. You can edit or remove any
                      of them afterward.
                    </span>
                  </span>
                </label>
              </div>
            </Panel>
          )}

          <p className="vo-caption">
            This reflects what your VA record says today. Rating Raider never files anything for you and never predicts
            an outcome — an accredited VSO can review it with you for free.
          </p>

          {/* Sticky apply bar */}
          <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-between gap-3 rounded-control border border-line bg-surface/95 p-3 shadow-lg backdrop-blur">
            <span className="flex items-center gap-2 text-sm text-muted">
              <ShieldCheck size={15} style={{ color: hueInk('emerald') }} />
              {hasChanges ? (
                <>
                  {changedCount > 0 && `${changedCount} condition${changedCount === 1 ? '' : 's'} to update`}
                  {changedCount > 0 && willCreate > 0 && ', '}
                  {willCreate > 0 && `${willCreate} to add`}
                  {preview.combined_rating != null && (changedCount > 0 || willCreate > 0) && ', '}
                  {preview.combined_rating != null && `combined → ${preview.combined_rating}%`}
                </>
              ) : (
                'Nothing to change — your workspace already matches this record.'
              )}
            </span>
            <div className="flex shrink-0 items-center gap-2">
              <button onClick={startOver} className="vo-btn-secondary" disabled={applying}>
                Start over
              </button>
              <button
                onClick={() => void apply()}
                disabled={applying || previewLoading || !hasChanges}
                className="vo-btn-primary"
              >
                {applying ? <Spinner size={15} className="text-white" /> : <Sparkles size={15} />}
                Apply to my claim
                <ArrowRight size={15} />
              </button>
            </div>
          </div>
        </>
      ) : (
        // Safety net — data present but preview not yet available and no error.
        <EmptyState
          hue="violet"
          icon={<Landmark size={20} />}
          title="Getting your VA record ready…"
          description="One moment while we line up what your record says against your conditions."
        />
      )}
    </div>
  )
}
