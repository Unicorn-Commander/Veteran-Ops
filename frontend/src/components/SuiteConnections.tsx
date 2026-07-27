/**
 * Suite connection strip — Glitter Mane (health chart) + VA.gov (when enabled).
 * Makes the optional bridge discoverable: GM is source-of-truth for living health
 * data; Rating Raider imports with provenance. No dual-master auto-sync.
 */
import {
  ArrowRight,
  HeartPulse,
  Landmark,
  RefreshCw,
  Sparkles,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { useAsync } from '../hooks/useAsync'
import { glitterApi, vaApi } from '../lib/api'
import { hueInk, hueSoftVar, hueStyle, type Hue } from '../lib/hues'
import { Spinner } from './ui'
import type { CSSProperties, ReactNode } from 'react'

function Dot({ tone }: { tone: 'neutral' | 'warning' | 'success' }) {
  const color = tone === 'success' ? 'var(--success)' : tone === 'warning' ? 'var(--warning)' : 'var(--faint)'
  return (
    <span
      aria-hidden
      className="inline-block h-2 w-2 shrink-0 rounded-full"
      style={{ background: color, boxShadow: tone === 'success' ? `0 0 6px ${color}` : 'none' }}
    />
  )
}

export function SuiteConnections({
  compact = false,
  className,
}: {
  compact?: boolean
  className?: string
}) {
  const {
    data: gm,
    loading: gmLoading,
    error: gmError,
    reload: reloadGm,
  } = useAsync(() => glitterApi.status().catch(() => null), [])
  const {
    data: va,
    loading: vaLoading,
    reload: reloadVa,
  } = useAsync(() => vaApi.status().catch(() => null), [])

  const gmTone: 'neutral' | 'warning' | 'success' =
    gmLoading || gmError || !gm?.enabled ? 'neutral' : gm.reachable ? 'success' : 'warning'
  const vaEnabled = va?.enabled === true
  const vaConnected = vaEnabled && (va?.connected === true || (va?.connections?.length ?? 0) > 0)
  const vaTone: 'neutral' | 'warning' | 'success' = !vaEnabled
    ? 'neutral'
    : va?.needs_reconnect
      ? 'warning'
      : vaConnected
        ? 'success'
        : 'warning'

  if (compact) {
    return (
      <div
        className={`vo-card flex flex-wrap items-center gap-3 px-4 py-3 ${className ?? ''}`}
        role="region"
        aria-label="Suite connections"
      >
        <span className="flex items-center gap-1.5 text-xs text-muted">
          <Dot tone={gmTone} />
          <HeartPulse size={13} className="text-h-violet" aria-hidden />
          Glitter Mane{' '}
          <span className="font-semibold text-txt">
            {gmLoading ? '…' : !gm?.enabled ? 'not configured' : gm.reachable ? 'connected' : 'unreachable'}
          </span>
        </span>
        <span className="text-faint" aria-hidden>
          ·
        </span>
        <span className="flex items-center gap-1.5 text-xs text-muted">
          <Dot tone={vaTone} />
          <Landmark size={13} className="text-h-sky" aria-hidden />
          VA.gov{' '}
          <span className="font-semibold text-txt">
            {vaLoading ? '…' : !vaEnabled ? 'not enabled' : vaConnected ? 'connected' : 'not linked'}
          </span>
        </span>
        <Link to="/settings" className="ml-auto text-xs font-semibold text-brand hover:underline">
          Manage connections
        </Link>
      </div>
    )
  }

  return (
    <div
      className={`vo-card vo-accent space-y-3 p-4 sm:p-5 ${className ?? ''}`}
      style={hueStyle('violet') as CSSProperties}
      role="region"
      aria-label="Health chart and VA connections"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-micro font-bold uppercase tracking-wide" style={{ color: hueInk('violet') }}>
            Suite connections
          </p>
          <h2 className="text-base font-bold text-txt">Your health chart & VA data</h2>
          <p className="mt-0.5 max-w-xl text-sm text-muted">
            Same medical records often belong in both places: Glitter Mane as your living health chart, Rating Raider
            as claim evidence and C&amp;P prep. Import is confirm-first — nothing dual-writes automatically. VA-style
            exam prep lives in Rating Raider (C&amp;P companion / Ask Raider); treating clinicians still write real
            opinions.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            reloadGm()
            reloadVa()
          }}
          className="vo-icon-btn vo-btn-ghost"
          aria-label="Refresh connection status"
        >
          <RefreshCw size={15} />
        </button>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        <ConnectionTile
          hue="violet"
          icon={HeartPulse}
          title="Glitter Mane"
          subtitle="Personal health chart"
          tone={gmTone}
          status={
            gmLoading ? (
              <span className="inline-flex items-center gap-1">
                <Spinner size={12} /> Checking…
              </span>
            ) : !gm?.enabled ? (
              'Bridge not configured'
            ) : gm.reachable ? (
              'Connected — same UC account'
            ) : (
              `Configured but unreachable${gm.detail ? ` — ${gm.detail}` : ''}`
            )
          }
          actions={
            gm?.enabled && gm.reachable ? (
              <>
                <Link to="/conditions?import=glitter" className="vo-btn-secondary text-xs">
                  Import from Glitter Mane
                </Link>
                <Link to="/symptom-log" className="vo-btn-ghost text-xs">
                  Symptom log
                </Link>
              </>
            ) : (
              <Link to="/settings" className="vo-btn-ghost text-xs">
                Settings
              </Link>
            )
          }
        />
        <ConnectionTile
          hue="sky"
          icon={Landmark}
          title="VA.gov"
          subtitle="Official VA records"
          tone={vaTone}
          status={
            vaLoading ? (
              <span className="inline-flex items-center gap-1">
                <Spinner size={12} /> Checking…
              </span>
            ) : !vaEnabled ? (
              'Not enabled on this host'
            ) : vaConnected ? (
              va.needs_reconnect ? 'Needs reconnect' : 'Linked — you control consent'
            ) : (
              'Available — connect in Settings'
            )
          }
          actions={
            <Link to="/settings" className="vo-btn-secondary text-xs">
              {vaEnabled ? (vaConnected ? 'Manage VA' : 'Connect VA') : 'See Settings'}
            </Link>
          }
        />
      </div>
    </div>
  )
}

