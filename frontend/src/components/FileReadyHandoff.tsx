import {
  ArrowRight,
  CheckCircle2,
  Circle,
  ExternalLink,
  FileCheck,
  ShieldCheck,
} from 'lucide-react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { useAsync } from '../hooks/useAsync'
import { analysisApi } from '../lib/api'
import { hueInk, hueSoftVar, hueStyle, type Hue } from '../lib/hues'
import type { FileReadiness, FileReadinessHandoff as HandoffLinksData } from '../types'
import { ErrorBlock, LoadingBlock, Panel } from './ui'

const HUE: Hue = 'emerald'

/** Fallbacks if an older backend omits handoff — still pro-se only. */
const FALLBACK_HANDOFF: HandoffLinksData = {
  va_gov_claim_url: 'https://www.va.gov/disability/file-disability-claim-form-21-526ez/',
  vso_url: 'https://www.va.gov/get-help-from-accredited-representative/',
  itf_url: 'https://www.va.gov/disability/how-to-file-claim/intent-to-file/',
  form526_route: '/application',
  packet_note:
    'We prepare the packet; you or a free VA-accredited VSO submit. Rating Raider never e-files for you.',
}

/**
 * File-ready handoff panel — score, remaining needs, and the paths the veteran
 * (or a free VSO) uses to actually submit. Rating Raider never files.
 */
export function FileReadyHandoff({
  compact = false,
  className,
}: {
  /** Slimmer strip for dashboard / tight layouts. */
  compact?: boolean
  className?: string
}) {
  const { data, loading, error, reload } = useAsync(() => analysisApi.fileReadiness())

  if (loading) {
    return compact ? null : <LoadingBlock label="Checking whether you're ready to prepare filing…" />
  }
  if (error) {
    return compact ? null : (
      <ErrorBlock message={error} onRetry={reload} />
    )
  }
  if (!data) return null

  return <FileReadyHandoffBody data={data} compact={compact} className={className} />
}

