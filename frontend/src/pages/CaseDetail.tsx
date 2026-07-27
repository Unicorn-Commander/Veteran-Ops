import {
  ArrowLeft,
  Briefcase,
  Check,
  Mail,
  MessageSquare,
  Phone,
  Plus,
  Save,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Badge, EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { ConsentPanel } from '../components/ConsentPanel'
import { useToast } from '../components/Toast'
import { useWorkspace } from '../context/WorkspaceContext'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { ApiError, orgsApi } from '../lib/api'
import { casesApi, type Case, type CaseNote, type CaseStatus } from '../lib/caseloadApi'
import { formatDateTime, humanize } from '../lib/format'
import type { OrgMember } from '../types'

const STATUS_TONE: Record<CaseStatus, 'neutral' | 'primary' | 'accent' | 'success'> = {
  intake: 'neutral',
  active: 'primary',
  filed: 'accent',
  closed: 'success',
}

const STATUS_OPTIONS: CaseStatus[] = ['intake', 'active', 'filed', 'closed']

type LoadResult = { kind: 'ok'; case: Case } | { kind: 'notfound' }

function initials(name: string): string {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || 'V'
}

export function CaseDetail() {
  const { id = '' } = useParams()
  const { current } = useWorkspace()
  const canManage = current?.role === 'owner' || current?.role === 'admin'

  const { data, loading, error, reload, setData } = useAsync<LoadResult>(async () => {
    try {
      const c = await casesApi.get(id)
      return { kind: 'ok', case: c }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return { kind: 'notfound' }
      throw err
    }
  }, [id])

  if (loading) return <LoadingBlock label="Loading case…" />
  if (error || !data) return <ErrorBlock message={error ?? 'Could not load this case.'} onRetry={reload} />

  if (data.kind === 'notfound') {
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
        <Panel hue="violet">
          <div className="p-5">
            <EmptyState
              hue="violet"
              icon={<Briefcase size={22} />}
              title="Case not found or not assigned to you"
              description="This case may have been closed, or you're not one of its assignees. Ask a team admin if you think you should have access."
              action={
                <Link to="/caseload" className="vo-btn-secondary text-sm">
                  <ArrowLeft size={15} /> Back to caseload
                </Link>
              }
            />
          </div>
        </Panel>
      </div>
    )
  }

  const c = data.case
  // Optimistic local update helper so children can refresh the header without a
  // full round-trip after they PATCH the case.
  const applyCase = (updated: Case) => setData({ kind: 'ok', case: updated })

  return (
    <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
      <Link to="/caseload" className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-txt">
        <ArrowLeft size={15} /> Caseload
      </Link>

      <div className="vo-page-head vo-section-band">
        <h1 className="vo-page-title">{c.veteran_name || 'Case'}</h1>
      </div>

      <CaseHeader c={c} onUpdated={applyCase} />

      <ConsentPanel caseId={c.id} consentStatus={c.consent_status} onChange={reload} />

      <AssigneesSection caseId={c.id} assignees={c.assignees} canManage={!!canManage} onUpdated={applyCase} />

      <NotesSection caseId={c.id} />
    </div>
  )
}

