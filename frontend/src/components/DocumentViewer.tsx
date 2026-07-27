import { Download, FileText, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ErrorBlock, LoadingBlock, Spinner } from './ui'
import { errorMessage } from '../hooks/useAsync'
import { documentsApi } from '../lib/api'
import type { DocumentItem } from '../types'

type ViewerDoc = Pick<DocumentItem, 'id' | 'filename' | 'title' | 'content_type'>
type ViewerFocus = {
  char_start: number
  char_end: number
  quote: string
  page?: number | null
  note?: string | null
}

function previewKind(contentType: string | null, filename: string): 'pdf' | 'image' | 'text' | 'download' {
  const ct = (contentType || '').toLowerCase()
  const name = filename.toLowerCase()
  if (ct.includes('pdf') || name.endsWith('.pdf')) return 'pdf'
  // HEIC/HEIF and TIFF often fail in-browser; still try image path then fall back to download UI.
  if (ct.startsWith('image/') || /\.(png|jpe?g|gif|webp|bmp|heic|heif|tiff?)$/.test(name)) return 'image'
  if (ct.startsWith('text/') || /\.(txt|csv|xml)$/.test(name)) return 'text'
  return 'download'
}

/** Ensure the blob has a browser-renderable MIME (storage often returns octet-stream). */
function ensureBlobType(
  blob: Blob,
  kind: 'pdf' | 'image' | 'text' | 'download',
  contentType: string | null | undefined,
  filename: string,
): Blob {
  if (blob.type && blob.type !== 'application/octet-stream') return blob
  const ct = (contentType || '').toLowerCase()
  const name = filename.toLowerCase()
  let mime = ct && ct !== 'application/octet-stream' ? ct : ''
  if (!mime) {
    if (kind === 'pdf' || name.endsWith('.pdf')) mime = 'application/pdf'
    else if (name.endsWith('.png')) mime = 'image/png'
    else if (/\.jpe?g$/.test(name)) mime = 'image/jpeg'
    else if (name.endsWith('.gif')) mime = 'image/gif'
    else if (name.endsWith('.webp')) mime = 'image/webp'
    else if (name.endsWith('.bmp')) mime = 'image/bmp'
    else if (kind === 'text') mime = 'text/plain'
  }
  return mime ? new Blob([blob], { type: mime }) : blob
}

function windowAround(text: string, start: number, end: number, radius = 240) {
  const lo = Math.max(0, start - radius)
  const hi = Math.min(text.length, end + radius)
  return {
    prefix: text.slice(lo, start),
    focus: text.slice(start, end),
    suffix: text.slice(end, hi),
  }
}

