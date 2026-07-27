import { ListChecks, Trash2, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { EmptyState, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { ratingApi } from '../lib/api'
import { hueFor } from '../lib/hues'
import { formatDateTime } from '../lib/format'
import { SCENARIO_LOAD_KEY } from '../lib/scenarioBridge'
import type { RatingScenario } from '../types'

export function Scenarios() {
  const { toast } = useToast()
  const navigate = useNavigate()
  const { data, loading, error, reload, setData } = useAsync(() => ratingApi.scenarios.list())

  const loadIntoCalculator = (scenario: RatingScenario) => {
    try {
      localStorage.setItem(SCENARIO_LOAD_KEY, JSON.stringify(scenario.entries))
    } catch {
      /* noop */
    }
    navigate('/calculator')
  }

  const remove = async (id: string) => {
    if (!window.confirm('Delete this scenario?')) return
    try {
      await ratingApi.scenarios.remove(id)
      setData((prev) => (prev ?? []).filter((s) => s.id !== id))
      toast('Scenario deleted.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div data-section="math" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Ratings math</p>
        <h1 className="vo-page-title">Saved scenarios</h1>
        <p className="vo-page-sub">What-ifs you've saved from the calculator.</p>
      </div>

      {loading ? (
        <LoadingBlock label="Loading scenarios…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState
          hue="sky"
          icon={<ListChecks size={20} />}
          title="No scenarios saved yet"
          description="Build a combination in the calculator, then save it as a scenario to compare later."
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {data.map((scenario) => (
            <Panel key={scenario.id} hue={hueFor(scenario.id)} title={scenario.name} subtitle={formatDateTime(scenario.created_at)}>
              <div className="flex h-full flex-col p-5">
                <div className="mb-3 flex items-end gap-2">
                  <span className="vo-wordmark text-4xl font-extrabold leading-none tabular-nums">
                    {scenario.result?.combined ?? '—'}%
                  </span>
                  <span className="pb-1 text-xs text-faint">combined</span>
                </div>
                <div className="mb-4 flex flex-1 flex-wrap gap-1.5">
                  {scenario.entries.map((e, i) => (
                    <span key={i} className="vo-chip">
                      {e.label} <span className="tabular-nums text-txt">{e.percent}%</span>
                      {e.side ? <span className="text-faint">({e.side})</span> : null}
                    </span>
                  ))}
                </div>
                <div className="flex gap-2">
                  <button onClick={() => loadIntoCalculator(scenario)} className="vo-btn-secondary min-h-10 flex-1 justify-center text-sm">
                    <Upload size={14} /> Load into calculator
                  </button>
                  <button onClick={() => void remove(scenario.id)} className="vo-icon-btn vo-btn-ghost text-muted hover:text-danger" aria-label="Delete scenario">
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            </Panel>
          ))}
        </div>
      )}
    </div>
  )
}
