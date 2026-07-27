import {
  ArrowRightLeft,
  Briefcase,
  Building2,
  Check,
  ClipboardList,
  Crown,
  Mail,
  Plus,
  Send,
  Shield,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Badge, EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { useAuth } from '../context/AuthContext'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { entitlementsApi, orgsApi, setWorkspace } from '../lib/api'
import { humanize } from '../lib/format'
import type { Entitlements, Invite, Org, OrgMember, OrgRole } from '../types'

const ROLE_OPTIONS: OrgRole[] = ['owner', 'admin', 'staff', 'member']

interface TeamsData {
  orgs: Org[]
  entitlements: Entitlements
  members: OrgMember[]
  invites: Invite[]
}

async function loadTeams(): Promise<TeamsData> {
  const [orgs, entitlements] = await Promise.all([orgsApi.list(), entitlementsApi.get()])
  const isOrg = entitlements.kind === 'org'
  const canManage = entitlements.role === 'owner' || entitlements.role === 'admin'
  const [members, invites] = await Promise.all([
    isOrg ? orgsApi.members().catch(() => [] as OrgMember[]) : Promise.resolve([] as OrgMember[]),
    isOrg && canManage ? orgsApi.invites().catch(() => [] as Invite[]) : Promise.resolve([] as Invite[]),
  ])
  return { orgs, entitlements, members, invites }
}

export function Teams() {
  const { toast } = useToast()
  const { data, loading, error, reload } = useAsync(loadTeams)

  if (loading)
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
        <LoadingBlock label="Loading your teams…" />
      </div>
    )
  if (error || !data)
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
        <ErrorBlock message={error ?? 'Could not load your teams.'} onRetry={reload} />
      </div>
    )

  const { orgs, entitlements, members, invites } = data
  const activeId = entitlements.workspace_id
  const isOrgActive = entitlements.kind === 'org'
  const canManage = entitlements.role === 'owner' || entitlements.role === 'admin'

  return (
    <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
      <div className="vo-page-head vo-section-band">
        <h1 className="vo-page-title">Teams &amp; workspaces</h1>
        <p className="vo-page-sub">
          Switch between your personal space and any teams you belong to, create a new team, or manage members.
        </p>
      </div>

      {!isOrgActive && <CaseworkerExplainer />}

      <WorkspacesSection orgs={orgs} activeId={activeId} toast={toast} />

      <CreateTeamSection reload={reload} toast={toast} />

      {isOrgActive ? (
        <ManageTeamSection
          entitlements={entitlements}
          members={members}
          invites={invites}
          canManage={canManage}
          reload={reload}
          toast={toast}
        />
      ) : (
        <Panel hue="emerald" title="Manage a team" subtitle="Members, roles, and invitations">
          <div className="p-5">
            <EmptyState
              hue="emerald"
              icon={<Users size={22} />}
              title="Switch to a team to manage members"
              description="You're currently in your personal workspace. Switch to a team above (or create one) to invite teammates and manage roles."
            />
          </div>
        </Panel>
      )}
    </div>
  )
}

// ---- Discoverability: what a team unlocks (caseworker / VSO / family) ----

/** Solo veterans never see the Caseload or Org console — they only appear once you're
 * in a team workspace. This explains WHO teams are for (VSOs, caseworkers, family
 * members helping a veteran) and WHAT switching to a team reveals, so the multi-user
 * case-management capability is actually findable. */
function CaseworkerExplainer() {
  const rows = [
    {
      icon: <Briefcase size={16} />,
      title: 'Manage a caseload of veterans',
      body: 'A shared list of everyone you help, each with their own case file — for VSOs, county/state veterans offices, or anyone assisting more than one veteran.',
    },
    {
      icon: <Users size={16} />,
      title: 'Assign cases and share notes with teammates',
      body: 'Assign a veteran to a caseworker, keep case notes the whole team can see, and hand a case off without losing history.',
    },
    {
      icon: <ShieldCheck size={16} />,
      title: 'Consent stays on the record',
      body: "Every case tracks the veteran's consent before their information is shared with the team — the veteran always controls their own record.",
    },
  ]
  return (
    <Panel hue="indigo" title="Helping more than one veteran?" subtitle="For VSOs, caseworkers, and family members">
      <div className="space-y-4 p-5">
        <p className="text-sm leading-relaxed text-muted">
          If you help several veterans — as a Veterans Service Officer, a caseworker, or a family member assisting more
          than one person — create a <strong className="text-txt">team</strong> below. A team unlocks a shared{' '}
          <strong className="text-txt">Caseload</strong> and <strong className="text-txt">Org console</strong> (they
          appear in your sidebar once you switch into the team).
        </p>
        <ul className="grid gap-3 sm:grid-cols-3">
          {rows.map((r) => (
            <li key={r.title} className="rounded-control border border-line bg-surface2/40 p-3.5">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-h-indigo-soft text-h-indigo">
                {r.icon}
              </span>
              <p className="mt-2.5 text-sm font-semibold text-txt">{r.title}</p>
              <p className="mt-1 text-xs leading-relaxed text-muted">{r.body}</p>
            </li>
          ))}
        </ul>
        <p className="flex items-start gap-2 text-xs leading-relaxed text-faint">
          <ClipboardList size={14} className="mt-0.5 shrink-0" />
          Working on just your own claim? You don't need a team — your personal workspace already has everything.
        </p>
      </div>
    </Panel>
  )
}

// ---- Section 1: your workspaces ----

