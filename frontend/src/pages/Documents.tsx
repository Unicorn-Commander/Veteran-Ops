import {
  Archive,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ClipboardCheck,
  Copy,
  Eye,
  FileCode2,
  FileWarning,
  Link2,
  Loader2,
  RefreshCw,
  RotateCcw,
  ScanText,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  TriangleAlert,
  UploadCloud,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { DocumentViewer } from '../components/DocumentViewer'
import { DropZone } from '../components/DropZone'
import { Checkbox, EmptyState, ErrorBlock, HueBadge, LoadingBlock, Spinner } from '../components/ui'
import { Tooltip } from '../components/InfoTip'
import { Legend, type LegendGroup } from '../components/Legend'
import { UploadGuidance } from '../components/UploadGuidance'
import { useToast } from '../components/Toast'
import { errorMessage } from '../hooks/useAsync'
import { conditionsApi, documentsApi, profileApi } from '../lib/api'
import {
  armDeferredAnalysis,
  getDeferredAnalysisSnapshot,
  setAnalyzeAfterUploadOptIn,
  subscribeDeferredAnalysis,
  type DeferredAnalysisSnapshot,
} from '../lib/deferredAnalysisStore'

import { formatBytes, formatDate, humanize } from '../lib/format'
import { hueInk, hueSoftVar, hueStyle, type Hue } from '../lib/hues'
import type {
  CcdParsed,
  ClaimedCondition,
  DocConditionMention,
  DocumentSearchHit,
  DocumentSearchResult,
  DocumentSummary,
  DocType,
  DocumentItem,
  DocumentStatus,
  DocumentUploadItem,
  EvidenceKind,
  ResetRecords,
} from '../types'

/** Identity hue per document type — lets a long stack of review cards be
 * scanned by color at a glance instead of reading every label. */
const DOC_TYPE_HUES: Record<DocType, Hue> = {
  rating_decision: 'emerald',
  decision_letter: 'indigo',
  str: 'cyan',
  dbq: 'violet',
  treatment_record: 'teal',
  private_medical_opinion: 'rose',
  lay_statement: 'pink',
  service_record: 'lime',
  other: 'orange',
}

/** Plain-language meaning per document type — shown as a hover/focus tooltip on
 * each doc-type badge and gathered into the page legend below, so a color-coded
 * badge is never a mystery. */
const DOC_TYPE_INFO: Record<DocType, string> = {
  rating_decision: 'A VA rating decision — the ratings and effective dates VA assigned to your conditions.',
  decision_letter: "A VA decision letter explaining what was granted or denied and why.",
  str: 'Service treatment records (STRs) — the medical records from your time in service.',
  dbq: 'A Disability Benefits Questionnaire — a provider’s exam findings on VA’s standardized form.',
  treatment_record: 'A treatment record — notes from a VA, military, or private medical visit.',
  private_medical_opinion: 'A private medical / nexus opinion linking a condition to your service.',
  lay_statement: 'A lay or buddy statement — a first-hand account from you or someone who knows your case.',
  service_record: 'A service record — personnel, deployment, or other military paperwork.',
  other: "Something that didn’t fit the categories above — still stored and searchable.",
}

/** Reusable doc-type badge that carries its meaning as a keyboard-reachable
 * tooltip. Used in the card header and in search results so the symbol explains
 * itself everywhere it appears. */
function DocTypeBadge({ type }: { type: DocType }) {
  return (
    <Tooltip content={DOC_TYPE_INFO[type]}>
      <HueBadge hue={DOC_TYPE_HUES[type]}>{humanize(type)}</HueBadge>
    </Tooltip>
  )
}

// /documents — WAVE2-SPEC §4, the document intake pipeline. Shapes reconciled
// against the real backend/app/routers/documents.py + schemas.py: notably,
// GET /documents (list) returns DocumentOut WITHOUT `extracted` — only
// GET /documents/{id} (DocumentDetailOut) includes it, so this page
// backfills extraction detail per "ready" document after each list load.

const DOC_TYPES: DocType[] = [
  'rating_decision',
  'decision_letter',
  'str',
  'dbq',
  'treatment_record',
  'private_medical_opinion',
  'lay_statement',
  'service_record',
  'other',
]
const STATUSES: DocumentStatus[] = ['uploaded', 'processing', 'ready', 'failed', 'duplicate']

type DocGroup =
  | { kind: 'type'; key: string; type: DocType; docs: DocumentItem[] }
  | { kind: 'unsorted'; key: 'unsorted'; docs: DocumentItem[] }
  | { kind: 'flagged'; key: 'flagged'; docs: DocumentItem[] }

/** Partition the flat document list into calm, ordered groups: each recognized
 * doc type in DOC_TYPES order, then anything not yet classified, then the
 * "possibly not related" flag last. Flagged docs are pulled out first so they
 * surface in their own group instead of hiding inside "Other" (the relevance
 * flag only ever lands on other/unclassified docs anyway). Order is stable and
 * empty groups are dropped — a group only appears when it has documents. */
function groupDocuments(docs: DocumentItem[]): DocGroup[] {
  const flagged = docs.filter((d) => d.relevance_flagged)
  const rest = docs.filter((d) => !d.relevance_flagged)
  const byType = new Map<DocType, DocumentItem[]>()
  const unsorted: DocumentItem[] = []
  for (const d of rest) {
    if (d.doc_type) {
      const arr = byType.get(d.doc_type) ?? []
      arr.push(d)
      byType.set(d.doc_type, arr)
    } else {
      unsorted.push(d)
    }
  }
  const groups: DocGroup[] = []
  for (const t of DOC_TYPES) {
    const arr = byType.get(t)
    if (arr && arr.length) groups.push({ kind: 'type', key: t, type: t, docs: arr })
  }
  if (unsorted.length) groups.push({ kind: 'unsorted', key: 'unsorted', docs: unsorted })
  if (flagged.length) groups.push({ kind: 'flagged', key: 'flagged', docs: flagged })
  return groups
}

/** The Documents-page key: what each doc-type color means, plus the
 * "possibly not related" flag and the duplicate marker. Rendered by <Legend>. */
const DOC_LEGEND_GROUPS: LegendGroup[] = [
  {
    label: 'Document types',
    items: DOC_TYPES.map((t) => ({
      badge: <HueBadge hue={DOC_TYPE_HUES[t]}>{humanize(t)}</HueBadge>,
      desc: DOC_TYPE_INFO[t],
    })),
  },
  {
    label: 'Flags',
    items: [
      {
        badge: (
          <span className="vo-chip text-muted">
            <FileWarning size={12} /> Possibly not related
          </span>
        ),
        desc: "Rating Raider doesn’t think this belongs to a VA claim. It’s kept, never deleted for you, and counts toward nothing on its own — remove it only if it isn’t part of your claim.",
      },
      {
        badge: (
          <span className="vo-chip text-muted">
            <Copy size={12} /> Duplicate — skipped
          </span>
        ),
        desc: 'The same content as a record you already uploaded, so it wasn’t processed or analyzed again — nothing is double-counted.',
      },
    ],
  },
]
// Per-file cap 50MB; a .zip bundle (of any of the above) gets a bigger 200MB
// allowance since it's a bulk dump, not a single scan.
const MAX_FILE_BYTES = 50 * 1024 * 1024
// Text / health-summary formats get the bigger lane (mirrors the backend): a
// MyHealtheVet Blue Button "text" export or a C-CDA XML is often tens of MB in
// one file, and text costs nothing to OCR. Kept under the ~100 MB edge limit.
const MAX_TEXT_BYTES = 95 * 1024 * 1024
const TEXT_EXTS = ['.txt', '.csv', '.xml']
const MAX_ZIP_BYTES = 200 * 1024 * 1024
const maxBytesFor = (f: File) =>
  isZipFile(f)
    ? MAX_ZIP_BYTES
    : TEXT_EXTS.some((e) => f.name.toLowerCase().endsWith(e))
      ? MAX_TEXT_BYTES
      : MAX_FILE_BYTES
// The backend rejects a single upload request of >100 loose files (a fan-out
// guard) and the edge caps the body size. So a big folder drop is split into
// sequential batches that stay under BOTH: at most 90 files AND ~80MB per
// request (comfortably under the ~100MB edge limit). A .zip is one file here and
// expands server-side, so it never needs batching.
const MAX_FILES_PER_BATCH = 90
const MAX_BYTES_PER_BATCH = 80 * 1024 * 1024

/** Split files into upload batches within the per-request file-count and size
 * caps. A single file larger than the size cap still goes in its own batch (the
 * server applies the real per-file limit). */
function batchForUpload(files: File[]): File[][] {
  const batches: File[][] = []
  let cur: File[] = []
  let curBytes = 0
  for (const f of files) {
    if (cur.length > 0 && (cur.length >= MAX_FILES_PER_BATCH || curBytes + f.size > MAX_BYTES_PER_BATCH)) {
      batches.push(cur)
      cur = []
      curBytes = 0
    }
    cur.push(f)
    curBytes += f.size
  }
  if (cur.length > 0) batches.push(cur)
  return batches
}
// Matches backend/app/routers/documents.py _is_zip() exactly — used only to
// pick the right client-side size cap before upload; the server re-validates.
const isZipFile = (f: File) =>
  f.name.toLowerCase().endsWith('.zip') ||
  f.type === 'application/zip' ||
  f.type === 'application/x-zip-compressed'

const DOC_TYPE_TO_EVIDENCE_KIND: Record<DocType, EvidenceKind> = {
  rating_decision: 'other',
  decision_letter: 'other',
  str: 'service_record',
  dbq: 'dbq',
  treatment_record: 'treatment_record',
  private_medical_opinion: 'nexus_letter',
  lay_statement: 'lay_statement',
  service_record: 'service_record',
  other: 'other',
}

export function Documents() {
  const { toast } = useToast()
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  // Group the list by document type by default so a big pile of uploads reads
  // clearly. Meaningless when a single type is already filtered, so it's
  // disabled in that case (see the toggle below).
  const [grouped, setGrouped] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [conditions, setConditions] = useState<ClaimedCondition[]>([])
  const [summary, setSummary] = useState<DocumentSummary | null>(null)
  const [retryingFailed, setRetryingFailed] = useState(false)
  const [viewerDoc, setViewerDoc] = useState<DocumentItem | null>(null)
  const [resetResult, setResetResult] = useState<ResetRecords | null>(null)

  // M2 — "Analyze after upload" opt-in. Starts only after this upload batch
  // finishes. State lives in deferredAnalysisStore so leaving the page does not
  // cancel the wait or hide a started run.
  const [deferredAnalysis, setDeferredAnalysis] = useState<DeferredAnalysisSnapshot>(() =>
    getDeferredAnalysisSnapshot(),
  )
  const analyzeAfterUpload = deferredAnalysis.optIn
  /** Only while a post-upload run is actively in flight (not a stale completed id). */
  const analysisStartedRunId =
    deferredAnalysis.phase === 'running' ? deferredAnalysis.runId : null
  const analysisStartError = deferredAnalysis.phase === 'error' ? deferredAnalysis.error : null
  const analysisWaiting =
    deferredAnalysis.phase === 'waiting' || deferredAnalysis.phase === 'starting'

  // Post-upload autonomy: pending review-queue values + a one-shot "processing
  // finished" success nudge so the next step is obvious.
  const [reviewPendingValues, setReviewPendingValues] = useState<number | null>(null)
  const [showProcessDoneNudge, setShowProcessDoneNudge] = useState(false)
  const wasProcessingRef = useRef(false)

  useEffect(() => subscribeDeferredAnalysis(setDeferredAnalysis), [])

  const load = useCallback(async () => {
    try {
      const rows = await documentsApi.list({ status: statusFilter || undefined, doc_type: typeFilter || undefined })
      // List omits `extracted`. Merge so 3s polling never wipes confirm buttons
      // and rating chips that were backfilled via GET /documents/{id}.
      setDocs((prev) => {
        const prevById = new Map(prev.map((d) => [d.id, d]))
        return rows.map((row) => {
          const old = prevById.get(row.id)
          if (!old) return row
          return {
            ...row,
            extracted: row.extracted !== undefined ? row.extracted : old.extracted,
            text_content: row.text_content !== undefined ? row.text_content : old.text_content,
          }
        })
      })
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [statusFilter, typeFilter])

  // GET /documents/summary feeds the header strip — degrade silently (older
  // backend, or a transient error) rather than showing a broken strip.
  const loadSummary = useCallback(async () => {
    try {
      setSummary(await documentsApi.summary())
    } catch {
      setSummary(null)
    }
  }, [])

  // Review queue pending counts for the post-process banner. Degrade silently
  // if the endpoint 404s (older backend).
  const loadReviewPending = useCallback(async () => {
    try {
      const items = await documentsApi.reviewQueue()
      const values = items.reduce(
        (n, it) => n + (it.fields_pending || 0) + (it.missing_conditions || 0),
        0,
      )
      setReviewPendingValues(values > 0 ? values : items.length)
    } catch {
      setReviewPendingValues(null)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    void load()
    void loadSummary()
    void loadReviewPending()
  }, [load, loadSummary, loadReviewPending])

  useEffect(() => {
    conditionsApi.list().then(setConditions).catch(() => setConditions([]))
  }, [])

  // Poll every 3s while anything is still uploaded/processing — refresh the
  // summary strip alongside the list so its counts stay live too.
  useEffect(() => {
    const inFlight = docs.some((d) => d.status === 'uploaded' || d.status === 'processing')
    if (!inFlight) return
    const t = window.setInterval(() => {
      void load()
      void loadSummary()
      void loadReviewPending()
    }, 3000)
    return () => window.clearInterval(t)
  }, [docs, load, loadSummary, loadReviewPending])

  // When a processing wave settles (all ready / none in-flight) and at least one
  // doc is ready, surface the success nudge + refresh review-queue counts.
  useEffect(() => {
    const inFlight = docs.some((d) => d.status === 'uploaded' || d.status === 'processing')
    const readyCount = docs.filter((d) => d.status === 'ready').length
    if (inFlight) {
      wasProcessingRef.current = true
      return
    }
    if (wasProcessingRef.current && readyCount > 0) {
      wasProcessingRef.current = false
      setShowProcessDoneNudge(true)
      void loadReviewPending()
      void loadSummary()
      // Do NOT prewarm case-candidates here — that hits analysis (and optionally GPU)
      // without an explicit click. Build Case starts only when the veteran asks.
      // One-shot identity re-extract per browser session after a processing wave.
      try {
        if (sessionStorage.getItem('vo_identity_reextract_once') !== '1') {
          sessionStorage.setItem('vo_identity_reextract_once', '1')
          void profileApi.reextractIdentity().catch(() => {})
        }
      } catch {
        /* storage unavailable */
      }
    }
  }, [docs, loadReviewPending, loadSummary])

  // GET /documents (list) omits `extracted` — backfill it per "ready" document
  // via GET /documents/{id} so review cards can show conditions/rating info.
  useEffect(() => {
    const toFetch = docs.filter((d) => d.status === 'ready' && d.extracted === undefined)
    if (toFetch.length === 0) return
    let cancelled = false
    void Promise.all(toFetch.map((d) => documentsApi.get(d.id).catch(() => null))).then((details) => {
      if (cancelled) return
      setDocs((prev) =>
        prev.map((d) => {
          const detail = details.find((x) => x?.id === d.id)
          return detail ? { ...d, ...detail } : d
        })
      )
    })
    return () => {
      cancelled = true
    }
  }, [docs])

  const handleFiles = async (files: File[]) => {
    const overLimit = (f: File) => f.size > maxBytesFor(f)
    const tooLarge = files.filter(overLimit)
    const ok = files.filter((f) => !overLimit(f))
    if (tooLarge.length > 0) {
      // Name each oversized file + its size so it's never mistaken for a file
      // that's silently "still processing" — a common Blue Button confusion.
      for (const f of tooLarge.slice(0, 5)) {
        toast(
          `"${f.name}" (${formatBytes(f.size)}) is too large to upload — it was NOT added. ` +
            `Limit: 95MB for text/XML, 50MB otherwise. Try a smaller date range or split it.`,
          'error',
        )
      }
      if (tooLarge.length > 5) {
        toast(`…and ${tooLarge.length - 5} more oversized file(s) were skipped.`, 'error')
      }
    }
    if (ok.length === 0) return
    setUploading(true)
    try {
      // A big folder drop is split into sequential batches so it never trips the
      // backend's per-request file-count cap or the edge body-size limit. Each
      // batch's accepted docs are prepended as they land, so the list fills in
      // progressively instead of waiting for the whole dump.
      const batches = batchForUpload(ok)
      const allItems: DocumentUploadItem[] = []
      for (let i = 0; i < batches.length; i++) {
        if (batches.length > 1) {
          toast(`Uploading ${ok.length} files — batch ${i + 1} of ${batches.length}…`, 'info')
        }
        const result = await documentsApi.upload(batches[i])
        allItems.push(...result.items)
        const acc = result.items.filter((it) => it.accepted && it.document)
        if (acc.length > 0) {
          setDocs((prev) => [...acc.map((it) => it.document as DocumentItem), ...prev])
        }
      }
      const accepted = allItems.filter((it) => it.accepted && it.document)
      const rejected = allItems.filter((it) => !it.accepted)
      if (accepted.length > 0) {
        toast(`${accepted.length} file${accepted.length === 1 ? '' : 's'} uploaded — processing…`, 'success')
      }
      // M2: if the veteran opted in, arm a session-scoped wait so analysis still
      // starts if they leave this page while the batch processes.
      if (analyzeAfterUpload && accepted.length > 0) {
        armDeferredAnalysis(accepted.map((it) => (it.document as DocumentItem).id))
      }
      // Cap the error toasts so a large dump can't spray hundreds of them.
      for (const item of rejected.slice(0, 8)) {
        toast(`${item.filename}: ${item.detail ?? (item.duplicate ? 'Already uploaded.' : 'Rejected.')}`, 'error')
      }
      if (rejected.length > 8) {
        toast(`…and ${rejected.length - 8} more file${rejected.length - 8 === 1 ? '' : 's'} skipped.`, 'error')
      }
      void loadSummary()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setUploading(false)
    }
  }

  const retryAllFailed = async () => {
    setRetryingFailed(true)
    try {
      const result = await documentsApi.reprocessFailed()
      toast(
        result.requeued > 0
          ? `Reprocessing ${result.requeued} document${result.requeued === 1 ? '' : 's'}…`
          : 'Nothing to retry.',
        result.requeued > 0 ? 'info' : 'success'
      )
      await Promise.all([load(), loadSummary()])
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setRetryingFailed(false)
    }
  }

  // After a "Reset my records" wipe: reflect the emptied state immediately, then
  // re-sync docs / summary / conditions from the server and surface the counts.
  const handleResetDone = (result: ResetRecords) => {
    setResetResult(result)
    setDocs([])
    setViewerDoc(null)
    void load()
    void loadSummary()
    conditionsApi.list().then(setConditions).catch(() => setConditions([]))
    toast(
      `Records reset — deleted ${result.documents} document${result.documents === 1 ? '' : 's'} and everything derived from them.`,
      'success',
    )
  }

  const remove = async (id: string) => {
    if (!window.confirm('Delete this document? This cannot be undone.')) return
    try {
      await documentsApi.remove(id)
      setDocs((prev) => prev.filter((d) => d.id !== id))
      toast('Document deleted.', 'success')
      void loadSummary()
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const reprocess = async (id: string) => {
    try {
      // response_model=DocumentOut — no `extracted`; clear it locally so the
      // ready-document backfill effect refetches once processing finishes.
      const updated = await documentsApi.reprocess(id)
      setDocs((prev) => prev.map((d) => (d.id === id ? { ...d, ...updated, extracted: undefined } : d)))
      toast('Reprocessing started.', 'info')
      void loadSummary()
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const updateDocType = async (id: string, doc_type: DocType) => {
    try {
      // response_model=DocumentDetailOut — includes `extracted`, safe to merge whole.
      const updated = await documentsApi.update(id, { doc_type })
      setDocs((prev) => prev.map((d) => (d.id === id ? { ...d, ...updated } : d)))
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const linkToCondition = async (
    doc: DocumentItem,
    conditionId: string,
    conditionName: string,
  ): Promise<boolean> => {
    try {
      const kind = DOC_TYPE_TO_EVIDENCE_KIND[doc.doc_type ?? 'other']
      const result = await documentsApi.link(doc.id, { condition_id: conditionId, kind })
      // result.document is a DocumentOut (no `extracted`) — merge only the
      // fields it carries so the cached extraction detail isn't clobbered.
      setDocs((prev) => prev.map((d) => (d.id === doc.id ? { ...d, condition_id: result.document.condition_id } : d)))
      toast(`Linked to ${conditionName}.`, 'success')
      return true
    } catch (err) {
      toast(errorMessage(err), 'error')
      return false
    }
  }

  // Returns whether the rating was actually persisted, so the button only marks
  // itself "Updated" on real success — never on a silent no-op or an error (which
  // is what made confirming a rating look like it "did nothing").
  const confirmRating = async (
    item: DocConditionMention,
    suggestedConditionId: string | null | undefined,
  ): Promise<boolean> => {
    if (item.rating_percent == null) {
      toast(`No rating percentage was read for ${item.name}, so there's nothing to confirm.`, 'error')
      return false
    }
    try {
      const existing = suggestedConditionId
        ? conditions.find((c) => c.id === suggestedConditionId)
        : conditions.find((c) => c.name.toLowerCase() === item.name.toLowerCase())
      if (existing) {
        const updated = await conditionsApi.update(existing.id, { current_rating: item.rating_percent })
        setConditions((prev) => prev.map((c) => (c.id === updated.id ? updated : c)))
        toast(`Updated ${existing.name} to ${item.rating_percent}%.`, 'success')
      } else {
        const created = await conditionsApi.create({
          name: item.name,
          claim_type: 'increase',
          status: 'considering',
          current_rating: item.rating_percent,
          diagnostic_code: item.diagnostic_code ?? undefined,
        })
        setConditions((prev) => [created, ...prev])
        toast(`Added ${item.name} at ${item.rating_percent}%.`, 'success')
      }
      return true
    } catch (err) {
      toast(errorMessage(err), 'error')
      return false
    }
  }

  // One card render, shared by the flat and grouped views so both stay in
  // lockstep as callbacks change.
  const renderCard = (doc: DocumentItem) => (
    <DocumentCard
      key={doc.id}
      doc={doc}
      conditions={conditions}
      onDelete={() => void remove(doc.id)}
      onReprocess={() => void reprocess(doc.id)}
      onDocTypeChange={(t) => void updateDocType(doc.id, t)}
      onLink={(conditionId, name) => linkToCondition(doc, conditionId, name)}
      onConfirmRating={(item, conditionId) => confirmRating(item, conditionId)}
      onView={() => setViewerDoc(doc)}
    />
  )

  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Document intake</p>
        <h1 className="vo-page-title">Documents</h1>
        <p className="vo-page-sub">
          Dump everything that supports your claim — C-file, rating decisions, STRs, DBQs, treatment notes, private
          opinions, nexus letters, scanned paper. The same medical records often live in Glitter Mane as your health
          chart; here they become <strong className="font-semibold text-txt">claim evidence</strong> you confirm.
          Rating Raider reads each file privately on our servers — never commercial AI clouds. Nothing is filed for you.
        </p>
        <p className="mt-2 text-xs leading-relaxed text-faint">
          Self-help software: you organize and prepare; you or a free accredited VSO file. We never e-file.
        </p>
      </div>

      {resetResult && <ResetResultBanner result={resetResult} onDismiss={() => setResetResult(null)} />}

      {summary && summary.total > 0 && <SummaryStrip summary={summary} onRetryFailed={() => void retryAllFailed()} retrying={retryingFailed} />}

      {/* Pending review queue — primary post-process action when values need confirmation.
          Sticky near the top so it doesn't "jump away" as individual cards re-render. */}
      {reviewPendingValues != null && reviewPendingValues > 0 && (
        <div
          className="vo-card vo-accent sticky top-2 z-10 flex flex-wrap items-center gap-3 p-4 sm:p-5"
          style={hueStyle('amber') as CSSProperties}
          role="status"
        >
          <span
            aria-hidden
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
            style={{ background: hueSoftVar('amber'), color: hueInk('amber') }}
          >
            <ClipboardCheck size={20} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="font-semibold text-txt">
              {reviewPendingValues} value{reviewPendingValues === 1 ? '' : 's'} need your confirmation
            </p>
            <p className="text-sm text-muted">
              Approve/correct flagged fields in the <strong className="text-txt">Review queue</strong> (separate page).
              On each document card you can also link conditions and confirm rating % from decision letters — those
              buttons stay on the card when the file is Ready.
            </p>
          </div>
          <Link to="/review-queue" className="vo-btn-primary shrink-0 text-sm">
            Open review queue <ArrowRight size={14} />
          </Link>
        </div>
      )}

      {/* After a processing wave completes: clear next-step nudge. */}
      {showProcessDoneNudge &&
        !docs.some((d) => d.status === 'uploaded' || d.status === 'processing') &&
        docs.some((d) => d.status === 'ready') && (
          <div
            className="vo-card vo-accent flex flex-wrap items-center gap-3 p-4 sm:p-5"
            style={hueStyle('emerald') as CSSProperties}
            role="status"
          >
            <span
              aria-hidden
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
              style={{ background: hueSoftVar('emerald'), color: hueInk('emerald') }}
            >
              <CheckCircle2 size={20} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="font-semibold text-txt">
                {reviewPendingValues != null && reviewPendingValues > 0
                  ? 'Next: confirm what we found'
                  : analysisStartedRunId
                    ? 'Records ready — analysis is running'
                    : 'Records ready — next step'}
              </p>
              <p className="text-sm text-muted">
                {reviewPendingValues != null && reviewPendingValues > 0
                  ? 'Confirm flagged values first, then populate your case and run analysis. Suggestions are already preparing in the background.'
                  : analysisStartedRunId
                    ? 'Your opted-in full analysis started automatically. Also confirm profile details and conditions when ready.'
                    : 'Suggested path: confirm findings → populate case from records → run analysis. Nothing is filed for you.'}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {reviewPendingValues != null && reviewPendingValues > 0 ? (
                <Link to="/review-queue" className="vo-btn-primary shrink-0 text-sm">
                  Confirm values <ArrowRight size={14} />
                </Link>
              ) : (
                <Link to="/build-case" className="vo-btn-primary shrink-0 text-sm">
                  <Sparkles size={14} /> Populate case from records
                </Link>
              )}
              <Link to="/profile?start=1" className="vo-btn-secondary shrink-0 text-sm">
                Profile suggestions
              </Link>
              <Link to="/analysis" className="vo-btn-secondary shrink-0 text-sm">
                Analysis Center
              </Link>
              <button
                type="button"
                onClick={() => setShowProcessDoneNudge(false)}
                className="vo-btn-ghost shrink-0 text-sm"
                aria-label="Dismiss next-step nudge"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

      {docs.some((d) => d.status === 'ready') && (
        <RecordsSearch onOpenDocument={(doc) => setViewerDoc(doc)} onResetDone={handleResetDone} />
      )}

      <InvitingDropZone onFiles={(files) => void handleFiles(files)} disabled={uploading} />
      <UploadGuidance />
      <div className="flex flex-wrap items-center gap-2">
        <span className="vo-chip-hue" style={hueStyle('teal') as CSSProperties}>
          <FileCode2 size={12} /> VA Health Summary (CCD XML) supported — parsed exactly, no AI needed
        </span>
        <span className="vo-chip-hue" style={hueStyle('amber') as CSSProperties}>
          <Archive size={12} /> ZIP archives supported
        </span>
      </div>

      {/* M2 — opt-in: analysis only ever runs because the veteran asked for it
          here, and only once this upload finishes. Survives navigating away. */}
      <Checkbox
        label="Analyze after upload finishes processing"
        description="When this batch finishes reading, we start one full comprehensive analysis over your whole file — even if you leave this page. Leave off to run it yourself later from Analysis Center. Nothing is filed for you."
        checked={analyzeAfterUpload}
        onChange={(e) => setAnalyzeAfterUploadOptIn(e.target.checked)}
      />
      {analysisWaiting && (
          <p className="flex items-center gap-2 text-sm text-muted" role="status">
            <Loader2 size={14} className="animate-spin" />
            Analysis will start automatically once processing finishes for this batch
            {deferredAnalysis.pendingIds.length > 0
              ? ` (${deferredAnalysis.pendingIds.length} file${deferredAnalysis.pendingIds.length === 1 ? '' : 's'} watching)`
              : ''}
            . Safe to leave this page — progress continues in the background.
          </p>
        )}
      {analysisStartedRunId && (
        <div
          className="flex flex-wrap items-center justify-between gap-3 rounded-control border px-4 py-3 text-sm"
          style={{ borderColor: 'color-mix(in srgb, var(--hue-fuchsia) 30%, transparent)', background: 'var(--hue-fuchsia-soft)' }}
          role="status"
        >
          <p className="flex items-center gap-2 text-txt">
            <Sparkles size={15} style={{ color: hueInk('fuchsia') }} />
            Full analysis started after upload — it runs in the background even if you leave.
          </p>
          <Link to="/analysis" className="vo-btn-secondary shrink-0 text-xs">
            View progress on Analysis Center
          </Link>
        </div>
      )}
      {analysisStartError && (
        <p className="flex items-center gap-2 text-sm text-danger" role="alert">
          <FileWarning size={14} /> Couldn&apos;t start analysis automatically ({analysisStartError}). You can start it from the{' '}
          <Link to="/analysis" className="font-semibold text-brand hover:text-brand-hover">
            Analysis Center
          </Link>
          .
        </p>
      )}

      {uploading && (
        <p className="flex items-center gap-2 text-sm text-muted">
          <Spinner size={14} /> Uploading…
        </p>
      )}

      <div className="flex flex-wrap gap-3">
        <label className="text-sm">
          <span className="vo-label">Status</span>
          <select className="vo-input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{humanize(s)}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="vo-label">Type</span>
          <select className="vo-input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
            <option value="">All types</option>
            {DOC_TYPES.map((t) => (
              <option key={t} value={t}>{humanize(t)}</option>
            ))}
          </select>
        </label>
        <label
          className={`flex cursor-pointer select-none items-center gap-2 self-end pb-2 text-sm ${
            typeFilter ? 'cursor-not-allowed opacity-50' : 'text-muted hover:text-txt'
          }`}
          title={typeFilter ? 'Already filtered to one type' : 'Group the list by document type'}
        >
          <input
            type="checkbox"
            className="vo-check"
            checked={grouped && !typeFilter}
            disabled={!!typeFilter}
            onChange={(e) => setGrouped(e.target.checked)}
          />
          Group by type
        </label>
      </div>

      {docs.length > 0 && <Legend groups={DOC_LEGEND_GROUPS} />}

      {loading ? (
        <LoadingBlock label="Loading documents…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={() => void load()} />
      ) : docs.length === 0 ? (
        <EmptyState
          hue="amber"
          icon={<UploadCloud size={20} />}
          title="No documents yet"
          description="Rating decisions, service treatment records, DBQs, provider notes, discharge paperwork — military, VA, or private medical, scanned or digital. Drop it above (ZIPs welcome) and Rating Raider will sort it out."
          action={
            <Link to="/records" className="text-sm font-semibold text-brand hover:text-brand-hover">
              Don't have some of these yet? Get your records →
            </Link>
          }
        />
      ) : grouped && !typeFilter ? (
        <div className="space-y-6">
          {groupDocuments(docs).map((g) => (
            <section key={g.key} className="space-y-3">
              <div className="flex items-center gap-2">
                {g.kind === 'type' ? (
                  <DocTypeBadge type={g.type} />
                ) : g.kind === 'flagged' ? (
                  <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-danger">
                    <FileWarning size={13} /> Possibly not related
                  </span>
                ) : (
                  <span className="text-xs font-semibold text-muted">Not yet sorted</span>
                )}
                <span className="text-micro tabular-nums text-faint">{g.docs.length}</span>
              </div>
              <div className="space-y-4">{g.docs.map(renderCard)}</div>
            </section>
          ))}
        </div>
      ) : (
        <div className="space-y-4">{docs.map(renderCard)}</div>
      )}
      <DocumentViewer doc={viewerDoc} onClose={() => setViewerDoc(null)} />
    </div>
  )
}

/** DropZone (shared component) wrapped in a page-local "inviting" shell: a
 * glow ring that reacts to drag-over (via DropZone's onDragStateChange) and a
 * soft hover lift so the target reads as an obvious, friendly landing spot
 * rather than a bare dashed box. */
/** Semantic search over the veteran's OWN uploaded records (document RAG). It
 * surfaces the passages in their evidence — it never adds an interpretation. */
function RecordsSearch({
  onOpenDocument,
  onResetDone,
}: {
  onOpenDocument: (doc: DocumentItem) => void
  onResetDone: (result: ResetRecords) => void
}) {
  const { toast } = useToast()
  const [q, setQ] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [result, setResult] = useState<DocumentSearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reindexing, setReindexing] = useState(false)
  const [reocring, setReocring] = useState(false)

  const run = useCallback(async (raw: string) => {
    const term = raw.trim()
    if (term.length < 2) return
    setLoading(true)
    setError(null)
    setSubmitted(term)
    try {
      setResult(await documentsApi.search(term, { k: 8 }))
    } catch (e) {
      setError(errorMessage(e))
      setResult(null)
    } finally {
      setLoading(false)
    }
  }, [])

  // Heal records that predate document-RAG (no chunks) or were chunked during
  // an embeddings outage (no vectors) — POST /documents/reindex re-chunks +
  // re-embeds them from stored text. No re-OCR; runs in the background.
  const reindex = useCallback(async () => {
    setReindexing(true)
    try {
      const r = await documentsApi.reindex()
      toast(
        r.queued > 0
          ? `Indexing ${r.queued} record${r.queued === 1 ? '' : 's'} for search — this runs in the background.`
          : 'All your records are already searchable.',
        r.queued > 0 ? 'info' : 'success',
      )
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setReindexing(false)
    }
  }, [toast])

  // Re-OCR every stored record through the CURRENT OCR pipeline (page
  // preprocessing + the decorrelated cross-read engine). Unlike reprocess, this
  // CLEARS the cached text so the file is genuinely re-read — that's how an OCR
  // improvement reaches documents that were already extracted. Costs a credit each.
  const reprocessOcr = useCallback(async () => {
    setReocring(true)
    try {
      const r = await documentsApi.reprocessOcr()
      toast(
        r.requeued > 0
          ? `Re-reading ${r.requeued} record${r.requeued === 1 ? '' : 's'} with the latest OCR — this runs in the background.`
          : 'No stored records to re-OCR (re-upload any whose file is gone).',
        r.requeued > 0 ? 'info' : 'success',
      )
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setReocring(false)
    }
  }, [toast])

  return (
    <section className="vo-card space-y-3 p-4 sm:p-5" style={hueStyle('sky') as CSSProperties}>
      <div className="space-y-1">
        <p className="flex items-center gap-1.5 text-micro font-semibold uppercase" style={{ color: hueInk('sky') }}>
          <Search size={13} /> Search your records
        </p>
        <p className="vo-caption">
          Ask in plain words — “continuity of knee pain”, “tinnitus onset”, “PTSD stressor”. Rating Raider finds the
          passages inside your own uploaded documents so you can point straight to your evidence. It reads privately on
          our servers and never adds an opinion.
        </p>
      </div>
      <form className="flex flex-col gap-2 sm:flex-row" onSubmit={(e) => { e.preventDefault(); void run(q) }}>
        <input
          className="vo-input flex-1"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Find something in your records…"
          aria-label="Search your records"
        />
        <button type="submit" className="vo-btn-primary shrink-0" disabled={loading || q.trim().length < 2}>
          {loading ? <Spinner size={14} /> : <Search size={14} />} Search
        </button>
      </form>
      {loading ? (
        <LoadingBlock label="Searching your records…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={() => void run(submitted)} />
      ) : result ? (
        result.hits.length === 0 ? (
          <p className="vo-caption">
            No passages in your records matched “{submitted}”. Try different words, or upload more records above.
          </p>
        ) : (
          <div className="space-y-2">
            <p className="text-micro text-muted">
              {result.hits.length} passage{result.hits.length === 1 ? '' : 's'} from your records ·{' '}
              {result.semantic ? 'meaning-based match' : 'keyword match'}
            </p>
            {result.hits.map((h, i) => (
              <RecordExcerpt key={`${h.document_id}-${h.chunk_index}-${i}`} hit={h} onOpenDocument={onOpenDocument} />
            ))}
          </div>
        )
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2.5">
        <p className="text-micro text-faint">
          Improved the reader? Re-OCR re-reads your files with the latest engine. Index makes older records searchable.
        </p>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
          <button
            type="button"
            onClick={() => void reprocessOcr()}
            disabled={reocring}
            className="vo-btn-ghost text-micro font-semibold text-muted hover:text-txt"
            title="Clear the cached text and re-read every stored record through the current OCR pipeline (preprocessing + cross-read). Costs a credit per record."
          >
            {reocring ? <Spinner size={12} /> : <RefreshCw size={12} />} Re-OCR my records
          </button>
          <button
            type="button"
            onClick={() => void reindex()}
            disabled={reindexing}
            className="vo-btn-ghost text-micro font-semibold text-muted hover:text-txt"
          >
            {reindexing ? <Spinner size={12} /> : <RefreshCw size={12} />} Index older records
          </button>
          <ResetRecordsButton onDone={onResetDone} />
        </div>
      </div>
    </section>
  )
}

/** "Reset my records" — DESTRUCTIVE right-to-erasure + cold-benchmark reset. Opens
 * a confirmation modal that spells out what is deleted vs. preserved and requires
 * the veteran to type RESET before the button enables. On success it hands the
 * counts back up so the page can refresh + show what was wiped. */
function ResetRecordsButton({ onDone }: { onDone: (result: ResetRecords) => void }) {
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [resetting, setResetting] = useState(false)
  const canReset = confirmText.trim().toUpperCase() === 'RESET'

  const close = () => {
    if (resetting) return
    setOpen(false)
    setConfirmText('')
  }

  const doReset = async () => {
    if (!canReset || resetting) return
    setResetting(true)
    try {
      const result = await documentsApi.reset()
      setOpen(false)
      setConfirmText('')
      onDone(result)
    } catch (err) {
      toast(errorMessage(err), 'error')
      setResetting(false)
    }
  }

  // Escape closes the modal (unless a reset is in flight).
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !resetting) {
        setOpen(false)
        setConfirmText('')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, resetting])

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="vo-btn-ghost text-micro font-semibold text-danger hover:bg-danger-soft hover:text-danger"
        title="Permanently delete ALL your uploaded records and everything derived from them. Preserves your account, profile, deadlines, symptom logs, and analysis-run history."
      >
        <RotateCcw size={12} /> Reset my records
      </button>
      {open && (
        <ResetRecordsModal
          confirmText={confirmText}
          onConfirmTextChange={setConfirmText}
          canReset={canReset}
          resetting={resetting}
          onCancel={close}
          onConfirm={() => void doReset()}
        />
      )}
    </>
  )
}

const RESET_DELETED = [
  'Uploaded documents',
  'Extracted facts',
  'Search-index chunks',
  'Conditions',
  'Evidence items',
  'Evidence citations',
  'Rating scenarios',
  'Checklist items',
  'Analysis caches',
]

const RESET_PRESERVED = [
  'Your account & profile',
  'ITF deadlines',
  'Symptom logs',
  'VA connections',
  'Prior analysis-run history',
]

function ResetRecordsModal({
  confirmText,
  onConfirmTextChange,
  canReset,
  resetting,
  onCancel,
  onConfirm,
}: {
  confirmText: string
  onConfirmTextChange: (value: string) => void
  canReset: boolean
  resetting: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-3"
      role="dialog"
      aria-modal="true"
      aria-labelledby="reset-records-title"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCancel()
      }}
    >
      <div className="flex max-h-[92vh] w-full max-w-lg flex-col overflow-hidden rounded-pane border border-line bg-surface shadow-xl">
        <div className="flex items-start gap-3 border-b border-line px-5 py-4">
          <span
            aria-hidden
            className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
            style={{ background: 'var(--danger-soft)', color: 'var(--danger)' }}
          >
            <TriangleAlert size={18} />
          </span>
          <div className="min-w-0">
            <h2 id="reset-records-title" className="text-heading text-txt">
              Reset my records
            </h2>
            <p className="text-xs text-muted">Permanent and irreversible</p>
          </div>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
          <p className="text-sm leading-relaxed text-txt">
            This permanently deletes <strong>all your uploaded records</strong> and everything Rating Raider derived
            from them. It cannot be undone — consider downloading your data from Settings first.
          </p>

          <div className="rounded-control border border-danger-soft bg-danger-soft/40 p-3.5">
            <p className="flex items-center gap-1.5 text-micro font-semibold uppercase tracking-wide text-danger">
              <Trash2 size={12} /> Permanently deleted
            </p>
            <ul className="mt-2 grid gap-x-4 gap-y-1 text-sm text-txt/90 sm:grid-cols-2">
              {RESET_DELETED.map((t) => (
                <li key={t} className="flex items-start gap-1.5">
                  <span aria-hidden className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-danger" /> {t}
                </li>
              ))}
            </ul>
          </div>

          <div
            className="rounded-control border p-3.5"
            style={{
              borderColor: 'color-mix(in srgb, var(--hue-emerald) 30%, transparent)',
              background: 'var(--hue-emerald-soft)',
            }}
          >
            <p
              className="flex items-center gap-1.5 text-micro font-semibold uppercase tracking-wide"
              style={{ color: hueInk('emerald') }}
            >
              <ShieldCheck size={12} /> Kept safe
            </p>
            <ul className="mt-2 grid gap-x-4 gap-y-1 text-sm text-txt/90 sm:grid-cols-2">
              {RESET_PRESERVED.map((t) => (
                <li key={t} className="flex items-start gap-1.5">
                  <CheckCircle2 size={13} className="mt-0.5 shrink-0" style={{ color: hueInk('emerald') }} /> {t}
                </li>
              ))}
            </ul>
          </div>

          <div className="space-y-2">
            <label htmlFor="reset-confirm" className="block text-xs font-semibold text-txt">
              Type <strong style={{ color: 'var(--danger)' }}>RESET</strong> to confirm:
            </label>
            <input
              id="reset-confirm"
              type="text"
              autoComplete="off"
              autoFocus
              value={confirmText}
              onChange={(e) => onConfirmTextChange(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && canReset && !resetting) onConfirm()
              }}
              placeholder="RESET"
              className="vo-input focus:border-danger"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line px-5 py-4">
          <button type="button" onClick={onCancel} disabled={resetting} className="vo-btn-ghost text-sm">
            Cancel
          </button>
          <button type="button" onClick={onConfirm} disabled={!canReset || resetting} className="vo-btn-danger text-sm">
            {resetting ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
            {resetting ? 'Resetting…' : 'Permanently reset my records'}
          </button>
        </div>
      </div>
    </div>
  )
}

/** Page-level confirmation of a reset: the counts wiped + a nudge to re-upload the
 * C-file. Survives the RecordsSearch unmount that follows an emptied doc list. */
function ResetResultBanner({ result, onDismiss }: { result: ResetRecords; onDismiss: () => void }) {
  const stats: { label: string; n: number }[] = [
    { label: 'documents', n: result.documents },
    { label: 'conditions', n: result.conditions },
    { label: 'evidence items', n: result.evidence },
    { label: 'citations', n: result.citations },
    { label: 'facts', n: result.facts },
    { label: 'chunks', n: result.chunks },
    { label: 'scenarios', n: result.scenarios },
    { label: 'checklist items', n: result.checklist },
    { label: 'caches', n: result.caches },
  ].filter((s) => s.n > 0)

  return (
    <div className="vo-panel vo-accent p-5" style={hueStyle('emerald') as CSSProperties} role="status">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
            style={{ background: hueSoftVar('emerald'), color: hueInk('emerald') }}
          >
            <CheckCircle2 size={18} />
          </span>
          <div className="min-w-0">
            <h2 className="text-heading text-txt">Your records were reset</h2>
            <p className="mt-1 text-sm leading-relaxed text-muted">
              {stats.length > 0 ? (
                <>
                  Deleted{' '}
                  {stats.map((s, i) => (
                    <span key={s.label}>
                      {i > 0 ? ', ' : ''}
                      <strong className="tabular-nums text-txt">{s.n}</strong> {s.label}
                    </span>
                  ))}
                  .
                </>
              ) : (
                'There was nothing left to delete.'
              )}
            </p>
            <p className="mt-2 text-sm text-txt/90">
              You're starting fresh — upload your C-file again below to rebuild your case (and capture a cold
              benchmark). Your profile, deadlines, symptom logs, and analysis-run history were kept.
            </p>
          </div>
        </div>
        <button type="button" onClick={onDismiss} className="vo-icon-btn vo-btn-ghost shrink-0" aria-label="Dismiss">
          <X size={16} />
        </button>
      </div>
    </div>
  )
}

function RecordExcerpt({ hit, onOpenDocument }: { hit: DocumentSearchHit; onOpenDocument: (doc: DocumentItem) => void }) {
  const open = () => {
    onOpenDocument({
      id: hit.document_id,
      filename: hit.filename,
      title: hit.title,
      content_type: null,
      size_bytes: 0,
      sha256: '',
      status: 'ready',
      doc_type: hit.doc_type,
      doc_date: hit.doc_date,
      summary: null,
      condition_id: null,
      error: null,
      created_at: '',
      updated_at: '',
    })
  }
  return (
    <button
      type="button"
      onClick={open}
      className="block w-full space-y-1.5 rounded-control border border-line bg-surface2 p-3 text-left transition hover:border-brand/40 hover:bg-surface"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-micro font-semibold">{hit.title || hit.filename}</span>
        {hit.doc_type && <DocTypeBadge type={hit.doc_type} />}
        {hit.doc_date && <span className="text-micro text-muted">{formatDate(hit.doc_date)}</span>}
      </div>
      <p className="whitespace-pre-wrap text-body">{hit.excerpt}</p>
    </button>
  )
}

function InvitingDropZone({ onFiles, disabled }: { onFiles: (files: File[]) => void; disabled?: boolean }) {
  const [active, setActive] = useState(false)
  const [hover, setHover] = useState(false)

  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      className="relative rounded-pane transition-all duration-200"
      style={{
        boxShadow: active
          ? '0 0 0 1px var(--hue-amber), 0 12px 40px color-mix(in srgb, var(--hue-amber) 32%, transparent)'
          : hover && !disabled
            ? '0 8px 28px color-mix(in srgb, var(--hue-amber) 18%, transparent)'
            : 'none',
        transform: active ? 'scale(1.005)' : 'scale(1)',
      }}
    >
      <DropZone
        onFiles={onFiles}
        disabled={disabled}
        onDragStateChange={setActive}
        accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.gif,.webp,.heic,.heif,.txt,.csv,.xml,.docx,.doc,.rtf,.odt,.xlsx,.xls,.zip"
        hint="Loose files, whole folders, or ZIPs — PDFs, scans & photos (incl. iPhone HEIC), Word/RTF/OpenDocument, Excel, TXT, and VA Health Summary XML. 50MB per file, 200MB per ZIP"
      />
    </div>
  )
}

/** Header strip fed by GET /documents/summary — counts by status at a glance,
 * plus a one-click "Retry all failed" (POST /documents/reprocess-failed).
 * `queued` reads from by_status.uploaded specifically so it stays visually
 * distinct from `processing`, even though both mean "not ready yet". */
function SummaryStrip({
  summary,
  onRetryFailed,
  retrying,
}: {
  summary: DocumentSummary
  onRetryFailed: () => void
  retrying: boolean
}) {
  const ready = summary.by_status.ready ?? 0
  const queued = summary.queued ?? summary.by_status.uploaded ?? 0
  const processing = summary.processing ?? summary.by_status.processing ?? 0
  const failed = summary.by_status.failed ?? 0

  return (
    <div
      className="vo-panel vo-accent flex flex-wrap items-center justify-between gap-3 px-5 py-3.5"
      style={hueStyle('amber') as CSSProperties}
    >
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
        <SummaryStat label="Total" value={summary.total} />
        {ready > 0 && <SummaryStat label="Ready" value={ready} hue="emerald" />}
        {queued > 0 && <SummaryStat label="Queued" value={queued} hue="sky" />}
        {processing > 0 && <SummaryStat label="Processing" value={processing} hue="amber" />}
        {failed > 0 && <SummaryStat label="Failed" value={failed} hue="rose" />}
      </div>
      {failed > 0 && (
        <button onClick={onRetryFailed} disabled={retrying} className="vo-btn-secondary shrink-0 text-xs">
          {retrying ? <Spinner size={13} /> : <RefreshCw size={13} />}
          Retry all failed
        </button>
      )}
    </div>
  )
}

function SummaryStat({ label, value, hue }: { label: string; value: number; hue?: Hue }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span
        className="text-base font-bold tabular-nums text-txt"
        style={hue ? { color: hueInk(hue) } : undefined}
      >
        {value}
      </span>
      <span className="text-xs text-faint">{label}</span>
    </span>
  )
}

function StatusIndicator({ status }: { status: DocumentStatus }) {
  if (status === 'processing' || status === 'uploaded') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-warn">
        <Loader2 size={13} className="animate-spin" /> {humanize(status)}
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-medium text-danger">
        <FileWarning size={13} /> Failed
      </span>
    )
  }
  if (status === 'duplicate') {
    return (
      <span
        className="inline-flex items-center gap-1.5 text-xs font-medium text-muted"
        title="Skipped — this is the same content as a document you already have, so it wasn't processed or analyzed again."
      >
        <Copy size={13} /> Duplicate — skipped
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium text-success">
      <CheckCircle2 size={13} /> Ready
    </span>
  )
}

/** Processing state gets a shimmer treatment (reusing the shared .vo-skel
 * shimmer keyframe from index.css/tailwind.config.js) instead of a bare
 * spinner line — reads as active work happening, not a stuck screen. */
function ProcessingBlock() {
  return (
    <div className="space-y-2.5 rounded-control border border-[color-mix(in_oklab,var(--hue-sky)_25%,transparent)] bg-h-sky-soft/40 p-3.5">
      <p className="flex items-center gap-2 text-sm text-txt">
        <Loader2 size={14} className="animate-spin text-h-sky" />
        Reading and summarizing this document — this page checks in every few seconds.
      </p>
      <div className="space-y-1.5">
        <div className="vo-skel h-3 w-full" />
        <div className="vo-skel h-3 w-5/6" />
        <div className="vo-skel h-3 w-2/3" />
      </div>
    </div>
  )
}

function DocumentCard({
  doc,
  conditions,
  onDelete,
  onReprocess,
  onDocTypeChange,
  onLink,
  onConfirmRating,
  onView,
}: {
  doc: DocumentItem
  conditions: ClaimedCondition[]
  onDelete: () => void
  onReprocess: () => void
  onDocTypeChange: (t: DocType) => void
  onLink: (conditionId: string, name: string) => Promise<boolean>
  onConfirmRating: (item: DocConditionMention, conditionId: string | null | undefined) => Promise<boolean>
  onView: () => void
}) {
  const extracted = doc.extracted
  const mentioned = extracted?.conditions_mentioned ?? []
  const suggestedLinks = extracted?.suggested_links ?? []
  const ratingItems = (extracted?.rating_summary?.length ? extracted.rating_summary : mentioned).filter(
    (m) => m.rating_percent != null
  )
  const [linked, setLinked] = useState<Set<string>>(new Set())
  const [linking, setLinking] = useState<Set<string>>(new Set())
  const [confirmed, setConfirmed] = useState<Set<string>>(new Set())
  const [confirming, setConfirming] = useState<Set<string>>(new Set())

  const findSuggestion = (name: string) =>
    suggestedLinks.find((l) => l.name.toLowerCase() === name.toLowerCase())

  const typeHue = doc.doc_type ? DOC_TYPE_HUES[doc.doc_type] : undefined
  // A VA rating decision / decision letter can be run through the Wave 4
  // decoder — surface a jump straight to it, prefilled to this document.
  const isDecision =
    extracted?.is_va_decision === true ||
    doc.doc_type === 'rating_decision' ||
    doc.doc_type === 'decision_letter'
  return (
    <div
      className={typeHue ? 'vo-panel vo-accent overflow-hidden' : 'vo-panel overflow-hidden'}
      style={typeHue ? (hueStyle(typeHue) as CSSProperties) : undefined}
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-txt">{doc.title || doc.filename}</h3>
            <StatusIndicator status={doc.status} />
            {doc.doc_type && <DocTypeBadge type={doc.doc_type} />}
          </div>
          <p className="mt-1 text-xs text-faint">
            {doc.filename} · {formatBytes(doc.size_bytes)} · uploaded {formatDate(doc.created_at)}
            {doc.doc_date ? ` · dated ${formatDate(doc.doc_date)}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={onView}
            className="vo-btn-secondary text-xs"
            title="View uploaded original"
          >
            <Eye size={13} /> View
          </button>
          {isDecision && doc.status === 'ready' && (
            <Link
              to={`/decode?doc=${doc.id}`}
              className="vo-btn-secondary text-xs"
              title="Decode this VA decision into plain English + next steps"
            >
              <ScanText size={13} /> Decode
            </Link>
          )}
          <select
            className="vo-input py-1.5 text-xs"
            aria-label="Document type"
            value={doc.doc_type ?? ''}
            onChange={(e) => onDocTypeChange(e.target.value as DocType)}
          >
            <option value="" disabled>
              Set type…
            </option>
            {DOC_TYPES.map((t) => (
              <option key={t} value={t}>{humanize(t)}</option>
            ))}
          </select>
          <button
            onClick={onDelete}
            className="vo-icon-btn vo-btn-ghost text-muted hover:text-danger"
            aria-label="Delete document"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      <div className="space-y-4 p-5">
        {doc.status === 'processing' || doc.status === 'uploaded' ? (
          <ProcessingBlock />
        ) : doc.status === 'failed' ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-warn/30 bg-h-amber-soft px-4 py-3.5">
            <p className="text-sm text-txt">
              {doc.error || 'Processing failed.'} Try reprocessing, or check the file isn’t corrupted/password-protected.
            </p>
            <button onClick={onReprocess} className="vo-btn-secondary shrink-0 text-xs">
              <RefreshCw size={13} /> Try again
            </button>
          </div>
        ) : doc.status === 'duplicate' ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-line bg-surface2 px-4 py-3.5">
            <p className="flex items-start gap-2 text-sm text-muted">
              <Copy size={15} className="mt-0.5 shrink-0" />
              <span>
                This is the same content as a document you already uploaded, so it wasn’t processed or analyzed again —
                nothing here is double-counted. You can delete it, or reprocess if you believe it’s actually different.
              </span>
            </p>
            <button onClick={onReprocess} className="vo-btn-secondary shrink-0 text-xs">
              <RefreshCw size={13} /> Reprocess anyway
            </button>
          </div>
        ) : (
          <>
            {doc.relevance_flagged && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-line bg-surface2 px-4 py-3.5">
                <p className="flex items-start gap-2 text-sm text-muted">
                  <FileWarning size={15} className="mt-0.5 shrink-0" />
                  <span>
                    This doesn’t look like it belongs to a VA claim
                    {doc.relevance_reason ? ` (${doc.relevance_reason})` : ''}. It’s kept and
                    still counts toward nothing on its own — if it isn’t part of your claim you
                    can delete it, or leave it if it belongs here. Nothing was removed for you.
                  </span>
                </p>
                <button onClick={onDelete} className="vo-btn-secondary shrink-0 text-xs">
                  <Trash2 size={13} /> Delete
                </button>
              </div>
            )}

            {doc.summary && <p className="text-sm text-txt">{doc.summary}</p>}

            {extracted?.ccd && <CcdDetails ccd={extracted.ccd} />}

            {mentioned.length > 0 && (
              <div>
                <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-faint">
                  <Sparkles size={12} className="text-brand" /> Found on this record
                </p>
                <p className="mb-2 text-xs text-muted">
                  Conditions stay on the card. Rating % updates only appear for decision letters (below). Flagged
                  values that need a choice live in{' '}
                  <Link to="/review-queue" className="font-semibold text-brand hover:text-brand-hover">
                    Review queue
                  </Link>
                  .
                </p>
                <div className="flex flex-wrap gap-2">
                  {mentioned.map((m, i) => {
                    const suggestion = findSuggestion(m.name)
                    const linkKey = `${doc.id}:${m.name}:${i}`
                    const isLinked = linked.has(linkKey) || doc.condition_id === suggestion?.condition_id
                    return (
                      <div
                        key={i}
                        className="flex items-center gap-2 rounded-full border border-line bg-surface2 py-1.5 pl-3.5 pr-1.5 text-sm"
                      >
                        <span className="font-medium text-txt">{m.name}</span>
                        {m.diagnostic_code && <span className="text-xs text-faint">DC {m.diagnostic_code}</span>}
                        {m.rating_percent != null && <span className="text-xs text-muted">{m.rating_percent}%</span>}
                        {m.decision && <span className="text-xs text-muted">({humanize(m.decision)})</span>}
                        {m.va_classification && (
                          <span
                            className="vo-chip-hue"
                            style={hueStyle('indigo') as CSSProperties}
                            title={`VA's official contention classification${m.va_classification_code ? ` (code ${m.va_classification_code})` : ''} — matched deterministically, no AI`}
                          >
                            {m.va_classification}
                          </span>
                        )}
                        {suggestion?.condition_id && (
                          <button
                            onClick={async () => {
                              if (isLinked || linking.has(linkKey)) return
                              setLinking((prev) => new Set(prev).add(linkKey))
                              const ok = await onLink(suggestion.condition_id as string, m.name)
                              setLinking((prev) => {
                                const next = new Set(prev)
                                next.delete(linkKey)
                                return next
                              })
                              if (ok) setLinked((prev) => new Set(prev).add(linkKey))
                            }}
                            disabled={isLinked || linking.has(linkKey)}
                            className={`vo-btn gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${
                              isLinked
                                ? 'bg-h-emerald-soft text-success'
                                : 'bg-brand text-white hover:bg-brand-hover'
                            }`}
                          >
                            {isLinked ? (
                              <CheckCircle2 size={12} />
                            ) : linking.has(linkKey) ? (
                              <Spinner size={12} />
                            ) : (
                              <Link2 size={12} />
                            )}
                            {isLinked ? 'Linked' : linking.has(linkKey) ? 'Linking…' : `Link to ${suggestion.name}`}
                          </button>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {extracted?.is_va_decision && ratingItems.length > 0 && (
              <div className="flex gap-3 rounded-control border border-warn/30 bg-h-amber-soft p-4">
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-warn/20 text-warn">
                  <Sparkles size={16} />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-txt">Rating decision detected</p>
                  <p className="mt-0.5 text-xs text-muted">Confirm each line below — nothing updates automatically.</p>
                  <div className="mt-3 space-y-2">
                    {ratingItems.map((item, i) => {
                      const suggestion = findSuggestion(item.name)
                      const key = `${doc.id}:${item.name}:${i}`
                      const isDone = confirmed.has(key)
                      return (
                        <div
                          key={i}
                          className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-line bg-surface px-3.5 py-2.5 text-sm"
                        >
                          <span className="text-txt">
                            {item.name} → <strong>{item.rating_percent}%</strong>
                          </span>
                          <button
                            onClick={async () => {
                              if (isDone || confirming.has(key)) return
                              setConfirming((prev) => new Set(prev).add(key))
                              const ok = await onConfirmRating(item, suggestion?.condition_id)
                              setConfirming((prev) => {
                                const next = new Set(prev)
                                next.delete(key)
                                return next
                              })
                              // Only mark done when it actually persisted — on
                              // failure the button stays live so it can be retried.
                              if (ok) setConfirmed((prev) => new Set(prev).add(key))
                            }}
                            disabled={isDone || confirming.has(key)}
                            className={`vo-btn text-xs ${
                              isDone
                                ? 'border border-success/40 bg-h-emerald-soft text-success'
                                : 'bg-brand text-white shadow-sm hover:bg-brand-hover'
                            }`}
                          >
                            {isDone ? <CheckCircle2 size={13} /> : confirming.has(key) ? <Spinner size={13} /> : null}
                            {isDone ? 'Updated' : confirming.has(key) ? 'Updating…' : 'Confirm & update my ratings'}
                          </button>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            )}

            {mentioned.length === 0 && !doc.summary && (
              <p className="text-sm text-muted">No details extracted yet.</p>
            )}

            {conditions.length === 0 && (
              <p className="text-xs text-faint">
                <Link to="/conditions" className="font-semibold text-brand hover:text-brand-hover">
                  Add a condition
                </Link>{' '}
                to link this document's evidence directly.
              </p>
            )}
          </>
        )}
      </div>
    </div>
  )
}

// ── CCD (VA Health Summary) detail ───────────────────────────────────────────

/** Sections the CCD panel surfaces (intake/ccd.py parse keys), in the order a
 * claim reader cares about. Vitals/labs/encounters stay count-only chips —
 * the clinically claim-relevant lists get expandable detail. */
const CCD_SECTIONS = [
  { key: 'problems', label: 'Conditions' },
  { key: 'medications', label: 'Medications' },
  { key: 'allergies', label: 'Allergies' },
  { key: 'immunizations', label: 'Immunizations' },
] as const

type CcdSectionKey = (typeof CCD_SECTIONS)[number]['key']

function ccdItemText(key: CcdSectionKey, item: Record<string, unknown>): { title: string; detail: string } {
  const s = (v: unknown) => (typeof v === 'string' && v ? v : null)
  if (key === 'problems') {
    return {
      title: s(item.name) ?? '—',
      detail: [
        s(item.status) ? humanize(s(item.status)) : null,
        s(item.onset_date) ? `onset ${formatDate(s(item.onset_date))}` : null,
        s(item.resolved_date) ? `resolved ${formatDate(s(item.resolved_date))}` : null,
      ]
        .filter(Boolean)
        .join(' · '),
    }
  }
  if (key === 'medications') {
    return {
      title: s(item.name) ?? '—',
      detail: [
        s(item.dose) ? `${s(item.dose)}${s(item.dose_unit) ? ` ${s(item.dose_unit)}` : ''}` : null,
        s(item.status) ? humanize(s(item.status)) : null,
        s(item.start_date) ? `from ${formatDate(s(item.start_date))}` : null,
      ]
        .filter(Boolean)
        .join(' · '),
    }
  }
  if (key === 'allergies') {
    return {
      title: s(item.substance) ?? '—',
      detail: [s(item.reaction), s(item.severity)].filter(Boolean).join(' · '),
    }
  }
  return {
    title: s(item.name) ?? '—',
    detail: s(item.date) ? formatDate(s(item.date)) : '',
  }
}

/** extracted.ccd — the deterministic C-CDA parse. Counts up front, each
 * claim-relevant section expandable; vitals/labs/encounters as count chips. */
function CcdDetails({ ccd }: { ccd: CcdParsed }) {
  const [open, setOpen] = useState<CcdSectionKey | null>(null)
  const extraCounts = [
    ccd.vitals.length > 0 ? `${ccd.vitals.length} vital signs` : null,
    ccd.labs.length > 0 ? `${ccd.labs.length} lab results` : null,
    ccd.encounters.length > 0 ? `${ccd.encounters.length} encounters` : null,
  ].filter(Boolean)

  return (
    <div
      className="space-y-3 rounded-control border p-4"
      style={{
        // NOTE: slash-opacity on the var-driven h-* colors (e.g. border-[color-mix(in_oklab,var(--hue-teal)_25%,transparent)])
        // silently emits nothing in this Tailwind setup — use color-mix inline.
        borderColor: 'color-mix(in srgb, var(--hue-teal) 25%, transparent)',
        background: 'var(--hue-teal-soft)',
      }}
    >
      <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-faint">
        <FileCode2 size={12} className="text-h-teal" /> VA Health Summary — parsed exactly, no AI involved
      </p>
      <div className="flex flex-wrap gap-2">
        {CCD_SECTIONS.map(({ key, label }) => {
          const count = ccd[key].length
          const isOpen = open === key
          return (
            <button
              key={key}
              onClick={() => setOpen(isOpen ? null : key)}
              disabled={count === 0}
              aria-expanded={isOpen}
              className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                isOpen
                  ? 'bg-h-teal-soft text-txt'
                  : count > 0
                    ? 'border-line bg-surface2 text-txt hover:border-line2'
                    : 'border-line bg-surface2 text-faint'
              }`}
              style={isOpen ? { borderColor: 'color-mix(in srgb, var(--hue-teal) 50%, transparent)' } : undefined}
            >
              {label}
              <span className="font-bold tabular-nums">{count}</span>
              {count > 0 && <ChevronDown size={12} className={`transition-transform ${isOpen ? 'rotate-180' : ''}`} />}
            </button>
          )
        })}
      </div>
      {open && (
        <ul className="vo-step-enter max-h-64 space-y-1.5 overflow-y-auto">
          {(ccd[open] as unknown as Record<string, unknown>[]).map((item, i) => {
            const { title, detail } = ccdItemText(open, item)
            return (
              <li key={i} className="rounded-control border border-line bg-surface px-3.5 py-2 text-sm">
                <span className="font-medium text-txt">{title}</span>
                {detail && <span className="text-xs text-muted"> — {detail}</span>}
              </li>
            )
          })}
        </ul>
      )}
      {extraCounts.length > 0 && <p className="text-xs text-faint">Also parsed: {extraCounts.join(', ')}.</p>}
    </div>
  )
}
