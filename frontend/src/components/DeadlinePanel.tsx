import { AlertTriangle, ArrowRight, CalendarClock, Clock, Loader2, Mail } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Deadline, DeadlineUrgency } from '../types'
import { errorMessage } from '../hooks/useAsync'
import { deadlinesApi } from '../lib/api'
import { useToast } from './Toast'
import { EmptyState, ErrorBlock } from './ui'

/**
 * Deadline guardian panel (veteran-workflows research §cross-cutting #2). Renders
 * the veteran's time-sensitive 1-year clocks with a countdown, what to do, and a
 * link to the feature that acts on it. Data is deterministic (GET /deadlines).
 *
 * Urgency is conveyed with SEMANTIC status colors — red/amber/green from the
 * --danger / --warning / --success tokens (themed for light+dark in index.css),
 * deliberately NOT the brand accent — so a countdown reads as urgency, never as
 * decoration. Renders nothing when the veteran has no deadlines.
 */

const URGENCY: Record<DeadlineUrgency, { color: string; tint: string; ring: string; label: string }> = {
  overdue: {
    color: 'color-mix(in srgb, var(--danger) var(--mix-ink, 92%), var(--txt))',
    tint: 'color-mix(in srgb, var(--danger) 14%, transparent)',
    ring: 'color-mix(in srgb, var(--danger) 42%, transparent)',
    label: 'Overdue',
  },
  soon: {
    color: 'color-mix(in srgb, var(--warning) var(--mix-ink, 92%), var(--txt))',
    tint: 'color-mix(in srgb, var(--warning) 16%, transparent)',
    ring: 'color-mix(in srgb, var(--warning) 44%, transparent)',
    label: 'Due soon',
  },
  ok: {
    color: 'color-mix(in srgb, var(--success) var(--mix-ink, 92%), var(--txt))',
    tint: 'color-mix(in srgb, var(--success) 14%, transparent)',
    ring: 'color-mix(in srgb, var(--success) 40%, transparent)',
    label: 'On track',
  },
}

function countdownLabel(daysLeft: number | null): string {
  if (daysLeft === null) return 'Date not detected'
  if (daysLeft < 0) {
    const past = Math.abs(daysLeft)
    return `${past} day${past === 1 ? '' : 's'} overdue`
  }
  if (daysLeft === 0) return 'Due today'
  return `${daysLeft} day${daysLeft === 1 ? '' : 's'} left`
}

