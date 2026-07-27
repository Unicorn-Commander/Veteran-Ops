import { ChevronRight, Shield } from 'lucide-react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { analysisApi } from '../lib/api'
import { hueFor, hueInk, PROGRAM_HUES, type Hue } from '../lib/hues'
import type { PresumptiveMatch } from '../types'

/** Map the backend's human program label (e.g. "PACT Act — burn pits / airborne
 * hazards") onto the fixed program hues; unknown programs get a stable hash hue. */
function programHue(program: string): Hue {
  const p = program.toLowerCase()
  if (p.includes('pact')) return PROGRAM_HUES.pact
  if (p.includes('agent orange') || p.includes('herbicide')) return PROGRAM_HUES.agent_orange
  if (p.includes('gulf war')) return PROGRAM_HUES.gulf_war
  if (p.includes('radiation')) return PROGRAM_HUES.radiation
  if (p.includes('lejeune')) return PROGRAM_HUES.camp_lejeune
  return hueFor(program)
}

export function Presumptives() {
  const { data, loading, error, reload } = useAsync(() => analysisApi.presumptives())

  const matches = data?.matches ?? []

  const grouped = matches.reduce<Record<string, PresumptiveMatch[]>>((acc, m) => {
    ;(acc[m.program || 'Other'] ??= []).push(m)
    return acc
  }, {})

  return (
    <div data-section="insight" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Pattern insight</p>
        <h1 className="vo-page-title">Presumptive conditions</h1>
        <p className="vo-page-sub">
          A rule-based screen of your service periods and exposures against VA's presumptive lists — PACT Act, Agent
          Orange, Gulf War, radiation, and Camp Lejeune. Membership is determined by fixed rules, never guessed.
        </p>
      </div>

      {loading ? (
        <LoadingBlock label="Screening your profile…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={reload} />
      ) : matches.length === 0 ? (
        <EmptyState
          hue="fuchsia"
          icon={<Shield size={20} />}
          title="No presumptive matches yet"
          description="Based on what's in your profile now, nothing matched. Add service periods and exposures (including POW internment days if relevant) so Rating Raider can check VA's lists."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Link to="/profile?start=1" className="vo-btn-primary text-sm">
                Update profile
              </Link>
              <Link to="/onboarding" className="vo-btn-secondary text-sm">
                Guided setup
              </Link>
            </div>
          }
        />
      ) : (
        <div className="space-y-5">
          {Object.entries(grouped).map(([program, items]) => {
            const hue = programHue(program)
            return (
              <Panel key={program} hue={hue} title={program}>
                <ul className="divide-y divide-line">
                  {items.map((m, i) => (
                    <li key={i} className="p-5">
                      <h3 className="text-sm font-semibold text-txt">{m.condition}</h3>
                      {m.matched_reason && (
                        <div
                          className="mt-2 rounded-control border px-3 py-2 text-sm font-medium leading-snug"
                          style={{
                            borderColor: `color-mix(in srgb, var(--hue-${hue}) 35%, transparent)`,
                            background: `var(--hue-${hue}-soft)`,
                            color: hueInk(hue),
                          }}
                        >
                          Why this matched: {m.matched_reason}
                        </div>
                      )}
                      <p className="mt-2 text-sm text-muted">{m.rationale}</p>
                      {m.conditions.length > 0 && (
                        <details className="vo-disclosure group mt-2.5">
                          <summary className="flex items-center gap-1.5 text-xs font-medium uppercase text-faint transition-colors hover:text-muted">
                            <ChevronRight
                              size={12}
                              className="shrink-0 transition-transform duration-200 group-open:rotate-90"
                            />
                            {m.conditions.length} condition{m.conditions.length === 1 ? '' : 's'} on this presumptive list
                          </summary>
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {m.conditions.map((c) => (
                              <span key={c} className="rounded-full border border-line bg-surface2 px-2.5 py-0.5 text-xs text-muted">
                                {c}
                              </span>
                            ))}
                          </div>
                        </details>
                      )}
                      {m.source && <span className="vo-chip mt-2.5 inline-flex">{m.source}</span>}
                    </li>
                  ))}
                </ul>
              </Panel>
            )
          })}
        </div>
      )}
    </div>
  )
}
