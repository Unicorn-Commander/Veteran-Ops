import {
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  FileCheck2,
  FileClock,
  FileWarning,
  Hourglass,
  Landmark,
  RefreshCw,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, EmptyState, ErrorBlock, HueBadge, LoadingBlock, Panel, Spinner } from '../components/ui'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { ApiError, vaApi } from '../lib/api'
import { formatDate, humanize } from '../lib/format'
import type { Hue } from '../lib/hues'
import type { VaClaim, VaItf } from '../types'

// /claims — wave 3 claims-status page (routers/va.py GET /va/claims,
// GET /va/itf/active, POST /va/itf). Everything renders from the veteran's
// own VA.gov-consented connection. The one write on this page (Intent to
// File) shows exactly what will be submitted and requires the veteran's
// explicit confirmation — the same act as filing it on VA.gov.

/** VA.gov's 5-step claim process, in plain English (normalize.CLAIM_PHASES
 * decodes the status string to the step number; we decode the step in place). */
const PHASES = [
  { step: 1, label: 'Claim received', plain: 'VA has your claim.' },
  { step: 2, label: 'Initial review', plain: 'A reviewer is checking your claim.' },
  {
    step: 3,
    label: 'Evidence gathering, review, and decision',
    plain: 'VA is collecting evidence, reviewing it, and making a decision — usually the longest step.',
  },
  { step: 4, label: 'Preparation for notification', plain: 'Your decision letter is being prepared.' },
  { step: 5, label: 'Complete', plain: 'VA has decided your claim and sent your letter.' },
]

export function Claims() {
  const { data: status, loading: statusLoading } = useAsync(() => vaApi.status())
  const claimsConnected = Boolean(status?.enabled && status.connections.some((c) => c.api === 'claims'))

  const {
    data: claimsData,
    loading: claimsLoading,
    error: claimsError,
    reload: reloadClaims,
  } = useAsync(() => (claimsConnected ? vaApi.claims() : Promise.resolve(null)), [claimsConnected])

  return (
    <div data-section="claim" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Claim tools</p>
        <h1 className="vo-page-title">Claims status</h1>
        <p className="vo-page-sub">
          Where each of your VA claims stands, decoded into plain English — pulled straight from VA on your own
          consented sign-in. Read-only: checking status changes nothing.
        </p>
      </div>

      {statusLoading ? (
        <LoadingBlock label="Checking your VA connection…" />
      ) : !status?.enabled ? (
        <EmptyState
          hue="emerald"
          icon={<Landmark size={20} />}
          title="VA connection not configured"
          description="This server isn't set up for the VA connection — your administrator configures it. Everything else in Rating Raider works without it."
        />
      ) : !claimsConnected ? (
        <EmptyState
          hue="emerald"
          icon={<Landmark size={20} />}
          title="Connect the Claims API to see your claim status"
          description="You sign in at VA.gov and consent there; you can revoke anytime. Connect from the VA.gov card in Settings."
          action={
            <Link to="/settings" className="vo-btn-primary">
              Go to Settings <ArrowRight size={15} />
            </Link>
          }
        />
      ) : (
        <>
          {claimsLoading ? (
            <LoadingBlock label="Pulling your claims from VA…" />
          ) : claimsError ? (
            <ErrorBlock
              message={`${claimsError} If your VA sign-in expired, reconnect from Settings.`}
              onRetry={reloadClaims}
            />
          ) : !claimsData || claimsData.claims.length === 0 ? (
            <EmptyState
              hue="emerald"
              icon={<Hourglass size={20} />}
              title="No claims on file"
              description="VA didn't return any benefits claims for your account. When you file one (yourself or with a VSO), its status shows up here."
            />
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-sm text-muted">
                  {claimsData.claims.length} claim{claimsData.claims.length === 1 ? '' : 's'} on file with VA
                </p>
                <button onClick={reloadClaims} className="vo-btn-ghost text-xs">
                  <RefreshCw size={13} /> Refresh
                </button>
              </div>
              {claimsData.claims.map((claim, i) => (
                <ClaimCard key={claim.id ?? i} claim={claim} />
              ))}
            </div>
          )}

          <ItfPanel />
        </>
      )}
    </div>
  )
}