function formatDue(due: string | null): string | null {
  if (!due) return null
  const d = new Date(`${due}T00:00:00`)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

function deadlineAction(deadline: Deadline): string {
  if (deadline.kind === 'itf') {
    return 'Review your Intent to File and prepare the related claim before the date shown. Confirm the date and any exception with VA or an accredited VSO.'
  }
  if (deadline.kind === 'appeal') {
    return 'If you disagree with the decision, compare the review lanes and confirm the deadline printed on your letter. Filing timing can affect continuous pursuit and a potential effective date.'
  }
  return 'Review the dependent form and timing rules. A filing date may affect when added compensation can begin; confirm the 30% threshold and your date with VA or a VSO.'
}

/** On-demand email digest — works with or without tracked deadlines. */
function EmailDigestButton({ hasDeadlines }: { hasDeadlines: boolean }) {
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)

  const send = async () => {
    setBusy(true)
    try {
      const res = await deadlinesApi.notifyMe()
      if (res.sent) {
        toast(res.reason === 'ok' || !res.reason
          ? 'Digest emailed to your account address.'
          : res.reason, 'success')
      } else {
        const reason = res.reason || ''
        const friendly =
          reason === 'smtp_auth_failed'
            ? 'Email server rejected login (suite noreply password needs a reset). Your deadlines are still tracked in-app.'
            : reason === 'smtp_unreachable'
              ? 'Could not reach the email server. Your deadlines are still tracked in-app — try again later.'
              : reason === 'deadline_emails_disabled'
                ? 'Deadline emails are turned off on this host.'
                : reason === 'no_email'
                  ? 'Your account has no email address on file.'
                  : reason === 'no_urgent' || reason === 'no_deadlines'
                    ? hasDeadlines
                      ? 'Nothing urgent enough to email right now — open Deadlines in-app for the full list.'
                      : 'No tracked deadlines to include yet.'
                    : reason ||
                      (hasDeadlines
                        ? 'Could not send the digest right now.'
                        : 'No deadlines to include, or email is not configured on this host.')
        toast(
          friendly,
          reason.includes('smtp') || reason.includes('send_failed') ? 'error' : 'info',
        )
      }
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      type="button"
      onClick={() => void send()}
      disabled={busy}
      className="vo-btn-secondary min-h-11 text-sm"
    >
      {busy ? <Loader2 size={15} className="animate-spin" /> : <Mail size={15} />}
      {busy ? 'Sending…' : 'Email me a digest'}
    </button>
  )
}

export function DeadlinePanel({ deadlines, onRetry }: { deadlines: Deadline[] | null; onRetry?: () => void }) {
  if (deadlines === null) {
    return (
      <ErrorBlock
        message="We couldn't check your tracked deadlines. Check your connection, then try again; confirm any date on your VA letter in the meantime."
        onRetry={onRetry}
      />
    )
  }

  if (deadlines.length === 0) {
    return (
      <div className="space-y-3">
        <EmptyState
          hue="emerald"
          icon={<CalendarClock size={20} />}
          title="No tracked deadlines right now"
          description="Rating Raider did not find an active Intent to File, decision-review, or dependent deadline in the records it could read. Always confirm dates on VA letters."
        />
        <div className="flex flex-wrap items-center justify-center gap-2">
          <EmailDigestButton hasDeadlines={false} />
        </div>
        <p className="text-center text-xs text-faint">
          Sends a test digest to your account email when suite SMTP is configured — useful even with no clocks.
        </p>
      </div>
    )
  }

  return (
    <section aria-label="Your deadlines" className="vo-card overflow-hidden">
      <header className="flex flex-wrap items-center gap-2.5 border-b border-line px-5 py-3.5">
        <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface2 text-muted">
          <CalendarClock size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-txt">Deadline guardian</h2>
          <p className="text-xs text-faint">
            Time-sensitive dates found in your records — with the action and source letter still yours to confirm.
          </p>
        </div>
        <EmailDigestButton hasDeadlines />
      </header>

      <ul className="divide-y divide-line">
        {deadlines.map((d, i) => {
          const u = URGENCY[d.urgency] ?? URGENCY.soon
          const due = formatDue(d.due_date)
          const overdue = d.days_left !== null && d.days_left < 0
          const dateUnknown = d.days_left === null
          const statusLabel = dateUnknown ? 'Date needed' : u.label
          return (
            <li key={`${d.kind}-${i}`} className="px-5 py-4">
              <div className="flex items-start gap-3.5">
                {/* Countdown chip — semantic urgency color, tabular for scanability. */}
                <div
                  className="flex w-16 shrink-0 flex-col items-center justify-center rounded-xl px-2 py-2 text-center"
                  style={{ background: u.tint, boxShadow: `inset 0 0 0 1px ${u.ring}` }}
                  aria-label={countdownLabel(d.days_left)}
                >
                  <span aria-hidden="true" className="text-xl font-bold leading-none tabular-nums" style={{ color: u.color }}>
                    {d.days_left === null ? '—' : Math.abs(d.days_left)}
                  </span>
                  <span aria-hidden="true" className="mt-1 text-[10px] font-semibold uppercase leading-none tracking-wide" style={{ color: u.color }}>
                    {d.days_left === null ? 'unknown' : overdue ? 'days over' : 'days left'}
                  </span>
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span
                      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold"
                      style={{ background: u.tint, color: u.color }}
                    >
                      {overdue ? <AlertTriangle size={11} aria-hidden="true" /> : <Clock size={11} aria-hidden="true" />}
                      {statusLabel}
                    </span>
                    <span className="text-xs font-medium tabular-nums text-muted">{countdownLabel(d.days_left)}</span>
                    {due && <span className="text-xs text-faint">· due {due}</span>}
                  </div>
                  <h3 className="mt-1.5 text-sm font-semibold text-txt">{d.title}</h3>
                  <p className="mt-1 text-sm leading-relaxed text-muted">{deadlineAction(d)}</p>
                  <Link
                    to={d.related_route}
                    className="group mt-2 inline-flex min-h-10 items-center gap-1 rounded-control px-1 text-sm font-semibold text-brand transition-colors hover:text-brand-hover"
                  >
                    Review this deadline
                    <ArrowRight size={14} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" aria-hidden="true" />
                  </Link>
                </div>
              </div>
            </li>
          )
        })}
      </ul>
      <p className="border-t border-line px-5 py-3 text-xs leading-relaxed text-faint">
        These are educational reminders computed from dates Rating Raider could read. VA deadlines and
        effective-date rules have exceptions; confirm every date on the source letter or with a VA-accredited VSO.
      </p>
    </section>
  )
}