function CaseHeader({ c, onUpdated }: { c: Case; onUpdated: (c: Case) => void }) {
  const { toast } = useToast()
  const [savingStatus, setSavingStatus] = useState(false)
  const [summary, setSummary] = useState(c.summary ?? '')
  const [savingSummary, setSavingSummary] = useState(false)
  const summaryDirty = summary.trim() !== (c.summary ?? '').trim()

  const changeStatus = async (status: CaseStatus) => {
    if (status === c.status) return
    setSavingStatus(true)
    try {
      const updated = await casesApi.update(c.id, { status })
      toast(`Status set to ${humanize(status)}.`, 'success')
      onUpdated(updated)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSavingStatus(false)
    }
  }

  const saveSummary = async () => {
    setSavingSummary(true)
    try {
      const updated = await casesApi.update(c.id, { summary: summary.trim() || null })
      toast('Summary saved.', 'success')
      onUpdated(updated)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSavingSummary(false)
    }
  }

  return (
    <Panel hue="violet">
      <div className="space-y-4 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand">
              <Briefcase size={22} />
            </span>
            <div className="min-w-0">
              <p className="truncate text-heading text-txt">{c.veteran_name}</p>
              <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted">
                {c.veteran_email && (
                  <span className="inline-flex items-center gap-1">
                    <Mail size={12} /> {c.veteran_email}
                  </span>
                )}
                {c.veteran_phone && (
                  <span className="inline-flex items-center gap-1">
                    <Phone size={12} /> {c.veteran_phone}
                  </span>
                )}
                <span>Opened {formatDateTime(c.created_at)}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge tone={STATUS_TONE[c.status]}>{humanize(c.status)}</Badge>
            <label className="sr-only" htmlFor="case-status">
              Case status
            </label>
            <select
              id="case-status"
              className="vo-input h-9 w-auto py-1 text-sm"
              value={c.status}
              disabled={savingStatus}
              onChange={(e) => void changeStatus(e.target.value as CaseStatus)}
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {humanize(s)}
                </option>
              ))}
            </select>
          </div>
        </div>

        <label className="block text-sm">
          <span className="vo-label">Summary</span>
          <textarea
            className="vo-input min-h-[80px] resize-y leading-relaxed"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            placeholder="A short note on where this claim stands — conditions, next steps, anything the team should know."
          />
        </label>
        {summaryDirty && (
          <div className="flex items-center gap-2">
            <button onClick={() => void saveSummary()} disabled={savingSummary} className="vo-btn-primary text-sm">
              {savingSummary ? <Spinner size={14} className="text-white" /> : <Save size={14} />}
              Save summary
            </button>
            <button onClick={() => setSummary(c.summary ?? '')} className="vo-btn-ghost text-sm">
              Cancel
            </button>
          </div>
        )}
      </div>
    </Panel>
  )
}