export function DocumentViewer({
  doc,
  focus,
  onClose,
}: {
  doc: ViewerDoc | null
  focus?: ViewerFocus | null
  onClose: () => void
}) {
  const [blob, setBlob] = useState<Blob | null>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [text, setText] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const passageRef = useRef<HTMLDivElement | null>(null)

  const kind = useMemo(() => (doc ? previewKind(doc.content_type, doc.filename) : 'download'), [doc])

  useEffect(() => {
    if (!doc) return
    let cancelled = false
    let objectUrl: string | null = null
    setBlob(null)
    setUrl(null)
    setText(null)
    setError(null)
    setLoading(true)

    void Promise.all([documentsApi.file(doc.id), documentsApi.get(doc.id)])
      .then(async ([b, detailDoc]) => {
        if (cancelled) return
        // Storage/proxy sometimes serves application/octet-stream — stamp a real
        // MIME so iframe/img previews work.
        const typed = ensureBlobType(b, kind, doc.content_type, doc.filename)
        setBlob(typed)
        objectUrl = URL.createObjectURL(typed)
        setUrl(objectUrl)
        setText(detailDoc.text_content ?? (kind === 'text' ? await typed.text() : null))
      })
      .catch((err) => {
        if (!cancelled) setError(errorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [doc, kind])

  useEffect(() => {
    if (focus && !loading && !error && passageRef.current) {
      passageRef.current.scrollIntoView({ block: 'start', behavior: 'smooth' })
    }
  }, [focus, loading, error])

  if (!doc) return null

  const download = async () => {
    setDownloading(true)
    try {
      await documentsApi.downloadFile(doc.id, doc.filename, blob ?? undefined)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-3">
      <div className="flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-pane border border-line bg-surface shadow-xl">
        <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-txt">{doc.title || doc.filename}</p>
            <p className="truncate text-xs text-faint">{doc.filename}</p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <button type="button" onClick={() => void download()} disabled={downloading || loading} className="vo-btn-secondary text-xs">
              {downloading ? <Spinner size={13} /> : <Download size={13} />}
              Download original
            </button>
            <button type="button" onClick={onClose} className="vo-icon-btn vo-btn-ghost" aria-label="Close document viewer">
              <X size={16} />
            </button>
          </div>
        </div>
        <div className="min-h-[55vh] flex-1 overflow-auto bg-surface2 p-3">
          {loading ? (
            <LoadingBlock label="Loading document…" />
          ) : error ? (
            <ErrorBlock message={error} />
          ) : (
            <div className="space-y-3">
              {focus && text && (
                <div ref={passageRef} className="rounded-control border border-line bg-surface px-4 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-faint">Highlighted passage</p>
                  {typeof focus.page === 'number' && <p className="mt-1 text-xs text-muted">Page {focus.page}</p>}
                  <pre className="mt-2 whitespace-pre-wrap rounded-control bg-surface2 p-3 text-sm text-txt">
                    {(() => {
                      const start = Math.max(0, Math.min(focus.char_start, text.length))
                      const end = Math.max(start, Math.min(focus.char_end, text.length))
                      const slice = windowAround(text, start, end)
                      return (
                        <>
                          {slice.prefix}
                          <mark className="rounded bg-[color-mix(in_oklab,var(--hue-teal)_22%,white)] px-0.5 text-txt">
                            {slice.focus || focus.quote}
                          </mark>
                          {slice.suffix}
                        </>
                      )
                    })()}
                  </pre>
                  {focus.note && <p className="mt-2 text-xs text-muted">Note: {focus.note}</p>}
                </div>
              )}
              {kind === 'pdf' && url ? (
                <iframe
                  src={`${url}#toolbar=1&navpanes=0`}
                  title={doc.filename}
                  className="h-[72vh] w-full rounded-control border border-line bg-white"
                />
              ) : kind === 'image' && url ? (
                <div className="flex min-h-[60vh] items-start justify-center">
                  <img
                    src={url}
                    alt={doc.filename}
                    className="max-h-[72vh] max-w-full rounded-control object-contain"
                    onError={() =>
                      setError(
                        'This image format can’t be previewed in the browser (common with HEIC/TIFF). Use Download original.',
                      )
                    }
                  />
                </div>
              ) : kind === 'text' ? (
                <pre className="min-h-[60vh] whitespace-pre-wrap rounded-control border border-line bg-surface p-4 text-sm text-txt">
                  {text}
                </pre>
              ) : (
                <div className="flex min-h-[55vh] flex-col items-center justify-center gap-3 text-center">
                  <FileText size={28} className="text-muted" />
                  <p className="max-w-md text-sm text-muted">
                    This file type cannot be previewed in the browser. Download the original to view it locally.
                  </p>
                  {text && (
                    <details className="w-full max-w-2xl text-left">
                      <summary className="cursor-pointer text-sm font-medium text-brand">Show extracted text</summary>
                      <pre className="mt-2 max-h-[40vh] overflow-auto whitespace-pre-wrap rounded-control border border-line bg-surface p-3 text-xs text-txt">
                        {text}
                      </pre>
                    </details>
                  )}
                  <button type="button" onClick={() => void download()} disabled={downloading} className="vo-btn-primary">
                    {downloading ? <Spinner size={14} /> : <Download size={14} />}
                    Download original
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
