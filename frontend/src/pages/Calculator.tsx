import { AlertCircle, Award, FlaskConical, GitMerge, Minus, Plus, Save, Trash2, TrendingDown, TrendingUp } from 'lucide-react'
import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, HueBadge, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage } from '../hooks/useAsync'
import { ratingApi } from '../lib/api'
import { hueInk } from '../lib/hues'
import { dictText } from '../lib/format'
import { SCENARIO_LOAD_KEY } from '../lib/scenarioBridge'
import type { CombinedResult, RatingEntry, RatingStep, SmcFlag } from '../types'

interface EntryRow {
  id: string
  label: string
  percent: number
  side: '' | 'left' | 'right'
  group: string
  hypothetical: boolean
  enabled: boolean
}

let rowSeq = 0
function newRow(patch: Partial<EntryRow> = {}): EntryRow {
  return {
    id: `row-${++rowSeq}`,
    label: '',
    percent: 10,
    side: '',
    group: '',
    hypothetical: false,
    enabled: true,
    ...patch,
  }
}

function toApiEntries(rows: EntryRow[]): RatingEntry[] {
  return rows
    .filter((r) => r.label.trim() && r.percent > 0)
    .map((r) => ({
      label: r.label.trim(),
      percent: r.percent,
      side: r.side || null,
      group: r.group.trim() || null,
    }))
}

// ---- Step-log helpers ------------------------------------------------------
// The engine (backend/app/rating/engine.py) emits a stable step shape per
// kind ('note' | 'order' | 'bilateral' | 'combine' | 'round') with a running
// `value` on the math-bearing kinds. The TS type keeps this as a loose
// Record<string, unknown> because it crosses a service boundary — these
// helpers read it defensively (never compute anything themselves) so the
// timeline can show a live capacity bar without assuming a shape that isn't
// guaranteed.
function stepKind(step: RatingStep): string {
  const k = step['kind']
  return typeof k === 'string' ? k : 'step'
}
function stepValue(step: RatingStep): number | undefined {
  const v = step['value']
  return typeof v === 'number' ? v : undefined
}
const STEP_BAR_HUE: Record<string, string> = {
  bilateral: 'var(--hue-cyan)',
  combine: 'var(--brand)',
  round: 'var(--hue-teal)',
}

function flagField(flag: SmcFlag, key: string): string | undefined {
  const v = (flag as Record<string, unknown>)[key]
  return typeof v === 'string' && v.trim() ? v : undefined
}

function DeltaBadge({ from, to }: { from: number; to: number }) {
  const diff = to - from
  const tone = diff > 0 ? 'success' : diff < 0 ? 'warning' : 'neutral'
  const Icon = diff > 0 ? TrendingUp : diff < 0 ? TrendingDown : Minus
  return (
    <Badge tone={tone}>
      <Icon size={12} />
      <span className="tabular-nums">
        {from}% → {to}%
      </span>
    </Badge>
  )
}

