import {
  AlertCircle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  ExternalLink,
  History,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import { useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { ProSeDisclaimer } from '../components/Disclaimer'
import { EmptyState, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { analysisApi } from '../lib/api'
import { formatDate } from '../lib/format'
import { hueInk, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { WhatsChangedItem } from '../types'

// /whats-changed — "What's changed since you were rated." Compares the veteran's rating
// date against dated VA regulatory changes and surfaces the ones that touch their
// conditions or exposures. The facts (what changed, when, the source) are curated + cited
// — never AI. Only the optional per-item "what this means for you" read is model-generated,
// on demand. Educational self-help; a VSO files with you.

const HUE: Hue = 'teal'

const SIGNAL: Record<WhatsChangedItem['action_signal'], { label: string; hue: Hue }> = {
  review: { label: 'Worth reviewing', hue: 'emerald' },
  check_eligibility: { label: 'Check if it applies to you', hue: 'sky' },
  watch: { label: 'Proposed — watch, not final', hue: 'amber' },
}

export function WhatsChanged() {
  const { data, loading, error, reload } = useAsync(() => analysisApi.whatsChanged())

  return (
    <div
      data-section="insight"
      className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 pb-20 sm:p-6"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: hueInk(HUE) }}>
          Insights · What's new for you
        </p>
        <h1 className="vo-page-title">What's changed since you were rated</h1>
        <p className="vo-page-sub">
          VA rules, presumptives, and criteria change over time. Rating Raider checks what took effect{' '}
          <em>after</em> your rating and could matter for your conditions — so you're never relying on a rule that
          shifted under you. It's educational self-help; nothing here predicts a VA decision.
        </p>
      </div>

      <ProSeDisclaimer />

      {loading && !data ? (
        <Panel hue={HUE}>
          <div className="p-5">
            <LoadingBlock label="Checking what's changed since your rating…" />
          </div>
        </Panel>
      ) : error ? (
        <Panel hue="rose">
          <div className="p-5">
            <ErrorBlock message={error} onRetry={reload} />
          </div>
        </Panel>
      ) : (
        <>
          <RatingDateStrip
            ratingDate={data?.rating_date ?? null}
            source={data?.rating_date_source ?? null}
            needs={data?.needs_rating_date ?? false}
          />

          {(data?.items.length ?? 0) === 0 ? (
            <Panel hue={HUE}>
              <div className="p-5">
                <EmptyState
                  hue={HUE}
                  icon={<CheckCircle2 size={22} />}
                  title="Nothing new to flag right now"
                  description={
                    data?.needs_rating_date
                      ? "We couldn't find a rating decision on file to anchor the comparison. Upload your rating decision (or add your conditions and service details), and we'll check what's changed since."
                      : "Based on your conditions and service on file, no rule change or new presumptive has taken effect since your rating that we'd flag. As you add conditions or new rules land, this fills in."
                  }
                  action={
                    <Link to="/documents" className="vo-btn-primary text-sm">
                      Add your records
                    </Link>
                  }
                />
              </div>
            </Panel>
          ) : (
            <div className="space-y-4">
              {data!.items.map((item) => (
                <ChangeCard key={item.id} item={item} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function RatingDateStrip({
  ratingDate,
  source,
  needs,
}: {
  ratingDate: string | null
  source: string | null
  needs: boolean
}) {
  const hue: Hue = needs ? 'amber' : HUE
  return (
    <div
      className="flex flex-wrap items-center gap-3 rounded-control border-l-[3px] px-4 py-3"
      style={{ borderColor: hueVar(hue), background: hueSoftVar(hue) }}
    >
      <CalendarClock size={18} style={{ color: hueInk(hue) }} className="shrink-0" />
      {needs ? (
        <p className="text-sm text-txt/90">
          No rating date on file yet — comparing against all recent changes. Upload your rating decision to anchor this
          to your actual rating date.
        </p>
      ) : (
        <p className="text-sm text-txt/90">
          Comparing against your rating date:{' '}
          <span className="font-semibold" style={{ color: hueInk(hue) }}>
            {formatDate(ratingDate)}
          </span>
          {source && <span className="text-muted"> (from your {source.replace('_', ' ')})</span>}
        </p>
      )}
    </div>
  )
}

function ChangeCard({ item }: { item: WhatsChangedItem }) {
  const sig = SIGNAL[item.action_signal]
  const proposed = item.status === 'proposed'
  const [assessment, setAssessment] = useState<string | null>(null)
  const [assessing, setAssessing] = useState(false)
  const [assessError, setAssessError] = useState<string | null>(null)

  const runAssess = async () => {
    setAssessing(true)
    setAssessError(null)
    try {
      const res = await analysisApi.whatsChangedAssess(item.id)
      setAssessment(res.assessment || 'No specific read was available — discuss the details with a VSO.')
    } catch {
      setAssessError("Couldn't generate a personalized read just now. The change details above still apply.")
    } finally {
      setAssessing(false)
    }
  }

  return (
    <div className="vo-card vo-accent p-5" style={hueStyle(sig.hue) as CSSProperties}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-bold leading-snug text-txt">{item.title}</h2>
            {proposed && (
              <span className="vo-chip-hue" style={hueStyle('amber') as CSSProperties}>
                Proposed
              </span>
            )}
          </div>
          <p className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
            <History size={12} /> Took effect {formatDate(item.effective_date)}
          </p>
        </div>
        <span className="vo-chip-hue shrink-0" style={hueStyle(sig.hue) as CSSProperties}>
          {sig.label}
        </span>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-txt/90">{item.summary}</p>

      <div
        className="mt-3 flex items-start gap-2 rounded-control px-3 py-2 text-sm"
        style={{ background: 'var(--surface)' }}
      >
        <Sparkles size={14} className="mt-0.5 shrink-0" style={{ color: hueInk(sig.hue) }} />
        <span className="text-txt/85">
          Flagged because it touches <span className="font-medium">{item.matched_detail}</span>.
        </span>
      </div>

      <p className="mt-3 text-sm leading-relaxed text-muted">{item.action_hint}</p>

      {/* The ONE AI step — opt-in, on demand (no model runs just by opening the page). */}
      {assessment ? (
        <div
          className="mt-4 rounded-control border-l-[3px] px-3.5 py-3"
          style={{ borderColor: hueVar(sig.hue), background: hueSoftVar(sig.hue) }}
        >
          <p className="mb-1 flex items-center gap-1.5 text-micro font-bold uppercase tracking-wide" style={{ color: hueInk(sig.hue) }}>
            <Sparkles size={12} /> What this may mean for you
          </p>
          <p className="text-sm leading-relaxed text-txt/90">{assessment}</p>
          <p className="mt-2 text-micro text-faint">
            A person-specific read from your on-device assistant — educational, not a prediction. Confirm with a VSO.
          </p>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button type="button" onClick={runAssess} disabled={assessing} className="vo-btn-secondary text-sm">
            {assessing ? (
              <>
                <RefreshCw size={14} className="animate-spin" /> Reading your situation…
              </>
            ) : (
              <>
                <Sparkles size={14} /> What does this mean for me?
              </>
            )}
          </button>
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-sm font-semibold"
            style={{ color: hueInk(sig.hue) }}
          >
            Read the source <ExternalLink size={13} />
          </a>
        </div>
      )}

      {assessError && (
        <p className="mt-2 flex items-center gap-1.5 text-xs text-danger">
          <AlertCircle size={12} /> {assessError}
        </p>
      )}

      {item.matched_by === 'condition' && !assessment && (
        <Link
          to="/conditions"
          className="mt-3 inline-flex items-center gap-1 text-xs font-semibold text-muted hover:text-txt"
        >
          Review your conditions <ArrowRight size={12} />
        </Link>
      )}
    </div>
  )
}
