import { ShieldAlert, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useFocusTrap } from '../hooks/useFocusTrap'
import { Checkbox } from './ui'

export const DISCLAIMER_TEXT =
  "Veteran-Ops is self-help educational software; Rating Raider is your claims agent inside the app. Neither is legal advice, a VA-accredited representative or agent, nor affiliated with the U.S. Department of Veterans Affairs. For free help filing or appealing, use a VA-accredited Veterans Service Officer (VSO) — VFW, DAV, The American Legion, or your state/county veterans office. Verify current rating criteria at eCFR / VA.gov — regulations change."

/** The standing pro-se disclaimer shown on every advocate surface (chat, briefing,
 * findings). Rating Raider is a full advocate that helps a veteran represent
 * THEMSELVES — this line keeps the pro-se framing unmistakable everywhere the app
 * reasons about their claim. */
export const PRO_SE_DISCLAIMER =
  "Veteran-Ops is self-help software for veterans representing themselves; Rating Raider is the in-app claims agent. It is not your accredited representative, does not file for you, and VA makes every decision. A free VSO or accredited attorney can review — recommended, not required."

const ACK_KEY = 'vo_disclaimer_ack'

export function hasAcknowledgedDisclaimer(): boolean {
  try {
    return localStorage.getItem(ACK_KEY) === '1'
  } catch {
    return false
  }
}

export function acknowledgeDisclaimer(): void {
  try {
    localStorage.setItem(ACK_KEY, '1')
  } catch {
    /* noop */
  }
}

export function clearDisclaimerAck(): void {
  try {
    localStorage.removeItem(ACK_KEY)
  } catch {
    /* noop */
  }
}

/** Persistent, compact disclaimer shown in the footer of every page. */
const FOOTER_DISMISS_KEY = 'vo_disclaimer_footer_dismissed'

export function DisclaimerFooter({ className = '' }: { className?: string }) {
  // Dismissible: the full text is a one-time-acknowledged first-run modal and is
  // always reachable at /legal (and re-showable from Settings), so the persistent
  // footer can be closed. Once dismissed it stays hidden (localStorage).
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(FOOTER_DISMISS_KEY) === '1'
    } catch {
      return false
    }
  })
  if (dismissed) return null

  const close = () => {
    try {
      localStorage.setItem(FOOTER_DISMISS_KEY, '1')
    } catch {
      /* noop */
    }
    setDismissed(true)
  }

  return (
    <footer className={`vo-no-print relative border-t border-line px-4 py-3 ${className}`}>
      <p className="mx-auto flex max-w-6xl items-start gap-2 pr-8 text-center text-micro leading-relaxed text-faint sm:text-left">
        <ShieldAlert size={14} className="mt-0.5 hidden shrink-0 sm:block" aria-hidden="true" />
        <span>
          {DISCLAIMER_TEXT}{' '}
          <Link to="/legal" className="font-semibold text-muted underline underline-offset-2 hover:text-txt">
            Terms &amp; privacy
          </Link>
        </span>
      </p>
      <button
        type="button"
        onClick={close}
        aria-label="Dismiss disclaimer"
        title="Dismiss (always available on the Terms &amp; privacy page)"
        className="absolute right-2 top-2 rounded-md p-1.5 text-faint transition-colors hover:bg-surface2 hover:text-txt"
      >
        <X size={15} />
      </button>
    </footer>
  )
}

/**
 * Standing pro-se disclaimer for advocate surfaces (chat, briefing, findings).
 * Non-dismissible by design — it must remain visible wherever Rating Raider is
 * actively reasoning about the veteran's claim, so the "you represent yourself"
 * framing never scrolls away. Compact `role="note"` callout in Aurora's slate/quiet
 * style so it reads as a persistent footnote, not an alarm.
 */
export function ProSeDisclaimer({ className = '' }: { className?: string }) {
  return (
    <div
      role="note"
      className={`flex items-start gap-2 rounded-control border border-line bg-surface2 px-3.5 py-2.5 text-micro leading-relaxed text-muted ${className}`}
    >
      <ShieldAlert size={14} className="mt-0.5 shrink-0 text-faint" aria-hidden="true" />
      <span>
        {PRO_SE_DISCLAIMER}{' '}
        <Link
          to="/legal"
          className="font-semibold text-muted underline underline-offset-2 hover:text-txt"
        >
          Terms &amp; privacy
        </Link>
      </span>
    </div>
  )
}

/**
 * First-run consent modal. Shown once (ack persisted in localStorage) and
 * re-invocable from Settings ("re-show first-run modal"). The veteran must
 * acknowledge before using the app — this is a plain-language restatement of
 * the legal-lane framing, never gating on anything the backend tracks.
 */
export function DisclaimerModal({ onAccept }: { onAccept: () => void }) {
  const [checked, setChecked] = useState(false)
  const dialogRef = useRef<HTMLDivElement>(null)

  // Move focus into the gate, trap Tab within it, and restore focus on accept.
  useFocusTrap(dialogRef)

  // Lock page scroll while the gate is up.
  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [])

  return (
    <div
      ref={dialogRef}
      className="vo-no-print animate-fade-in fixed inset-0 z-[100] flex items-center justify-center bg-black/60 px-4 py-8 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="disclaimer-title"
    >
      <div className="vo-panel animate-pop-in w-full max-w-lg overflow-hidden shadow-pop">
        <div className="border-b border-line px-6 py-5">
          <h1
            id="disclaimer-title"
            tabIndex={-1}
            data-autofocus
            className="text-lg font-bold text-txt focus:outline-none"
          >
            Before you start your claim
          </h1>
          <p className="mt-1 text-sm text-muted">
            A quick, honest note on what Rating Raider is — and isn't.
          </p>
        </div>

        <div className="space-y-4 px-6 py-6">
          <p className="text-sm leading-relaxed text-txt">
            Rating Raider is <strong>self-help software you operate yourself</strong> — like tax-prep
            software for your VA disability claim. It helps you organize evidence, understand
            rating criteria, and see how your conditions combine. You always drive: you decide
            what to claim, you gather your evidence, and you file.
          </p>
          <div className="rounded-control border border-line bg-surface2 px-4 py-3.5 text-xs leading-relaxed text-muted">
            {DISCLAIMER_TEXT}
          </div>
          <Checkbox
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
            label={
              <>
                I understand Rating Raider is educational software, not a VA-accredited representative,
                and I'm free to use a VSO for free help at any time.
              </>
            }
          />
        </div>

        <div className="flex justify-end gap-2 border-t border-line px-6 py-4">
          <button
            onClick={() => {
              acknowledgeDisclaimer()
              onAccept()
            }}
            disabled={!checked}
            className="vo-btn-primary"
          >
            Continue to Rating Raider
          </button>
        </div>
      </div>
    </div>
  )
}
