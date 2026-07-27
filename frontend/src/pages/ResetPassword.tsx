import { AlertCircle, CheckCircle2, Eye, EyeOff, Lock } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { Spinner } from '../components/ui'
import { errorMessage } from '../hooks/useAsync'
import { auth } from '../lib/api'

/** Read the signed reset token from the URL fragment (`#token=<jwt>`), with a
 * `?token=` query fallback. Mirrors VerifyEmail / SsoCallback. */
function readToken(): string | null {
  const rawHash = window.location.hash
  const hashParams = new URLSearchParams(rawHash.startsWith('#') ? rawHash.slice(1) : rawHash)
  const fromHash = hashParams.get('token')
  if (fromHash) return fromHash
  const query = new URLSearchParams(window.location.search)
  return query.get('token')
}

const MIN_LEN = 8

export function ResetPassword() {
  const [token, setTokenState] = useState<string | null>(null)
  const [noToken, setNoToken] = useState(false)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const t = readToken()
    // Scrub the token out of the address bar so it never sits in history.
    if (window.location.hash || window.location.search) {
      window.history.replaceState(null, '', window.location.pathname)
    }
    if (!t) {
      setNoToken(true)
      return
    }
    setTokenState(t)
  }, [])

  const tooShort = password.length > 0 && password.length < MIN_LEN
  const mismatch = confirm.length > 0 && confirm !== password
  const canSubmit = password.length >= MIN_LEN && confirm === password && !submitting

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!token || !canSubmit) return
    setError(null)
    setSubmitting(true)
    try {
      const res = await auth.resetPassword(token, password)
      setMessage(res.message || 'Your password has been reset.')
      setDone(true)
    } catch (err) {
      setError(errorMessage(err) || 'This link is invalid or has expired.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthShell>
      {noToken ? (
        <div className="animate-pop-in flex flex-col items-center gap-4 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-danger-soft text-danger">
            <AlertCircle size={28} />
          </span>
          <div>
            <h1 className="text-heading text-txt">This link is invalid or has expired</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              Request a fresh reset link and we'll email you a new one.
            </p>
          </div>
          <Link to="/forgot-password" className="vo-btn-primary text-sm">
            Request a new link
          </Link>
        </div>
      ) : done ? (
        <div className="animate-pop-in flex flex-col items-center gap-4 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-h-emerald-soft text-success">
            <CheckCircle2 size={28} />
          </span>
          <div>
            <h1 className="text-heading text-txt">Password reset</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              {message ?? 'Your password has been reset. You can sign in with it now.'}
            </p>
          </div>
          <Link to="/login" className="vo-btn-primary text-sm">
            Continue to sign in
          </Link>
        </div>
      ) : (
        <>
          <div className="mb-6 text-center">
            <h1 className="text-heading text-txt">Set a new password</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              Choose a strong password — at least {MIN_LEN} characters.
            </p>
          </div>

          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div className="relative">
              <label htmlFor="password" className="vo-label">
                New password
              </label>
              <span className="pointer-events-none absolute left-3 top-[34px] text-faint">
                <Lock size={16} />
              </span>
              <input
                id="password"
                className="vo-input pl-9 pr-12"
                type={showPw ? 'text' : 'password'}
                autoComplete="new-password"
                placeholder={`At least ${MIN_LEN} characters`}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                minLength={MIN_LEN}
                required
              />
              <button
                type="button"
                onClick={() => setShowPw((s) => !s)}
                aria-label={showPw ? 'Hide password' : 'Show password'}
                className="absolute right-1 top-[26px] flex h-10 w-10 items-center justify-center rounded-lg text-faint transition-colors hover:text-txt"
              >
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>

            <div className="relative">
              <label htmlFor="confirm" className="vo-label">
                Confirm password
              </label>
              <span className="pointer-events-none absolute left-3 top-[34px] text-faint">
                <Lock size={16} />
              </span>
              <input
                id="confirm"
                className="vo-input pl-9"
                type={showPw ? 'text' : 'password'}
                autoComplete="new-password"
                placeholder="Re-enter your new password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                minLength={MIN_LEN}
                required
              />
            </div>

            {(tooShort || mismatch) && (
              <p className="text-xs text-warn" aria-live="polite">
                {tooShort ? `Use at least ${MIN_LEN} characters.` : "Those passwords don't match yet."}
              </p>
            )}

            {error && (
              <div role="alert" className="animate-pop-in rounded-xl border border-danger bg-danger-soft px-3.5 py-2.5 text-sm text-danger">
                {error}
              </div>
            )}

            <button type="submit" disabled={!canSubmit} className="vo-btn-primary w-full">
              {submitting && <Spinner size={16} className="text-white" />}
              Reset password
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-muted">
            <Link to="/login" className="font-semibold text-brand transition-colors hover:text-brand-hover">
              Back to sign in
            </Link>
          </p>
        </>
      )}
    </AuthShell>
  )
}

/** Public-page frame matching the Login front door (living aurora + wordmark). */
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
        </div>
      </div>
    </div>
  )
}
