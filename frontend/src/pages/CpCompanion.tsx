import {
  AlertCircle,
  CheckCircle2,
  ClipboardList,
  HeartHandshake,
  Info,
  ListChecks,
  MessageSquareQuote,
  ShieldAlert,
  Stethoscope,
  XCircle,
} from 'lucide-react'
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorBlock, LoadingBlock } from '../components/ui'
import { errorMessage } from '../hooks/useAsync'
import { cpApi } from '../lib/api'
import { humanize } from '../lib/format'
import { CLAIM_TYPE_HUES, hueInk, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { CpCompanion as CpCompanionData, CpCondition } from '../types'

const SECTION_HUE: Hue = 'indigo'

export function CpCompanion() {
  const [conditions, setConditions] = useState<CpCondition[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const [companion, setCompanion] = useState<CpCompanionData | null>(null)
  const [loading, setLoading] = useState(false)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [retryNonce, setRetryNonce] = useState(0)

  useEffect(() => {
    cpApi
      .conditions()
      .then((rows) => {
        setConditions(rows)
        setListError(null)
        if (rows.length > 0) setSelectedId((prev) => prev ?? rows[0].id)
      })
      .catch((e) => setListError(errorMessage(e)))
  }, [])

  useEffect(() => {
    if (!selectedId) return
    setLoading(true)
    setDetailError(null)
    cpApi
      .get(selectedId)
      .then((c) => {
        setCompanion(c)
        setDetailError(null)
      })
      .catch((e) => setDetailError(errorMessage(e)))
      .finally(() => setLoading(false))
  }, [selectedId, retryNonce])

  return (
    <div data-section="guide" className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Guides</p>
        <h1 className="vo-page-title">C&amp;P exam companion</h1>
        <p className="vo-page-sub max-w-[72ch] leading-relaxed">
          A Compensation &amp; Pension (C&amp;P) exam is where a VA examiner evaluates your condition the way rating
          criteria require — often with a Disability Benefits Questionnaire (DBQ). This companion is a{' '}
          <strong className="font-semibold text-txt">VA-oriented medical prep tool inside Rating Raider</strong>:
          what to expect, the form the examiner likely uses, the §4 tiers being assessed, and how to describe symptoms
          honestly (worst day, frequency, function). It is not a diagnosis, not a doctor&apos;s opinion, and not
          advice to exaggerate. Your treatment records and private opinions still come from providers (or Glitter Mane
          as your health chart); this prep is for the claim exam path. The examiner&apos;s findings drive your rating.
        </p>
      </div>

      {listError ? (
        <ErrorBlock message={listError} onRetry={() => window.location.reload()} />
      ) : conditions === null ? (
        <LoadingBlock label="Loading your conditions…" />
      ) : conditions.length === 0 ? (
        <EmptyState
          hue={SECTION_HUE}
          icon={<Stethoscope size={20} />}
          title="No conditions to prepare for yet"
          description="Add the conditions you're claiming and Rating Raider will build a C&P exam prep guide for each one."
          action={
            <Link to="/conditions" className="text-sm font-semibold text-brand hover:text-brand-hover">
              Add a condition →
            </Link>
          }
        />
      ) : (
        <>
          <ConditionPicker conditions={conditions} selectedId={selectedId} onSelect={setSelectedId} />

          {loading ? (
            <LoadingBlock label="Preparing your exam guide…" />
          ) : detailError ? (
            <ErrorBlock message={detailError} onRetry={() => setRetryNonce((n) => n + 1)} />
          ) : companion ? (
            <CompanionBody companion={companion} />
          ) : null}
        </>
      )}
    </div>
  )
}

/** Chip-row picker — one hued chip per claimed condition, active chip filled. */
function ConditionPicker({
  conditions,
  selectedId,
  onSelect,
}: {
  conditions: CpCondition[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <div>
      <p className="mb-2 text-micro font-semibold uppercase tracking-wide text-faint">Choose a condition</p>
      <div className="flex flex-wrap gap-2">
        {conditions.map((c) => {
          const hue = CLAIM_TYPE_HUES[c.claim_type] ?? SECTION_HUE
          const active = c.id === selectedId
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => onSelect(c.id)}
              aria-pressed={active}
              className="inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors"
              style={
                active
                  ? {
                      borderColor: `color-mix(in srgb, ${hueVar(hue)} 45%, transparent)`,
                      background: `color-mix(in srgb, ${hueVar(hue)} 16%, var(--surface))`,
                      color: hueInk(hue),
                    }
                  : {
                      borderColor: 'var(--line)',
                      background: 'var(--surface2)',
                      color: 'var(--muted)',
                    }
              }
            >
              <span className="truncate">{c.name}</span>
              {c.diagnostic_code && <span className="font-mono text-xs opacity-70">DC {c.diagnostic_code}</span>}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function CompanionBody({ companion }: { companion: CpCompanionData }) {
  const { condition, dbq, what_to_expect, rating_criteria, how_to_describe, dos, donts, disclaimer } = companion
  const claimHue = CLAIM_TYPE_HUES[condition.claim_type] ?? SECTION_HUE

  return (
    <div className="space-y-5">
      {/* Condition header */}
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="vo-heading">{condition.name}</h2>
        <span
          className="rounded-full px-2.5 py-1 text-xs font-medium"
          style={{ background: `color-mix(in srgb, ${hueVar(claimHue)} 14%, var(--surface))`, color: hueInk(claimHue) }}
        >
          {humanize(condition.claim_type)}
        </span>
        {condition.diagnostic_code && (
          <span className="font-mono text-xs text-faint">Diagnostic code {condition.diagnostic_code}</span>
        )}
      </div>

      {/* What to expect */}
      <BulletPanel hue={SECTION_HUE} icon={<Info size={17} />} title="What to expect" items={what_to_expect} />

      {/* DBQ (the examiner's form) */}
      {dbq && (
        <Panel hue="violet" icon={<ClipboardList size={17} />} title="The examiner's questionnaire">
          <p className="text-sm font-medium text-txt">{dbq}</p>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">
            This is the Disability Benefits Questionnaire (DBQ) the examiner most likely works from for this condition.
            You don't fill it out — the examiner does — but knowing which form it is tells you what they'll be looking
            for. You can read a blank copy on VA.gov to see the questions in advance.
          </p>
        </Panel>
      )}

      {/* Rating criteria tiers */}
      {rating_criteria.length > 0 && (
        <Panel hue="sky" icon={<ListChecks size={17} />} title="What's being assessed — the rating criteria">
          <p className="mb-3 text-sm leading-relaxed text-muted">
            These are the §4 rating tiers for this diagnostic code — the yardstick the examiner's findings are measured
            against. Seeing them helps you describe the symptoms that actually matter. It does not mean you'll be rated
            at any particular level.
          </p>
          <ol className="space-y-2.5">
            {rating_criteria.map((tier, i) => (
              <li key={`${tier.percent}-${i}`} className="flex gap-3 rounded-xl border border-line bg-surface2/60 p-3">
                <span
                  className="flex h-9 shrink-0 items-center justify-center rounded-lg px-2.5 text-sm font-bold tabular-nums"
                  style={{ background: 'var(--hue-sky-soft)', color: hueInk('sky') }}
                >
                  {tier.percent}%
                </span>
                <div className="min-w-0 space-y-1 self-center">
                  {tier.criteria.map((phrase, j) => (
                    <p key={j} className="text-sm leading-relaxed text-txt">
                      {phrase}
                    </p>
                  ))}
                </div>
              </li>
            ))}
          </ol>
        </Panel>
      )}

      {/* How to describe your symptoms */}
      <BulletPanel
        hue="teal"
        icon={<MessageSquareQuote size={17} />}
        title="How to describe your symptoms"
        intro="Answer honestly — this is the single most important thing. The examiner is documenting how the condition affects you over time, not just at this moment."
        items={how_to_describe}
      />

      {/* Dos / Don'ts side-by-side */}
      <div className="grid gap-4 md:grid-cols-2">
        <ListCard
          tone="do"
          icon={<CheckCircle2 size={17} />}
          title="Do"
          items={dos}
          bullet={<CheckCircle2 size={14} className="mt-0.5 shrink-0" style={{ color: hueVar('emerald') }} />}
        />
        <ListCard
          tone="dont"
          icon={<ShieldAlert size={17} />}
          title="Don't"
          items={donts}
          bullet={<XCircle size={14} className="mt-0.5 shrink-0" style={{ color: hueVar('amber') }} />}
        />
      </div>

      {/* VSO help */}
      <div className="vo-card vo-accent flex items-start gap-3.5 p-5" style={hueStyle('orange') as CSSProperties}>
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: 'var(--hue-orange-soft)', color: 'var(--hue-orange)' }}
        >
          <HeartHandshake size={20} />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-txt">A VSO can help you prepare — for free</h3>
          <p className="mt-1 max-w-[70ch] text-sm leading-relaxed text-muted">
            A VA-accredited Veterans Service Officer can walk you through what to expect at your C&amp;P exam at no cost.
            Rating Raider organizes your information; a VSO can advise and act on your behalf.
          </p>
          <a
            href="https://www.va.gov/get-help-from-accredited-representative/"
            target="_blank"
            rel="noreferrer"
            className="mt-2.5 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
          >
            Find a VSO →
          </a>
        </div>
      </div>

      {/* Disclaimer */}
      <p className="flex items-start gap-2 text-xs leading-relaxed text-faint">
        <AlertCircle size={13} className="mt-0.5 shrink-0" />
        <span>{disclaimer}</span>
      </p>
    </div>
  )
}

/** Titled panel shell with a hued icon-chip header. */
function Panel({
  hue,
  icon,
  title,
  children,
}: {
  hue: Hue
  icon: ReactNode
  title: string
  children: ReactNode
}) {
  return (
    <section className="vo-panel vo-accent overflow-hidden" style={hueStyle(hue) as CSSProperties}>
      <header className="flex items-center gap-2.5 border-b border-line px-5 py-3.5">
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
          style={{ background: `color-mix(in srgb, ${hueVar(hue)} 14%, var(--surface))`, color: hueInk(hue) }}
        >
          {icon}
        </span>
        <h3 className="vo-heading">{title}</h3>
      </header>
      <div className="p-5">{children}</div>
    </section>
  )
}

/** Panel of educational bullets with hued dot markers. */
function BulletPanel({
  hue,
  icon,
  title,
  intro,
  items,
}: {
  hue: Hue
  icon: ReactNode
  title: string
  intro?: string
  items: string[]
}) {
  return (
    <Panel hue={hue} icon={icon} title={title}>
      {intro && <p className="mb-3 text-sm leading-relaxed text-muted">{intro}</p>}
      <ul className="space-y-2.5">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2.5 text-sm leading-relaxed text-txt">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: hueVar(hue) }} aria-hidden />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

/** Do / Don't list — Don't is a calm caution (amber), not an alarm. */
function ListCard({
  tone,
  icon,
  title,
  items,
  bullet,
}: {
  tone: 'do' | 'dont'
  icon: ReactNode
  title: string
  items: string[]
  bullet: ReactNode
}) {
  const hue: Hue = tone === 'do' ? 'emerald' : 'amber'
  return (
    <section
      className="vo-panel overflow-hidden"
      style={
        {
          ...hueStyle(hue),
          borderColor: `color-mix(in srgb, ${hueVar(hue)} 28%, var(--line))`,
        } as CSSProperties
      }
    >
      <header
        className="flex items-center gap-2 border-b px-5 py-3.5"
        style={{ borderColor: `color-mix(in srgb, ${hueVar(hue)} 22%, var(--line))` }}
      >
        <span style={{ color: hueInk(hue) }}>{icon}</span>
        <h3 className="vo-heading" style={{ color: hueInk(hue) }}>
          {title}
        </h3>
      </header>
      <ul className="space-y-2.5 p-5">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2 text-sm leading-relaxed text-txt">
            {bullet}
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