function ConnectionTile({
  hue,
  icon: Icon,
  title,
  subtitle,
  tone,
  status,
  actions,
}: {
  hue: Hue
  icon: typeof HeartPulse
  title: string
  subtitle: string
  tone: 'neutral' | 'warning' | 'success'
  status: ReactNode
  actions: ReactNode
}) {
  return (
    <div className="rounded-control border border-line bg-surface2 p-3.5">
      <div className="flex items-start gap-2.5">
        <span
          aria-hidden
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
        >
          <Icon size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <Dot tone={tone} />
            <p className="text-sm font-semibold text-txt">{title}</p>
          </div>
          <p className="text-xs text-faint">{subtitle}</p>
          <p className="mt-1 text-xs leading-relaxed text-muted">{status}</p>
          <div className="mt-2 flex flex-wrap gap-1.5">{actions}</div>
        </div>
      </div>
    </div>
  )
}

/**
 * After analysis (or anytime): if GM is reachable and has conditions not yet
 * imported, offer a confirm-first import path. Does not auto-write.
 */
export function GlitterImportOpportunity({
  onImported,
  className,
}: {
  onImported?: () => void
  className?: string
}) {
  const { data: status } = useAsync(() => glitterApi.status().catch(() => null), [])
  const ready = !!status?.enabled && !!status?.reachable
  const { data: gmConditions, loading } = useAsync(
    () => (ready ? glitterApi.conditions().catch(() => []) : Promise.resolve([])),
    [ready],
  )
  const count = gmConditions?.length ?? 0

  if (!ready || loading) return null
  if (count === 0) {
    return (
      <div
        className={`vo-card flex flex-wrap items-center gap-3 border border-line px-4 py-3 ${className ?? ''}`}
        role="status"
      >
        <HeartPulse size={16} className="shrink-0 text-h-violet" aria-hidden />
        <p className="min-w-0 flex-1 text-sm text-muted">
          Glitter Mane is connected. No conditions there yet — log health in GM, then import into your claim here.
        </p>
        <a
          href="https://glittermane.magicunicorn.dev"
          target="_blank"
          rel="noreferrer"
          className="text-xs font-semibold text-brand hover:underline"
        >
          Open Glitter Mane
        </a>
      </div>
    )
  }

  return (
    <div
      className={`vo-card vo-accent flex flex-wrap items-start gap-3 p-4 sm:p-5 ${className ?? ''}`}
      style={hueStyle('teal') as CSSProperties}
      role="region"
      aria-label="Import from Glitter Mane"
    >
      <span
        aria-hidden
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar('teal'), color: hueInk('teal') }}
      >
        <Sparkles size={18} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-micro font-bold uppercase tracking-wide" style={{ color: hueInk('teal') }}>
          Health chart → claim (confirm first)
        </p>
        <h2 className="text-base font-bold text-txt">
          {count} condition{count === 1 ? '' : 's'} in Glitter Mane
        </h2>
        <p className="mt-0.5 text-sm leading-relaxed text-muted">
          Import creates claim-side copies tagged from GM — your health chart stays the source of truth. You pick what
          to bring over; nothing dual-writes in the background.
        </p>
      </div>
      <Link
        to="/conditions?import=glitter"
        className="vo-btn-primary min-h-11 shrink-0 text-sm"
        onClick={onImported}
      >
        Review & import <ArrowRight size={15} />
      </Link>
    </div>
  )
}
