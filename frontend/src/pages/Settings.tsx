import {
  CheckCircle2,
  Download,
  Landmark,
  Link2Off,
  Loader2,
  LogOut,
  Mail,
  Moon,
  Puzzle,
  RefreshCw,
  Rocket,
  RotateCcw,
  ShieldAlert,
  Sun,
  Trash2,
  TriangleAlert,
  XCircle,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Panel, Spinner } from '../components/ui'
import { CFileProcessing } from '../components/CFileProcessing'
import { useAuth } from '../context/AuthContext'
import { DISCLAIMER_TEXT } from '../components/Disclaimer'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { accountApi, deadlinesApi, documentsApi, glitterApi, vaApi } from '../lib/api'
import { formatDateTime } from '../lib/format'
import type { ResetRecords, VaApiKey, VaConnectionStatus } from '../types'

function GroupLabel({ children }: { children: ReactNode }) {
  return <h2 className="vo-label-micro px-1">{children}</h2>
}

/** Status dot semantics shared by connection rows: gray/still = unknown or
 * not configured, amber = configured but unreachable, green (with a soft
 * glow) = connected and healthy. */
function StatusDot({ tone }: { tone: 'neutral' | 'warning' | 'success' }) {
  const color = tone === 'success' ? 'var(--success)' : tone === 'warning' ? 'var(--warning)' : 'var(--faint)'
  return (
    <span
      aria-hidden
      className="inline-block h-2 w-2 shrink-0 rounded-full"
      style={{ background: color, boxShadow: tone === 'success' ? `0 0 6px ${color}` : 'none' }}
    />
  )
}

/** Settings Connections — Glitter Mane health chart bridge (WAVE2-SPEC §5).
 * GM = living health chart (source of truth). Rating Raider = claim workspace.
 * Import is confirm-first; no automatic dual-write. */
function ConnectionsCard() {
  const { data, loading, error, reload } = useAsync(() => glitterApi.status())
  const tone: 'neutral' | 'warning' | 'success' =
    loading || error || !data?.enabled ? 'neutral' : data.reachable ? 'success' : 'warning'

  return (
    <Panel hue="violet" title="Connections" subtitle="Health chart & suite bridges — optional, confirm-first">
      <div className="space-y-3 p-5">
        <p className="text-xs leading-relaxed text-muted">
          <strong className="font-semibold text-txt">Glitter Mane</strong> holds your ongoing health record.
          <strong className="font-semibold text-txt"> Rating Raider</strong> holds the VA claim. When connected
          (same Unicorn Commander account), you can import conditions, check-ins, and measurements into the claim —
          tagged with provenance. Nothing dual-writes in the background.
        </p>
        <div className="flex items-start justify-between gap-3 rounded-control border border-line bg-surface2 px-4 py-3.5">
          <div className="flex items-start gap-2.5">
            <Puzzle size={16} className="mt-0.5 shrink-0 text-h-violet" />
            <div>
              <div className="flex items-center gap-1.5">
                <StatusDot tone={tone} />
                <p className="text-sm font-semibold text-txt">Glitter Mane</p>
              </div>
              <p className="mt-0.5 text-xs text-muted">
                Personal health chart — import into claims when you choose.
              </p>
              {loading ? (
                <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted">
                  <Spinner size={12} /> Checking…
                </p>
              ) : error || !data?.enabled ? (
                <p className="mt-1.5 text-xs text-faint">Not configured — set by your administrator on this host.</p>
              ) : data.reachable ? (
                <p className="mt-1.5 flex items-center gap-1.5 text-xs text-success">
                  <CheckCircle2 size={13} /> Connected and reachable
                </p>
              ) : (
                <p className="mt-1.5 flex items-center gap-1.5 text-xs text-danger">
                  <XCircle size={13} /> Configured but not reachable right now{data.detail ? ` — ${data.detail}` : ''}
                </p>
              )}
            </div>
          </div>
          <button
            onClick={reload}
            className="vo-icon-btn vo-btn-ghost text-muted hover:text-txt"
            aria-label="Recheck connection"
            title="Recheck"
          >
            <RefreshCw size={14} />
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/conditions?import=glitter" className="vo-btn-secondary text-xs">
            Conditions import
          </Link>
          <Link to="/symptom-log" className="vo-btn-secondary text-xs">
            Symptom log
          </Link>
          <a
            href="https://glittermane.magicunicorn.dev"
            target="_blank"
            rel="noreferrer"
            className="vo-btn-ghost text-xs"
          >
            Open Glitter Mane
          </a>
        </div>
      </div>
    </Panel>
  )
}