function AssigneesSection({
  caseId,
  assignees,
  canManage,
  onUpdated,
}: {
  caseId: string
  assignees: Case['assignees']
  canManage: boolean
  onUpdated: (c: Case) => void
}) {
  const { toast } = useToast()
  const [busy, setBusy] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)
  const [picking, setPicking] = useState(false)

  // Org members are only needed once the admin opens the "Assign" picker.
  const { data: members, loading: loadingMembers } = useAsync<OrgMember[]>(
    () => (canManage && picking ? orgsApi.members().catch(() => []) : Promise.resolve([])),
    [canManage, picking]
  )

  const assignedIds = new Set(assignees.map((a) => a.user_id))
  const available = (members ?? []).filter((m) => !assignedIds.has(m.user_id))

  const assign = async (userId: string) => {
    setBusy(userId)
    try {
      const updated = await casesApi.assign(caseId, userId)
      toast('Caseworker assigned.', 'success')
      onUpdated(updated)
      setPicking(false)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(null)
    }
  }

  const unassign = async (userId: string) => {
    setBusy(userId)
    try {
      await casesApi.unassign(caseId, userId)
      // The DELETE returns 204; refetch the case to reflect the new roster.
      const updated = await casesApi.get(caseId)
      toast('Caseworker removed.', 'success')
      onUpdated(updated)
      setConfirmRemove(null)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel
      hue="emerald"
      title="Assigned caseworkers"
      subtitle={canManage ? 'Who on your team is working this case' : 'Your team members on this case'}
      action={
        canManage && !picking ? (
          <button onClick={() => setPicking(true)} className="vo-btn-secondary text-sm">
            <UserPlus size={14} /> Assign
          </button>
        ) : undefined
      }
    >
      <div className="space-y-4 p-5">
        {assignees.length === 0 ? (
          <EmptyState hue="emerald" icon={<Users size={22} />} title="No one assigned yet" />
        ) : (
          <ul className="divide-y divide-line">
            {assignees.map((a) => (
              <li key={a.user_id} className="flex items-center gap-3 py-2.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface2 text-xs font-bold text-muted">
                  {initials(a.full_name || a.email)}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-txt">{a.full_name || a.email}</p>
                  <p className="truncate text-xs text-muted">{a.email}</p>
                </div>
                {canManage &&
                  (confirmRemove === a.user_id ? (
                    <span className="flex items-center gap-1">
                      <button
                        onClick={() => void unassign(a.user_id)}
                        disabled={busy === a.user_id}
                        className="vo-btn-ghost text-xs text-danger hover:bg-danger-soft"
                      >
                        {busy === a.user_id ? <Spinner size={13} /> : <Check size={13} />} Confirm
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
                      onClick={() => setConfirmRemove(a.user_id)}
                      disabled={busy === a.user_id}
                      className="vo-icon-btn vo-btn-ghost text-faint hover:text-danger"
                      aria-label={`Remove ${a.email}`}
                      title="Remove from case"
                    >
                      <X size={15} />
                    </button>
                  ))}
              </li>
            ))}
          </ul>
        )}

        {canManage && picking && (
          <div className="rounded-control border border-line bg-surface2 p-4">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-txt">Add a caseworker</p>
              <button onClick={() => setPicking(false)} className="vo-btn-ghost text-xs">
                Done
              </button>
            </div>
            {loadingMembers ? (
              <div className="flex items-center gap-2 py-2 text-sm text-muted">
                <Spinner size={14} /> Loading members…
              </div>
            ) : available.length === 0 ? (
              <p className="py-1 text-sm text-muted">Everyone on the team is already assigned.</p>
            ) : (
              <ul className="flex flex-col gap-1">
                {available.map((m) => (
                  <li key={m.user_id}>
                    <button
                      onClick={() => void assign(m.user_id)}
                      disabled={busy === m.user_id}
                      className="flex w-full items-center gap-3 rounded-control px-2 py-2 text-left transition-colors hover:bg-surface"
                    >
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface text-xs font-bold text-muted">
                        {initials(m.full_name || m.email)}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-txt">{m.full_name || m.email}</span>
                        <span className="block truncate text-xs text-muted">{humanize(m.role)}</span>
                      </span>
                      {busy === m.user_id ? <Spinner size={14} /> : <Plus size={15} className="text-muted" />}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </Panel>
  )
}

function NotesSection({ caseId }: { caseId: string }) {
  const { toast } = useToast()
  const { data: notes, loading, error, reload, setData } = useAsync<CaseNote[]>(
    () => casesApi.notes(caseId),
    [caseId]
  )
  const [body, setBody] = useState('')
  const [saving, setSaving] = useState(false)

  const addNote = async (e: FormEvent) => {
    e.preventDefault()
    const trimmed = body.trim()
    if (!trimmed || saving) return
    setSaving(true)
    try {
      const note = await casesApi.addNote(caseId, trimmed)
      setData((prev) => [note, ...(prev ?? [])])
      setBody('')
      toast('Note added.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel hue="teal" title="Case notes" subtitle="A running log for your team (not shared with the VA)">
      <div className="space-y-4 p-5">
        <form onSubmit={addNote} className="space-y-2">
          <label className="block text-sm">
            <span className="sr-only">Add a note</span>
            <textarea
              className="vo-input min-h-[80px] resize-y leading-relaxed"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="Log a call, a next step, or anything the team should know…"
            />
          </label>
          <button type="submit" disabled={!body.trim() || saving} className="vo-btn-primary text-sm">
            {saving ? <Spinner size={14} className="text-white" /> : <Plus size={14} />}
            Add note
          </button>
        </form>

        {loading ? (
          <LoadingBlock label="Loading notes…" />
        ) : error ? (
          <ErrorBlock message={error} onRetry={reload} />
        ) : (notes ?? []).length === 0 ? (
          <EmptyState hue="teal" icon={<MessageSquare size={22} />} title="No notes yet" description="Your first note will show here." />
        ) : (
          <ul className="space-y-3">
            {(notes ?? []).map((n) => (
              <li key={n.id} className="rounded-control border border-line bg-surface2 px-4 py-3">
                <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted">
                  <span className="truncate font-medium text-txt">{n.author_email}</span>
                  <span className="shrink-0">{formatDateTime(n.created_at)}</span>
                </div>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-txt">{n.body}</p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Panel>
  )
}