export function Calculator() {
  const { toast } = useToast()
  const navigate = useNavigate()
  const [rows, setRows] = useState<EntryRow[]>(() => {
    try {
      const pending = localStorage.getItem(SCENARIO_LOAD_KEY)
      if (pending) {
        localStorage.removeItem(SCENARIO_LOAD_KEY)
        const entries = JSON.parse(pending) as RatingEntry[]
        if (Array.isArray(entries) && entries.length > 0) {
          return entries.map((e) =>
            newRow({ label: e.label, percent: e.percent, side: (e.side ?? '') as EntryRow['side'], group: e.group ?? '' })
          )
        }
      }
    } catch {
      /* fall through to default row */
    }
    return [newRow({ label: 'Tinnitus', percent: 10 })]
  })
  const [realResult, setRealResult] = useState<CombinedResult | null>(null)
  const [previewResult, setPreviewResult] = useState<CombinedResult | null>(null)
  const [calculating, setCalculating] = useState(false)
  const [calcError, setCalcError] = useState<string | null>(null)
  const [savingName, setSavingName] = useState('')
  const [showSave, setShowSave] = useState(false)
  const [saving, setSaving] = useState(false)

  const realRows = useMemo(() => rows.filter((r) => !r.hypothetical), [rows])
  const previewRows = useMemo(() => rows.filter((r) => !r.hypothetical || r.enabled), [rows])
  const hasHypothetical = previewRows.length !== realRows.length

  useEffect(() => {
    const realEntries = toApiEntries(realRows)
    const previewEntries = toApiEntries(previewRows)
    if (realEntries.length === 0) {
      setRealResult(null)
      setPreviewResult(null)
      setCalcError(null)
      return
    }
    const timer = window.setTimeout(async () => {
      setCalculating(true)
      setCalcError(null)
      try {
        const real = await ratingApi.calculate(realEntries)
        setRealResult(real)
        if (hasHypothetical && previewEntries.length > 0) {
          const preview = await ratingApi.calculate(previewEntries)
          setPreviewResult(preview)
        } else {
          setPreviewResult(real)
        }
      } catch (err) {
        setCalcError(errorMessage(err))
      } finally {
        setCalculating(false)
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, 350)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(rows)])

  const addEntry = (hypothetical = false) => setRows((prev) => [...prev, newRow({ hypothetical })])
  const updateRow = (id: string, patch: Partial<EntryRow>) =>
    setRows((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)))
  const removeRow = (id: string) => setRows((prev) => prev.filter((r) => r.id !== id))

  const saveScenario = async () => {
    if (!savingName.trim()) return
    setSaving(true)
    try {
      await ratingApi.scenarios.create({ name: savingName.trim(), entries: toApiEntries(previewRows) })
      toast('Scenario saved.', 'success')
      setShowSave(false)
      setSavingName('')
      navigate('/scenarios')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  const displayResult = hasHypothetical ? previewResult : realResult
  const delta =
    hasHypothetical && realResult && previewResult && realResult.combined !== previewResult.combined
      ? { from: realResult.combined, to: previewResult.combined }
      : null

  const bilateralStep = displayResult?.steps.find((s) => stepKind(s) === 'bilateral')

  return (
    <div data-section="math" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Ratings math</p>
        <h1 className="vo-page-title">Combined ratings calculator</h1>
        <p className="vo-page-sub">
          Enter each disability's percentage per §4.25. The math (bilateral factor, rounding) is deterministic — the
          same formula VA uses.
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
        {/* Entries — kept neutral so the sky "hero" result panel reads as the payoff */}
        <Panel title="Disabilities">
          <div className="space-y-3 p-5">
            {rows.length === 0 && (
              <p className="rounded-control border border-dashed border-line px-3.5 py-3 text-sm text-muted">
                No disabilities yet — add your first one below.
              </p>
            )}
            {rows.map((row) => (
              <EntryRowView
                key={row.id}
                row={row}
                onChange={(patch) => updateRow(row.id, patch)}
                onRemove={() => removeRow(row.id)}
              />
            ))}
            <div className="flex flex-wrap gap-2 pt-1">
              <button onClick={() => addEntry(false)} className="vo-btn-secondary text-sm">
                <Plus size={14} /> Add disability
              </button>
              <button onClick={() => addEntry(true)} className="vo-btn-ghost text-sm text-muted">
                <FlaskConical size={14} /> Add what-if
              </button>
            </div>
          </div>
        </Panel>

        {/* Result — the hero panel of /calculator */}
        <Panel hue="sky" title="Combined result">
          <div className="space-y-4 p-5">
            {calcError && (
              <div role="alert" className="flex items-start gap-2 rounded-control border border-danger bg-danger-soft px-3.5 py-2.5 text-sm text-danger">
                <AlertCircle size={15} className="mt-0.5 shrink-0" /> {calcError}
              </div>
            )}
            {!displayResult ? (
              <p className="text-sm text-muted">Add at least one disability to see the combined result.</p>
            ) : (
              <>
                <div className="flex flex-wrap items-end gap-3">
                  <span className="vo-wordmark text-6xl font-extrabold leading-none tabular-nums">
                    {displayResult.combined}%
                  </span>
                  {calculating && <Spinner size={16} className="mb-2 text-muted" />}
                  {delta && <DeltaBadge from={delta.from} to={delta.to} />}
                </div>
                <p className="text-xs text-faint">
                  Raw (pre-rounding): {displayResult.raw}% · rounds to nearest 10 (ending-in-5 rounds up)
                </p>

                {bilateralStep && (
                  <div className="vo-accent rounded-card border border-[color-mix(in_oklab,var(--hue-cyan)_30%,transparent)] bg-h-cyan-soft p-4" style={{ '--hue': 'var(--hue-cyan)', '--hue-soft': 'var(--hue-cyan-soft)' } as CSSProperties}>
                    <div className="mb-1.5 flex items-center gap-2">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface text-h-cyan">
                        <GitMerge size={13} />
                      </span>
                      <h3 className="text-sm font-semibold" style={{ color: hueInk('cyan') }}>Bilateral factor applied</h3>
                      <span className="vo-chip border-[color-mix(in_oklab,var(--hue-cyan)_30%,transparent)] bg-surface text-h-cyan">38 CFR §4.26</span>
                    </div>
                    <p className="text-sm text-txt">{dictText(bilateralStep)}</p>
                  </div>
                )}

                {displayResult.smc_flags?.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="vo-label-micro flex items-center gap-1.5">
                      <Award size={12} /> Worth discussing with your provider
                    </h3>
                    {displayResult.smc_flags.map((flag, i) => {
                      const title = flagField(flag, 'title') ?? flagField(flag, 'label')
                      const text = flagField(flag, 'text') ?? flagField(flag, 'description') ?? dictText(flag)
                      const source = flagField(flag, 'source')
                      return (
                        <div
                          key={i}
                          className="vo-accent space-y-1.5 rounded-card border border-[color-mix(in_oklab,var(--hue-fuchsia)_25%,transparent)] bg-h-fuchsia-soft p-3.5"
                          style={{ '--hue': 'var(--hue-fuchsia)', '--hue-soft': 'var(--hue-fuchsia-soft)' } as CSSProperties}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            {title && <p className="text-sm font-semibold" style={{ color: hueInk('fuchsia') }}>{title}</p>}
                            {source && <span className="vo-chip shrink-0 border-[color-mix(in_oklab,var(--hue-fuchsia)_25%,transparent)] bg-surface text-micro text-h-fuchsia">{source}</span>}
                          </div>
                          <p className="text-sm text-txt">{text}</p>
                        </div>
                      )
                    })}
                  </div>
                )}

                <div>
                  <h3 className="vo-label-micro mb-2.5">Step by step</h3>
                  <ol className="space-y-0">
                    {displayResult.steps.map((step, i) => {
                      const kind = stepKind(step)
                      const value = stepValue(step)
                      const barColor = STEP_BAR_HUE[kind]
                      const isLast = i === displayResult.steps.length - 1
                      return (
                        <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
                          {!isLast && (
                            <span aria-hidden className="absolute left-[11px] top-6 bottom-0 w-px bg-line" />
                          )}
                          <span
                            className="relative z-10 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border text-micro font-bold tabular-nums"
                            style={{
                              borderColor: barColor ?? 'var(--border-2)',
                              color: barColor ?? 'var(--faint)',
                              background: barColor ? `color-mix(in srgb, ${barColor} 16%, transparent)` : 'var(--surface2)',
                            }}
                          >
                            {i + 1}
                          </span>
                          <div className="min-w-0 flex-1 pt-0.5">
                            <p className="text-sm text-txt">{dictText(step)}</p>
                            {value !== undefined && (
                              <div className="mt-1.5 flex items-center gap-2">
                                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface2">
                                  <div
                                    className="h-full rounded-full transition-all duration-500"
                                    style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: barColor ?? 'var(--brand)' }}
                                  />
                                </div>
                                <span className="w-10 shrink-0 text-right text-xs tabular-nums text-faint">{value}%</span>
                              </div>
                            )}
                          </div>
                        </li>
                      )
                    })}
                  </ol>
                </div>

                <div className="border-t border-line pt-4">
                  {!showSave ? (
                    <button onClick={() => setShowSave(true)} className="vo-btn-secondary w-full justify-center text-sm">
                      <Save size={14} /> Save as scenario
                    </button>
                  ) : (
                    <form
                      className="flex gap-2"
                      onSubmit={(e) => {
                        e.preventDefault()
                        void saveScenario()
                      }}
                    >
                      <input
                        autoFocus
                        className="vo-input"
                        placeholder="Scenario name"
                        value={savingName}
                        onChange={(e) => setSavingName(e.target.value)}
                      />
                      <button type="submit" disabled={saving || !savingName.trim()} className="vo-btn-primary h-10 w-10 shrink-0 p-0">
                        {saving ? <Spinner size={16} className="text-white" /> : <Save size={15} />}
                      </button>
                    </form>
                  )}
                </div>
              </>
            )}
          </div>
        </Panel>
      </div>
    </div>
  )
}

