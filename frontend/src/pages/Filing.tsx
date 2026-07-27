import {
  ArrowRight,
  Check,
  ExternalLink,
  FileText,
  HeartHandshake,
  ListChecks,
  Quote,
} from 'lucide-react'
import { useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { FileReadyHandoff } from '../components/FileReadyHandoff'
import { EmptyState, ErrorBlock, LoadingBlock } from '../components/ui'
import { FilledFormPanel } from '../components/FilledFormPanel'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { checklistApi, filingApi } from '../lib/api'
import { asArray } from '../lib/format'
import { hueInk, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { FilingLane } from '../types'

/** Rotating accent so a long stack of filing-lane cards doesn't read as one
 * monochrome wall — each card in the list gets the next hue in the cycle. */
const CARD_HUE_CYCLE: Hue[] = ['indigo', 'sky', 'cyan', 'violet']

/** Lane titles occasionally carry a VA form number, e.g. "VA Form 20-0995:
 * Supplemental Claim" — pull it into a badge and keep the rest as headline.
 * Falls back to the plain title if nothing matches. */
function splitFormNumber(title: string): { code: string | null; headline: string } {
  const m = title.match(/^\s*((?:DD|VA)[\s-]?(?:Form\s*)?\d[\w-]*)\s*[:\-–—]\s*(.+)$/i)
  if (!m) return { code: null, headline: title }
  return { code: m[1].toUpperCase().replace(/\s+/g, ' '), headline: m[2].trim() }
}

/** The VA forms Rating Raider can pre-fill — the filler registry ids in
 * backend/app/pdf/registry.py. A filing lane earns an inline "download your
 * pre-filled draft" panel only when it maps to one of these. */
const FILLABLE_FORM_IDS = new Set(['21-526ez', '20-0995', '21-8940', '21-686c', '21-4138', '21-4142'])

/** Resolve the fillable form a lane is about, if any. Lane titles rarely print
 * the form number — it lives in the lane's `source` (e.g. "VA Form 21-526EZ;
 * M21-1" or "Forms 20-0995, 20-0996, 10182") — so we scan title + source for VA
 * form tokens (NN-NNNN[suffix]), lower-case them, and keep only ids the filler
 * registry actually serves. That deliberately ignores the forms we can't fill
 * (20-0996, 10182, 21-0966 ITF, 20-10206 FOIA, SF-180), so those lanes stay
 * text-only. A small keyword fallback covers the two form-bearing lanes in case
 * a KB edit ever drops the bare number. Returns null for text-only lanes. */
function laneFormId(lane: FilingLane): string | null {
  const hay = `${lane.title} ${lane.source ?? ''}`
  for (const tok of hay.match(/\b\d{2}-\d{3,5}[a-z]{0,2}\b/gi) ?? []) {
    const id = tok.toLowerCase()
    if (FILLABLE_FORM_IDS.has(id)) return id
  }
  const t = lane.title.toLowerCase()
  if (t.includes('initial claim')) return '21-526ez'
  if (t.includes('decision review')) return '20-0995'
  return null
}

const FILLABLE = new Set(['21-526ez', '20-0995', '21-8940', '21-686c', '21-4138', '21-4142'])

export function Filing() {
  const { toast } = useToast()
  const [params] = useSearchParams()
  // Rating Raider (or a link) can open a specific pre-filled form via ?form=<id>.
  const requestedForm = (params.get('form') || '').toLowerCase()
  const openForm = FILLABLE.has(requestedForm) ? requestedForm : null
  const { data, loading, error, reload } = useAsync(() => filingApi.lanes())
  const lanes = data ? asArray<FilingLane>(data, 'lanes') : []
  const [addedKeys, setAddedKeys] = useState<Set<string>>(new Set())

  const addToChecklist = async (lane: FilingLane, key: string) => {
    try {
      await checklistApi.create({ text: `Review: ${lane.title}`, category: 'filing' })
      setAddedKeys((prev) => new Set(prev).add(key))
      toast('Added to your checklist.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div data-section="guide" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Filing guide</p>
        <h1 className="vo-page-title">Filing lanes guide</h1>
        <p className="vo-page-sub max-w-[70ch] leading-relaxed">
          How claims and appeals actually move through VA — FDC, supplemental claims, Higher-Level Review, the Board,
          effective dates, and CUE. This is background reading, not instructions to file for you.
        </p>
      </div>

      {openForm && (
        // Rating Raider (or a deep link) opened a specific pre-filled form — surface
        // it at the top, ready to review/print, before the reading material below.
        <div className="rounded-panel border border-brand/30 bg-brand-soft/30 p-1">
          <FilledFormPanel
            formId={openForm}
            hue="indigo"
            title={`Your pre-filled ${openForm.toUpperCase()} (draft you review & sign)`}
          />
        </div>
      )}

      <FileReadyHandoff />

      <div
        className="vo-card vo-accent flex items-start gap-3.5 p-5"
        style={{ '--hue': 'var(--hue-orange)', '--hue-soft': 'var(--hue-orange-soft)' } as React.CSSProperties}
      >
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: 'var(--hue-orange-soft)', color: 'var(--hue-orange)' }}
        >
          <HeartHandshake size={20} />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-txt">Get free, accredited help</h2>
          <p className="mt-1 max-w-[70ch] text-sm leading-relaxed text-muted">
            A VA-accredited Veterans Service Officer (VSO) can file and represent you at no cost — VFW, DAV, The
            American Legion, or your state/county veterans office. Rating Raider organizes your information; a VSO can
            act on your behalf.
          </p>
          <a
            href="https://www.va.gov/get-help-from-accredited-representative/"
            target="_blank"
            rel="noreferrer"
            className="mt-2.5 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
          >
            Find a VSO <ExternalLink size={13} />
          </a>
        </div>
      </div>

      {loading ? (
        <LoadingBlock label="Loading filing guide…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={reload} />
      ) : lanes.length === 0 ? (
        <EmptyState
          hue="indigo"
          icon={<FileText size={20} />}
          title="Filing guide not available yet"
          description="You can still prepare your packet and hand it to VA.gov or a free VSO — we never file for you."
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              <Link to="/application" className="vo-btn-primary text-sm">
                Open 21-526EZ draft <ArrowRight size={14} />
              </Link>
              <Link to="/conditions" className="vo-btn-secondary text-sm">
                Add conditions
              </Link>
            </div>
          }
        />
      ) : (
        <>
          <SectionNav
            items={lanes.map((lane, i) => {
              const key = lane.key ?? String(i)
              const { headline } = splitFormNumber(lane.title)
              return { id: `filing-${key}`, label: headline, hue: CARD_HUE_CYCLE[i % CARD_HUE_CYCLE.length] }
            })}
          />
          <div className="space-y-4">
            {lanes.map((lane, i) => {
              const key = lane.key ?? String(i)
              const { code, headline } = splitFormNumber(lane.title)
              const added = addedKeys.has(key)
              const hue = CARD_HUE_CYCLE[i % CARD_HUE_CYCLE.length]
              const formId = laneFormId(lane)
              return (
                <article
                  key={key}
                  id={`filing-${key}`}
                  className="vo-panel vo-accent scroll-mt-24 overflow-hidden"
                  style={hueStyle(hue) as CSSProperties}
                >
                  <header className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
                    <div className="flex min-w-0 items-center gap-2.5">
                      {code && (
                        <span
                          className="shrink-0 rounded-md border px-2 py-1 font-mono text-xs font-bold tracking-wide"
                          style={{ borderColor: `color-mix(in srgb, ${hueVar(hue)} 40%, transparent)`, background: hueSoftVar(hue), color: hueInk(hue) }}
                        >
                          {code}
                        </span>
                      )}
                      <h2 className="vo-heading truncate">{headline}</h2>
                    </div>
                    <button
                      onClick={() => void addToChecklist(lane, key)}
                      disabled={added}
                      className={`text-xs transition-all ${
                        added
                          ? 'vo-btn border border-success/40 bg-h-emerald-soft text-success'
                          : 'vo-btn-secondary'
                      }`}
                    >
                      {added ? <Check size={13} /> : <ListChecks size={13} />}
                      {added ? 'Added to checklist' : 'Add to checklist'}
                    </button>
                  </header>
                  <div className="vo-prose max-w-[70ch] p-5" dangerouslySetInnerHTML={{ __html: renderContent(lane.content) }} />
                  {formId && (
                    // Surface the pre-filled OFFICIAL PDF right where the veteran is
                    // reading about this lane — same reusable panel the Appeals/Statement/
                    // TDIU pages use (fetches the AUTO-FILL / YOU-COMPLETE preview and
                    // downloads the draft). Inset so it reads as this card's action zone.
                    // Legal-lane voice intact: a draft you review & sign; we never file it.
                    <div className="px-5 pb-5">
                      <FilledFormPanel
                        formId={formId}
                        hue={hue}
                        title={`Download your pre-filled ${formId.toUpperCase()} (draft you review & sign)`}
                      />
                    </div>
                  )}
                  {lane.source && (
                    <footer className="flex items-center gap-1.5 border-t border-line px-5 py-3">
                      <Quote size={11} className="shrink-0 text-faint" />
                      <span className="vo-chip border-none bg-transparent px-0 py-0 text-faint">{lane.source}</span>
                    </footer>
                  )}
                </article>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}

/** Slim anchor-nav — one chip per lane card below, hued to match (targets carry
 * scroll-mt-24 to clear the shared Shell topbar). NOT sticky: a sticky pill row
 * scrolls with the viewport and covers the content below it (the same "tags in
 * the way" problem fixed on the Battle Plan). It scrolls away with the page. */
function SectionNav({ items }: { items: { id: string; label: string; hue: Hue }[] }) {
  return (
    <nav
      aria-label="Jump to section"
      className="vo-no-print -mx-1 flex flex-wrap gap-1.5 rounded-full border border-line bg-surface/90 px-2 py-1.5"
    >
      {items.map((it) => (
        <a key={it.id} href={`#${it.id}`} className="vo-chip-hue no-underline" style={hueStyle(it.hue) as CSSProperties}>
          {it.label}
        </a>
      ))}
    </nav>
  )
}

/** Render markdown-ish KB content (plain text with blank-line paragraphs) as
 * safe HTML — no markdown lib dependency, just paragraph + line-break splits. */
function renderContent(content: string): string {
  const escaped = content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return escaped
    .split(/\n{2,}/)
    .map((p) => `<p>${p.replace(/\n/g, '<br/>')}</p>`)
    .join('')
}
