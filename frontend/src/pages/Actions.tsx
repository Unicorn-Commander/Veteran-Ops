import { ArrowRight, FileCheck2, FileText, Link2, RefreshCw, Search, Sparkles, Stethoscope, Users } from 'lucide-react'
import { useId, useRef, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { proactiveEvidenceApi, strategyApi, profileApi } from '../lib/api'
import type { EvidenceOpportunity, EvidenceReviewItem } from '../lib/api'
import { hueInk, hueStyle, type Hue } from '../lib/hues'

const TYPE_META: Record<string, { label: string; icon: typeof FileText; hue: Hue }> = {
  nexus: { label: 'Nexus letter', icon: Stethoscope, hue: 'violet' },
  buddy_statement: { label: 'Buddy / lay statement', icon: Users, hue: 'sky' },
  dbq: { label: 'DBQ', icon: FileCheck2, hue: 'emerald' },
}

/** A single re-run action button that shows progress and toasts its result. */
function RunButton({
  label,
  hint,
  icon: Icon,
  run,
}: {
  label: string
  hint: string
  icon: typeof RefreshCw
  run: () => Promise<string>
}) {
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const go = async () => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    try {
      toast(await run(), 'success')
    } catch (e) {
      toast(`The analysis couldn't finish. ${errorMessage(e)} Check your connection, then try again.`, 'error')
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }
  return (
    <button
      type="button"
      onClick={go}
      disabled={busy}
      aria-busy={busy}
      className="flex w-full items-start gap-3 rounded-control border border-line bg-surface2 p-3.5 text-left transition-colors hover:border-brand/40 disabled:opacity-60"
    >
      <span className="mt-0.5 shrink-0 text-brand" aria-hidden="true">
        {busy ? <Spinner size={18} /> : <Icon size={18} />}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-txt">{busy ? `${label} in progress…` : label}</span>
        <span className="block text-xs leading-relaxed text-muted">{hint}</span>
      </span>
    </button>
  )
}

function HaveCard({ item }: { item: EvidenceReviewItem }) {
  const meta = TYPE_META[item.evidence_type] ?? TYPE_META.dbq
  const Icon = meta.icon
  return (
    <div className="flex items-start gap-3 rounded-control border border-line bg-surface2 p-3.5" style={hueStyle(meta.hue) as CSSProperties}>
      <Icon size={16} className="mt-0.5 shrink-0" style={{ color: hueInk(meta.hue) }} />
      <div className="min-w-0">
        <p className="text-sm font-medium text-txt">{item.document_title || 'Evidence document'}</p>
        <p className="mt-0.5 text-xs text-muted">
          {meta.label}
          {item.condition ? <> · linked to <span className="font-medium text-txt">{item.condition}</span></> : <> · not yet matched to a condition</>}
        </p>
      </div>
    </div>
  )
}

function escapeDraftText(value: string): string {
  return value.replace(
    /[&<>]/g,
    (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[character] as string,
  )
}

function printDraft(title: string, markdown: string): boolean {
  let w: Window | null = null
  try {
    w = window.open('', '_blank', 'width=800,height=1000')
  } catch {
    return false
  }
  if (!w) return false
  try {
    w.opener = null
    // Minimal, clean print styling — markdown headings/bold rendered simply.
    const html = escapeDraftText(markdown)
      .replace(/^# (.*)$/gm, '<h1>$1</h1>')
      .replace(/^## (.*)$/gm, '<h2>$1</h2>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.+?)\*/g, '<em>$1</em>')
      .replace(/\n{2,}/g, '</p><p>')
      .replace(/\n/g, '<br>')
    w.document.write(
      `<!doctype html><title>${escapeDraftText(title)}</title><style>body{font:14px/1.6 Georgia,serif;max-width:7in;margin:1in auto;padding:0 1rem;color:#111}h1{font-size:20px}h2{font-size:16px;margin-top:1.4em}p{margin:.8em 0}@media print{body{margin:.6in auto}}</style><p>${html}</p>`,
    )
    w.document.close()
    w.focus()
    window.setTimeout(() => {
      try {
        if (!w?.closed) w.print()
      } catch {
        // The veteran can still use the browser's print command in the opened draft.
      }
    }, 300)
    return true
  } catch {
    w.close()
    return false
  }
}

function OpportunityCard({ opp }: { opp: EvidenceOpportunity }) {
  const { toast } = useToast()
  const draftId = useId()
  const isNexus = opp.opportunity === 'nexus'
  const meta = isNexus ? TYPE_META.nexus : TYPE_META.buddy_statement
  const Icon = meta.icon
  const [showDraft, setShowDraft] = useState(false)
  return (
    <div className="rounded-control border border-line bg-surface2 p-4" style={hueStyle(meta.hue) as CSSProperties}>
      <div className="flex items-start gap-2.5">
        <Icon size={16} className="mt-0.5 shrink-0" style={{ color: hueInk(meta.hue) }} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-txt">
            {isNexus ? 'Possible nexus evidence gap' : 'Possible firsthand-evidence gap'}: {opp.condition}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {isNexus
              ? 'Rating Raider found references to a diagnosis and an in-service event, but did not find a medical nexus opinion. A qualified provider must decide whether an opinion is appropriate.'
              : 'Rating Raider found an in-service event and a possible gap in firsthand evidence about later symptoms. A witness should include only what they personally observed.'}
          </p>
          {opp.needs_veteran && (
            <p className="mt-1.5 text-xs leading-relaxed text-txt">
              <span className="font-medium">What you do:</span> {opp.needs_veteran}
            </p>
          )}
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            {opp.draft ? (
              <>
                <span className="inline-flex items-center gap-1 text-xs font-semibold" style={{ color: hueInk('emerald') }}>
                  <FileText size={13} /> Draft ready
                </span>
                <button
                  type="button"
                  onClick={() => setShowDraft((v) => !v)}
                  aria-expanded={showDraft}
                  aria-controls={draftId}
                  className="inline-flex min-h-10 items-center rounded-control px-2.5 text-sm font-semibold text-brand hover:bg-surface hover:text-brand-hover"
                >
                  {showDraft ? 'Hide draft' : 'View draft'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (!printDraft(opp.draft!.title, opp.draft!.markdown)) {
                      toast('Your browser blocked the print window. Allow pop-ups for this site, then try again.', 'error')
                    }
                  }}
                  className="inline-flex min-h-10 items-center rounded-control px-2.5 text-sm font-medium text-muted hover:bg-surface hover:text-txt"
                >
                  Print / save PDF
                </button>
              </>
            ) : (
              <Link to={opp.draft_route} className="inline-flex min-h-10 items-center gap-1 rounded-control px-2.5 text-sm font-semibold text-brand hover:bg-surface hover:text-brand-hover">
                Prepare the draft <ArrowRight size={14} />
              </Link>
            )}
            {isNexus && (
              <Link to="/raider" className="inline-flex min-h-10 items-center gap-1 rounded-control px-2.5 text-xs font-medium text-muted hover:bg-surface hover:text-txt">
                <Search size={12} /> Ask Rating Raider to pull supporting research
              </Link>
            )}
          </div>
          {showDraft && opp.draft && (
            <pre
              id={draftId}
              className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-control border border-line bg-surface p-3 text-xs leading-relaxed text-txt"
              tabIndex={0}
              role="region"
              aria-label={`${opp.draft.title} draft`}
            >
              {opp.draft.markdown}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}

/** "Run it yourself" — proactive evidence (what we found + what's worth adding) plus
 * the explicit re-run controls, so a veteran can put Rating Raider to work on demand. */
export function Actions() {
  const { data, loading, error, reload } = useAsync(() => proactiveEvidenceApi.review(), [])

  return (
    <div data-section="claim" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Put Rating Raider to work</p>
        <h1 className="vo-page-title">Evidence &amp; analysis</h1>
        <p className="vo-page-sub max-w-[70ch] leading-relaxed">
          Rating Raider reviews the records you added, groups possible evidence by condition, and flags gaps worth
          checking. Re-run an analysis after you add something new, then review every suggestion before you act.
        </p>
      </div>

      {/* Re-run controls — the explicit "do the work" actions. */}
      <Panel hue="violet" title="Run the analysis" subtitle="Nothing runs until you choose a button">
        <div className="grid gap-2.5 p-4 sm:grid-cols-2">
          <RunButton
            label="Match found evidence to conditions"
            hint="Organize likely nexus letters, buddy statements, and DBQs under the matching condition."
            icon={Link2}
            run={async () => {
              const r = await proactiveEvidenceApi.autoLink()
              reload()
              return r.linked.length
                ? `Matched ${r.linked.length} document${r.linked.length === 1 ? '' : 's'} to your conditions.`
                : 'Everything we could confidently match is already organized.'
            }}
          />
          <RunButton
            label="Refresh Claim Plan"
            hint="Specialists + plain-language plan only (minutes). Not the full Analysis Center pass."
            icon={RefreshCw}
            run={async () => {
              await strategyApi.refresh()
              return 'Claim Plan refreshed (specialists + briefing). For whole-file review, use Run analysis.'
            }}
          />
          <RunButton
            label="Run rating deep dive only"
            hint="Compare conditions to 38 CFR rating paths. Part of full review, not the whole pipeline."
            icon={Sparkles}
            run={async () => {
              const r = await strategyApi.runDeepDive()
              return `Deep dive complete — ${r.candidates_considered ?? 0} rating paths reviewed.`
            }}
          />
          <RunButton
            label="Re-scan my records"
            hint="Read your uploaded documents again for your details and evidence."
            icon={Search}
            run={async () => {
              const r = await profileApi.reextractIdentity()
              return r.message
            }}
          />
        </div>
      </Panel>

      {loading && !data ? (
        <div className="flex min-h-[24rem] items-center justify-center">
          <LoadingBlock label="Reading your evidence…" />
        </div>
      ) : error && !data ? (
        <ErrorBlock message={`We couldn't read your evidence review. ${error} Check your connection, then try again.`} onRetry={reload} />
      ) : !data ? (
        <EmptyState
          hue="violet"
          icon={<FileText size={20} />}
          title="Your evidence review is not ready yet"
          description="Add a record or run an analysis, then return here to review what Rating Raider organized."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Link to="/documents" className="vo-btn-primary text-sm">
                Upload records
              </Link>
              <Link to="/analysis" className="vo-btn-secondary text-sm">
                Run analysis
              </Link>
            </div>
          }
        />
      ) : (
        <>
          {error && (
            <ErrorBlock
              message={`We couldn't refresh the evidence review. The findings below are the last version we loaded. ${error}`}
              onRetry={reload}
            />
          )}
          {loading && (
            <p className="px-1 text-sm text-muted" role="status" aria-live="polite">
              Refreshing your evidence review…
            </p>
          )}
          <Panel hue="emerald" title="Already in your file" subtitle="Evidence we found and matched to your conditions">
            <div className="space-y-2.5 p-4">
              {data.already_in_your_file.length === 0 ? (
                <EmptyState
                  hue="emerald"
                  icon={<FileText size={20} />}
                  title="No evidence documents detected yet"
                  description="Upload VA letters, medical records, DBQs, or statements, then Rating Raider can look for likely matches."
                  action={
                    <Link to="/documents" className="vo-btn-primary text-sm">
                      Upload records
                    </Link>
                  }
                />
              ) : (
                data.already_in_your_file.map((item, i) => <HaveCard key={i} item={item} />)
              )}
            </div>
          </Panel>

          <Panel hue="amber" title="Worth reviewing" subtitle="Possible evidence gaps to check before you decide what to add">
            <div className="space-y-2.5 p-4">
              {data.worth_adding.length === 0 ? (
                <EmptyState hue="amber" icon={<Sparkles size={20} />} title="Nothing obvious to add right now"
                  description="As you add records, Rating Raider will flag possible gaps for you to review." />
              ) : (
                data.worth_adding.map((opp, i) => <OpportunityCard key={i} opp={opp} />)
              )}
            </div>
          </Panel>

          <p className="px-1 text-xs leading-relaxed text-faint">{data.disclaimer}</p>
        </>
      )}
    </div>
  )
}