function EntryRowView({
  row,
  onChange,
  onRemove,
}: {
  row: EntryRow
  onChange: (patch: Partial<EntryRow>) => void
  onRemove: () => void
}) {
  return (
    <div
      className={
        row.hypothetical
          ? 'rounded-control border border-dashed border-[color-mix(in_oklab,var(--hue-sky)_40%,transparent)] bg-h-sky-soft/40 p-3.5'
          : 'rounded-control border border-line bg-surface2 p-3.5'
      }
    >
      <div className="flex flex-wrap items-center gap-2.5">
        {row.hypothetical && <HueBadge hue="sky">what-if</HueBadge>}
        <input
          className="vo-input min-w-[140px] flex-1"
          placeholder="Label (e.g. Left knee strain)"
          aria-label="Condition label"
          value={row.label}
          onChange={(e) => onChange({ label: e.target.value })}
        />
        <input
          type="number"
          min={0}
          max={100}
          step={10}
          className="vo-input w-24"
          aria-label="Disability rating percent"
          value={row.percent}
          onChange={(e) => onChange({ percent: Number(e.target.value) || 0 })}
        />
        <select
          className="vo-input w-32"
          aria-label="Body side"
          value={row.side}
          onChange={(e) => onChange({ side: e.target.value as EntryRow['side'] })}
        >
          <option value="">No side</option>
          <option value="left">Left</option>
          <option value="right">Right</option>
        </select>
        <input
          className="vo-input w-28"
          placeholder="Group"
          aria-label="Bilateral pairing group"
          title="Pairs entries for bilateral factor, e.g. 'knee'"
          value={row.group}
          onChange={(e) => onChange({ group: e.target.value })}
        />
        {row.hypothetical && (
          <label className="flex min-h-[2.5rem] items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={row.enabled} onChange={(e) => onChange({ enabled: e.target.checked })} className="vo-check" />
            Include
          </label>
        )}
        <button onClick={onRemove} className="vo-icon-btn vo-btn-ghost text-muted hover:text-danger" aria-label="Remove entry">
          <Trash2 size={15} />
        </button>
      </div>
    </div>
  )
}