function FileReadyHandoffBody({
  data,
  compact,
  className,
}: {
  data: FileReadiness
  compact: boolean
  className?: string
}) {
  const handoff = data.handoff ?? FALLBACK_HANDOFF
  const score =
    typeof data.file_ready_score === 'number'
      ? data.file_ready_score
      : data.total_conditions > 0
        ? Math.round((data.ready_conditions / data.total_conditions) * 100)
        : 0
  const blockers =
    data.blockers?.length > 0
      ? data.blockers
      : (data.still_needed ?? []).map((n) => ({
          label: n.label,
          route: n.route,
          how: n.how,
        }))

  if (compact) {
    if (!data.has_conditions) return null
    return (
      <div
        className={`vo-card vo-accent flex flex-wrap items-center gap-3 p-4 sm:p-5 ${className ?? ''}`}
        style={hueStyle(HUE) as CSSProperties}
        role="region"
        aria-label="File-ready handoff"
      >
        <span
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}
        >
          {data.all_ready ? <CheckCircle2 size={20} /> : <FileCheck size={20} />}
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-txt">
            {data.all_ready
              ? "You're ready to prepare filing"
              : `${data.ready_conditions} of ${data.total_conditions} conditions ready · ${score}%`}
          </p>
          <p className="text-sm text-muted">
            {data.all_ready
              ? handoff.packet_note
              : blockers[0]
                ? `Still needed: ${blockers[0].label}`
                : 'Close the remaining evidence gaps, then prepare filing.'}
          </p>
        </div>
        <Link
          to={data.all_ready ? handoff.form526_route || '/application' : '/evidence'}
          className="vo-btn-primary shrink-0 text-sm"
        >
          {data.all_ready ? 'Prepare application' : 'Review gaps'} <ArrowRight size={14} />
        </Link>
      </div>
    )
  }

  if (!data.has_conditions) {
    return (
      <Panel
        hue="amber"
        className={className}
        title="File readiness"
        subtitle="Add the conditions you're claiming to see what's still needed before you file"
      >
        <div className="space-y-3 p-5">
          <p className="text-sm leading-relaxed text-muted">
            Rating Raider scores readiness from the evidence you&apos;ve identified — not a prediction of VA&apos;s
            decision.
          </p>
          <Link to="/conditions" className="vo-btn-primary inline-flex text-sm">
            Add your conditions <ArrowRight size={14} />
          </Link>
          <HandoffLinksRow handoff={handoff} />
          <LegalLine note={handoff.packet_note} disclaimer={data.disclaimer} />
        </div>
      </Panel>
    )
  }

  if (data.all_ready) {
    return (
      <Panel
        hue={HUE}
        className={className}
        title="You're ready to prepare filing"
        subtitle={`${data.ready_conditions} of ${data.total_conditions} condition${data.total_conditions === 1 ? '' : 's'} · file-ready score ${score}%`}
      >
        <div className="space-y-4 p-5">
          <p className="text-sm leading-relaxed text-muted">
            Your core evidence is identified for every condition. Review the assembled application, print or download
            what you need, then submit through VA.gov or hand the packet to a free accredited VSO.
          </p>
          <HandoffLinksRow handoff={handoff} primary />
          <LegalLine note={handoff.packet_note} disclaimer={data.disclaimer} />
        </div>
      </Panel>
    )
  }

  return (
    <Panel
      hue="amber"
      className={className}
      title="File readiness"
      subtitle={`${data.ready_conditions} of ${data.total_conditions} ready · ${score}% · ${blockers.length} item${blockers.length === 1 ? '' : 's'} still needed`}
    >
      <div className="space-y-4 p-5">
        {blockers.length > 0 && (
          <ul className="space-y-2">
            {blockers.slice(0, 6).map((need, i) => (
              <li key={i}>
                <Link
                  to={need.route}
                  className="vo-card vo-accent vo-card-hover flex items-start gap-3 p-3"
                  style={hueStyle('amber') as CSSProperties}
                >
                  <span
                    aria-hidden
                    className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
                    style={{ background: hueSoftVar('amber'), color: hueInk('amber') }}
                  >
                    <Circle size={13} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold leading-snug text-txt">{need.label}</span>
                    <span className="mt-0.5 block text-sm text-muted">{need.how}</span>
                  </span>
                  <ArrowRight size={15} className="mt-1 shrink-0 text-muted" />
                </Link>
              </li>
            ))}
          </ul>
        )}
        <HandoffLinksRow handoff={handoff} />
        <LegalLine note={handoff.packet_note} disclaimer={data.disclaimer} />
      </div>
    </Panel>
  )
}

function HandoffLinksRow({
  handoff,
  primary = false,
}: {
  handoff: HandoffLinksData
  primary?: boolean
}) {
  return (
    <div className="flex flex-wrap gap-2">
      <Link
        to={handoff.form526_route || '/application'}
        className={primary ? 'vo-btn-primary text-sm' : 'vo-btn-secondary text-sm'}
      >
        <FileCheck size={14} /> Application (21-526EZ)
      </Link>
      <Link to="/itf" className="vo-btn-secondary text-sm">
        Intent to File
      </Link>
      <Link to="/filing" className="vo-btn-secondary text-sm">
        Filing guide
      </Link>
      <a
        href={handoff.va_gov_claim_url}
        target="_blank"
        rel="noreferrer"
        className="vo-btn-secondary text-sm"
      >
        VA.gov disability claim <ExternalLink size={13} />
      </a>
      <a href={handoff.vso_url} target="_blank" rel="noreferrer" className="vo-btn-secondary text-sm">
        Find accredited rep <ExternalLink size={13} />
      </a>
      {handoff.itf_url && (
        <a href={handoff.itf_url} target="_blank" rel="noreferrer" className="vo-btn-secondary text-sm">
          VA.gov Intent to File <ExternalLink size={13} />
        </a>
      )}
    </div>
  )
}

function LegalLine({ note, disclaimer }: { note: string; disclaimer?: string }) {
  return (
    <div
      className="flex items-start gap-2.5 rounded-control border border-line bg-surface2 px-3.5 py-3 text-xs leading-relaxed text-muted"
      role="note"
    >
      <ShieldCheck size={15} className="mt-0.5 shrink-0 text-h-emerald" aria-hidden />
      <p>
        <strong className="font-semibold text-txt">We never file for you.</strong> {note}
        {disclaimer ? ` ${disclaimer}` : ''}
      </p>
    </div>
  )
}