function WorkspacesSection({
  orgs,
  activeId,
  toast,
}: {
  orgs: Org[]
  activeId: string
  toast: (m: string, tone?: 'success' | 'error' | 'info') => void
}) {
  const switchTo = (org: Org) => {
    setWorkspace(org.id)
    toast(`Switching to ${org.name}…`, 'info')
    // Full reload so every workspace-scoped screen refetches under the new tenant.
    window.location.reload()
  }

  return (
    <Panel hue="violet" title="Your workspaces" subtitle="Everywhere you can work">
      <ul className="divide-y divide-line">
        {orgs.map((org) => {
          const isActive = org.id === activeId
          const isTeam = org.kind === 'org'
          return (
            <li key={org.id} className="flex flex-wrap items-center gap-3 px-5 py-4">
              <span
                className={
                  isTeam
                    ? 'flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand'
                    : 'flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-surface2 text-muted'
                }
              >
                {isTeam ? <Building2 size={18} /> : <Sparkles size={18} />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="truncate font-semibold text-txt">{org.name}</p>
                  <Badge tone={isTeam ? 'primary' : 'neutral'}>{isTeam ? 'Team' : 'Personal'}</Badge>
                  {isActive && <Badge tone="success">Current</Badge>}
                </div>
                <p className="mt-0.5 text-xs text-muted">
                  {humanize(org.plan_tier)} plan
                  {isTeam && (
                    <>
                      {' '}
                      · {org.member_count} member{org.member_count === 1 ? '' : 's'}
                    </>
                  )}{' '}
                  · your role: {humanize(org.role)}
                </p>
              </div>
              {isActive ? (
                <span className="flex items-center gap-1.5 text-sm font-semibold text-success">
                  <Check size={15} /> Active
                </span>
              ) : (
                <button onClick={() => switchTo(org)} className="vo-btn-secondary text-sm">
                  <ArrowRightLeft size={14} /> Switch to
                </button>
              )}
            </li>
          )
        })}
      </ul>
    </Panel>
  )
}

// ---- Section 2: create a team ----

function CreateTeamSection({
  reload,
  toast,
}: {
  reload: () => void
  toast: (m: string, tone?: 'success' | 'error' | 'info') => void
}) {
  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [created, setCreated] = useState<Org | null>(null)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || creating) return
    setCreating(true)
    try {
      const org = await orgsApi.create(trimmed)
      toast(`Team "${org.name}" created.`, 'success')
      setName('')
      setCreated(org)
      reload()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setCreating(false)
    }
  }

  const switchToCreated = () => {
    if (!created) return
    setWorkspace(created.id)
    window.location.reload()
  }

  return (
    <Panel hue="teal" title="Create a team" subtitle="Manage a shared caseload, or collaborate with others">
      <div className="space-y-4 p-5">
        {created && (
          <div className="animate-pop-in flex flex-wrap items-center justify-between gap-3 rounded-control border border-success/40 bg-h-emerald-soft px-4 py-3 text-sm">
            <span className="text-txt">
              <strong>{created.name}</strong> is ready.
            </span>
            <button onClick={switchToCreated} className="vo-btn-secondary text-sm">
              <ArrowRightLeft size={14} /> Switch to it
            </button>
          </div>
        )}

        <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
          <div className="min-w-[12rem] flex-1">
            <label htmlFor="team-name" className="vo-label">
              Team name
            </label>
            <input
              id="team-name"
              className="vo-input"
              type="text"
              placeholder="e.g. Smith Family, VSO Office"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
            />
          </div>
          <button type="submit" disabled={!name.trim() || creating} className="vo-btn-primary text-sm">
            {creating ? <Spinner size={15} className="text-white" /> : <Plus size={15} />}
            Create team
          </button>
        </form>

        <p className="text-xs leading-relaxed text-muted">
          Teams are free to create. Adding teammates requires a team plan — you'll see an upgrade prompt if you're
          over your seat limit.
        </p>
      </div>
    </Panel>
  )
}

// ---- Section 3: manage the active team ----

function ManageTeamSection({
  entitlements,
  members,
  invites,
  canManage,
  reload,
  toast,
}: {
  entitlements: Entitlements
  members: OrgMember[]
  invites: Invite[]
  canManage: boolean
  reload: () => void
  toast: (m: string, tone?: 'success' | 'error' | 'info') => void
}) {
  const { user } = useAuth()
  const [busyUser, setBusyUser] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)
  const canInvite = entitlements.features.includes('org_invites')

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
    <div className="space-y-6">
      <Panel
        hue="emerald"
        title="Members"
        subtitle={`${members.length} in ${entitlements.tier ? humanize(entitlements.tier) + ' · ' : ''}seat limit ${entitlements.seat_limit}`}
      >
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
                  {canManage ? (
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
                  ) : (
                    <Badge tone={isOwner ? 'warning' : 'neutral'}>{humanize(member.role)}</Badge>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </Panel>

      {canManage && (
        <>
          <InviteForm canInvite={canInvite} reload={reload} toast={toast} />

          {invites.length > 0 && (
            <Panel hue="teal" title="Pending invitations" subtitle="Sent, not yet accepted">
              <ul className="divide-y divide-line">
                {invites.map((inv) => (
                  <PendingInviteRow key={inv.id} invite={inv} reload={reload} toast={toast} />
                ))}
              </ul>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}

function InviteForm({
  canInvite,
  reload,
  toast,
}: {
  canInvite: boolean
  reload: () => void
  toast: (m: string, tone?: 'success' | 'error' | 'info') => void
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
          <div className="relative min-w-[14rem] flex-1">
            <label htmlFor="invite-email" className="vo-label">
              Email
            </label>
            <span className="pointer-events-none absolute left-3 top-[34px] text-faint">
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
          <div>
            <label htmlFor="invite-role" className="vo-label">
              Role
            </label>
            <select
              id="invite-role"
              className="vo-input h-[42px] w-auto"
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
  toast: (m: string, tone?: 'success' | 'error' | 'info') => void
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
