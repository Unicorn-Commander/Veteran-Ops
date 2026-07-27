import { Eye, EyeOff, Lock, Mail, Sparkles, User as UserIcon } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { DISCLAIMER_TEXT } from '../components/Disclaimer'
import { Spinner } from '../components/ui'
import { useAuth } from '../context/AuthContext'
import { errorMessage } from '../hooks/useAsync'
import { auth as authApi, ssoLoginUrl } from '../lib/api'
import type { AuthConfig } from '../types'

type Mode = 'login' | 'register'

export function Login() {
  const [mode, setMode] = useState<Mode>('login')
  const { login, register } = useAuth()
  const navigate = useNavigate()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [config, setConfig] = useState<AuthConfig | null>(null)
  const [configError, setConfigError] = useState(false)
  const [configAttempt, setConfigAttempt] = useState(0)

  useEffect(() => {
    let active = true
    setConfig(null)
    setConfigError(false)
    void authApi.config()
      .then((value) => {
        if (active) {
          setConfig(value)
          if (!value.registration_open) setMode('login')
        }
      })
      .catch(() => {
        if (active) setConfigError(true)
      })
    return () => {
      active = false
    }
  }, [configAttempt])

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (mode === 'login') {
        await login(email.trim(), password)
      } else {
        await register(email.trim(), password, fullName.trim())
      }
      navigate('/', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const isLogin = mode === 'login'

  return (
    <main className="relative flex min-h-[100dvh] flex-col overflow-hidden">
      {/* The living aurora — the front door's one moment of drama. Three
          blurred hue blobs on slow offset drifts (CSS-only, reduced-motion
          collapses them to a static wash). */}
      <div className="vo-aurora-live" aria-hidden="true">
        <i />
        <i />
        <i />
      </div>

      <div className="relative flex flex-1 items-center justify-center px-4 py-10">
        <div className="vo-page w-full max-w-md" data-section="home">
          <div className="mb-7 flex flex-col items-center text-center">
            <Wordmark size={48} />
            <p className="mt-3 max-w-sm text-body text-muted">
              {isLogin
                ? 'Welcome back. Pick up your claim where you left off.'
                : 'Create your account to start organizing your claim — your data, your call.'}
            </p>
          </div>

          <div className="vo-card p-6 shadow-pop sm:p-8">
            {!config && !configError && (
              <div className="flex min-h-32 items-center justify-center gap-2 text-sm text-muted" role="status">
                <Spinner size={17} /> Checking sign-in options…
              </div>
            )}

            {configError && (
              <div role="alert" className="space-y-4 rounded-control border border-warn/40 bg-h-amber-soft p-4 text-sm">
                <p className="text-txt">
                  We couldn't load the available sign-in options. Please try again.
                </p>
                <button type="button" onClick={() => setConfigAttempt((value) => value + 1)} className="vo-btn-secondary w-full">
                  Try again
                </button>
              </div>
            )}

            {config && (
              <>
                {config.sso_enabled && (
                  <a href={ssoLoginUrl()} className="vo-btn-primary group w-full justify-center py-3 text-body">
                    <Sparkles size={16} className="transition-transform duration-200 ease-out group-hover:rotate-12 group-hover:scale-110" />
                    Sign in with {config.sso_label}
                  </a>
                )}

                {config.sso_enabled && config.password_login_enabled && (
                  <div className="my-5 flex items-center gap-3 text-xs text-faint">
                    <span className="h-px flex-1 bg-line" />
                    or use your password
                    <span className="h-px flex-1 bg-line" />
                  </div>
                )}

                {config.password_login_enabled && (
                  <>
                    {config.registration_open && (
                      <div className="mb-6 grid grid-cols-2 gap-1 rounded-xl border border-line bg-surface2 p-1">
                        <TabButton active={isLogin} onClick={() => setMode('login')}>
                          Sign in
                        </TabButton>
                        <TabButton active={!isLogin} onClick={() => setMode('register')}>
                          Create account
                        </TabButton>
                      </div>
                    )}

                    <form onSubmit={onSubmit} className="space-y-4" noValidate>
                      {!isLogin && (
                        <Field id="full_name" label="Full name" icon={<UserIcon size={16} />}>
                          <input
                            id="full_name"
                            className="vo-input pl-9"
                            type="text"
                            autoComplete="name"
                            placeholder="Alex Rivera"
                            value={fullName}
                            onChange={(e) => setFullName(e.target.value)}
                            required={!isLogin}
                          />
                        </Field>
                      )}

                      <Field id="email" label="Email" icon={<Mail size={16} />}>
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
                      </Field>

                      <Field id="password" label="Password" icon={<Lock size={16} />}>
                        <input
                          id="password"
                          className="vo-input pl-9 pr-12"
                          type={showPw ? 'text' : 'password'}
                          autoComplete={isLogin ? 'current-password' : 'new-password'}
                          placeholder={isLogin ? 'Your password' : 'At least 8 characters'}
                          value={password}
                          onChange={(e) => setPassword(e.target.value)}
                          minLength={isLogin ? undefined : 8}
                          required
                        />
                        <button
                          type="button"
                          onClick={() => setShowPw((s) => !s)}
                          aria-label={showPw ? 'Hide password' : 'Show password'}
                          className="absolute right-0 top-[26px] flex h-11 w-11 items-center justify-center rounded-lg text-faint transition-colors hover:text-txt"
                        >
                          {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                        </button>
                      </Field>

                      {isLogin && config.password_reset_enabled && (
                        <div className="-mt-1 text-right">
                          <Link
                            to="/forgot-password"
                            className="inline-flex min-h-11 items-center text-sm font-semibold text-brand transition-colors hover:text-brand-hover"
                          >
                            Forgot password?
                          </Link>
                        </div>
                      )}

                      {error && (
                        <div role="alert" className="animate-pop-in rounded-xl border border-danger bg-danger-soft px-3.5 py-2.5 text-sm text-danger">
                          {error}
                        </div>
                      )}

                      <button type="submit" disabled={submitting} className="vo-btn-primary w-full">
                        {submitting && <Spinner size={16} className="text-white" />}
                        {isLogin ? 'Sign in' : 'Create account'}
                      </button>
                    </form>

                    {config.registration_open && (
                      <p className="mt-5 text-center text-sm text-muted">
                        {isLogin ? "Don't have an account? " : 'Already have an account? '}
                        <button
                          onClick={() => setMode(isLogin ? 'register' : 'login')}
                          className="min-h-11 font-semibold text-brand transition-colors hover:text-brand-hover"
                        >
                          {isLogin ? 'Create one' : 'Sign in'}
                        </button>
                      </p>
                    )}
                  </>
                )}

                {!config.sso_enabled && !config.password_login_enabled && (
                  <div role="status" className="rounded-control border border-line bg-surface2 p-4 text-sm text-muted">
                    Access is currently closed on this instance. Contact its administrator for enrollment help.
                  </div>
                )}

                {config.sso_enabled && !config.password_login_enabled && (
                  <p className="mt-4 text-center text-sm text-muted">Use {config.sso_label} to access your account.</p>
                )}
              </>
            )}
          </div>

          <p className="mt-6 px-2 text-center text-xs leading-relaxed text-muted">{DISCLAIMER_TEXT}</p>

          <p className="mt-5 text-center text-xs text-faint">
            Made with care by{' '}
            <a
              href="https://magicunicorn.tech"
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-11 items-center font-semibold text-muted transition-colors hover:text-brand"
            >
              Magic Unicorn
            </a>
          </p>
        </div>
      </div>
    </main>
  )
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`min-h-11 rounded-lg py-2 text-sm font-semibold transition-all duration-200 ease-out ${
        active ? 'bg-surface text-txt shadow-sm' : 'text-muted hover:text-txt'
      }`}
    >
      {children}
    </button>
  )
}

function Field({
  id,
  label,
  icon,
  children,
}: {
  id: string
  label: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="relative">
      <label htmlFor={id} className="vo-label">
        {label}
      </label>
      <span className="pointer-events-none absolute left-3 top-[34px] text-faint">{icon}</span>
      {children}
    </div>
  )
}
