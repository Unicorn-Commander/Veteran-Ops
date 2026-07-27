import { AlertCircle, ArrowRight, Ban, Clock, LogIn, LogOut, MailWarning, RefreshCw, Users } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Wordmark } from '../components/Brand'
import { Badge, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { useAuth } from '../context/AuthContext'
import { errorMessage } from '../hooks/useAsync'
import { invitesApi, setWorkspace } from '../lib/api'
import { humanize } from '../lib/format'
import type { InvitePreview } from '../types'

const PENDING_KEY = 'vo_pending_invite'

/** Read the invite token from the URL fragment (`#token=<jwt>`), query fallback. */
function readToken(): string | null {
  const rawHash = window.location.hash
  const hashParams = new URLSearchParams(rawHash.startsWith('#') ? rawHash.slice(1) : rawHash)
  const fromHash = hashParams.get('token')
  if (fromHash) return fromHash
  const query = new URLSearchParams(window.location.search)
  return query.get('token')
}

export function InviteAccept() {
  const { user, loading: authLoading, logout } = useAuth()
  const navigate = useNavigate()
  const { toast } = useToast()

  const [token, setToken] = useState<string | null>(null)
  const [tokenResolved, setTokenResolved] = useState(false)
  const [preview, setPreview] = useState<InvitePreview | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [previewNonce, setPreviewNonce] = useState(0)
  const [accepting, setAccepting] = useState(false)

  // Resolve the token from the URL (preferred) or a prior stash. Stashing it in
  // sessionStorage lets the veteran sign in and come back to this page with the
  // invite intact.
  useEffect(() => {
    const fromUrl = readToken()
    if (fromUrl) {
      try {
        sessionStorage.setItem(PENDING_KEY, fromUrl)
      } catch {
        /* storage unavailable — the URL token still works this session */
      }
      if (window.location.hash || window.location.search) {
        window.history.replaceState(null, '', window.location.pathname)
      }
      setToken(fromUrl)
    } else {
      let stashed: string | null = null
      try {
        stashed = sessionStorage.getItem(PENDING_KEY)
      } catch {
        /* noop */
      }
      setToken(stashed)
    }
    setTokenResolved(true)
  }, [])

  // Preview the invite once we know the token AND the user is signed in.
  useEffect(() => {
    if (!tokenResolved || authLoading) return
    if (!user || !token) return
    let active = true
    setPreviewLoading(true)
    setPreviewError(null)
    invitesApi
      .preview(token)
      .then((p) => {
        if (active) {
          setPreview(p)
          setPreviewLoading(false)
        }
      })
      .catch((err) => {
        if (active) {
          setPreviewError(errorMessage(err))
          setPreviewLoading(false)
        }
      })
    return () => {
      active = false
    }
  }, [tokenResolved, authLoading, user, token, previewNonce])

  const accept = async () => {
    if (!token) return
    setAccepting(true)
    try {
      const org = await invitesApi.accept(token)
      // Make the joined team the active tenant so /teams opens on it.
      setWorkspace(org.id)
      try {
        sessionStorage.removeItem(PENDING_KEY)
      } catch {
        /* noop */
      }
      toast(`You've joined ${org.name}.`, 'success')
      navigate('/teams', { replace: true })
    } catch (err) {
      toast(errorMessage(err), 'error')
      setAccepting(false)
    }
  }

  const switchAccount = () => {
    // Keep the stashed token so they can return after signing in as the invitee.
    logout()
    navigate('/login')
  }

  // ---- Render ----

  if (!tokenResolved || authLoading) {
    return (
      <AuthShell>
        <div className="flex flex-col items-center gap-3 py-4 text-center">
          <Spinner size={22} />
          <p className="text-sm text-muted" role="status" aria-live="polite">
            Loading your invitation…
          </p>
        </div>
      </AuthShell>
    )
  }

  if (!token) {
    return (
      <AuthShell>
        <StatusCard
          tone="error"
          icon={<AlertCircle size={28} />}
          title="No invitation found"
          body="This invitation link is missing or invalid. Ask whoever invited you to send a fresh link."
          action={
            <Link to="/login" className="vo-btn-secondary text-sm">
              Go to sign in
            </Link>
          }
        />
      </AuthShell>
    )
  }

  // Not signed in — instruct them to sign in with the invited email, then return.
  if (!user) {
    return (
      <AuthShell>
        <div className="animate-pop-in flex flex-col items-center gap-4 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-soft text-brand">
            <Users size={28} />
          </span>
          <div>
            <h1 className="text-heading text-txt">You've been invited to a team</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              Sign in — or create an account — with the email your invitation was sent to, then return to this
              link to accept.
            </p>
          </div>
          <Link to="/login" className="vo-btn-primary group text-sm">
            <LogIn size={15} />
            Sign in to accept
            <ArrowRight size={15} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
          </Link>
          <p className="text-xs text-faint">We'll keep your invitation ready while you sign in.</p>
        </div>
      </AuthShell>
    )
  }

  if (previewLoading) {
    return (
      <AuthShell>
        <div className="flex flex-col items-center gap-3 py-4 text-center">
          <Spinner size={22} />
          <p className="text-sm text-muted" role="status" aria-live="polite">
            Checking your invitation…
          </p>
        </div>
      </AuthShell>
    )
  }

  if (previewError || !preview) {
    return (
      <AuthShell>
        <StatusCard
          tone="error"
          icon={<AlertCircle size={28} />}
          title="We couldn't load this invitation"
          body={previewError ?? 'This invitation is invalid or has expired.'}
          action={
            <div className="flex flex-wrap items-center justify-center gap-2">
              {previewError && (
                <button
                  type="button"
                  onClick={() => setPreviewNonce((n) => n + 1)}
                  className="vo-btn-secondary text-sm"
                >
                  <RefreshCw size={15} />
                  Try again
                </button>
              )}
              <Link to="/" className="vo-btn-ghost text-sm">
                Back to Rating Raider
              </Link>
            </div>
          }
        />
      </AuthShell>
    )
  }

  // Non-pending states.
  if (preview.status !== 'pending') {
    const copy: Record<string, { icon: React.ReactNode; title: string; body: string }> = {
      expired: {
        icon: <Clock size={28} />,
        title: 'This invitation has expired',
        body: `Your invitation to ${preview.org_name} is no longer valid. Ask an admin to send you a new one.`,
      },
      accepted: {
        icon: <Users size={28} />,
        title: 'This invitation was already used',
        body: `You're already a member of ${preview.org_name}. Head to Teams to manage it.`,
      },
      revoked: {
        icon: <Ban size={28} />,
        title: 'This invitation was revoked',
        body: `Your invitation to ${preview.org_name} was withdrawn. Ask an admin to send a new one if this is a mistake.`,
      },
    }
    const c = copy[preview.status] ?? copy.expired
    return (
      <AuthShell>
        <StatusCard
          tone={preview.status === 'accepted' ? 'neutral' : 'error'}
          icon={c.icon}
          title={c.title}
          body={c.body}
          action={
            <Link to={preview.status === 'accepted' ? '/teams' : '/'} className="vo-btn-secondary text-sm">
              {preview.status === 'accepted' ? 'Go to Teams' : 'Back to Rating Raider'}
            </Link>
          }
        />
      </AuthShell>
    )
  }

  // Pending, but the signed-in account's email doesn't match the invitee.
  if (!preview.email_matches) {
    return (
      <AuthShell>
        <div className="animate-pop-in flex flex-col items-center gap-4 text-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-h-amber-soft text-warn">
            <MailWarning size={28} />
          </span>
          <div>
            <h1 className="text-heading text-txt">This invitation is for a different email</h1>
            <p className="mt-1.5 text-sm leading-relaxed text-muted">
              <strong className="text-txt">{preview.org_name}</strong> invited{' '}
              <strong className="text-txt">{preview.email}</strong>, but you're signed in as{' '}
              <strong className="text-txt">{user.email}</strong>. Sign in with the invited email to accept.
            </p>
          </div>
          <button onClick={switchAccount} className="vo-btn-primary text-sm">
            <LogOut size={15} />
            Sign in with a different account
          </button>
          <Link to="/" className="text-sm font-semibold text-muted transition-colors hover:text-txt">
            Not now
          </Link>
        </div>
      </AuthShell>
    )
  }

  // Pending + email matches → the happy path.
  return (
    <AuthShell>
      <div className="animate-pop-in flex flex-col items-center gap-5 text-center">
        <span className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-soft text-brand">
          <Users size={28} />
        </span>
        <div>
          <h1 className="text-heading text-txt">Join {preview.org_name}</h1>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">
            {preview.invited_by_email ? (
              <>
                <strong className="text-txt">{preview.invited_by_email}</strong> invited you to collaborate.
              </>
            ) : (
              <>You've been invited to collaborate.</>
            )}
          </p>
        </div>

        <div className="w-full space-y-2.5 rounded-2xl border border-line bg-surface2 p-4 text-left text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted">Team</span>
            <span className="font-semibold text-txt">{preview.org_name}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted">Your role</span>
            <Badge tone="primary">{humanize(preview.role)}</Badge>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-muted">Invited email</span>
            <span className="truncate font-medium text-txt">{preview.email}</span>
          </div>
        </div>

        <button onClick={accept} disabled={accepting} className="vo-btn-primary w-full">
          {accepting ? <Spinner size={16} className="text-white" /> : <Users size={16} />}
          Accept invitation
        </button>
        <Link to="/" className="text-sm font-semibold text-muted transition-colors hover:text-txt">
          Maybe later
        </Link>
      </div>
    </AuthShell>
  )
}

function StatusCard({
  tone,
  icon,
  title,
  body,
  action,
}: {
  tone: 'error' | 'neutral'
  icon: React.ReactNode
  title: string
  body: string
  action?: React.ReactNode
}) {
  return (
    <div
      className="animate-pop-in flex flex-col items-center gap-4 text-center"
      role={tone === 'error' ? 'alert' : undefined}
    >
      <span
        className={
          tone === 'error'
            ? 'flex h-14 w-14 items-center justify-center rounded-full bg-danger-soft text-danger'
            : 'flex h-14 w-14 items-center justify-center rounded-full bg-surface2 text-muted'
        }
      >
        {icon}
      </span>
      <div>
        <h1 className="text-heading text-txt">{title}</h1>
        <p className="mt-1.5 text-sm leading-relaxed text-muted">{body}</p>
      </div>
      {action}
    </div>
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
