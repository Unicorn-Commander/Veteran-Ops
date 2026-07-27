import { MailWarning, Send, X } from 'lucide-react'
import type { CSSProperties } from 'react'
import { useState } from 'react'
import { Spinner } from './ui'
import { useToast } from './Toast'
import { useAuth } from '../context/AuthContext'
import { errorMessage } from '../hooks/useAsync'
import { hueStyle } from '../lib/hues'
import { auth } from '../lib/api'

/** A quiet, dismissible nudge shown at the top of the dashboard while the
 * signed-in veteran's email is still unverified. Renders nothing when there's
 * no user or the email is already verified. Theme-aware + accessible. */
export function EmailVerifyBanner() {
  const { user } = useAuth()
  const { toast } = useToast()
  const [dismissed, setDismissed] = useState(false)
  const [sending, setSending] = useState(false)

  if (!user || user.email_verified || dismissed) return null

  const resend = async () => {
    setSending(true)
    try {
      const res = await auth.requestVerification()
      toast(res.message || 'Verification email sent — check your inbox.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSending(false)
    }
  }

  return (
    <div
      role="status"
      className="vo-card vo-accent flex flex-col items-start justify-between gap-3 p-4 sm:flex-row sm:items-center"
      style={hueStyle('amber') as CSSProperties}
    >
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-h-amber-soft text-warn">
          <MailWarning size={16} />
        </span>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-txt">Please verify your email</p>
          <p className="mt-0.5 text-sm leading-relaxed text-muted">
            Check your inbox at <strong className="text-txt">{user.email}</strong> for a verification link.
          </p>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2 self-stretch sm:self-auto">
        <button onClick={() => void resend()} disabled={sending} className="vo-btn-secondary text-sm">
          {sending ? <Spinner size={14} /> : <Send size={14} />}
          Resend email
        </button>
        <button
          onClick={() => setDismissed(true)}
          aria-label="Dismiss"
          className="vo-icon-btn vo-btn-ghost text-faint hover:text-txt"
          title="Dismiss"
        >
          <X size={15} />
        </button>
      </div>
    </div>
  )
}
