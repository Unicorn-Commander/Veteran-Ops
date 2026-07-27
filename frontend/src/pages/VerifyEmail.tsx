import { AlertCircle, ArrowRight, CheckCircle2, MailCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { errorMessage } from '../hooks/useAsync'
import { auth } from '../lib/api'

/** Pull the signed token out of the URL. The verify link lands as
 * `.../verify-email#token=<jwt>` (fragment — never sent to server logs); a
 * `?token=` query is accepted as a fallback for older mailers. */
function readToken(): string | null {
  const rawHash = window.location.hash
  const hashParams = new URLSearchParams(rawHash.startsWith('#') ? rawHash.slice(1) : rawHash)
  const fromHash = hashParams.get('token')
  if (fromHash) return fromHash
  const query = new URLSearchParams(window.location.search)
  return query.get('token')
}

type Status = 'loading' | 'success' | 'error'

export function VerifyEmail() {
  const { user, refresh } = useAuth()
  const [status, setStatus] = useState<Status>('loading')
  const [message, setMessage] = useState<string | null>(null)
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current) return
    ran.current = true
    const token = readToken()
    // Scrub the token out of the address bar/history immediately.
    if (window.location.hash || window.location.search) {
      window.history.replaceState(null, '', window.location.pathname)
    }
    if (!token) {
      setStatus('error')
      setMessage('This link is invalid or has expired.')
      return
    }
    auth
      .confirmVerification(token)
      .then(async (res) => {
        setStatus('success')
        setMessage(res.message || 'Your email is verified.')
        // If we're signed in, refresh so the banner disappears app-wide.
        try {
          await refresh()
        } catch {
          /* not signed in — verification still succeeded */
        }
      })
      .catch((err) => {
        setStatus('error')
        setMessage(errorMessage(err) || 'This link is invalid or has expired.')
      })
  }, [refresh])

  return (
    <AuthShell>
      {status === 'loading' && (
        <div className="flex flex-col items-center gap-3 py-4 text-center">
          <Spinner size={22} />
          <p className="text-sm text-muted" role="status" aria-live="polite">
            Verifying your email…
          </p>
        </div>
      )}

      {status === 'success' && (
        <div className="animate-pop-in flex flex-col items-center gap-4 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-h-emerald-soft text-success">
            <CheckCircle2 size={28} />
          </span>
          <div>
            <h1 className="text-heading text-txt">Your email is verified</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              {message ?? 'Thanks — your account is all set.'}
            </p>
          </div>
          <Link to={user ? '/' : '/login'} className="vo-btn-primary group text-sm">
            {user ? 'Continue to Rating Raider' : 'Continue to sign in'}
            <ArrowRight size={15} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
          </Link>
        </div>
      )}

      {status === 'error' && (
        <div className="animate-pop-in flex flex-col items-center gap-4 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-danger-soft text-danger">
            <AlertCircle size={28} />
          </span>
          <div>
            <h1 className="text-heading text-txt">We couldn't verify that link</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              {message ?? 'This link is invalid or has expired.'} You can request a fresh verification email from
              your settings once signed in.
            </p>
          </div>
          <Link to={user ? '/' : '/login'} className="vo-btn-secondary text-sm">
            {user ? 'Back to Rating Raider' : 'Back to sign in'}
          </Link>
        </div>
      )}
    </AuthShell>
  )
}

/** The public-page frame: living aurora + wordmark + a single centered card —
 * matches the Login / SSO-callback front door so these flows feel native. */
function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative flex min-h-[100dvh] flex-col overflow-hidden">
      <div className="vo-aurora-live" aria-hidden="true">
        <i />
        <i />
        <i />
      </div>
      <div className="relative flex flex-1 items-center justify-center px-4 py-10">
        <div className="vo-page w-full max-w-md" data-section="home">
          <div className="mb-7 flex flex-col items-center text-center">
            <Wordmark size={44} />
          </div>
          <div className="vo-card p-6 shadow-pop sm:p-8">{children}</div>
          <p className="mt-6 flex items-center justify-center gap-1.5 text-center text-xs text-faint">
            <MailCheck size={13} /> Rating Raider · secure email verification
          </p>
        </div>
      </div>
    </div>
  )
}
