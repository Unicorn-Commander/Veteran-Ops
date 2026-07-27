import { AlertTriangle, ShieldCheck } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useAsync } from '../hooks/useAsync'
import { metaApi } from '../lib/api'
import { formatDate } from '../lib/format'
import { hueStyle, type Hue } from '../lib/hues'
import { cx } from './ui'

export function KbFreshnessNote({
  hue = 'sky',
  fallbackVerifiedAsOf,
  className,
}: {
  hue?: Hue
  fallbackVerifiedAsOf?: string | null
  className?: string
}) {
  const { data } = useAsync(() => metaApi.get().catch(() => null), [])
  const verifiedAsOf = data?.kb_verified_as_of ?? fallbackVerifiedAsOf ?? null
  if (!verifiedAsOf) return null
  const stale = data?.kb_stale === true
  const unknown = data?.kb_status === 'unknown'
  const Icon = stale || unknown ? AlertTriangle : ShieldCheck
  return (
    <div
      className={cx(
        'vo-accent rounded-control border border-line bg-surface2 px-3.5 py-3 text-sm',
        className
      )}
      style={hueStyle(stale || unknown ? 'amber' : hue) as CSSProperties}
    >
      <div className="flex items-start gap-2.5">
        <Icon size={16} className={cx('mt-0.5 shrink-0', stale || unknown ? 'text-warn' : 'text-muted')} />
        <div className="min-w-0">
          <p className="font-medium text-txt">Criteria verified as of {formatDate(verifiedAsOf)}.</p>
          {stale && (
            <p className="mt-1 text-xs leading-relaxed text-muted">
              VA regulations may have changed since this date. Verify current criteria at eCFR / VA.gov.
            </p>
          )}
          {unknown && (
            <p className="mt-1 text-xs leading-relaxed text-muted">
              Current eCFR freshness could not be confirmed. Treat criteria as unverified until the check succeeds.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
