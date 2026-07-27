import {
  Banknote,
  ChevronDown,
  Info,
  ListEnd,
  Plus,
  ScrollText,
  Trash2,
  TriangleAlert,
} from 'lucide-react'
import { useState } from 'react'
import { AnimatedNumber, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage } from '../hooks/useAsync'
import { ratingApi } from '../lib/api'
import type { BackpayInput, BackpayPeriodInput, BackpayResult } from '../types'

// /backpay — wave 3 retro/back-pay estimator (POST /rating/backpay,
// routers/rating.py BackpayIn → rating/backpay.py compute_backpay()). All the
// math is deterministic and server-side from official VA rate tables; this
// page only collects the timeline and renders the ledger. Legal lane:
// estimates only — VA's award letter and payment history are authoritative.

const PERCENTS = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

interface PeriodForm {
  from: string
  to: string
  percent: number
  spouse: boolean
  children_under_18: number
  children_in_school: number
  parents: number
  spouse_aa: boolean
}

function emptyPeriod(percent = 50): PeriodForm {
  return {
    from: '',
    to: '',
    percent,
    spouse: false,
    children_under_18: 0,
    children_in_school: 0,
    parents: 0,
    spouse_aa: false,
  }
}

function toPayload(p: PeriodForm): BackpayPeriodInput {
  return {
    from_date: p.from,
    to_date: p.to || null,
    combined_percent: p.percent,
    dependents: {
      spouse: p.spouse,
      children_under_18: p.children_under_18,
      children_in_school: p.children_in_school,
      parents: p.parents,
      spouse_aa: p.spouse_aa,
    },
  }
}

const usd = (n: number | null | undefined): string =>
  n == null ? '—' : n.toLocaleString('en-US', { style: 'currency', currency: 'USD' })

export function Backpay() {
  const { toast } = useToast()
  const [periods, setPeriods] = useState<PeriodForm[]>([emptyPeriod()])
  const [received, setReceived] = useState<PeriodForm[]>([])
  const [computing, setComputing] = useState(false)
  const [result, setResult] = useState<BackpayResult | null>(null)

  const compute = async () => {
    const missing = [...periods, ...received].some((p) => !p.from)
    if (missing) {
      toast('Every period needs an effective (from) date.', 'error')
      return
    }
    const body: BackpayInput = {
      periods: periods.map(toPayload),
      payment_already_received: received.length > 0 ? received.map(toPayload) : undefined,
    }
    setComputing(true)
    try {
      setResult(await ratingApi.backpay(body))
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setComputing(false)
    }
  }

  return (
    <div data-section="math" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Ratings math</p>
        <h1 className="vo-page-title">Back-pay estimator</h1>
        <p className="vo-page-sub">
          Estimate retroactive pay from a rating's effective date, month by month, straight from VA's published rate
          tables. Estimates only — VA's award letter and payment history are authoritative.
        </p>
      </div>

      <Panel
        title="Your rating timeline"
        subtitle="Each period starts at its EFFECTIVE date (per the award letter), not the first payment date"
      >
        <div className="space-y-4 p-5">
          {periods.map((p, i) => (
            <PeriodEditor
              key={i}
              period={p}
              index={i}
              onChange={(patch) => setPeriods((prev) => prev.map((x, j) => (j === i ? { ...x, ...patch } : x)))}
              onRemove={periods.length > 1 ? () => setPeriods((prev) => prev.filter((_, j) => j !== i)) : undefined}
            />
          ))}
          <button onClick={() => setPeriods((prev) => [...prev, emptyPeriod(prev[prev.length - 1]?.percent ?? 50)])} className="vo-btn-secondary text-sm">
            <Plus size={14} /> Add another period (e.g. an increase)
          </button>
        </div>
      </Panel>

      <Panel
        hue="cyan"
        title="Payments already received (optional)"
        subtitle="If VA was already paying you at a lower rate, the estimate nets that out"
      >
        <div className="space-y-4 p-5">
          {received.length === 0 ? (
            <p className="text-sm text-muted">
              Leave this empty if you weren't being paid during the window — the estimate then shows the full amount.
            </p>
          ) : (
            received.map((p, i) => (
              <PeriodEditor
                key={i}
                period={p}
                index={i}
                onChange={(patch) => setReceived((prev) => prev.map((x, j) => (j === i ? { ...x, ...patch } : x)))}
                onRemove={() => setReceived((prev) => prev.filter((_, j) => j !== i))}
              />
            ))
          )}
          <button onClick={() => setReceived((prev) => [...prev, emptyPeriod(prev[prev.length - 1]?.percent ?? 10)])} className="vo-btn-secondary text-sm">
            <Plus size={14} /> Add a received-payments period
          </button>
        </div>
      </Panel>

      <div className="flex items-center gap-3">
        <button onClick={() => void compute()} disabled={computing} className="vo-btn-primary">
          {computing ? <Spinner size={16} className="text-white" /> : <Banknote size={15} />}
          Estimate my back pay
        </button>
        <p className="text-xs text-muted">Deterministic math from official VA rate tables — no AI involved.</p>
      </div>

      {result && <Results result={result} />}
    </div>
  )
}

