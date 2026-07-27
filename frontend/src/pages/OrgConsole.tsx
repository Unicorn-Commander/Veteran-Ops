import {
  Activity,
  Building2,
  Check,
  Crown,
  Mail,
  Pencil,
  Send,
  Shield,
  ShieldAlert,
  Sparkles,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Badge, EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { useAuth } from '../context/AuthContext'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { creditsApi, entitlementsApi, orgsApi } from '../lib/api'
import { auditApi, type AuditEntry } from '../lib/caseloadApi'
import { formatDateTime, humanize, titleCase } from '../lib/format'
import type { AdminGrants, Entitlements, Invite, Org, OrgMember, OrgRole } from '../types'

const ROLE_OPTIONS: OrgRole[] = ['owner', 'admin', 'staff', 'member']

/** Humanize audit action strings like "case.consent.grant" → "Captured consent".
 * Falls back to a title-cased dotted path so an unknown action still reads. */
const ACTION_LABELS: Record<string, string> = {
  'case.create': 'Opened a case',
  'case.update': 'Updated a case',
  'case.assign': 'Assigned a caseworker',
  'case.unassign': 'Removed a caseworker',
  'case.consent.grant': 'Captured consent',
  'case.consent.revoke': 'Revoked consent',
  'case.note.create': 'Added a case note',
  'member.add': 'Added a member',
  'member.role': 'Changed a member role',
  'member.remove': 'Removed a member',
  'invite.create': 'Sent an invitation',
  'invite.revoke': 'Revoked an invitation',
  'invite.accept': 'Accepted an invitation',
  'org.rename': 'Renamed the org',
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? titleCase(action.replace(/\./g, ' '))
}

interface ConsoleData {
  entitlements: Entitlements
  org: Org | null
  members: OrgMember[]
  invites: Invite[]
  audit: AuditEntry[]
  grants: AdminGrants | null
}

async function loadConsole(): Promise<ConsoleData> {
  const entitlements = await entitlementsApi.get()
  const isOrg = entitlements.kind === 'org'
  const canManage = entitlements.role === 'owner' || entitlements.role === 'admin'
  const [org, members, invites, audit] = await Promise.all([
    isOrg ? orgsApi.current().catch(() => null) : Promise.resolve(null),
    isOrg ? orgsApi.members().catch(() => [] as OrgMember[]) : Promise.resolve([] as OrgMember[]),
    isOrg && canManage ? orgsApi.invites().catch(() => [] as Invite[]) : Promise.resolve([] as Invite[]),
    isOrg && canManage ? auditApi.list(100).catch(() => [] as AuditEntry[]) : Promise.resolve([] as AuditEntry[]),
  ])
  const grants = isOrg && canManage ? await creditsApi.adminGrants().catch(() => null) : null
  return { entitlements, org, members, invites, audit, grants }
}

export function OrgConsole() {
  const { toast } = useToast()
  const { data, loading, error, reload } = useAsync(loadConsole)

  if (loading) return <LoadingBlock label="Loading org console…" />
  if (error || !data) return <ErrorBlock message={error ?? 'Could not load the console.'} onRetry={reload} />

  const { entitlements, org, members, invites, audit, grants } = data
  const isOrgActive = entitlements.kind === 'org'
  const canManage = entitlements.role === 'owner' || entitlements.role === 'admin'

  const head = (
    <div className="vo-page-head vo-section-band">
      <h1 className="vo-page-title">Org console</h1>
      <p className="vo-page-sub">Settings, members, invitations, and the activity trail for your team.</p>
    </div>
  )

  if (!isOrgActive) {
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
        {head}
        <Panel hue="violet">
          <div className="p-5">
            <EmptyState
              hue="violet"
              icon={<Building2 size={22} />}
              title="Switch to a team to open the console"
              description="You're in your personal workspace. Switch to a team using the workspace switcher up top, or create one."
              action={
                <Link to="/teams" className="vo-btn-primary text-sm">
                  <Users size={15} /> Go to Teams
                </Link>
              }
            />
          </div>
        </Panel>
      </div>
    )
  }

  if (!canManage) {
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
        {head}
        <Panel hue="amber">
          <div className="p-5">
            <EmptyState
              hue="amber"
              icon={<ShieldAlert size={22} />}
              title="You need admin access"
              description="The org console is for team owners and admins. Ask an admin to change your role if you need to manage the team."
              action={
                <Link to="/teams" className="vo-btn-secondary text-sm">
                  Back to Teams
                </Link>
              }
            />
          </div>
        </Panel>
      </div>
    )
  }

  return (
    <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
      {head}
      <OrgHeaderSection entitlements={entitlements} org={org} members={members} reload={reload} toast={toast} />
      <MembersSection members={members} entitlements={entitlements} reload={reload} toast={toast} />
      <InviteSection canInvite={entitlements.features.includes('org_invites')} reload={reload} toast={toast} />
      {invites.length > 0 && (
        <Panel hue="teal" title="Pending invitations" subtitle="Sent, not yet accepted">
          <ul className="divide-y divide-line">
            {invites.map((inv) => (
              <PendingInviteRow key={inv.id} invite={inv} reload={reload} toast={toast} />
            ))}
          </ul>
        </Panel>
      )}
      {grants && (
        <GrantAdminSection grants={grants} reload={reload} toast={toast} />
      )}
      <AuditSection audit={audit} />
    </div>
  )
}

