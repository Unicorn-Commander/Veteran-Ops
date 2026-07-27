import {
  ArrowUpRight,
  CalendarClock,
  CheckCircle2,
  FileText,
  Hourglass,
  Info,
  Landmark,
  ScanText,
  Scale,
  ShieldCheck,
  Sigma,
  Users,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { EmptyState, ErrorBlock, HueBadge, LoadingBlock, Spinner, cx } from '../components/ui'
import { CreditLimitNotice } from '../components/CreditLimitNotice'
import { errorMessage } from '../hooks/useAsync'
import { ApiError, decoderApi } from '../lib/api'
import { formatDate, formatDateTime, humanize } from '../lib/format'
import { hueInk, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type {
  DecodeAppealWindow,
  DecodeCombinedCheck,
  DecodeDecision,
  DecodeOption,
  DecodeResult,
  DocumentItem,
} from '../types'

// /decode — WAVE 4 decision-letter decoder. Turns an already-uploaded VA rating
// decision / decision letter into plain English + AMA appeal lanes. Reads the
// LOCKED DecodeOut shape (WAVE4-DECODER-SPEC). Legal lane, load-bearing: this is
// EDUCATIONAL only — the VA's official combined evaluation on the letter CONTROLS,
// our recompute is a cross-check, and every next-step surfaces a free VSO. Nothing
// here files or sends anything on the veteran's behalf.

/** Outcome → identity hue (spec: granted=emerald, denied=rose, deferred=amber). */
const OUTCOME_HUES: Record<string, Hue> = {
  granted: 'emerald',
  denied: 'rose',
  deferred: 'amber',
}
const outcomeHue = (d: DecodeDecision): Hue =>
  (d.decision && OUTCOME_HUES[d.decision]) || 'indigo'

/** Human labels for the three service-connection elements a denial can miss. */
const MISSING_LABELS: Record<string, string> = {
  current_disability: 'Current diagnosis',
  in_service_event: 'In-service event',
  nexus: 'Medical nexus',
}
const missingLabel = (k: string): string => MISSING_LABELS[k] ?? humanize(k)

/** AMA lane → hue. supplemental_claim leads (emerald) when there are denials. */
const OPTION_HUES: Record<string, Hue> = {
  supplemental_claim: 'emerald',
  higher_level_review: 'sky',
  board_appeal: 'indigo',
}
const OPTION_ICONS: Record<string, typeof Scale> = {
  supplemental_claim: FileText,
  higher_level_review: Scale,
  board_appeal: Landmark,
}

/** A decodable letter's identity hue in the selector. */
const letterHue = (d: DocumentItem): Hue => (d.doc_type === 'rating_decision' ? 'emerald' : 'indigo')

export function Decode() {
  const [params, setParams] = useSearchParams()
  const docParam = params.get('doc')

  const [letters, setLetters] = useState<DocumentItem[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [unavailable, setUnavailable] = useState(false)

  const [result, setResult] = useState<DecodeResult | null>(null)
  const [loadingDecode, setLoadingDecode] = useState(false)
  const [needsDecode, setNeedsDecode] = useState(false)
  const [decodeError, setDecodeError] = useState<string | null>(null)
  const [creditError, setCreditError] = useState<string | null>(null)
  const [decoding, setDecoding] = useState(false)

  // GET /documents/decodable. Degrade gracefully: a 404 (older backend) — or any
  // error — resolves to an empty state, never a crash.
  const loadList = useCallback(async () => {
    setListError(null)
    setUnavailable(false)
    try {
      setLetters(await decoderApi.decodable())
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setUnavailable(true)
        setLetters([])
      } else {
        setListError(errorMessage(err))
        setLetters([])
      }
    }
  }, [])

  useEffect(() => {
    void loadList()
  }, [loadList])

  // The selected letter: the ?doc= param if it's a real decodable letter,
  // otherwise the first one. Reading straight from the URL keeps deep links
  // (from Documents' "Decode" button) working.
  const selectedId = useMemo(() => {
    if (!letters || letters.length === 0) return null
    if (docParam && letters.some((d) => d.id === docParam)) return docParam
    return letters[0].id
  }, [letters, docParam])

  const selected = useMemo(
    () => letters?.find((d) => d.id === selectedId) ?? null,
    [letters, selectedId]
  )

  // Try the cached decode for the selected letter. 404 → not decoded yet, show
  // the decode CTA; anything else → a real error with retry.
  const fetchDecode = useCallback((id: string) => {
    let cancelled = false
    setLoadingDecode(true)
    setResult(null)
    setNeedsDecode(false)
    setDecodeError(null)
    setCreditError(null)
    decoderApi
      .getDecode(id)
      .then((r) => {
        if (cancelled) return
        setResult(r)
        setLoadingDecode(false)
      })
      .catch((err) => {
        if (cancelled) return
        setLoadingDecode(false)
        if (err instanceof ApiError && err.status === 404) setNeedsDecode(true)
        else if (err instanceof ApiError && err.status === 402) setCreditError(err.message)
        else setDecodeError(errorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!selectedId) return
    return fetchDecode(selectedId)
  }, [selectedId, fetchDecode])

  const select = (id: string) => setParams({ doc: id }, { replace: true })

  // POST /documents/{id}/decode — runs the (LLM-backed) decode. Several seconds.
  const runDecode = async () => {
    if (!selectedId) return
    setDecoding(true)
    setDecodeError(null)
    setCreditError(null)
    try {
      const r = await decoderApi.decode(selectedId)
      setResult(r)
      setNeedsDecode(false)
    } catch (err) {
      if (err instanceof ApiError && err.status === 402) setCreditError(err.message)
      else setDecodeError(errorMessage(err))
    } finally {
      setDecoding(false)
    }
  }

  return (
    <div data-section="insight" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Decision decoder</p>
        <h1 className="vo-page-title">Decode your VA decision</h1>
        <p className="vo-page-sub">
          Upload a VA rating decision or decision letter and Rating Raider reads it privately on our own servers — never
          sent to commercial AI clouds — into plain English: what was granted or denied and why, an educational
          cross-check of your combined rating, your appeal deadline, and the exact next-step lanes. Educational only —
          the VA's letter is authoritative, and free VSO help is one click away.
        </p>
      </div>

      {letters === null ? (
        <LoadingBlock label="Looking for your decision letters…" />
      ) : listError ? (
        <ErrorBlock message={listError} onRetry={() => void loadList()} />
      ) : letters.length === 0 ? (
        <DecodeEmptyState unavailable={unavailable} />
      ) : (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
          <LetterSelector letters={letters} selectedId={selectedId} onSelect={select} />
          <div className="min-w-0 space-y-5">
            {selected && (
              <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-faint">
                <ScanText size={13} className="shrink-0" style={{ color: 'var(--section-hue)' }} />
                <span className="font-medium text-muted">{selected.title || selected.filename}</span>
                {selected.doc_date && <span>· dated {formatDate(selected.doc_date)}</span>}
              </p>
            )}

            {loadingDecode ? (
              <LoadingBlock label="Opening your decoded decision…" />
            ) : creditError ? (
              <CreditLimitNotice />
            ) : decodeError ? (
              <ErrorBlock
                message={decodeError}
                onRetry={() => {
                  if (selectedId) fetchDecode(selectedId)
                }}
              />
            ) : needsDecode && !result ? (
              <DecodeCta decoding={decoding} onDecode={() => void runDecode()} />
            ) : result ? (
              <DecodeReport result={result} />
            ) : null}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Empty / invitation states ────────────────────────────────────────────────

function DecodeEmptyState({ unavailable }: { unavailable: boolean }) {
  if (unavailable) {
    return (
      <EmptyState
        hue="violet"
        icon={<ScanText size={20} />}
        title="Decoder not available yet"
        description="This copy of Veteran-Ops can't reach the decision decoder right now. Your uploaded letters are safe in Documents — check back shortly."
        action={
          <Link to="/documents" className="text-sm font-semibold text-brand hover:text-brand-hover">
            Go to Documents →
          </Link>
        }
      />
    )
  }
  return (
    <EmptyState
      hue="fuchsia"
      icon={<ScanText size={20} />}
      title="No decision letters to decode yet"
      description="Upload a VA rating decision or decision letter in Documents and Rating Raider will turn it into plain English — what was granted or denied and why, your combined-rating cross-check, your appeal deadline, and your next-step options."
      action={
        <Link to="/documents" className="text-sm font-semibold text-brand hover:text-brand-hover">
          Upload a decision letter →
        </Link>
      }
    />
  )
}

// ── Letter selector ──────────────────────────────────────────────────────────

function LetterSelector({
  letters,
  selectedId,
  onSelect,
}: {
  letters: DocumentItem[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <aside className="self-start lg:sticky lg:top-4">
      <p className="vo-label-micro mb-2 px-1">
        {letters.length} decision letter{letters.length === 1 ? '' : 's'}
      </p>
      <div className="flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0" role="listbox" aria-label="Your decision letters">
        {letters.map((d) => {
          const active = d.id === selectedId
          const hue = letterHue(d)
          return (
            <button
              key={d.id}
              type="button"
              role="option"
              aria-selected={active}
              onClick={() => onSelect(d.id)}
              className={cx(
                'w-56 shrink-0 rounded-control border px-3.5 py-3 text-left transition-colors lg:w-full',
                active ? 'text-txt' : 'border-line bg-surface2 text-muted hover:border-line2 hover:text-txt'
              )}
              style={
                active
                  ? {
                      borderColor: `color-mix(in srgb, ${hueVar(hue)} 55%, transparent)`,
                      background: hueSoftVar(hue),
                    }
                  : undefined
              }
            >
              <span className="block truncate text-sm font-semibold text-txt">{d.title || d.filename}</span>
              <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {d.doc_type && <HueBadge hue={hue}>{humanize(d.doc_type)}</HueBadge>}
                <span className="text-xs text-faint">{formatDate(d.doc_date || d.created_at)}</span>
              </span>
            </button>
          )
        })}
      </div>
    </aside>
  )
}

// ── Decode call-to-action (not yet decoded) ──────────────────────────────────

function DecodeCta({ decoding, onDecode }: { decoding: boolean; onDecode: () => void }) {
  if (decoding) {
    return (
      <div
        className="vo-panel vo-accent flex flex-col items-center gap-4 px-6 py-14 text-center"
        style={hueStyle('fuchsia') as CSSProperties}
      >
        <span
          className="flex h-14 w-14 items-center justify-center rounded-full"
          style={{ background: hueSoftVar('fuchsia'), color: hueVar('fuchsia') }}
        >
          <Spinner size={26} />
        </span>
        <div>
          <p className="text-heading text-txt">Reading your decision letter…</p>
          <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-muted">
            Reading it privately on our own servers — never sent to commercial AI clouds. This can take a few seconds
            while we work through every contention line by line.
          </p>
        </div>
      </div>
    )
  }
  return (
    <div
      className="vo-panel vo-accent flex flex-col items-center gap-4 px-6 py-12 text-center"
      style={hueStyle('fuchsia') as CSSProperties}
    >
      <span
        className="flex h-14 w-14 items-center justify-center rounded-full"
        style={{ background: hueSoftVar('fuchsia'), color: hueVar('fuchsia') }}
      >
        <ScanText size={26} />
      </span>
      <div>
        <p className="text-heading text-txt">Ready to decode this decision</p>
        <p className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-muted">
          We'll read the letter you already uploaded — nothing new to upload — and lay out every contention in plain
          English, cross-check your combined rating, and map your next-step options.
        </p>
      </div>
      <button onClick={onDecode} className="vo-btn-primary">
        <ScanText size={16} />
        Decode this decision
      </button>
    </div>
  )
}

// ── The decoded report ───────────────────────────────────────────────────────

function DecodeReport({ result }: { result: DecodeResult }) {
  const grants = result.decisions.filter((d) => d.decision === 'granted').length
  const denials = result.decisions.filter((d) => d.decision === 'denied').length
  const deferred = result.decisions.filter((d) => d.decision === 'deferred').length

  // Lead with the Supplemental Claim lane when anything was denied (spec).
  const orderedOptions = useMemo(() => {
    if (!result.has_denials) return result.options
    const lead = result.options.filter((o) => o.key === 'supplemental_claim')
    const rest = result.options.filter((o) => o.key !== 'supplemental_claim')
    return [...lead, ...rest]
  }, [result])

  return (
    <div className="space-y-5">
      {/* Summary line */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <span className="text-muted">
          VA decided{' '}
          <span className="font-semibold text-txt">
            {result.decisions.length} contention{result.decisions.length === 1 ? '' : 's'}
          </span>
        </span>
        <span className="flex flex-wrap items-center gap-1.5">
          {grants > 0 && <HueBadge hue="emerald">{grants} granted</HueBadge>}
          {denials > 0 && <HueBadge hue="rose">{denials} denied</HueBadge>}
          {deferred > 0 && <HueBadge hue="amber">{deferred} deferred</HueBadge>}
        </span>
        {result.decision_date && (
          <span className="text-xs text-faint">Decision dated {formatDate(result.decision_date)}</span>
        )}
      </div>

      {/* Decisions grid */}
      {result.decisions.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {result.decisions.map((d, i) => (
            <DecisionCard key={i} decision={d} />
          ))}
        </div>
      )}

      {/* Combined-evaluation cross-check + Appeal window */}
      <div className="grid gap-4 md:grid-cols-2">
        <CombinedCheckCard check={result.combined_check} />
        <AppealWindowCard window={result.appeal_window} />
      </div>

      {/* Your options */}
      <div>
        <h2 className="mb-1 flex items-center gap-2 text-heading text-txt">
          <Scale size={17} style={{ color: 'var(--section-hue)' }} /> Your options
        </h2>
        <p className="mb-3 text-sm text-muted">
          Three official AMA decision-review lanes — educational, not filed for you.
          {result.has_denials && ' With a denial in this decision, most veterans start with a Supplemental Claim.'}
        </p>
        <div className="grid gap-4 sm:grid-cols-3">
          {orderedOptions.map((opt, i) => (
            <OptionCard key={opt.key} option={opt} lead={result.has_denials && i === 0} />
          ))}
        </div>
      </div>

      {/* VSO referral — legally load-bearing, made prominent */}
      <VsoReferral text={result.vso_referral} />

      {/* Disclaimer + source note — always rendered */}
      <div className="space-y-2 rounded-control border border-line bg-surface2 px-4 py-3.5 text-xs leading-relaxed text-muted">
        <p className="flex items-start gap-2">
          <Info size={13} className="mt-0.5 shrink-0" style={{ color: 'var(--section-hue)' }} />
          <span>{result.disclaimer}</span>
        </p>
        <p className="flex items-start gap-2">
          <Info size={13} className="mt-0.5 shrink-0 text-faint" />
          <span>{result.source_note}</span>
        </p>
        <p className="pl-5 text-faint">Decoded {formatDateTime(result.decoded_at)}.</p>
      </div>
    </div>
  )
}

function DecisionCard({ decision }: { decision: DecodeDecision }) {
  const hue = outcomeHue(decision)
  const Icon = decision.decision === 'granted' ? CheckCircle2 : decision.decision === 'denied' ? XCircle : Hourglass
  const meta = [
    decision.rating_percent != null ? `${decision.rating_percent}%` : null,
    decision.diagnostic_code ? `DC ${decision.diagnostic_code}` : null,
    decision.effective_date ? `effective ${formatDate(decision.effective_date)}` : null,
  ].filter(Boolean)

  return (
    <div className="vo-panel vo-accent flex flex-col overflow-hidden" style={hueStyle(hue) as CSSProperties}>
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3.5">
        <div className="flex min-w-0 items-start gap-2.5">
          <Icon size={18} className="mt-0.5 shrink-0" style={{ color: hueVar(hue) }} aria-hidden />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-txt">{decision.name}</h3>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              {decision.decision && <HueBadge hue={hue}>{humanize(decision.decision)}</HueBadge>}
              {decision.va_classification && (
                <span
                  className="vo-chip-hue"
                  style={hueStyle('indigo') as CSSProperties}
                  title={`VA's official contention classification${
                    decision.va_classification_code ? ` (code ${decision.va_classification_code})` : ''
                  }`}
                >
                  {decision.va_classification}
                </span>
              )}
            </div>
          </div>
        </div>
        {decision.rating_percent != null && (
          <span className="shrink-0 text-2xl font-bold tabular-nums" style={{ color: hueInk(hue) }}>
            {decision.rating_percent}%
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        {meta.length > 0 && (
          <p className="text-xs text-faint">{meta.join(' · ')}</p>
        )}
        {decision.plain && <p className="text-sm leading-relaxed text-txt">{decision.plain}</p>}

        {decision.decision === 'denied' && decision.missing_elements.length > 0 && (
          <div className="mt-auto">
            <p className="vo-label-micro mb-1.5" style={{ color: hueInk('rose') }}>
              What the VA said was missing
            </p>
            <div className="flex flex-wrap gap-1.5">
              {decision.missing_elements.map((m) => (
                <span
                  key={m}
                  className="inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium"
                  style={{
                    borderColor: `color-mix(in srgb, ${hueVar('rose')} 40%, transparent)`,
                    background: hueSoftVar('rose'),
                    color: hueInk('rose'),
                  }}
                >
                  Missing: {missingLabel(m)}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function CombinedCheckCard({ check }: { check: DecodeCombinedCheck }) {
  const hue: Hue = check.matches === true ? 'emerald' : check.matches === false ? 'amber' : 'indigo'
  const label =
    check.matches === true ? 'Matches' : check.matches === false ? 'Worth a look' : 'Not enough to cross-check'
  const Icon = check.matches === true ? CheckCircle2 : check.matches === false ? Info : Sigma

  return (
    <div className="vo-panel vo-accent flex flex-col overflow-hidden" style={hueStyle(hue) as CSSProperties}>
      <header className="flex items-center gap-2.5 border-b border-line px-4 py-3.5">
        <Sigma size={16} className="shrink-0" style={{ color: hueVar(hue) }} aria-hidden />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-txt">Combined-rating cross-check</h2>
          <p className="text-xs text-muted">Our §4.25 recompute vs the letter</p>
        </div>
      </header>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <CheckStat label="VA stated" value={check.va_stated} />
          <span className="text-faint" aria-hidden>
            vs
          </span>
          <CheckStat label="We computed" value={check.computed} />
          <span
            className="ml-auto inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold"
            style={{
              borderColor: `color-mix(in srgb, ${hueVar(hue)} 40%, transparent)`,
              background: hueSoftVar(hue),
              color: hueInk(hue),
            }}
          >
            <Icon size={13} /> {label}
          </span>
        </div>
        {check.note && <p className="text-sm leading-relaxed text-muted">{check.note}</p>}
        <p className="mt-auto flex items-start gap-2 rounded-control border border-line bg-surface2 px-3 py-2 text-xs leading-relaxed text-muted">
          <Info size={13} className="mt-0.5 shrink-0" style={{ color: 'var(--section-hue)' }} />
          The combined rating printed on your VA letter is the number that controls — this is only an educational check.
        </p>
      </div>
    </div>
  )
}

function CheckStat({ label, value }: { label: string; value: number | null }) {
  return (
    <span className="flex flex-col">
      <span className="text-2xl font-bold tabular-nums text-txt">{value != null ? `${value}%` : '—'}</span>
      <span className="text-micro font-semibold uppercase tracking-wider text-faint">{label}</span>
    </span>
  )
}

function AppealWindowCard({ window: aw }: { window: DecodeAppealWindow }) {
  const days = aw.days_remaining
  const past = aw.expired === true || (days != null && days < 0)
  const known = aw.deadline != null && days != null

  let hue: Hue = 'indigo'
  if (known) {
    if (past || (days as number) < 30) hue = 'rose'
    else if ((days as number) <= 90) hue = 'amber'
    else hue = 'emerald'
  }

  return (
    <div className="vo-panel vo-accent flex flex-col overflow-hidden" style={hueStyle(hue) as CSSProperties}>
      <header className="flex items-center gap-2.5 border-b border-line px-4 py-3.5">
        <CalendarClock size={16} className="shrink-0" style={{ color: hueVar(hue) }} aria-hidden />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-txt">Appeal window</h2>
          <p className="text-xs text-muted">One year from the decision date</p>
        </div>
      </header>
      <div className="flex flex-1 flex-col gap-3 p-4">
        {!known ? (
          <p className="text-sm leading-relaxed text-muted">
            We couldn't find the decision date in this letter, so we can't count down your appeal window. Check the
            letter itself — you generally have <strong className="text-txt">one year</strong> from the date of the
            decision to appeal and preserve your effective date. A VSO can confirm your deadline.
          </p>
        ) : past ? (
          <>
            <span className="inline-flex w-fit items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-semibold"
              style={{
                borderColor: `color-mix(in srgb, ${hueVar(hue)} 45%, transparent)`,
                background: hueSoftVar(hue),
                color: hueInk(hue),
              }}
            >
              <Hourglass size={14} /> Window passed
            </span>
            <p className="text-sm leading-relaxed text-muted">
              The one-year window {aw.deadline ? <>closed {formatDate(aw.deadline)}</> : 'has passed'}. You may still
              file a <strong className="text-txt">Supplemental Claim</strong> with new and relevant evidence — talk to a
              VSO about protecting your effective date.
            </p>
          </>
        ) : (
          <>
            <div className="flex items-baseline gap-2">
              <span className="text-4xl font-bold tabular-nums" style={{ color: hueInk(hue) }}>
                {days}
              </span>
              <span className="text-sm font-medium text-muted">day{days === 1 ? '' : 's'} left</span>
            </div>
            <p className="text-sm leading-relaxed text-muted">
              You have until <strong className="text-txt">{formatDate(aw.deadline)}</strong> to appeal and preserve your
              effective date. Filing after that may push your effective date forward.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

function OptionCard({ option, lead }: { option: DecodeOption; lead: boolean }) {
  const hue = OPTION_HUES[option.key] ?? 'indigo'
  const Icon = OPTION_ICONS[option.key] ?? Scale
  return (
    <div
      className="vo-card vo-accent flex flex-col p-4"
      style={
        {
          '--hue': hueVar(hue),
          '--hue-soft': hueSoftVar(hue),
          ...(lead ? { boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${hueVar(hue)} 40%, transparent)` } : {}),
        } as CSSProperties
      }
    >
      <div className="flex items-center gap-2">
        <Icon size={16} className="shrink-0" style={{ color: hueVar(hue) }} aria-hidden />
        {option.form && <HueBadge hue={hue}>Form {option.form}</HueBadge>}
        {lead && (
          <span className="ml-auto text-micro font-semibold uppercase tracking-wider" style={{ color: hueInk(hue) }}>
            Start here
          </span>
        )}
      </div>
      <h3 className="mt-2 text-sm font-semibold text-txt">{option.title}</h3>
      {option.when && (
        <p className="mt-1 text-xs font-medium" style={{ color: hueInk(hue) }}>
          {option.when}
        </p>
      )}
      {option.detail && <p className="mt-2 flex-1 text-sm leading-relaxed text-muted">{option.detail}</p>}
      {option.source && (
        <p className="mt-3 border-t border-line pt-2.5 text-xs text-faint">{option.source}</p>
      )}
    </div>
  )
}

function VsoReferral({ text }: { text: ReactNode }) {
  return (
    <div className="vo-panel vo-accent flex items-start gap-3.5 px-5 py-4" style={hueStyle('emerald') as CSSProperties}>
      <span
        className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar('emerald'), color: hueVar('emerald') }}
      >
        <ShieldCheck size={18} />
      </span>
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-txt">
          <Users size={14} style={{ color: hueVar('emerald') }} /> Free help from a VA-accredited VSO
        </p>
        <p className="mt-1 text-sm leading-relaxed text-muted">{text}</p>
        <a
          href="https://www.va.gov/get-help-from-accredited-representative/find-rep/"
          target="_blank"
          rel="noopener noreferrer"
          className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
        >
          Find an accredited representative <ArrowUpRight size={14} />
        </a>
      </div>
    </div>
  )
}