/** The two VA Lighthouse API families the backend supports (routers/va.py:
 * OAuth is per-API, so each row connects independently). */
const VA_APIS: { key: VaApiKey; label: string; description: string }[] = [
  {
    key: 'verification',
    label: 'Service History & Ratings',
    description: 'Pull your service periods, combined rating, and individual ratings straight from VA.',
  },
  {
    key: 'claims',
    label: 'Claims',
    description: 'Track your open claims, decision letters, and Intent to File.',
  },
]

/** VA.gov (Lighthouse) connection card — wave 3. The veteran signs in AT
 * VA.gov (Login.gov / ID.me) and consents there; Veteran-Ops never sees the
 * VA.gov password. Handles the /settings?va=connected|error landing from the
 * OAuth callback (backend _landing()). */
function VaConnectionsCard() {
  const { toast } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const { data, loading, error, reload } = useAsync(() => vaApi.status())
  const [busy, setBusy] = useState<VaApiKey | null>(null)
  const handledLanding = useRef(false)

  // OAuth callback landing: ?va=connected&api=… or ?va=error&reason=…
  useEffect(() => {
    if (handledLanding.current) return
    const va = searchParams.get('va')
    if (!va) return
    handledLanding.current = true
    if (va === 'connected') {
      const api = searchParams.get('api')
      const label = VA_APIS.find((a) => a.key === api)?.label ?? 'VA'
      toast(`VA connected — ${label}. You consented at VA.gov; you can revoke anytime.`, 'success')
    } else {
      const reason = searchParams.get('reason')
      toast(`VA connection didn't complete${reason ? ` — ${reason.replace(/_/g, ' ')}` : ''}. You can try again below.`, 'error')
    }
    const next = new URLSearchParams(searchParams)
    next.delete('va')
    next.delete('api')
    next.delete('reason')
    setSearchParams(next, { replace: true })
    reload()
  }, [searchParams, setSearchParams, toast, reload])

  const connect = async (api: VaApiKey) => {
    setBusy(api)
    try {
      const { authorize_url } = await vaApi.connect(api)
      // Full-page navigation to VA's sign-in — the veteran consents there.
      window.location.assign(authorize_url)
    } catch (err) {
      toast(errorMessage(err), 'error')
      setBusy(null)
    }
  }

  const disconnect = async (api: VaApiKey, label: string) => {
    if (
      !window.confirm(
        `Disconnect ${label}? Rating Raider deletes its access immediately. You can also revoke from your VA.gov connected-apps page.`
      )
    )
      return
    setBusy(api)
    try {
      await vaApi.disconnect(api)
      toast(`${label} disconnected.`, 'success')
      reload()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(null)
    }
  }

  const connections = data?.connections ?? []
  const connFor = (api: VaApiKey): VaConnectionStatus | undefined => connections.find((c) => c.api === api)
  const verificationConnected = Boolean(connFor('verification'))
  const claimsConnected = Boolean(connFor('claims'))

  return (
    <Panel hue="violet" title="VA.gov (Lighthouse)" subtitle="Your own VA sign-in — read your official records">
      <div className="space-y-3 p-5">
        <div className="flex items-start gap-2.5">
          <Landmark size={16} className="mt-0.5 shrink-0 text-h-violet" />
          <p className="text-xs leading-relaxed text-muted">
            You sign in at VA.gov (Login.gov or ID.me) and consent there — Veteran-Ops never sees your VA.gov
            password, and you can revoke access anytime, here or from VA.gov's connected-apps page.
          </p>
        </div>

        {loading ? (
          <p className="flex items-center gap-1.5 text-xs text-muted">
            <Spinner size={12} /> Checking VA connection…
          </p>
        ) : error ? (
          <p className="flex items-center gap-1.5 text-xs text-danger">
            <XCircle size={13} /> Couldn't check the VA connection — {error}
          </p>
        ) : !data?.enabled ? (
          <p className="text-xs text-faint">
            The VA connection isn't configured on this server — this is set up by your administrator. Everything else
            in Rating Raider works without it.
          </p>
        ) : (
          <>
            {VA_APIS.map(({ key, label, description }) => {
              const conn = connFor(key)
              const stale = conn?.needs_reconnect ?? false
              return (
                <div
                  key={key}
                  className="flex flex-wrap items-start justify-between gap-3 rounded-control border border-line bg-surface2 px-4 py-3.5"
                  style={stale ? { borderColor: 'color-mix(in srgb, var(--warning) 45%, transparent)' } : undefined}
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <StatusDot tone={conn ? (stale ? 'warning' : 'success') : 'neutral'} />
                      <p className="text-sm font-semibold text-txt">{label}</p>
                    </div>
                    <p className="mt-0.5 text-xs text-muted">{description}</p>
                    {conn && !stale && (
                      <p className="mt-1.5 flex items-center gap-1.5 text-xs text-success">
                        <CheckCircle2 size={13} /> Connected {formatDateTime(conn.connected_at)}
                        {conn.last_sync_at ? ` · last pull ${formatDateTime(conn.last_sync_at)}` : ''}
                      </p>
                    )}
                    {conn && stale && (
                      <p className="mt-1.5 flex items-center gap-1.5 text-xs" style={{ color: 'var(--warning)' }}>
                        <TriangleAlert size={13} /> Your VA sign-in expired — reconnect to keep pulling your records.
                      </p>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {conn ? (
                      <>
                        {stale && (
                          <button onClick={() => void connect(key)} disabled={busy !== null} className="vo-btn-primary text-xs">
                            {busy === key ? <Spinner size={13} className="text-white" /> : <RefreshCw size={13} />} Reconnect
                          </button>
                        )}
                        <button
                          onClick={() => void disconnect(key, label)}
                          disabled={busy !== null}
                          className="vo-btn-ghost text-xs text-muted hover:text-danger"
                        >
                          <Link2Off size={13} /> Disconnect
                        </button>
                      </>
                    ) : (
                      <button onClick={() => void connect(key)} disabled={busy !== null} className="vo-btn-secondary text-xs">
                        {busy === key ? <Spinner size={13} /> : null} Connect at VA.gov
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
            {(verificationConnected || claimsConnected) && (
              <p className="text-xs text-muted">
                {verificationConnected && (
                  <>
                    <Link to="/va-sync" className="font-semibold text-brand hover:text-brand-hover">
                      Review what VA has on file
                    </Link>{' '}
                    — nothing changes here until you confirm it.{' '}
                  </>
                )}
                {claimsConnected && (
                  <>
                    Track your claims on the{' '}
                    <Link to="/claims" className="font-semibold text-brand hover:text-brand-hover">
                      Claims status
                    </Link>{' '}
                    page.
                  </>
                )}
              </p>
            )}
          </>
        )}
      </div>
    </Panel>
  )
}

/** Data portability + erasure (WAVE9). Export downloads the whole case file;
 * delete is irreversible and guarded by typing the account email exactly. */
function DataCard() {
  const { user, logout } = useAuth()
  const { toast } = useToast()
  const navigate = useNavigate()
  const [exporting, setExporting] = useState<'archive' | 'json' | null>(null)
  const [armed, setArmed] = useState(false)
  const [confirmEmail, setConfirmEmail] = useState('')
  const [deleting, setDeleting] = useState(false)
  const [resetArmed, setResetArmed] = useState(false)
  const [resetConfirm, setResetConfirm] = useState('')
  const [resetting, setResetting] = useState(false)
  const [resetDone, setResetDone] = useState<ResetRecords | null>(null)

  const canReset = resetConfirm.trim().toUpperCase() === 'RESET'
  const doReset = async () => {
    if (!canReset) return
    setResetting(true)
    try {
      const res = await documentsApi.reset()
      setResetDone(res)
      setResetArmed(false)
      setResetConfirm('')
      toast(`Records reset — ${res.documents} document${res.documents === 1 ? '' : 's'} and all derived analysis cleared.`, 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setResetting(false)
    }
  }

  const doExport = async (kind: 'archive' | 'json') => {
    setExporting(kind)
    try {
      if (kind === 'archive') await accountApi.exportArchive()
      else await accountApi.exportJson()
      toast('Your data is downloading.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setExporting(null)
    }
  }

  const emailMatches =
    confirmEmail.trim().toLowerCase() === (user?.email ?? '').trim().toLowerCase() &&
    confirmEmail.trim() !== ''

  const doDelete = async () => {
    if (!emailMatches) return
    setDeleting(true)
    try {
      await accountApi.deleteAccount(confirmEmail.trim())
      toast('Your account and all data have been permanently deleted.', 'success')
      logout()
      navigate('/login', { replace: true })
    } catch (err) {
      toast(errorMessage(err), 'error')
      setDeleting(false)
    }
  }

  return (
    <Panel hue="violet" title="Your data" subtitle="It's yours — take it or erase it, anytime">
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-txt">Download everything</h2>
            <p className="text-sm text-muted">
              A ZIP with your portable account data and every retained original record. A data-only JSON download is
              also available for large accounts.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => void doExport('archive')} disabled={exporting !== null} className="vo-btn-secondary shrink-0 text-sm">
              {exporting === 'archive' ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
              {exporting === 'archive' ? 'Preparing…' : 'Download archive'}
            </button>
            <button onClick={() => void doExport('json')} disabled={exporting !== null} className="vo-btn-ghost min-h-11 shrink-0 text-sm">
              {exporting === 'json' ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
              Data only (JSON)
            </button>
          </div>
        </div>

        <div className="rounded-control border border-line bg-surface2 p-4">
          <div className="flex items-start gap-2.5">
            <RotateCcw size={16} className="mt-0.5 shrink-0 text-muted" />
            <div className="min-w-0 flex-1">
              <h2 className="text-sm font-semibold text-txt">Reset my records</h2>
              <p className="mt-0.5 text-sm text-muted">
                Erases your uploaded documents and everything derived from them — conditions, evidence, search chunks,
                and analysis caches — but <strong className="font-semibold text-txt">keeps</strong> your account, profile,
                deadlines, and analysis-run history. A clean slate to re-upload your C-file.
              </p>
              {resetDone ? (
                <p className="mt-3 flex items-start gap-2 rounded-control border border-line bg-surface px-3 py-2 text-sm text-txt">
                  <CheckCircle2 size={15} className="mt-0.5 shrink-0" style={{ color: 'var(--success)' }} />
                  <span>
                    Done — cleared {resetDone.documents} document{resetDone.documents === 1 ? '' : 's'}, {resetDone.conditions}{' '}
                    condition{resetDone.conditions === 1 ? '' : 's'}, and all derived analysis. Re-upload your C-file to start fresh.
                  </span>
                </p>
              ) : !resetArmed ? (
                <button
                  onClick={() => setResetArmed(true)}
                  className="vo-btn-ghost mt-3 text-sm text-muted hover:text-txt"
                >
                  <RotateCcw size={15} /> Reset my records…
                </button>
              ) : (
                <div className="mt-3 space-y-2.5">
                  <label htmlFor="reset-confirm" className="block text-xs font-semibold text-txt">
                    Type <span className="font-mono font-semibold">RESET</span> to confirm:
                  </label>
                  <input
                    id="reset-confirm"
                    type="text"
                    autoComplete="off"
                    value={resetConfirm}
                    onChange={(e) => setResetConfirm(e.target.value)}
                    placeholder="RESET"
                    className="vo-input"
                  />
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => void doReset()} disabled={!canReset || resetting} className="vo-btn-primary text-sm">
                      {resetting ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />}
                      Reset my records
                    </button>
                    <button
                      onClick={() => {
                        setResetArmed(false)
                        setResetConfirm('')
                      }}
                      className="vo-btn-ghost text-sm"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="rounded-control border border-danger-soft bg-danger-soft/40 p-4">
          <div className="flex items-start gap-2.5">
            <TriangleAlert size={16} className="mt-0.5 shrink-0 text-danger" />
            <div className="min-w-0 flex-1">
              <h2 className="text-sm font-semibold text-txt">Delete my account</h2>
              <p className="mt-0.5 text-sm text-muted">
                Permanently erases your account and all your data — conditions, evidence, uploaded documents, everything.
                This cannot be undone. Consider downloading your data first.
              </p>
              {!armed ? (
                <button
                  onClick={() => setArmed(true)}
                  className="vo-btn-ghost mt-3 text-sm text-danger hover:bg-danger-soft"
                >
                  <Trash2 size={15} /> Delete my account…
                </button>
              ) : (
                <div className="mt-3 space-y-2.5">
                  <label htmlFor="delete-confirm-email" className="block text-xs font-semibold text-txt">
                    Type your email <span className="text-muted">({user?.email})</span> to confirm:
                  </label>
                  <input
                    id="delete-confirm-email"
                    type="email"
                    autoComplete="off"
                    value={confirmEmail}
                    onChange={(e) => setConfirmEmail(e.target.value)}
                    placeholder={user?.email ?? 'your email'}
                    className="vo-input focus:border-danger"
                  />
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={doDelete}
                      disabled={!emailMatches || deleting}
                      className="vo-btn-danger text-sm"
                    >
                      {deleting ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                      {deleting ? 'Deleting…' : 'Permanently delete everything'}
                    </button>
                    <button
                      onClick={() => {
                        setArmed(false)
                        setConfirmEmail('')
                      }}
                      disabled={deleting}
                      className="vo-btn-ghost text-sm"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </Panel>
  )
}

/** Deadline email digests — on-demand test via POST /deadlines/notify-me.
 * Delivery requires suite SMTP; without it the backend may log-only or return sent=false. */
function NotificationsCard() {
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [lastReason, setLastReason] = useState<string | null>(null)

  const sendTest = async () => {
    setBusy(true)
    setLastReason(null)
    try {
      const res = await deadlinesApi.notifyMe()
      const msg =
        res.reason ||
        (res.sent
          ? `Digest sent (${res.deadline_count} deadline${res.deadline_count === 1 ? '' : 's'}).`
          : 'Digest was not sent.')
      setLastReason(msg)
      toast(msg, res.sent ? 'success' : 'info')
    } catch (err) {
      const m = errorMessage(err)
      setLastReason(m)
      toast(m, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel hue="violet" title="Deadline emails" subtitle="Digest of clocks Rating Raider can track">
      <div className="space-y-3 p-5">
        <div className="flex items-start gap-2.5">
          <Mail size={16} className="mt-0.5 shrink-0 text-h-violet" />
          <p className="text-sm leading-relaxed text-muted">
            When <strong className="font-semibold text-txt">suite SMTP</strong> is configured on this host, Rating
            Raider can email you a deadline digest (Intent to File, decision-review windows, dependent timing) to the
            address on your account. Cron may send urgent-only digests; use the button below anytime to send a full
            test digest now.
          </p>
        </div>
        <p className="text-xs leading-relaxed text-faint">
          If SMTP is not set up, the send may log only or return a reason instead of an inbox message — ask your host
          admin to configure suite mail if you need real email delivery.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void sendTest()}
            disabled={busy}
            className="vo-btn-secondary min-h-11 text-sm"
          >
            {busy ? <Loader2 size={15} className="animate-spin" /> : <Mail size={15} />}
            {busy ? 'Sending…' : 'Send test digest'}
          </button>
        </div>
        {lastReason && (
          <p className="rounded-control border border-line bg-surface2 px-3 py-2 text-xs leading-relaxed text-muted" role="status">
            {lastReason}
          </p>
        )}
      </div>
    </Panel>
  )
}

export function Settings() {
  const { user, logout } = useAuth()
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')

  useEffect(() => {
    const saved = (localStorage.getItem('vo_theme') as 'dark' | 'light' | null) ?? 'dark'
    setTheme(saved)
  }, [])

  const applyTheme = (t: 'dark' | 'light') => {
    setTheme(t)
    document.documentElement.dataset.theme = t === 'light' ? 'light' : ''
    localStorage.setItem('vo_theme', t)
  }

  const showDisclaimerAgain = () => {
    window.dispatchEvent(new Event('vo:show-disclaimer'))
  }

  return (
    <div data-section="settings" className="vo-page mx-auto w-full max-w-2xl space-y-8 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Preferences</p>
        <h1 className="vo-page-title">Settings</h1>
      </div>

      {/* Account */}
      <div className="space-y-3">
        <GroupLabel>Account</GroupLabel>
        <Panel hue="violet" title="Your account">
          <div className="space-y-3 p-5">
            <p className="text-sm text-muted">{user?.email}</p>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={logout} className="vo-btn-ghost text-danger hover:bg-danger-soft">
                <LogOut size={15} /> Sign out
              </button>
            </div>
          </div>
        </Panel>
        <Panel hue="violet" title="Claim setup">
          <div className="space-y-3 p-5">
            <p className="text-sm text-muted">
              Re-run the guided setup to add service periods, exposures, or new conditions in one pass.
            </p>
            <Link to="/onboarding" className="vo-btn-secondary text-sm">
              <Rocket size={15} /> Restart guided setup
            </Link>
          </div>
        </Panel>
      </div>

      {/* Appearance */}
      <div className="space-y-3">
        <GroupLabel>Appearance</GroupLabel>
        <Panel hue="violet" title="Theme">
          <div className="flex items-center justify-between p-5">
            <div>
              <h2 className="text-sm font-semibold text-txt">Dark or light</h2>
              <p className="text-sm text-muted">Your choice, saved on this device.</p>
            </div>
            <div className="flex gap-1 rounded-control border border-line bg-surface2 p-1">
              <button
                onClick={() => applyTheme('dark')}
                aria-pressed={theme === 'dark'}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${theme === 'dark' ? 'bg-brand text-white' : 'text-muted'}`}
              >
                <Moon size={14} /> Dark
              </button>
              <button
                onClick={() => applyTheme('light')}
                aria-pressed={theme === 'light'}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${theme === 'light' ? 'bg-brand text-white' : 'text-muted'}`}
              >
                <Sun size={14} /> Light
              </button>
            </div>
          </div>
        </Panel>
      </div>

      {/* Notifications */}
      <div className="space-y-3">
        <GroupLabel>Notifications</GroupLabel>
        <NotificationsCard />
      </div>

      {/* Connections */}
      <div className="space-y-3">
        <GroupLabel>Connections</GroupLabel>
        <VaConnectionsCard />
        <ConnectionsCard />
      </div>

      {/* Your data */}
      <div className="space-y-3">
        <GroupLabel>Your data</GroupLabel>
        <DataCard />
      </div>

      {/* Privacy & C-file processing */}
      <div className="space-y-3">
        <GroupLabel>Privacy &amp; C-file processing</GroupLabel>
        <CFileProcessing />
      </div>

      {/* About & legal */}
      <div className="space-y-3">
        <GroupLabel>About &amp; legal</GroupLabel>
        <Panel hue="violet" title="Disclaimer">
          <div className="space-y-3 p-5">
            <div className="flex items-start gap-2.5 rounded-control border border-line bg-surface2 px-4 py-3.5 text-sm leading-relaxed text-muted">
              <ShieldAlert size={16} className="mt-0.5 shrink-0 text-faint" />
              <span>{DISCLAIMER_TEXT}</span>
            </div>
            <button onClick={showDisclaimerAgain} className="vo-btn-secondary text-sm">
              Show the first-run notice again
            </button>
          </div>
        </Panel>
        <p className="px-1 text-center text-micro text-faint">
          Veteran-Ops is self-help educational software — not legal advice, not a VA-accredited representative, and not
          affiliated with VA.{' '}
          <Link to="/legal" className="font-semibold text-muted underline underline-offset-2 hover:text-txt">
            Terms &amp; privacy
          </Link>
        </p>
      </div>
    </div>
  )
}