/** VA.gov's decode-in-place pattern: a condensed 5-segment phase bar — the
 * active segment carries the section hue (emerald), completed segments a soft
 * fill — with the current phase named in plain English below. */
function PhaseBar({ phase, status }: { phase: number | null; status: string | null }) {
  const current = phase != null ? PHASES.find((p) => p.step === phase) : undefined
  return (
    <div>
      <div className="flex gap-1.5" role="img" aria-label={current ? `Step ${current.step} of 5: ${current.label}` : 'Claim phase unknown'}>
        {PHASES.map((p) => {
          const isActive = phase != null && p.step === phase
          const isDone = phase != null && p.step < phase
          return (
            <span
              key={p.step}
              className="h-2 flex-1 rounded-full transition-colors"
              style={{
                background: isActive
                  ? 'var(--section-hue)'
                  : isDone
                    ? 'color-mix(in srgb, var(--section-hue) 40%, transparent)'
                    : 'var(--surface-2)',
                boxShadow: isActive ? '0 0 8px var(--section-glow)' : undefined,
                border: isActive || isDone ? 'none' : '1px solid var(--border)',
              }}
            />
          )
        })}
      </div>
      <p className="mt-2 text-sm">
        {current ? (
          <>
            <span className="font-semibold text-txt">
              Step {current.step} of 5 — {current.label}.
            </span>{' '}
            <span className="text-muted">{current.plain}</span>
          </>
        ) : (
          <span className="text-muted">
            Status from VA: <span className="font-medium text-txt">{status ?? 'unknown'}</span>
          </span>
        )}
      </p>
    </div>
  )
}

