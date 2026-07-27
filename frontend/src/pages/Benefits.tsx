import { Gift, MapPinned } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { KbFreshnessNote } from '../components/KbFreshnessNote'
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { benefitsApi, profileApi } from '../lib/api'
import { formatDate } from '../lib/format'
import type { BenefitItem, BenefitsOut, Profile } from '../types'

const US_STATES = [
  'AL',
  'AK',
  'AZ',
  'AR',
  'CA',
  'CO',
  'CT',
  'DE',
  'FL',
  'GA',
  'HI',
  'ID',
  'IL',
  'IN',
  'IA',
  'KS',
  'KY',
  'LA',
  'ME',
  'MD',
  'MA',
  'MI',
  'MN',
  'MS',
  'MO',
  'MT',
  'NE',
  'NV',
  'NH',
  'NJ',
  'NM',
  'NY',
  'NC',
  'ND',
  'OH',
  'OK',
  'OR',
  'PA',
  'RI',
  'SC',
  'SD',
  'TN',
  'TX',
  'UT',
  'VT',
  'VA',
  'WA',
  'WV',
  'WI',
  'WY',
  'DC',
  'PR',
  'VI',
  'GU',
  'AS',
]

const CATEGORY_META: Record<
  keyof Pick<BenefitsOut, 'federal' | 'state' | 'commercial'>,
  { label: string; hue: 'sky' | 'emerald' | 'amber'; subtitle: string }
> = {
  federal: {
    label: 'Federal',
    hue: 'sky',
    subtitle: 'VA and other federal programs',
  },
  state: {
    label: 'State',
    hue: 'emerald',
    subtitle: 'South Carolina programs and examples',
  },
  commercial: {
    label: 'Commercial / national',
    hue: 'amber',
    subtitle: 'National passes and partner programs',
  },
}

const CATEGORY_ORDER = ['federal', 'state', 'commercial'] as const

function ratingLabel(minRating: number): string {
  return minRating === 0 ? 'Any rating' : `${minRating}%+`
}

