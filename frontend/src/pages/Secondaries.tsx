import { FileText, FlaskConical, Sparkles, Stethoscope, Telescope } from 'lucide-react'
import { useState, type CSSProperties } from 'react'
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { CreditLimitNotice } from '../components/CreditLimitNotice'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { ApiError, analysisApi, conditionsApi } from '../lib/api'
import { hueInk, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { LandscapeLead, SecondarySuggestion } from '../types'

export function Secondaries() {
  const { toast } = useToast()
  const { data: conditions, loading: condLoading, error: condError, reload: reloadConditions } = useAsync(() => conditionsApi.list())
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [suggestions, setSuggestions] = useState<SecondarySuggestion[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [creditError, setCreditError] = useState<string | null>(null)
  const [ran, setRan] = useState(false)

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const run = async () => {
    setLoading(true)
    setError(null)
    setCreditError(null)
    setRan(true)
    try {
      // The API takes condition NAMES; an empty list means "use all my claimed conditions".
      const names = (conditions ?? []).filter((c) => selected.has(c.id)).map((c) => c.name)
      const res = await analysisApi.secondaries(names)
      setSuggestions(res.items)
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) {
        setCreditError(err.message)
        setSuggestions(null)
      } else {
        setError(errorMessage(err))
        toast(errorMessage(err), 'error')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div data-section="insight" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Pattern insight</p>
        <h1 className="vo-page-title">Suggested secondaries</h1>
        <p className="vo-page-sub">
          Conditions that often develop secondary to what you've already claimed — plausible connections worth
          discussing with your provider, not a diagnosis.
        </p>
      </div>

      <Panel hue="fuchsia" title="Pick conditions" subtitle="Leave none selected to check all">
        <div className="space-y-3 p-5">
          {condLoading ? (
            <LoadingBlock />
          ) : condError ? (
            <ErrorBlock message={condError} onRetry={reloadConditions} />
          ) : !conditions || conditions.length === 0 ? (
            <p className="text-sm text-muted">Add conditions first so Rating Raider has something to check against.</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {conditions.map((c) => (
                <button
                  key={c.id}
                  onClick={() => toggle(c.id)}
                  aria-pressed={selected.has(c.id)}
                  className={`min-h-10 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors ${
                    selected.has(c.id) ? 'border-brand bg-brand-soft text-brand' : 'border-line bg-surface2 text-muted hover:text-txt'
                  }`}
                >
                  {c.name}
                </button>
              ))}
            </div>
          )}
          <button onClick={() => void run()} disabled={loading} className="vo-btn-primary">
            {loading ? <Spinner size={16} className="text-white" /> : <Sparkles size={15} />}
            Suggest secondaries
          </button>
        </div>
      </Panel>

      {loading ? (
        <LoadingBlock label="Checking the secondary-conditions map…" />
      ) : creditError ? (
        <CreditLimitNotice />
      ) : error ? (
        <ErrorBlock message={error} onRetry={() => void run()} />
      ) : ran && (!suggestions || suggestions.length === 0) ? (
        <EmptyState
          hue="fuchsia"
          icon={<Sparkles size={20} />}
          title="No mapped patterns for your current conditions"
          description="This list only covers common, well-documented secondary patterns — a provider or VSO may see connections it doesn't."
        />
      ) : suggestions && suggestions.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {suggestions.map((s, i) => (
            <div
              key={i}
              className="vo-card vo-accent flex flex-col p-5"
              style={{ '--hue': 'var(--hue-pink)', '--hue-soft': 'var(--hue-pink-soft)' } as React.CSSProperties}
            >
              <div>
                <h3 className="text-base font-semibold text-txt">{s.secondary}</h3>
                <p className="mt-0.5 text-xs font-medium" style={{ color: hueInk('pink') }}>secondary to {s.primary}</p>
              </div>
              <p className="mt-3 flex-1 text-sm text-muted">{s.rationale}</p>
              <div className="mt-3 flex items-start gap-1.5 rounded-control border border-line bg-surface2 px-3 py-2 text-xs text-muted">
                <Stethoscope size={13} className="mt-0.5 shrink-0 text-brand" />
                Discuss this with your provider — they determine the medical connection.
              </div>
              {(s.dbq || s.source) && (
                <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-3">
                  {s.dbq && (
                    <span className="vo-chip">
                      <FileText size={11} className="shrink-0 text-brand" /> DBQ {s.dbq}
                    </span>
                  )}
                  {s.source && <span className="vo-chip">{s.source}</span>}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : null}

      <DeeperLeads hasConditions={!!conditions && conditions.length > 0} />
    </div>
  )
}

const STRENGTH: Record<LandscapeLead['strength'], { label: string; hue: Hue }> = {
  well_documented: { label: 'Well documented', hue: 'emerald' },
  plausible: { label: 'Plausible', hue: 'sky' },
  emerging: { label: 'Emerging', hue: 'amber' },
}

/** The deep landscape scan — model-suggested secondary LEADS BEYOND the curated map.
 * Opt-in (no model runs until the veteran asks). Framed hard as hypotheses to research
 * with a provider, never as facts or a claim of qualification. */
function DeeperLeads({ hasConditions }: { hasConditions: boolean }) {
  const HUE: Hue = 'teal'
  const [leads, setLeads] = useState<LandscapeLead[] | null>(null)
  const [disclaimer, setDisclaimer] = useState('')
  const [loading, setLoading] = useState(false)
  const [credit, setCredit] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    setLoading(true)
    setError(null)
    setCredit(false)
    try {
      const res = await analysisApi.landscapeScan()
      setLeads(res.leads)
      setDisclaimer(res.disclaimer)
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) setCredit(true)
      else setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Panel
      hue={HUE}
      title="Look deeper — leads to research"
      subtitle="Beyond the curated list: connections your assistant thinks are worth investigating with your doctor"
    >
      <div className="space-y-4 p-5" style={hueStyle(HUE) as CSSProperties}>
        <p className="flex items-start gap-2 rounded-control border-l-[3px] px-3.5 py-2.5 text-sm leading-relaxed text-txt/85"
          style={{ borderColor: hueVar(HUE), background: 'var(--surface2)' }}>
          <FlaskConical size={15} className="mt-0.5 shrink-0" style={{ color: hueInk(HUE) }} />
          <span>
            These aren't from a citation list — they're your assistant reasoning from medical knowledge to widen the net.
            Treat them as <span className="font-medium">questions to bring to a provider</span>, never as facts or a
            promise that you qualify.
          </span>
        </p>

        {!leads && (
          <button
            type="button"
            onClick={() => void run()}
            disabled={loading || !hasConditions}
            className="vo-btn-primary"
          >
            {loading ? <Spinner size={16} className="text-white" /> : <Telescope size={15} />}
            {loading ? 'Scanning the landscape…' : 'Scan for deeper connections'}
          </button>
        )}
        {!hasConditions && (
          <p className="text-sm text-muted">Add your conditions first so there's something to scan from.</p>
        )}

        {credit && <CreditLimitNotice />}
        {error && <ErrorBlock message={error} onRetry={() => void run()} />}

        {leads && leads.length === 0 && (
          <EmptyState
            hue={HUE}
            icon={<Telescope size={20} />}
            title="Nothing beyond the curated list this time"
            description="Your assistant didn't find well-founded connections past the ones already shown above. That can change as you add conditions."
          />
        )}

        {leads && leads.length > 0 && (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              {leads.map((l, i) => {
                const s = STRENGTH[l.strength]
                return (
                  <div key={i} className="vo-card vo-accent flex flex-col p-5" style={hueStyle(s.hue) as CSSProperties}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <h3 className="text-base font-semibold text-txt">{l.secondary}</h3>
                        <p className="mt-0.5 text-xs font-medium" style={{ color: hueInk(HUE) }}>
                          possibly secondary to {l.primary}
                        </p>
                      </div>
                      <span className="vo-chip-hue shrink-0" style={hueStyle(s.hue) as CSSProperties}>
                        {s.label}
                      </span>
                    </div>
                    <p className="mt-3 flex-1 text-sm text-muted">{l.mechanism}</p>
                    {l.discuss && (
                      <div className="mt-3 flex items-start gap-1.5 rounded-control border border-line bg-surface2 px-3 py-2 text-xs text-muted">
                        <Stethoscope size={13} className="mt-0.5 shrink-0" style={{ color: hueInk(HUE) }} />
                        {l.discuss}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            {disclaimer && <p className="text-xs leading-relaxed text-faint">{disclaimer}</p>}
          </>
        )}
      </div>
    </Panel>
  )
}
