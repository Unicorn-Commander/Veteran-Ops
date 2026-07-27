import { Briefcase, Building2, MessageSquare, Plus, Sparkles, Users } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Badge, EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { ApiError } from '../lib/api'
import { casesApi, type Case, type CaseStatus, type ConsentStatus } from '../lib/caseloadApi'
import { formatDateTime, humanize } from '../lib/format'

const STATUS_TONE: Record<CaseStatus, 'neutral' | 'primary' | 'accent' | 'success'> = {
  intake: 'neutral',
  active: 'primary',
  filed: 'accent',
  closed: 'success',
}

const CONSENT_TONE: Record<ConsentStatus, 'warning' | 'success' | 'danger'> = {
  none: 'warning',
  granted: 'success',
  revoked: 'danger',
}

const CONSENT_LABEL: Record<ConsentStatus, string> = {
  none: 'No consent',
  granted: 'Consent on file',
  revoked: 'Consent revoked',
}

/** Loader result — distinguishes the personal-workspace and tier-gated states
 * (surfaced as gentle empty states) from an actual load failure. */
type LoadResult =
  | { kind: 'ok'; cases: Case[] }
  | { kind: 'personal'; message: string }
  | { kind: 'upgrade'; message: string }

async function loadCaseload(): Promise<LoadResult> {
  try {
    const cases = await casesApi.list()
    return { kind: 'ok', cases }
  } catch (err) {
    if (err instanceof ApiError && err.status === 400) return { kind: 'personal', message: err.message }
    if (err instanceof ApiError && err.status === 402) return { kind: 'upgrade', message: err.message }
    throw err
  }
}

function initials(name: string): string {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() || 'V'
}

function AssigneeStack({ assignees }: { assignees: Case['assignees'] }) {
  if (assignees.length === 0) return <span className="text-xs text-faint">Unassigned</span>
  const shown = assignees.slice(0, 3)
  const extra = assignees.length - shown.length
  return (
    <div className="flex items-center" aria-label={`${assignees.length} assigned`}>
      {shown.map((a, i) => (
        <span
          key={a.user_id}
          className="flex h-7 w-7 items-center justify-center rounded-full border border-surface bg-surface2 text-micro font-bold text-muted"
          style={{ marginLeft: i === 0 ? 0 : -8 }}
          title={a.full_name || a.email}
        >
          {initials(a.full_name || a.email)}
        </span>
      ))}
      {extra > 0 && (
        <span
          className="flex h-7 w-7 items-center justify-center rounded-full border border-surface bg-surface2 text-micro font-bold text-muted"
          style={{ marginLeft: -8 }}
        >
          +{extra}
        </span>
      )}
    </div>
  )
}

