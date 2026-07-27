import { AlertCircle, CheckCircle2, Gauge } from 'lucide-react'
import { useEffect, useState, type CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorBlock, HueBadge, LoadingBlock } from '../components/ui'
import { errorMessage } from '../hooks/useAsync'
import { readinessApi } from '../lib/api'
import { humanize } from '../lib/format'
import { hueInk, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { ReadinessBand, ReadinessCondition, ReadinessResult } from '../types'

/** Band → hue, shared by the overall ring and the per-condition rows. */
const BAND_HUES: Record<ReadinessBand, Hue> = {
  early: 'rose',
  building: 'amber',
  strong: 'sky',
  complete: 'emerald',
}
const BAND_LABELS: Record<ReadinessBand, string> = {
  early: 'Early',
  building: 'Building',
  strong: 'Strong',
  complete: 'Complete',
}

export function Readiness() {
  const [data, setData] = useState<ReadinessResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    readinessApi
      .get()
      .then((r) => {
        setData(r)
        setError(null)
      })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    void load()
  }, [])

  return (
    <div data-section="claim" className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Claim tools</p>
        <h1 className="vo-page-title">Evidence readiness</h1>
        <p className="vo-page-sub">
          A single score per claim showing how much of the core service-connection evidence you've
          identified — built from the same gap analysis you see on each condition. It's a preparation
          gauge, not a prediction of the VA's decision.
        </p>
      </div>

      {loading ? (
        <LoadingBlock label="Scoring your claims…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={() => void load()} />
      ) : !data || data.conditions.length === 0 ? (
        <EmptyState
          hue="emerald"
          icon={<Gauge size={20} />}
          title="No conditions to score yet"
          description="Populate your case from records or add conditions by hand — then Rating Raider scores how ready each one's evidence is and shows what's missing."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Link to="/build-case" className="vo-btn-primary text-sm">
                Populate case from records
              </Link>
              <Link to="/conditions" className="vo-btn-secondary text-sm">
                Add a condition
              </Link>
            </div>
          }
        />
      ) : (
        <>
          <OverallRing overall={data.overall} />
          <div className="space-y-3">
            {data.conditions.map((c) => (
              <ConditionRow key={c.condition_id} c={c} />
            ))}
          </div>
          <p className="flex items-start gap-2 text-xs text-faint">
            <AlertCircle size={13} className="mt-0.5 shrink-0" />
            <span>{data.disclaimer}</span>
          </p>
        </>
      )}
    </div>
  )
}

function OverallRing({ overall }: { overall: ReadinessResult['overall'] }) {
  const hue = BAND_HUES[overall.band]
  const size = 132
  const stroke = 12
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const dash = (overall.score / 100) * circ

  return (
    <div className="vo-panel vo-accent flex flex-col items-center gap-5 p-6 sm:flex-row sm:items-center" style={hueStyle(hue) as CSSProperties}>
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90">
          <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth={stroke} />
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={hueVar(hue)}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circ}`}
            style={{ transition: 'stroke-dasharray 700ms cubic-bezier(0.16,1,0.3,1)' }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-bold tabular-nums" style={{ color: hueInk(hue) }}>
            {overall.score}
            <span className="text-lg">%</span>
          </span>
          <span className="text-micro font-semibold uppercase tracking-wider" style={{ color: hueVar(hue) }}>
            {BAND_LABELS[overall.band]}
          </span>
        </div>
      </div>
      <div className="min-w-0 text-center sm:text-left">
        <h2 className="text-lg font-semibold text-txt">Overall readiness</h2>
        <p className="mt-1 text-sm text-muted">{overall.label}</p>
        <p className="mt-2 text-xs text-faint">
          Averaged across {overall.conditions_scored} claim{overall.conditions_scored === 1 ? '' : 's'}.
        </p>
      </div>
    </div>
  )
}

function ConditionRow({ c }: { c: ReadinessCondition }) {
  const hue = BAND_HUES[c.band]
  return (
    <div className="vo-panel vo-accent overflow-hidden" style={hueStyle(hue) as CSSProperties}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link to={`/conditions/${c.condition_id}`} className="truncate text-sm font-semibold text-txt hover:text-brand">
              {c.name}
            </Link>
            <HueBadge hue={hue}>{BAND_LABELS[c.band]}</HueBadge>
            <span className="text-xs text-faint">{humanize(c.claim_type)}</span>
          </div>
          <p className="mt-1 text-xs text-faint">
            {c.satisfied} of {c.total} core elements in place
          </p>
        </div>
        <span className="shrink-0 text-2xl font-bold tabular-nums" style={{ color: hueInk(hue) }}>
          {c.score}%
        </span>
      </div>
      <div className="h-1.5 w-full bg-surface2">
        <div
          className="h-full transition-[width] duration-700"
          style={{ width: `${c.score}%`, background: hueVar(hue) }}
        />
      </div>
      {c.missing.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5 px-5 py-3">
          <span className="text-micro font-semibold uppercase tracking-wide text-faint">Still needed:</span>
          {c.missing.map((m) => (
            <span
              key={m}
              className="inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium"
              style={{
                borderColor: `color-mix(in srgb, ${hueVar('amber')} 40%, transparent)`,
                background: 'var(--hue-amber-soft)',
                color: hueInk('amber'),
              }}
            >
              {m}
            </span>
          ))}
        </div>
      ) : (
        <p className="flex items-center gap-1.5 px-5 py-3 text-xs font-medium text-success">
          <CheckCircle2 size={13} /> All core evidence identified — review with a VSO before filing.
        </p>
      )}
    </div>
  )
}