function ClaimCard({ claim }: { claim: VaClaim }) {
  const [eventsOpen, setEventsOpen] = useState(false)
  const events = claim.events ?? []
  return (
    <Panel
      title={claim.claim_type ? humanize(claim.claim_type) : 'VA claim'}
      subtitle={claim.date_filed ? `Filed ${formatDate(claim.date_filed)}` : undefined}
      action={
        claim.open === false ? (
          <Badge tone="neutral">Closed</Badge>
        ) : claim.open === true ? (
          <HueBadge hue="emerald">Open</HueBadge>
        ) : null
      }
    >
      <div className="space-y-4 p-5">
        <PhaseBar phase={claim.phase} status={claim.status} />

        {claim.documents_needed && (
          <div
            className="flex items-start gap-2.5 rounded-control border px-4 py-3.5 text-sm"
            style={{
              borderColor: 'color-mix(in srgb, var(--warning) 45%, transparent)',
              background: 'var(--hue-amber-soft)',
            }}
          >
            <FileWarning size={16} className="mt-0.5 shrink-0" style={{ color: 'var(--warning)' }} />
            <div>
              <p className="font-semibold text-txt">VA is waiting on documents</p>
              <p className="mt-0.5 text-muted">
                Check your VA.gov claim page or your mail for exactly what VA asked for — responding quickly keeps
                your claim moving.
              </p>
            </div>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {claim.development_letter_sent && (
            <Badge tone="neutral">
              <FileClock size={12} /> Development letter sent
            </Badge>
          )}
          {claim.decision_letter_sent && (
            <Badge tone="success">
              <FileCheck2 size={12} /> Decision letter sent
            </Badge>
          )}
          {claim.requested_decision && <Badge tone="neutral">Decision requested (FDC)</Badge>}
          {(claim.min_est_date || claim.max_est_date) && (
            <Badge tone="neutral">
              <CalendarClock size={12} /> Est. decision {formatDate(claim.min_est_date)} – {formatDate(claim.max_est_date)}
            </Badge>
          )}
        </div>

        {events.length > 0 && (
          <div>
            <button
              onClick={() => setEventsOpen((v) => !v)}
              className="flex items-center gap-1.5 text-sm font-semibold text-muted transition-colors hover:text-txt"
              aria-expanded={eventsOpen}
            >
              <ChevronDown size={15} className={`transition-transform ${eventsOpen ? 'rotate-180' : ''}`} />
              {eventsOpen ? 'Hide' : 'Show'} timeline ({events.length} event{events.length === 1 ? '' : 's'})
            </button>
            {eventsOpen && (
              <ol className="vo-step-enter mt-3 space-y-0">
                {events.map((ev, i) => (
                  <li key={i} className="relative flex gap-3 pb-3.5 text-sm last:pb-0">
                    {i < events.length - 1 && (
                      <span
                        aria-hidden
                        className="absolute left-[5px] top-4 h-full w-px"
                        style={{ background: 'var(--border-2)' }}
                      />
                    )}
                    <span
                      className="relative z-10 mt-1.5 h-[11px] w-[11px] shrink-0 rounded-full border-2 border-line bg-surface2"
                      aria-hidden
                    />
                    <span className="min-w-0">
                      <span className="font-medium text-txt">{humanize(ev.type)}</span>
                      {ev.filename && <span className="text-muted"> — {ev.filename}</span>}
                      <span className="block text-xs text-faint">{formatDate(ev.date)}</span>
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </div>
    </Panel>
  )
}

// ── Intent to File ────────────────────────────────────────────────────────────

/** Days until an ISO date (ceil — "expires today" counts as 0). */
function daysUntil(iso: string | null | undefined): number | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return Math.ceil((d.getTime() - Date.now()) / 86_400_000)
}

/** Urgency thresholds for the ITF expiry countdown: 90 / 30 / 7 days. */
function urgencyHue(days: number): Hue {
  if (days <= 7) return 'rose'
  if (days <= 30) return 'orange'
  if (days <= 90) return 'amber'
  return 'emerald'
}

function ItfPanel() {
  const { toast } = useToast()
  const { data, loading, error, reload, setData } = useAsync(() => vaApi.itfActive())
  const [modalOpen, setModalOpen] = useState(false)

  const days = data?.active ? daysUntil(data.expiration_date) : null

  return (
    <Panel
      hue="teal"
      title="Intent to File"
      subtitle="VA Form 0966 — locks in a potential effective date while you prepare"
    >
      <div className="space-y-3 p-5">
        <p className="text-sm text-muted">
          An Intent to File tells VA you plan to file a compensation claim. It's free, it doesn't start a claim, and
          it gives you up to a year to prepare while preserving the earlier effective date — often worth months of
          back pay.
        </p>

        {loading ? (
          <p className="flex items-center gap-1.5 text-xs text-muted">
            <Spinner size={12} /> Checking for an active Intent to File…
          </p>
        ) : error ? (
          <ErrorBlock message={error} onRetry={reload} />
        ) : data?.active ? (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-line bg-surface2 px-4 py-3.5">
            <div>
              <p className="flex items-center gap-1.5 text-sm font-semibold text-txt">
                <CheckCircle2 size={15} className="text-success" /> Active Intent to File on record
              </p>
              <p className="mt-0.5 text-xs text-muted">
                {data.creation_date ? `Filed ${formatDate(data.creation_date)} · ` : ''}
                {data.expiration_date ? `expires ${formatDate(data.expiration_date)}` : 'expiration date unknown'}
              </p>
            </div>
            {days != null && (
              <HueBadge hue={urgencyHue(days)}>
                <CalendarClock size={12} />
                {days <= 0 ? 'Expires today' : `${days} day${days === 1 ? '' : 's'} left`}
              </HueBadge>
            )}
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-control border border-line bg-surface2 px-4 py-3.5">
            <p className="text-sm text-muted">No active Intent to File on record with VA.</p>
            <button onClick={() => setModalOpen(true)} className="vo-btn-primary text-sm">
              File an Intent to File
            </button>
          </div>
        )}

        {days != null && days <= 90 && (
          <p className="text-xs text-muted">
            Your effective-date placeholder expires {days <= 0 ? 'today' : `in ${days} day${days === 1 ? '' : 's'}`} —
            if you plan to claim, aim to file before then (a VSO can help for free).
          </p>
        )}
      </div>

      {modalOpen && (
        <ItfConfirmModal
          onClose={() => setModalOpen(false)}
          onFiled={(itf) => {
            setModalOpen(false)
            setData(itf)
            toast('Intent to File submitted to VA — your potential effective date is locked in.', 'success')
          }}
        />
      )}
    </Panel>
  )
}

/** Explicit-confirmation modal: shows exactly what will be submitted before
 * the veteran presses the button (the backend refuses without confirm=true). */
function ItfConfirmModal({ onClose, onFiled }: { onClose: () => void; onFiled: (itf: VaItf) => void }) {
  const [submitting, setSubmitting] = useState(false)
  const [contractError, setContractError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  // Trap focus in the dialog + lock body scroll while it's open.
  useFocusTrap(dialogRef)
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const file = async () => {
    setSubmitting(true)
    setContractError(null)
    try {
      const itf = await vaApi.fileItf()
      onFiled(itf)
    } catch (err) {
      // 422 = the backend's confirmation contract; render its exact message.
      if (err instanceof ApiError && err.status === 422) setContractError(err.message)
      else setContractError(errorMessage(err))
      setSubmitting(false)
    }
  }

  return (
    <div
      ref={dialogRef}
      className="animate-fade-in fixed inset-0 z-[100] flex items-center justify-center bg-black/60 px-4 py-8 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="itf-title"
      onClick={onClose}
    >
      <div className="vo-panel animate-pop-in w-full max-w-lg overflow-hidden shadow-pop" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3 border-b border-line px-6 py-5">
          <div>
            <h2 id="itf-title" className="text-lg font-bold text-txt">
              File an Intent to File with VA?
            </h2>
            <p className="mt-1 text-sm text-muted">This one submits something to VA — read it before you press the button.</p>
          </div>
          <button onClick={onClose} className="vo-icon-btn vo-btn-ghost" aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3 px-6 py-5 text-sm leading-relaxed">
          <p className="text-txt">Pressing "File it" submits, on your own VA.gov-consented sign-in:</p>
          <ul className="ml-5 list-disc space-y-1.5 text-txt">
            <li>
              <strong>VA Form 0966 — Intent to File</strong>, type: <strong>compensation</strong>. Nothing else is sent.
            </li>
            <li>It locks in today as your potential effective date for up to one year while you prepare your claim.</li>
            <li>It's free, and it does <strong>not</strong> start or file a claim.</li>
            <li>
              <strong>You are the filer</strong>, acting through software you operate — the same act as filing it
              yourself on VA.gov.
            </li>
          </ul>
          <p className="text-xs text-muted">
            Rating Raider is self-help educational software, not a VA-accredited representative. A VSO can also file
            this for you, for free.
          </p>
          {contractError && (
            <p
              role="alert"
              className="rounded-control border bg-danger-soft px-3.5 py-2.5 text-sm text-danger"
              style={{ borderColor: 'color-mix(in srgb, var(--danger) 40%, transparent)' }}
            >
              {contractError}
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-6 py-4">
          <button onClick={onClose} className="vo-btn-secondary" disabled={submitting}>
            Cancel
          </button>
          <button onClick={() => void file()} disabled={submitting} className="vo-btn-primary">
            {submitting ? <Spinner size={16} className="text-white" /> : <CheckCircle2 size={15} />}
            File it — I understand what's being submitted
          </button>
        </div>
      </div>
    </div>
  )
}
