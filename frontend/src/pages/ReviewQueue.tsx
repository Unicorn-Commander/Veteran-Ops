import {
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  Eye,
  FileWarning,
  Loader2,
  Sparkles,
  Target,
  UploadCloud,
} from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { DocumentViewer } from '../components/DocumentViewer'
import { ProSeDisclaimer } from '../components/Disclaimer'
import { EmptyState, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { documentsApi } from '../lib/api'
import { formatDate } from '../lib/format'
import { hueStyle } from '../lib/hues'
import type { CSSProperties } from 'react'
import type { DocumentReviewQueueItem, ReconcileResolution, ReviewField } from '../types'

const HUE = 'amber' as const

function fieldLabel(f: ReviewField): string {
  const name = f.condition ? `${f.condition} — ` : ''
  const field = f.field.replace(/_/g, ' ')
  return `${name}${field}`
}

function valueText(v: number | string | null): string {
  if (v === null || v === undefined || v === '') return '—'
  return String(v)
}

/** One flagged document — expanded by default so the veteran always sees
 * what to do (collapsed cards were a common “empty / stuck” experience). */
function ReviewDocCard({
  item,
  onResolved,
  defaultOpen = true,
}: {
  item: DocumentReviewQueueItem
  onResolved: () => void
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const { data, loading, error, reload } = useAsync(
    () => (open ? documentsApi.review(item.id) : Promise.resolve(null)),
    [open, item.id],
  )
  const { toast } = useToast()
  const [choices, setChoices] = useState<Record<string, number | string | null>>({})
  const [dismissed, setDismissed] = useState<Record<string, boolean>>({})
  const [saving, setSaving] = useState(false)
  const [viewerOpen, setViewerOpen] = useState(false)

  const missing = (data?.missing_conditions ?? []).filter(
    (m): m is Record<string, unknown> => typeof m === 'object' && m !== null,
  )
  const fields = data?.fields ?? []
  const noActionable =
    !!data && fields.length === 0 && missing.length === 0
  const crossread = data?.crossread as
    | { pages_flagged?: number; note?: string; summary?: string }
    | null
    | undefined

  async function save() {
    setSaving(true)
    try {
      const resolutions: ReconcileResolution[] = Object.entries(choices).map(([field_id, value]) => ({
        field_id,
        value,
      }))
      const dismiss_missing = Object.entries(dismissed)
        .filter(([, on]) => on)
        .map(([name]) => name)
      await documentsApi.reconcile(item.id, { resolutions, dismiss_missing })
      toast('Saved your corrections', 'success')
      onResolved()
      await reload()
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  async function markReviewed() {
    setSaving(true)
    try {
      await documentsApi.reconcile(item.id, {
        resolutions: [],
        dismiss_missing: missing.map((m) => String(m.name || '')).filter(Boolean),
        clear_document: true,
      })
      toast('Marked as reviewed', 'success')
      onResolved()
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  const hasSelections = Object.keys(choices).length > 0 || Object.values(dismissed).some(Boolean)
  const summaryParts: string[] = []
  if (item.fields_pending > 0) {
    summaryParts.push(
      `${item.fields_pending} value${item.fields_pending === 1 ? '' : 's'} to confirm`,
    )
  }
  if (item.missing_conditions > 0) {
    summaryParts.push(
      `${item.missing_conditions} possible missed condition${item.missing_conditions === 1 ? '' : 's'}`,
    )
  }
  if (item.crossread_pages_flagged > 0) {
    summaryParts.push(`${item.crossread_pages_flagged} page(s) read two ways`)
  }
  if (summaryParts.length === 0) {
    summaryParts.push('Flagged for review')
  }

  return (
    <div className="rounded-control border border-line bg-surface2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        {open ? (
          <ChevronDown size={16} className="shrink-0 text-muted" />
        ) : (
          <ChevronRight size={16} className="shrink-0 text-muted" />
        )}
        <FileWarning size={16} className="shrink-0 text-h-amber" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-txt">{item.title || item.filename}</span>
          <span className="block text-xs text-muted">
            {summaryParts.join(' · ')}
            {item.doc_date ? ` · ${formatDate(item.doc_date)}` : ''}
          </span>
        </span>
      </button>

      {open && (
        <div className="border-t border-line px-4 py-4">
          {loading ? (
            <LoadingBlock label="Loading what needs your eye…" />
          ) : error ? (
            <ErrorBlock message={error} onRetry={reload} />
          ) : !data ? null : (
            <div className="space-y-5">
              {fields.length > 0 && (
                <div className="space-y-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted">
                    Choose the correct value for each field
                  </p>
                  {fields.map((f) => (
                    <div key={f.field_id} className="rounded-control border border-line bg-surface p-3.5">
                      <p className="text-sm font-semibold text-txt">{fieldLabel(f)}</p>
                      {f.span && (
                        <p className="mt-1 text-xs italic leading-relaxed text-muted">“{f.span}”</p>
                      )}
                      <div className="mt-3 flex flex-wrap gap-2">
                        <button
                          type="button"
                          onClick={() => setChoices((c) => ({ ...c, [f.field_id]: f.candidate_value }))}
                          aria-pressed={choices[f.field_id] === f.candidate_value}
                          className={`vo-chip-hue text-xs ${
                            choices[f.field_id] === f.candidate_value ? 'ring-2 ring-brand/40' : ''
                          }`}
                          style={hueStyle('emerald') as CSSProperties}
                        >
                          Record shows: {valueText(f.candidate_value)}
                        </button>
                        <button
                          type="button"
                          onClick={() => setChoices((c) => ({ ...c, [f.field_id]: f.extracted_value }))}
                          aria-pressed={choices[f.field_id] === f.extracted_value}
                          className={`vo-chip text-xs ${
                            choices[f.field_id] === f.extracted_value ? 'ring-2 ring-brand/40' : ''
                          }`}
                        >
                          Keep read: {valueText(f.extracted_value)}
                        </button>
                        <button
                          type="button"
                          onClick={() => setChoices((c) => ({ ...c, [f.field_id]: null }))}
                          aria-pressed={f.field_id in choices && choices[f.field_id] === null}
                          className={`vo-chip text-xs ${
                            f.field_id in choices && choices[f.field_id] === null ? 'ring-2 ring-brand/40' : ''
                          }`}
                        >
                          Neither (clear)
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {missing.length > 0 && (
                <div>
                  <p className="vo-label-micro mb-2 px-0.5">Possibly missed conditions</p>
                  <div className="space-y-2">
                    {missing.map((m, i) => {
                      const name = typeof m.name === 'string' ? m.name : `Condition ${i + 1}`
                      const span = typeof m.span === 'string' ? m.span : null
                      return (
                        <div
                          key={`${name}-${i}`}
                          className="rounded-control border border-line bg-surface p-3 text-sm"
                        >
                          <label className="flex cursor-pointer items-start gap-2.5">
                            <input
                              type="checkbox"
                              checked={!!dismissed[name]}
                              onChange={(e) => setDismissed((d) => ({ ...d, [name]: e.target.checked }))}
                              className="mt-0.5"
                            />
                            <span>
                              <span className="font-medium text-txt">{name}</span>
                              {span && <span className="block text-xs italic text-muted">“{span}”</span>}
                              <span className="block text-xs text-faint">
                                Check to dismiss if this is not a claim condition.
                              </span>
                            </span>
                          </label>
                          <div className="mt-2 flex flex-wrap gap-2 pl-6">
                            <Link
                              to={`/build-case?q=${encodeURIComponent(name)}`}
                              className="vo-btn-primary min-h-9 text-xs"
                            >
                              Include when populating case
                            </Link>
                            <Link
                              to={`/conditions?add=${encodeURIComponent(name)}`}
                              className="vo-btn-secondary min-h-9 text-xs"
                            >
                              Add condition
                            </Link>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {noActionable && (
                <div className="space-y-3 rounded-control border border-line bg-surface p-4 text-sm">
                  <p className="font-semibold text-txt">Nothing left to pick on this document</p>
                  <p className="text-xs leading-relaxed text-muted">
                    Rating Raider flagged this file because two OCR/readers sometimes disagreed on a page, or a
                    verify pass left a soft note. There is <strong className="text-txt">no percentage or
                    diagnostic code left for you to choose</strong> — so you are not approving a rating here.
                    You are only acknowledging the flag so the claim path can move on.
                  </p>
                  {item.crossread_pages_flagged > 0 && (
                    <p className="text-xs text-muted">
                      {item.crossread_pages_flagged} page
                      {item.crossread_pages_flagged === 1 ? '' : 's'} had a dual OCR read
                      {crossread && typeof crossread === 'object' && crossread.summary
                        ? `: ${String(crossread.summary)}`
                        : '.'}{' '}
                      Open the file if you want to eyeball the scan quality; otherwise clear the flag.
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => setViewerOpen(true)}
                      className="vo-btn-secondary min-h-10 text-sm"
                    >
                      <Eye size={15} /> View this document
                    </button>
                    <button
                      type="button"
                      onClick={() => void markReviewed()}
                      disabled={saving}
                      className="vo-btn-primary min-h-10 text-sm"
                    >
                      {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                      Clear flag & continue
                    </button>
                  </div>
                </div>
              )}

              <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={() => setViewerOpen(true)}
                  className="vo-btn-ghost min-h-10 text-sm"
                >
                  <Eye size={15} /> View file
                </button>
                <div className="flex flex-wrap justify-end gap-2">
                  {!noActionable && (fields.length > 0 || missing.length > 0) && (
                    <button
                      type="button"
                      onClick={() => void markReviewed()}
                      disabled={saving}
                      className="vo-btn-secondary flex items-center gap-1.5 text-sm"
                    >
                      {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                      Clear flag without changes
                    </button>
                  )}
                  {fields.length > 0 || missing.length > 0 ? (
                    <button
                      type="button"
                      onClick={() => void save()}
                      disabled={saving || !hasSelections}
                      className="vo-btn-primary flex items-center gap-1.5 text-sm"
                    >
                      {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                      Save corrections
                    </button>
                  ) : null}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {viewerOpen && (
        <DocumentViewer
          doc={{
            id: item.id,
            filename: item.filename,
            title: item.title,
            content_type: null,
          }}
          onClose={() => setViewerOpen(false)}
        />
      )}
    </div>
  )
}

function NextStepsCta({ afterBulk }: { afterBulk?: boolean }) {
  return (
    <div
      className="vo-card vo-accent space-y-4 p-5 sm:p-6"
      style={hueStyle('emerald') as CSSProperties}
      role="region"
      aria-label="Next steps after confirming findings"
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-surface2 text-h-emerald"
        >
          <CheckCircle2 size={22} />
        </span>
        <div className="min-w-0">
          <p className="vo-caption mb-0.5 text-h-emerald">Queue clear</p>
          <h2 className="text-lg font-bold tracking-tight text-txt sm:text-xl">
            {afterBulk ? 'Findings confirmed — what next?' : 'Nothing needs your review'}
          </h2>
          <p className="mt-1 max-w-[70ch] text-sm leading-relaxed text-muted">
            {afterBulk
              ? 'Next on the main path: populate conditions from records (or continue if they are already on your list), then analysis and claim plan. Profile only if yours is still empty.'
              : 'Flags only appear when a value still needs your eyes. This queue is clear — keep going on the claim path below.'}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Link to="/build-case" className="vo-btn-primary min-h-11 text-sm">
          <Sparkles size={15} /> Populate case
        </Link>
        <Link to="/analysis" className="vo-btn-secondary min-h-11 text-sm">
          Run analysis <ArrowRight size={14} />
        </Link>
        <Link to="/strategy" className="vo-btn-secondary min-h-11 text-sm">
          <Target size={15} /> Claim plan
        </Link>
        <Link to="/profile?start=1" className="vo-btn-ghost min-h-11 text-sm">
          Profile
        </Link>
        <Link to="/documents" className="vo-btn-ghost min-h-11 text-sm">
          <UploadCloud size={15} /> Documents
        </Link>
      </div>
    </div>
  )
}

export function ReviewQueue() {
  const { toast } = useToast()
  const { data, loading, error, reload } = useAsync(() => documentsApi.reviewQueue())
  const [bulkBusy, setBulkBusy] = useState(false)
  const [clearedByBulk, setClearedByBulk] = useState(false)

  const bulk = async (mode: 'accept_agreed' | 'accept_record' | 'clear_all') => {
    const labels: Record<typeof mode, string> = {
      accept_agreed: 'Accept all values both readers agree on',
      accept_record: "Accept every 'record shows' value (clears disagreements)",
      clear_all: 'Clear every review flag (no value changes — just unblocks the claim path)',
    }
    if (
      !window.confirm(
        `${labels[mode]}?\n\nThis is your confirmation. You can still open individual documents later.`,
      )
    ) {
      return
    }
    setBulkBusy(true)
    try {
      const res = await documentsApi.bulkReconcile({
        mode,
        dismiss_all_missing: mode === 'clear_all' || mode === 'accept_record',
      })
      if (mode === 'clear_all') {
        toast(
          `Cleared ${res.resolved_documents} document${res.resolved_documents === 1 ? '' : 's'} from the review queue.`,
          'success',
        )
      } else if (res.fields_applied === 0 && res.resolved_documents === 0) {
        toast(
          res.fields_skipped
            ? `No fields matched that bulk option (${res.fields_skipped} still disagree). Try “Accept all record shows” or open each document.`
            : 'Nothing applied. Try “Mark all reviewed” if the queue has only informational flags.',
          'info',
        )
      } else {
        toast(
          `Applied ${res.fields_applied} value${res.fields_applied === 1 ? '' : 's'} · cleared ${res.resolved_documents} document${res.resolved_documents === 1 ? '' : 's'}` +
            (res.fields_skipped ? ` · ${res.fields_skipped} still need a one-by-one choice` : '') +
            '.',
          'success',
        )
      }
      setClearedByBulk(true)
      await reload()
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setBulkBusy(false)
    }
  }

  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-3xl space-y-6 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Your confirmation required</p>
        <h1 className="vo-page-title">Confirm what we found</h1>
        <p className="vo-page-sub">
          Each card is one uploaded file. Open <strong className="font-semibold text-txt">View file</strong> to see
          the PDF/scan. When two readers disagreed on a percentage or code, pick which value is right. When the card
          says there is nothing left to pick, that is usually a soft OCR note — clear the flag to move on.
        </p>
      </div>

      <ProSeDisclaimer />

      {loading ? (
        <LoadingBlock label="Checking what needs your eye…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        clearedByBulk ? (
          <NextStepsCta afterBulk />
        ) : (
          <Panel hue={HUE}>
            <EmptyState
              hue={HUE}
              icon={<ClipboardCheck size={24} />}
              title="Nothing needs your review"
              description="When a document has a value that couldn't be confirmed, it shows up here. Continue the main claim path."
              action={
                <div className="flex flex-wrap gap-2">
                  <Link to="/build-case" className="vo-btn-primary text-sm">
                    <Sparkles size={15} /> Populate case
                  </Link>
                  <Link to="/analysis" className="vo-btn-secondary text-sm">
                    Run analysis <ArrowRight size={14} />
                  </Link>
                  <Link to="/documents" className="vo-btn-ghost text-sm">
                    <UploadCloud size={15} /> Documents
                  </Link>
                </div>
              }
            />
          </Panel>
        )
      ) : (
        <>
          <div
            className="vo-card vo-accent flex flex-col gap-3 p-4"
            style={hueStyle(HUE) as CSSProperties}
          >
            <div className="min-w-0 space-y-2">
              <p className="text-sm font-semibold text-txt">
                {data.length} document{data.length === 1 ? '' : 's'} need a look
              </p>
              <ul className="list-inside list-disc space-y-1 text-xs leading-relaxed text-muted">
                <li>
                  <strong className="text-txt">Accept all “record shows”</strong> — for each disputed number/code,
                  keep what the second reader (or source) showed. Best when “Accept agreed” applied 0.
                </li>
                <li>
                  <strong className="text-txt">Accept agreed only</strong> — only fields where both readers already
                  match; disagreements stay for one-by-one review.
                </li>
                <li>
                  <strong className="text-txt">Clear all flags</strong> — no value changes; removes soft OCR notes so
                  you can continue (open any file with View first if you want to inspect scans).
                </li>
              </ul>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={bulkBusy}
                onClick={() => void bulk('accept_record')}
                className="vo-btn-primary text-sm"
              >
                {bulkBusy ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
                Accept all “record shows”
              </button>
              <button
                type="button"
                disabled={bulkBusy}
                onClick={() => void bulk('accept_agreed')}
                className="vo-btn-secondary text-sm"
              >
                Accept agreed only
              </button>
              <button
                type="button"
                disabled={bulkBusy}
                onClick={() => void bulk('clear_all')}
                className="vo-btn-ghost text-sm"
              >
                Clear all flags
              </button>
            </div>
          </div>

          <div className="space-y-3">
            {data.map((item) => (
              <ReviewDocCard key={item.id} item={item} onResolved={() => void reload()} defaultOpen />
            ))}
          </div>
        </>
      )}
    </div>
  )
}