function BenefitCard({ item }: { item: BenefitItem }) {
  return (
    <article className="rounded-control border border-line bg-surface2 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-txt">{item.name}</h3>
          <p className="mt-1 text-sm leading-relaxed text-muted">{item.description}</p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <span className="vo-chip border-line bg-surface text-muted">{ratingLabel(item.min_rating)}</span>
          {item.requires_pt && <span className="vo-chip border-[color-mix(in_oklab,var(--warn)_45%,transparent)] bg-warn-soft text-warn">Needs Permanent &amp; Total</span>}
          <span className="vo-chip border-line bg-surface text-muted">{item.states.length === 0 ? 'Nationwide' : item.states.join(', ')}</span>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="vo-chip border-line bg-surface text-muted">Confidence: {item.confidence}</span>
        {item.verified_as_of && (
          <span className="vo-chip border-line bg-surface text-muted">Verified {formatDate(item.verified_as_of)}</span>
        )}
        {item.effective_date && (
          <span className="vo-chip border-line bg-surface text-muted">Effective {formatDate(item.effective_date)}</span>
        )}
        <a
          href={item.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-semibold text-brand hover:text-brand-hover"
        >
          Source: {item.source_name}
        </a>
      </div>
    </article>
  )
}

export function Benefits() {
  const { data: profile } = useAsync<Profile>(() => profileApi.get().catch(() => ({
    service_periods: [],
    combat_service: false,
    exposures: {
      burn_pits: false,
      agent_orange: false,
      gulf_war: false,
      radiation: false,
      camp_lejeune: false,
      mustard_gas: false,
      pow: false,
      other: '',
      locations: [],
    },
    current_combined_rating: null,
    state: null,
    notes: null,
  })))
  const [rating, setRating] = useState('')
  const [state, setState] = useState('')
  const [filtersReady, setFiltersReady] = useState(false)
  const [benefitsRequested, setBenefitsRequested] = useState(false)

  useEffect(() => {
    if (!profile || filtersReady) return
    setRating(profile.current_combined_rating == null ? '' : String(profile.current_combined_rating))
    setState(profile.state ?? '')
    setFiltersReady(true)
    setBenefitsRequested(true)
  }, [profile, filtersReady])

  const ratingValue = rating.trim() === '' ? undefined : Number(rating)
  const stateValue = state.trim() === '' ? undefined : state.trim().toUpperCase()
  const {
    data: benefits,
    loading: benefitsLoading,
    error,
    reload,
  } = useAsync<BenefitsOut | null>(
    () => (filtersReady ? benefitsApi.get({ rating: ratingValue, state: stateValue }) : Promise.resolve(null)),
    [filtersReady, ratingValue, stateValue]
  )

  if (!profile || !filtersReady || (benefitsRequested && !benefits && !error)) {
    return (
      <div data-section="insight" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6">
        <div className="vo-section-band">
          <p className="vo-caption mb-1">Benefits directory</p>
          <h1 className="vo-page-title">What your rating unlocks</h1>
          <p className="vo-page-sub">
            A curated, source-linked directory of programs your rating may help you qualify for. Educational only.
          </p>
        </div>
        <LoadingBlock label="Loading your profile and benefits…" />
      </div>
    )
  }

  return (
    <div data-section="insight" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Benefits directory</p>
        <h1 className="vo-page-title">What your rating unlocks</h1>
        <p className="vo-page-sub">
          A curated, source-linked directory of programs your rating may help you qualify for. Educational only, and
          it never guarantees a benefit or files anything for you.
        </p>
      </div>
      <KbFreshnessNote hue="amber" />

      <Panel hue="amber" title="Important disclaimer" subtitle="Educational only - verify with every provider">
        <div className="space-y-3 p-5 text-sm leading-relaxed text-muted">
          <p>
            Veteran-Ops is self-help educational software. It does not promise outcomes, and every program here can
            change. Confirm current rules, deadlines, and documentation with the official provider before you rely on
            anything.
          </p>
          <p className="font-medium text-txt">
            Programs change - confirm your eligibility with each provider.
          </p>
          <p>
            Benefits directory verified as of {formatDate(benefits?.verified_as_of)}.
          </p>
        </div>
      </Panel>

      <Panel hue="sky" title="Your filters" subtitle="Prefilled from your profile, but editable">
        <div className="grid gap-3 p-5 sm:grid-cols-2">
          <label className="text-sm">
            <span className="vo-label">Current combined rating (%)</span>
            <input
              type="number"
              min={0}
              max={100}
              step={1}
              className="vo-input"
              value={rating}
              onChange={(e) => setRating(e.target.value)}
            />
          </label>
          <label className="text-sm">
            <span className="vo-label">State of residence</span>
            <select className="vo-input" value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">—</option>
              {US_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <div className="flex items-center gap-2 text-xs text-muted sm:col-span-2">
            <MapPinned size={14} className="shrink-0 text-h-sky" />
            <span>
              State programs only show up when your profile or selector matches that state. More states are coming.
            </span>
          </div>
        </div>
      </Panel>

      {benefitsLoading && (
        <div className="flex items-center gap-2 px-1 text-sm text-muted">
          <Spinner size={16} />
          Updating results...
        </div>
      )}

      {error ? (
        <ErrorBlock message={error} onRetry={reload} />
      ) : benefits && allEmpty(benefits) ? (
        <EmptyState
          hue="fuchsia"
          icon={<Gift size={20} />}
          title="No benefits matched this filter"
          description="Try a higher rating or a state profile with known state programs. The directory only shows curated, source-linked items."
          action={
            <Link to="/profile" className="vo-btn-primary text-sm">
              Update profile
            </Link>
          }
        />
      ) : (
        <div className="space-y-5">
          {CATEGORY_ORDER.map((key) => {
            const meta = CATEGORY_META[key]
            const items = benefits?.[key] ?? []
            return (
              <Panel key={key} hue={meta.hue} title={meta.label} subtitle={meta.subtitle}>
                {items.length === 0 ? (
                  <div className="p-5 text-sm text-muted">
                    No {meta.label.toLowerCase()} items matched this filter. More states are coming.
                  </div>
                ) : (
                  <div className="space-y-3 p-5">
                    {items.map((item) => (
                      <BenefitCard key={item.id} item={item} />
                    ))}
                  </div>
                )}
              </Panel>
            )
          })}
        </div>
      )}
    </div>
  )
}

function allEmpty(benefits: BenefitsOut): boolean {
  return benefits.federal.length === 0 && benefits.state.length === 0 && benefits.commercial.length === 0
}