type ToastFn = (m: string, tone?: 'success' | 'error' | 'info') => void

function OrgHeaderSection({
  entitlements,
  org,
  members,
  reload,
  toast,
}: {
  entitlements: Entitlements
  org: Org | null
  members: OrgMember[]
  reload: () => void
  toast: ToastFn
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(org?.name ?? '')
  const [saving, setSaving] = useState(false)
  const seatUsed = org?.member_count ?? members.length
  const seatLimit = org?.seat_limit ?? entitlements.seat_limit

  const save = async (e: FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || saving) return
    setSaving(true)
    try {
      await orgsApi.rename(trimmed)
      toast('Org name updated.', 'success')
      setEditing(false)
      reload()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel hue="violet">
      <div className="flex flex-wrap items-start justify-between gap-4 p-5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand">
            <Building2 size={22} />
          </span>
          <div className="min-w-0">
            {editing ? (
              <form onSubmit={save} className="flex items-center gap-2">
                <input
                  className="vo-input h-9 py-1"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={120}
                  autoFocus
                  aria-label="Org name"
                />
                <button type="submit" disabled={!name.trim() || saving} className="vo-btn-primary text-sm">
                  {saving ? <Spinner size={13} className="text-white" /> : <Check size={13} />} Save
                </button>
                <button type="button" onClick={() => { setEditing(false); setName(org?.name ?? '') }} className="vo-btn-ghost text-sm">
                  Cancel
                </button>
              </form>
            ) : (
              <div className="flex items-center gap-2">
                <h2 className="truncate text-heading text-txt">{org?.name ?? 'Your team'}</h2>
                <button
                  onClick={() => { setName(org?.name ?? ''); setEditing(true) }}
                  className="vo-icon-btn vo-btn-ghost text-faint hover:text-txt"
                  aria-label="Rename org"
                  title="Rename"
                >
                  <Pencil size={14} />
                </button>
              </div>
            )}
            <p className="mt-1 text-xs text-muted">
              {humanize(entitlements.tier || org?.plan_tier || 'free')} plan · {seatUsed} of {seatLimit} seat
              {seatLimit === 1 ? '' : 's'} used
            </p>
          </div>
        </div>
        <Badge tone="primary">{humanize(entitlements.role)}</Badge>
      </div>
    </Panel>
  )
}

function MembersSection({
  members,
  entitlements,
  reload,
  toast,
}: {
  members: OrgMember[]
  entitlements: Entitlements
  reload: () => void
  toast: ToastFn
}) {
  const { user } = useAuth()
  const [busyUser, setBusyUser] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)

  const changeRole = async (member: OrgMember, role: OrgRole) => {
    if (role === member.role) return
    setBusyUser(member.user_id)
    try {
      await orgsApi.setMemberRole(member.user_id, role)
      toast(`${member.email} is now ${humanize(role)}.`, 'success')
      reload()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusyUser(null)
    }
  }

  const removeMember = async (member: OrgMember) => {
    setBusyUser(member.user_id)
    try {
      await orgsApi.removeMember(member.user_id)
      toast(`${member.email} removed from the team.`, 'success')
      setConfirmRemove(null)
      reload()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusyUser(null)
    }
  }

  return (
    <Panel hue="emerald" title="Members" subtitle={`${members.length} in ${humanize(entitlements.tier)} · seat limit ${entitlements.seat_limit}`}>
      {members.length === 0 ? (
        <div className="p-5">
          <EmptyState hue="emerald" icon={<Users size={22} />} title="No members yet" description="Invite teammates below to get started." />
        </div>
      ) : (
        <ul className="divide-y divide-line">
          {members.map((member) => {
            const isSelf = user?.id === member.user_id
            const isOwner = member.role === 'owner'
            return (
              <li key={member.user_id} className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface2 text-muted">
                  {isOwner ? <Crown size={16} className="text-h-amber" /> : <Shield size={16} />}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-txt">
                    {member.full_name || member.email}
                    {isSelf && <span className="ml-1.5 text-xs font-normal text-faint">(you)</span>}
                  </p>
                  <p className="truncate text-xs text-muted">{member.email}</p>
                </div>
                <div className="flex items-center gap-2">
                  <label className="sr-only" htmlFor={`role-${member.user_id}`}>
                    Role for {member.email}
                  </label>
                  <select
                    id={`role-${member.user_id}`}
                    className="vo-input h-9 w-auto py-1 text-sm"
                    value={member.role}
                    disabled={busyUser === member.user_id}
                    onChange={(e) => void changeRole(member, e.target.value as OrgRole)}
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r} value={r}>
                        {humanize(r)}
                      </option>
                    ))}
                  </select>
                  {confirmRemove === member.user_id ? (
                    <span className="flex items-center gap-1">
                      <button
                        onClick={() => void removeMember(member)}
                        disabled={busyUser === member.user_id}
                        className="vo-btn-ghost text-xs text-danger hover:bg-danger-soft"
                      >
                        {busyUser === member.user_id ? <Spinner size={13} /> : <Check size={13} />} Confirm
                      </button>
                      <button
                        onClick={() => setConfirmRemove(null)}
                        className="vo-icon-btn vo-btn-ghost text-faint hover:text-txt"
                        aria-label="Cancel"
                      >
                        <X size={14} />
                      </button>
                    </span>
                  ) : (
                    <button
                      onClick={() => setConfirmRemove(member.user_id)}
                      disabled={busyUser === member.user_id}
                      className="vo-icon-btn vo-btn-ghost text-faint hover:text-danger"
                      aria-label={`Remove ${member.email}`}
                      title="Remove member"
                    >
                      <Trash2 size={15} />
                    </button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}

function InviteSection({
  canInvite,
  reload,
  toast,
}: {
  canInvite: boolean
  reload: () => void
  toast: ToastFn
}) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<OrgRole>('member')
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const trimmed = email.trim()
    if (!trimmed || sending) return
    setNotice(null)
    setSending(true)
    try {
      await orgsApi.invite(trimmed, role)
      toast(`Invitation sent to ${trimmed}.`, 'success')
      setEmail('')
      reload()
    } catch (err) {
      // 402 = plan/seat limit; surface the server's friendly message as an
      // upgrade prompt rather than hiding the action.
      setNotice(errorMessage(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <Panel hue="emerald" title="Invite a teammate" subtitle="They'll get an email with a join link">
      <form onSubmit={onSubmit} className="space-y-4 p-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[14rem] flex-1">
            <label htmlFor="invite-email" className="vo-label">
              Email
            </label>
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint">
                <Mail size={16} />
              </span>
              <input
                id="invite-email"
                className="vo-input pl-9"
                type="email"
                placeholder="teammate@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </div>
          <div>
            <label htmlFor="invite-role" className="vo-label">
              Role
            </label>
            <select
              id="invite-role"
              className="vo-input w-auto"
              value={role}
              onChange={(e) => setRole(e.target.value as OrgRole)}
            >
              {ROLE_OPTIONS.filter((r) => r !== 'owner').map((r) => (
                <option key={r} value={r}>
                  {humanize(r)}
                </option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={!email.trim() || sending} className="vo-btn-primary text-sm">
            {sending ? <Spinner size={15} className="text-white" /> : <UserPlus size={15} />}
            Send invite
          </button>
        </div>

        {!canInvite && (
          <p className="flex items-start gap-2 text-xs leading-relaxed text-muted">
            <Sparkles size={14} className="mt-0.5 shrink-0 text-h-amber" />
            Inviting teammates needs a team plan. You can still send an invite — we'll show you exactly what to
            upgrade if you're over your seats.
          </p>
        )}

        {notice && (
          <div role="alert" className="animate-pop-in flex items-start gap-2.5 rounded-control border border-warn/40 bg-h-amber-soft px-4 py-3 text-sm">
            <Sparkles size={16} className="mt-0.5 shrink-0 text-warn" />
            <span className="text-txt">{notice}</span>
          </div>
        )}
      </form>
    </Panel>
  )
}

function PendingInviteRow({
  invite,
  reload,
  toast,
}: {
  invite: Invite
  reload: () => void
  toast: ToastFn
}) {
  const [revoking, setRevoking] = useState(false)

  const revoke = async () => {
    setRevoking(true)
    try {
      await orgsApi.revokeInvite(invite.id)
      toast(`Invitation to ${invite.email} revoked.`, 'success')
      reload()
    } catch (err) {
      toast(errorMessage(err), 'error')
      setRevoking(false)
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-3 px-5 py-3.5">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface2 text-muted">
        <Send size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-txt">{invite.email}</p>
        <p className="truncate text-xs text-muted">
          {humanize(invite.role)} · {humanize(invite.status)}
        </p>
      </div>
      <button onClick={() => void revoke()} disabled={revoking} className="vo-btn-ghost text-xs text-muted hover:text-danger">
        {revoking ? <Spinner size={13} /> : <X size={13} />} Revoke
      </button>
    </li>
  )
}

function AuditSection({ audit }: { audit: AuditEntry[] }) {
  return (
    <Panel hue="fuchsia" title="Activity trail" subtitle="The last 100 actions in this team (read-only)">
      {audit.length === 0 ? (
        <div className="p-5">
          <EmptyState hue="fuchsia" icon={<Activity size={22} />} title="No activity yet" description="Actions your team takes will show up here." />
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-faint">
                <th className="px-5 py-2.5 font-semibold">When</th>
                <th className="px-5 py-2.5 font-semibold">Who</th>
                <th className="px-5 py-2.5 font-semibold">Action</th>
                <th className="px-5 py-2.5 font-semibold">On</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {audit.map((e) => (
                <tr key={e.id} className="align-top">
                  <td className="whitespace-nowrap px-5 py-2.5 text-muted">{formatDateTime(e.created_at)}</td>
                  <td className="px-5 py-2.5 text-txt">{e.actor_email}</td>
                  <td className="px-5 py-2.5 text-txt">{actionLabel(e.action)}</td>
                  <td className="px-5 py-2.5 text-muted">
                    {e.entity ? (
                      <span>
                        {humanize(e.entity)}
                        {e.entity_id && <span className="ml-1 text-faint">#{e.entity_id.slice(0, 8)}</span>}
                      </span>
                    ) : (
                      <span className="text-faint">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  )
}

function GrantAdminSection({
  grants,
  reload,
  toast,
}: {
  grants: AdminGrants
  reload: () => void
  toast: ToastFn
}) {
  const [busyId, setBusyId] = useState<string | null>(null)

  const review = async (id: string, status: 'approved' | 'denied') => {
    if (busyId) return
    let reviewNote = status === 'approved' ? 'Approved from the org console.' : ''
    if (status === 'denied') {
      const reason = window.prompt('Why are you denying this application?', '')
      const trimmed = reason?.trim()
      if (!trimmed) {
        toast('Please enter a denial reason.', 'error')
        return
      }
      reviewNote = trimmed
    }
    setBusyId(id)
    try {
      await creditsApi.reviewGrantApplication(id, {
        status,
        review_note: reviewNote,
      })
      toast(status === 'approved' ? 'Grant approved.' : 'Grant denied.', 'success')
      reload()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <Panel hue="emerald" title="Grant pool" subtitle="Sponsor claims and grant approvals">
      <div className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <Metric label="Available claims" value={grants.pool.available_claims.toString()} />
          <Metric label="Earned" value={grants.pool.earned_claims.toString()} />
          <Metric label="Spent" value={grants.pool.spent_claims.toString()} />
        </div>
        <div className="space-y-2">
          <p className="text-sm font-semibold text-txt">Pending applications</p>
          {grants.applications.filter((a) => a.status === 'pending').length === 0 ? (
            <p className="text-sm text-muted">No pending applications right now.</p>
          ) : (
            grants.applications
              .filter((a) => a.status === 'pending')
              .slice(0, 6)
              .map((app) => (
              <div key={app.id} className="rounded-control border border-line bg-surface2 px-4 py-3 text-sm">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-medium text-txt">{app.contact_email ?? 'Applicant'}</p>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                      <span>
                        Income: {app.monthly_income_band ?? 'not set'}
                      </span>
                      <span>
                        Household: {app.household_size ?? 'not set'}
                      </span>
                      <span>
                        Employment: {humanize(app.employment_status)}
                      </span>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-muted">{app.hardship_summary}</p>
                  </div>
                  <Badge tone="warning">pending</Badge>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="vo-btn-primary text-xs"
                    disabled={busyId === app.id}
                    onClick={() => void review(app.id, 'approved')}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="vo-btn-secondary text-xs"
                    disabled={busyId === app.id}
                    onClick={() => void review(app.id, 'denied')}
                  >
                    Deny
                  </button>
                </div>
              </div>
              ))
          )}
        </div>
      </div>
    </Panel>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-control border border-line bg-surface2 px-4 py-3">
      <p className="text-xs uppercase tracking-wider text-faint">{label}</p>
      <p className="mt-1 text-2xl font-bold text-txt">{value}</p>
    </div>
  )
}