function PeriodEditor({
  period,
  index,
  onChange,
  onRemove,
}: {
  period: PeriodForm
  index: number
  onChange: (patch: Partial<PeriodForm>) => void
  onRemove?: () => void
}) {
  const [depsOpen, setDepsOpen] = useState(
    period.spouse || period.children_under_18 > 0 || period.children_in_school > 0 || period.parents > 0
  )
  const depsSummary =
    [
      period.spouse ? `spouse${period.spouse_aa ? ' (A&A)' : ''}` : null,
      period.children_under_18 > 0 ? `${period.children_under_18} child${period.children_under_18 === 1 ? '' : 'ren'} under 18` : null,
      period.children_in_school > 0 ? `${period.children_in_school} in school (18–23)` : null,
      period.parents > 0 ? `${period.parents} parent${period.parents === 1 ? '' : 's'}` : null,
    ]
      .filter(Boolean)
      .join(', ') || 'veteran alone'

  return (
    <div className="space-y-3 rounded-control border border-line bg-surface2 p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wider text-faint">Period {index + 1}</p>
        {onRemove && (
          <button onClick={onRemove} className="vo-icon-btn vo-btn-ghost text-muted hover:text-danger" aria-label={`Remove period ${index + 1}`}>
            <Trash2 size={14} />
          </button>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">
          <span className="vo-label">Effective date (from)</span>
          <input type="date" className="vo-input" value={period.from} onChange={(e) => onChange({ from: e.target.value })} required />
        </label>
        <label className="text-sm">
          <span className="vo-label">Until (optional)</span>
          <input type="date" className="vo-input" value={period.to} onChange={(e) => onChange({ to: e.target.value })} />
        </label>
        <label className="text-sm">
          <span className="vo-label">Combined rating</span>
          <select className="vo-input" value={period.percent} onChange={(e) => onChange({ percent: Number(e.target.value) })}>
            {PERCENTS.map((p) => (
              <option key={p} value={p}>
                {p}%
              </option>
            ))}
          </select>
        </label>
      </div>
      <div>
        <button
          onClick={() => setDepsOpen((v) => !v)}
          className="flex items-center gap-1.5 text-sm font-medium text-muted transition-colors hover:text-txt"
          aria-expanded={depsOpen}
          type="button"
        >
          <ChevronDown size={14} className={`transition-transform ${depsOpen ? 'rotate-180' : ''}`} />
          Dependents: <span className="text-txt">{depsSummary}</span>
        </button>
        {depsOpen && (
          <div className="vo-step-enter mt-3 grid gap-3 sm:grid-cols-2">
            <label className="flex min-h-[2.5rem] cursor-pointer items-center gap-2.5 text-sm text-txt">
              <input type="checkbox" className="vo-check" checked={period.spouse} onChange={(e) => onChange({ spouse: e.target.checked, spouse_aa: e.target.checked ? period.spouse_aa : false })} />
              Married (spouse)
            </label>
            <label className={`flex min-h-[2.5rem] items-center gap-2.5 text-sm text-txt ${period.spouse ? 'cursor-pointer' : 'opacity-50'}`}>
              <input type="checkbox" className="vo-check" disabled={!period.spouse} checked={period.spouse_aa} onChange={(e) => onChange({ spouse_aa: e.target.checked })} />
              Spouse receives Aid &amp; Attendance
            </label>
            <label className="text-sm">
              <span className="vo-label">Children under 18</span>
              <input type="number" min={0} max={20} className="vo-input" value={period.children_under_18} onChange={(e) => onChange({ children_under_18: Math.max(0, Math.min(20, Number(e.target.value) || 0)) })} />
            </label>
            <label className="text-sm">
              <span className="vo-label">Children 18–23 in school</span>
              <input type="number" min={0} max={20} className="vo-input" value={period.children_in_school} onChange={(e) => onChange({ children_in_school: Math.max(0, Math.min(20, Number(e.target.value) || 0)) })} />
            </label>
            <label className="text-sm">
              <span className="vo-label">Dependent parents (0–2)</span>
              <select className="vo-input" value={period.parents} onChange={(e) => onChange({ parents: Number(e.target.value) })}>
                {[0, 1, 2].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
            <p className="self-end pb-1 text-xs text-muted">10% and 20% ratings pay a flat rate regardless of dependents.</p>
          </div>
        )}
      </div>
    </div>
  )
}

function Results({ result }: { result: BackpayResult }) {
  const [ledgerOpen, setLedgerOpen] = useState(false)
  const years = Object.entries(result.by_year_subtotals)
  const maxNet = Math.max(1, ...years.map(([, v]) => Math.abs(v.net)))
  const cfr331 = result.assumptions.find((a) => a.includes('3.31'))

  return (
    <div className="space-y-5">
      {/* Dollars hero */}
      <Panel title="Estimated back pay" subtitle="Net of anything already received — an estimate, not a determination">
        <div className="space-y-4 p-5">
          <div>
            <p className="text-5xl font-bold tabular-nums text-txt">
              <AnimatedNumber value={result.total} format={(n) => usd(Math.round(n * 100) / 100)} />
            </p>
            <p className="mt-1.5 text-sm text-muted">
              Estimated <span className="font-semibold tabular-nums text-txt">{usd(result.entitled_total)}</span>
              {' − '}already received{' '}
              <span className="font-semibold tabular-nums text-txt">{usd(result.received_total)}</span> across{' '}
              {result.months.length} month{result.months.length === 1 ? '' : 's'}
            </p>
          </div>
          {cfr331 && (
            <p className="flex items-start gap-2 rounded-control border border-line bg-surface2 px-4 py-3 text-xs leading-relaxed text-muted">
              <Info size={14} className="mt-0.5 shrink-0" style={{ color: 'var(--section-hue)' }} />
              <span>{cfr331}</span>
            </p>
          )}

          {years.length > 0 && (
            <div>
              <p className="vo-label-micro mb-2">By year (net)</p>
              <div className="space-y-1.5">
                {years.map(([year, v]) => (
                  <div key={year} className="flex items-center gap-3 text-sm">
                    <span className="w-12 shrink-0 tabular-nums text-muted">{year}</span>
                    <span className="relative h-5 flex-1 overflow-hidden rounded bg-surface2">
                      <span
                        className="absolute inset-y-0 left-0 rounded"
                        style={{
                          width: `${Math.max(2, (Math.abs(v.net) / maxNet) * 100)}%`,
                          background:
                            'linear-gradient(90deg, var(--section-hue), color-mix(in srgb, var(--section-hue) 55%, transparent))',
                        }}
                      />
                    </span>
                    <span className="w-28 shrink-0 text-right font-semibold tabular-nums text-txt">{usd(v.net)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Panel>

      {result.excluded_months.length > 0 && (
        <div
          className="flex items-start gap-2.5 rounded-control border px-4 py-3.5 text-sm"
          style={{
            borderColor: 'color-mix(in srgb, var(--warning) 45%, transparent)',
            background: 'var(--hue-amber-soft)',
          }}
        >
          <TriangleAlert size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--warning)' }} />
          <div>
            <p className="font-semibold text-txt">
              {result.excluded_months.length} month{result.excluded_months.length === 1 ? '' : 's'} excluded from the
              total
            </p>
            <p className="mt-0.5 text-muted">
              These fall in rate years outside the verified VA.gov tables (covered:{' '}
              {result.rate_years_covered[0]}–{result.rate_years_covered[result.rate_years_covered.length - 1]}), so no
              amount is estimated for them — never guessed: {result.excluded_months.join(', ')}.
            </p>
          </div>
        </div>
      )}

      {/* Month-by-month ledger */}
      <Panel hue="cyan" title="Month-by-month ledger" subtitle="Every month, its rate-table amount, and why">
        <div className="p-5">
          <button
            onClick={() => setLedgerOpen((v) => !v)}
            className="flex items-center gap-1.5 text-sm font-semibold text-muted transition-colors hover:text-txt"
            aria-expanded={ledgerOpen}
          >
            <ChevronDown size={15} className={`transition-transform ${ledgerOpen ? 'rotate-180' : ''}`} />
            {ledgerOpen ? 'Hide' : 'Show'} all {result.months.length} months
          </button>
          {ledgerOpen && (
            <div className="vo-step-enter mt-3 overflow-x-auto">
              <table className="w-full min-w-[36rem] text-left text-sm">
                <thead>
                  <tr className="border-b border-line text-micro font-semibold uppercase tracking-wider text-faint">
                    <th className="py-2 pr-3">Month</th>
                    <th className="py-2 pr-3">Rating</th>
                    <th className="py-2 pr-3 text-right">Rate</th>
                    <th className="py-2 pr-3 text-right">Received</th>
                    <th className="py-2 pr-3 text-right">Net</th>
                    <th className="py-2">Note</th>
                  </tr>
                </thead>
                <tbody>
                  {result.months.map((m) => (
                    <tr key={m.month} className="border-b border-line align-top last:border-0">
                      <td className="py-2 pr-3 font-medium tabular-nums text-txt">{m.month}</td>
                      <td className="py-2 pr-3 tabular-nums text-muted">{m.percent != null ? `${m.percent}%` : '—'}</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-txt">{usd(m.rate)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-muted">{usd(m.received)}</td>
                      <td className="py-2 pr-3 text-right font-semibold tabular-nums text-txt">{usd(m.net)}</td>
                      <td className="max-w-[22rem] py-2 text-xs leading-relaxed text-muted">{m.note || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Panel>

      {/* Assumptions + not modeled — ALWAYS rendered, prominently (legal lane). */}
      <div className="grid gap-5 md:grid-cols-2">
        <Panel title={<span className="flex items-center gap-2"><ScrollText size={15} /> How this was calculated</span>} subtitle="The exact assumptions behind every number above">
          <ul className="space-y-2 p-5 text-sm leading-relaxed text-muted">
            {result.assumptions.map((a, i) => (
              <li key={i} className="flex gap-2">
                <span aria-hidden className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: 'var(--section-hue)' }} />
                <span>{a}</span>
              </li>
            ))}
          </ul>
        </Panel>
        <Panel hue="amber" title={<span className="flex items-center gap-2"><ListEnd size={15} /> Not modeled here</span>} subtitle="Any of these would change the real amounts">
          <ul className="space-y-2 p-5 text-sm leading-relaxed text-muted">
            {result.not_modeled.map((a, i) => (
              <li key={i} className="flex gap-2">
                <span aria-hidden className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: 'var(--hue-amber)' }} />
                <span>{a}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <p className="text-center text-xs text-faint">
        Estimates only — VA's award letter and payment history are authoritative. Rating Raider is self-help
        educational software, not a benefits determination.
      </p>
    </div>
  )
}
