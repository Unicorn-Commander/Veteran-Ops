import { CheckCircle2, Download, Loader2, PenLine } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Panel } from './ui'
import { useAsync } from '../hooks/useAsync'
import { ApiError, formsApi } from '../lib/api'
import { hueInk, hueLabel, type Hue } from '../lib/hues'

/**
 * Reusable "Download filled PDF (review & sign)" panel — the generalization of
 * Form526's PdfDownloadPanel across the VA form set (routers/forms.py).
 *
 * It fetches GET /api/forms/{formId} so the AUTO_FILLED / YOU_COMPLETE lists come
 * straight from the backend registry (single source of truth — honest labeling of
 * what's filled vs. what the veteran completes and signs), then downloads the
 * pre-filled OFFICIAL PDF as a DRAFT. Veteran-Ops never files anything.
 */
export function FilledFormPanel({
  formId,
  hue,
  title = 'Download the pre-filled official form',
}: {
  formId: string
  hue: Hue
  title?: string
}) {
  const ink = hueInk(hue)
  const label = hueLabel(hue)
  const { data: preview, error } = useAsync(() => formsApi.preview(formId), [formId])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const download = async () => {
    if (!preview) return
    setBusy(true)
    setErr(null)
    try {
      await formsApi.downloadPdf(formId, preview.draft_filename)
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not generate the PDF. Please try again.')
    } finally {
      setBusy(false)
    }
  }

  const subtitle = preview
    ? `VA Form ${preview.form_id.toUpperCase()} · ${preview.edition} edition (OMB ${preview.omb})`
    : `VA Form ${formId.toUpperCase()}`

  return (
    <Panel hue={hue} title={title} subtitle={subtitle}>
      <div className="p-5">
        <p className="text-sm leading-relaxed text-muted">
          This is the <strong className="text-txt">actual government PDF</strong>, pre-filled with the data we hold with
          confidence. It downloads as a <strong className="text-txt">draft</strong> — review every field, complete the
          blanks, and sign it before you file. Veteran-Ops never files it for you.
        </p>

        {error && (
          <p className="mt-3 text-sm font-medium" style={{ color: hueInk('rose') }}>
            Could not load the form details. Please try again.
          </p>
        )}

        {preview && (
          <>
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <div className="rounded-control border border-line bg-surface2 p-4">
                <p
                  className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide"
                  style={{ color: hueInk('emerald') }}
                >
                  <CheckCircle2 size={14} /> We fill this in
                </p>
                <ul className="space-y-1.5 text-sm text-txt">
                  {preview.auto_filled.map((t, i) => (
                    <li key={i} className="flex gap-2">
                      <CheckCircle2 size={14} className="mt-0.5 shrink-0" style={{ color: hueInk('emerald') }} />
                      <span>{t}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-control border border-line bg-surface2 p-4">
                <p
                  className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide"
                  style={{ color: ink }}
                >
                  <PenLine size={14} /> You complete &amp; sign
                </p>
                <ul className="space-y-1.5 text-sm text-txt">
                  {preview.you_complete.map((t: string, i: number) => (
                    <li key={i} className="flex gap-2">
                      <PenLine size={14} className="mt-0.5 shrink-0" style={{ color: ink }} />
                      <span>{t}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>

            {/* Edit-before-accept: the auto-filled values come from the veteran's
                profile — let them correct anything BEFORE the wholesale fill,
                rather than only after opening the PDF. */}
            <p className="mt-3 flex items-start gap-1.5 text-xs leading-relaxed text-muted">
              <PenLine size={13} className="mt-0.5 shrink-0" style={{ color: ink }} />
              <span>
                We fill these from your profile.{' '}
                <Link to="/profile" className="font-semibold text-brand hover:text-brand-hover">
                  Review and edit your details
                </Link>{' '}
                first if anything needs changing — then download.
              </span>
            </p>

            <div className="mt-4 flex flex-col items-start gap-2">
              <button onClick={download} disabled={busy} className="vo-btn-primary">
                {busy ? <Loader2 size={16} className="animate-spin" /> : <Download size={16} />}
                {busy ? 'Preparing your PDF…' : `Download pre-filled ${preview.form_id.toUpperCase()} (draft)`}
              </button>
              {err && (
                <p className="text-xs font-medium" style={{ color: hueInk('rose') }}>
                  {err}
                </p>
              )}
              <p className="text-xs text-faint" style={{ color: label }}>
                We never store or fill your SSN, date of birth, or address — those stay with you.
              </p>
            </div>
          </>
        )}
      </div>
    </Panel>
  )
}