export function Caseload() {
  const { data, loading, error, reload } = useAsync(loadCaseload)
  const [statusFilter, setStatusFilter] = useState<CaseStatus | 'all'>('all')

  if (loading) return <LoadingBlock label="Loading your caseload…" />
  if (error || !data) return <ErrorBlock message={error ?? 'Could not load the caseload.'} onRetry={reload} />

  if (data.kind === 'personal') {
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
        <PageHead />
        <Panel hue="violet">
          <div className="p-5">
            <EmptyState
              hue="violet"
              icon={<Building2 size={22} />}
              title="Switch to a team to use the caseload"
              description={data.message || 'The caseload lives inside a team workspace. Switch to a team using the workspace switcher up top, or create one.'}
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

  if (data.kind === 'upgrade') {
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
        <PageHead />
        <Panel hue="amber">
          <div className="p-5">
            <EmptyState
              hue="amber"
              icon={<Sparkles size={22} />}
              title="The caseload is a team-plan feature"
              description={data.message || 'Upgrade this team to manage a shared caseload of the veterans you help.'}
              action={
                <Link to="/settings" className="vo-btn-primary text-sm">
                  View plan
                </Link>
              }
            />
          </div>
        </Panel>
      </div>
    )
  }

  const cases = data.cases
  const filtered = statusFilter === 'all' ? cases : cases.filter((c) => c.status === statusFilter)

  return (
    <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
      <PageHead />

      <Panel
        hue="violet"
        title="Cases"
        subtitle={`${cases.length} veteran${cases.length === 1 ? '' : 's'} you're helping`}
        action={
          <div className="flex items-center gap-2">
            <label className="sr-only" htmlFor="case-status-filter">
              Filter by status
            </label>
            <select
              id="case-status-filter"
              className="vo-input h-9 w-auto py-1 text-sm"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as CaseStatus | 'all')}
            >
              <option value="all">All statuses</option>
              <option value="intake">Intake</option>
              <option value="active">Active</option>
              <option value="filed">Filed</option>
              <option value="closed">Closed</option>
            </select>
          </div>
        }
      >
        {cases.length === 0 ? (
          <div className="p-5">
            <EmptyState
              hue="violet"
              icon={<Briefcase size={22} />}
              title="No cases yet"
              description="Add the first veteran your team is helping using the form below."
            />
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-5 text-center text-sm text-muted">No cases with that status.</div>
        ) : (
          <ul className="divide-y divide-line">
            {filtered.map((c) => (
              <li key={c.id}>
                <Link
                  to={`/caseload/${c.id}`}
                  className="flex flex-wrap items-center gap-3 px-5 py-4 transition-colors hover:bg-surface2"
                >
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand">
                    <Briefcase size={18} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="truncate font-semibold text-txt">{c.veteran_name}</p>
                      <Badge tone={STATUS_TONE[c.status]}>{humanize(c.status)}</Badge>
                      <Badge tone={CONSENT_TONE[c.consent_status]}>{CONSENT_LABEL[c.consent_status]}</Badge>
                    </div>
                    <p className="mt-0.5 flex items-center gap-2 text-xs text-muted">
                      {c.veteran_email && <span className="truncate">{c.veteran_email}</span>}
                      <span className="inline-flex items-center gap-1">
                        <MessageSquare size={12} /> {c.note_count}
                      </span>
                      <span>· Updated {formatDateTime(c.updated_at)}</span>
                    </p>
                  </div>
                  <AssigneeStack assignees={c.assignees} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <NewCaseForm reload={reload} />
    </div>
  )
}

function PageHead() {
  return (
    <div className="vo-page-head vo-section-band">
      <h1 className="vo-page-title">Caseload</h1>
      <p className="vo-page-sub">
        The veterans your team is helping. A case is your file for assisting and organizing a veteran's claim —
        educational self-help. The veteran still drives and files their own claim; this is not VA representation.
      </p>
    </div>
  )
}

function NewCaseForm({ reload }: { reload: () => void }) {
  const { toast } = useToast()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [summary, setSummary] = useState('')
  const [creating, setCreating] = useState(false)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed || creating) return
    setCreating(true)
    try {
      const created = await casesApi.create({
        veteran_name: trimmed,
        veteran_email: email.trim() || undefined,
        veteran_phone: phone.trim() || undefined,
        summary: summary.trim() || undefined,
      })
      toast(`Case opened for ${created.veteran_name}.`, 'success')
      reload()
      navigate(`/caseload/${created.id}`)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setCreating(false)
    }
  }

  return (
    <Panel hue="teal" title="New case" subtitle="Open a file for a veteran you're helping">
      <form onSubmit={onSubmit} className="space-y-4 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="vo-label">Veteran's name *</span>
            <input
              className="vo-input"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Jordan Rivera"
              maxLength={200}
            />
          </label>
          <label className="block text-sm">
            <span className="vo-label">Email (optional)</span>
            <input
              className="vo-input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="veteran@example.com"
            />
          </label>
          <label className="block text-sm">
            <span className="vo-label">Phone (optional)</span>
            <input
              className="vo-input"
              type="tel"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="(555) 555-1234"
            />
          </label>
          <label className="block text-sm">
            <span className="vo-label">Short summary (optional)</span>
            <input
              className="vo-input"
              type="text"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="e.g. PTSD + tinnitus, gathering records"
              maxLength={280}
            />
          </label>
        </div>
        <button type="submit" disabled={!name.trim() || creating} className="vo-btn-primary text-sm">
          {creating ? <Spinner size={15} className="text-white" /> : <Plus size={15} />}
          Open case
        </button>
      </form>
    </Panel>
  )
}
