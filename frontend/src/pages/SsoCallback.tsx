import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'

const ERRORS: Record<string, string> = {
  not_entitled:
    "Your Unicorn Commander account isn't enabled for Rating Raider yet. Ask your administrator to grant access, then try again.",
  sso_failed: 'Single sign-on failed. Please try again.',
  bad_state: 'Your sign-in link expired. Please start again.',
  missing_code: 'Single sign-on did not complete. Please try again.',
  no_email: 'Your account has no email address, which Rating Raider requires.',
  email_unverified: 'Please verify your Unicorn Commander email, then sign in again.',
  no_account: 'No Rating Raider account exists for you, and self-service signup is off.',
}

/** Lands here from the backend OIDC callback with the token in the URL
 * FRAGMENT (#token=…) so it never appears in server/proxy logs — with a
 * ?token=… query fallback for older backends — or with ?error=… on failure. */
export function SsoCallback() {
  const [params] = useSearchParams()
  const { loginWithToken } = useAuth()
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const ran = useRef(false)

  useEffect(() => {
    if (ran.current) return
    ran.current = true
    // Fragment first (never sent to the server), query fallback for compat.
    const rawHash = window.location.hash
    const hashParams = new URLSearchParams(rawHash.startsWith('#') ? rawHash.slice(1) : rawHash)
    const token = hashParams.get('token') ?? params.get('token')
    const err = hashParams.get('error') ?? params.get('error')
    // Scrub the token (and everything else) out of the address bar and
    // history immediately so it never sits in browser history.
    if (rawHash || window.location.search) {
      window.history.replaceState(null, '', window.location.pathname)
    }
    if (err) {
      setError(ERRORS[err] ?? 'Sign-in could not be completed.')
      return
    }
    if (!token) {
      setError('Sign-in could not be completed.')
      return
    }
    loginWithToken(token)
      .then(() => navigate('/', { replace: true }))
      .catch(() => setError('Sign-in could not be completed.'))
  }, [params, loginWithToken, navigate])

  return (
    <div className="relative flex min-h-[100dvh] flex-col items-center justify-center overflow-hidden px-4">
      <div className="vo-aurora-live" aria-hidden="true">
        <i />
        <i />
        <i />
      </div>
      <div className="vo-page relative flex flex-col items-center" data-section="home">
        <Wordmark size={44} />
        {error ? (
          <div className="mt-6 w-full max-w-sm text-center">
            <div className="animate-pop-in rounded-xl border border-danger bg-danger-soft px-4 py-3 text-sm text-danger" role="alert">
              {error}
            </div>
            <button
              onClick={() => navigate('/login', { replace: true })}
              className="vo-btn-secondary mt-4 text-sm"
            >
              Back to sign in
            </button>
          </div>
        ) : (
          <p className="mt-6 flex items-center gap-2 text-sm text-muted" role="status" aria-live="polite">
            <Spinner size={16} /> Signing you in…
          </p>
        )}
      </div>
    </div>
  )
}
