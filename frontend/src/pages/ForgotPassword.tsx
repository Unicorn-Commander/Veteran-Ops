import { ArrowLeft, CheckCircle2, Mail } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { Spinner } from '../components/ui'
import { errorMessage } from '../hooks/useAsync'
import { auth } from '../lib/api'

export function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [sent, setSent] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const res = await auth.forgotPassword(email.trim())
      // Always show the same neutral message — never reveal whether the
      // account exists.
      setMessage(res.message || "If that email has an account, we've sent a reset link.")
      setSent(true)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthShell>
      {sent ? (
        <div className="animate-pop-in flex flex-col items-center gap-4 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-h-emerald-soft text-success">
            <CheckCircle2 size={28} />
          </span>
          <div>
            <h1 className="text-heading text-txt">Check your inbox</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              {message ?? "If that email has an account, we've sent a link to reset your password."}
            </p>
          </div>
          <Link to="/login" className="vo-btn-secondary group text-sm">
            <ArrowLeft size={15} className="transition-transform duration-200 ease-out group-hover:-translate-x-0.5" />
            Back to sign in
          </Link>
        </div>
      ) : (
        <>
          <div className="mb-6 text-center">
            <h1 className="text-heading text-txt">Reset your password</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              Enter your email and we'll send you a link to set a new one.
            </p>
          </div>

          <form onSubmit={onSubmit} className="space-y-4" noValidate>
            <div className="relative">
              <label htmlFor="email" className="vo-label">
                Email
              </label>
              <span className="pointer-events-none absolute left-3 top-[34px] text-faint">
                <Mail size={16} />
              </span>
              <input
                id="email"
                className="vo-input pl-9"
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            {error && (
              <div role="alert" className="animate-pop-in rounded-xl border border-danger bg-danger-soft px-3.5 py-2.5 text-sm text-danger">
                {error}
              </div>
            )}

            <button type="submit" disabled={submitting} className="vo-btn-primary w-full">
              {submitting && <Spinner size={16} className="text-white" />}
              Send reset link
            </button>
          </form>

          <p className="mt-5 text-center text-sm text-muted">
            Remembered it?{' '}
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
