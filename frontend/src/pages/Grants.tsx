import { Send, ShieldCheck, Wallet } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { creditsApi } from '../lib/api'
import { formatDateTime, humanize } from '../lib/format'
import type { GrantApplication, GrantApplicationInput } from '../types'

const EMPTY: GrantApplicationInput = {
  monthly_income_band: '',
  household_size: null,
  employment_status: 'other',
  hardship_summary: '',
  contact_email: '',
}

async function loadApps() {
  return creditsApi.grantApplications()
}

export function Grants() {
  const { toast } = useToast()
  const { data, loading, error, reload } = useAsync(loadApps)
  const [form, setForm] = useState<GrantApplicationInput>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const hardshipChars = form.hardship_summary.trim().length
  const hardshipTooShort = hardshipChars > 0 && hardshipChars < 20
  const contactEmail = (form.contact_email ?? '').trim()
  const formInvalid = submitting || !contactEmail || hardshipChars < 20

  if (loading) {
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6">
        <LoadingBlock label="Loading grant applications…" />
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6">
        <ErrorBlock message={error ?? 'Could not load grants.'} onRetry={reload} />
      </div>
    )
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (submitting) return
    const payload: GrantApplicationInput = {
      monthly_income_band: form.monthly_income_band?.trim() || null,
      household_size: form.household_size || null,
      employment_status: form.employment_status || null,
      hardship_summary: form.hardship_summary.trim(),
      contact_email: contactEmail || null,
    }
    if (payload.hardship_summary.length < 20 || !payload.contact_email) return
    setSubmitting(true)
    try {
      await creditsApi.submitGrantApplication(payload)
      toast('Grant application submitted.', 'success')
      setForm(EMPTY)
      reload()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="settings">
      <div className="vo-page-head vo-section-band">
        <h1 className="vo-page-title">Grant request</h1>
        <p className="vo-page-sub">
          If the Full Access price is out of reach, you can request a need-based grant. Keep it simple and honest;
          nothing here asks for sensitive financial documents.
        </p>
      </div>

      <Panel hue="amber" title="Apply for a grant" subtitle="A short means-assessment, reviewed by a person">
        <form onSubmit={submit} className="space-y-4 p-5">
          <p className="rounded-control border border-line bg-surface2 px-4 py-3 text-sm leading-relaxed text-muted">
            Grants are free, funded by other veterans, and limited — so there may be a wait, and we
            can't approve every request. We hold them for the folks who need them most. There's no
            shame in asking. We'll never ask for your SSN or VA file number here.
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="font-medium text-txt">Income band</span>
              <input
                className="vo-input"
                value={form.monthly_income_band ?? ''}
                onChange={(e) => setForm((prev) => ({ ...prev, monthly_income_band: e.target.value }))}
                placeholder="e.g. under $2,000/mo"
                maxLength={64}
              />
            </label>
            <label className="space-y-1 text-sm">
              <span className="font-medium text-txt">Household size</span>
              <input
                className="vo-input"
                type="number"
                min={1}
                max={12}
                value={form.household_size ?? ''}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, household_size: e.target.value ? Number(e.target.value) : null }))
                }
              />
            </label>
          </div>

          <label className="space-y-1 text-sm">
            <span className="font-medium text-txt">Employment status</span>
            <select
              className="vo-input"
              value={form.employment_status ?? 'other'}
              onChange={(e) => setForm((prev) => ({ ...prev, employment_status: e.target.value as GrantApplicationInput['employment_status'] }))}
            >
            {['other', 'unemployed', 'underemployed', 'employed', 'retired', 'student'].map((opt) => (
              <option key={opt} value={opt}>
                  {humanize(opt)}
                </option>
              ))}
            </select>
          </label>

          <label className="space-y-1 text-sm">
            <span className="font-medium text-txt">Why you need help</span>
            <textarea
              className="vo-input min-h-[140px]"
              value={form.hardship_summary}
              onChange={(e) => setForm((prev) => ({ ...prev, hardship_summary: e.target.value }))}
              placeholder="A short explanation of the hardship you want the grant to address."
              maxLength={2000}
            />
            <p className={`text-xs ${hardshipTooShort ? 'text-warn' : 'text-muted'}`}>
              {hardshipTooShort
                ? 'Please add at least a sentence or two so a reviewer has enough context.'
                : 'At least a sentence or two helps the reviewer understand the request.'}
            </p>
          </label>

          <label className="space-y-1 text-sm">
            <span className="font-medium text-txt">Best contact email</span>
            <input
              className="vo-input"
              type="email"
              value={form.contact_email ?? ''}
              onChange={(e) => setForm((prev) => ({ ...prev, contact_email: e.target.value }))}
              placeholder="you@example.com"
              required
            />
          </label>

          <button type="submit" disabled={formInvalid} className="vo-btn-primary text-sm">
            <Send size={15} /> Submit application
          </button>
        </form>
      </Panel>

      <Panel hue="emerald" title="Your applications" subtitle="Recent requests and their status">
        <div className="space-y-3 p-5">
          {data.length === 0 ? (
            <div className="rounded-control border border-dashed border-line bg-surface2 px-4 py-5 text-sm text-muted">
              No applications yet.
            </div>
          ) : (
            data.map((app) => <ApplicationRow key={app.id} app={app} />)
          )}
          <div className="pt-1">
            <Link to="/billing" className="vo-btn-secondary text-sm">
              <Wallet size={15} /> Back to billing
            </Link>
          </div>
        </div>
      </Panel>
    </div>
  )
}

function ApplicationRow({ app }: { app: GrantApplication }) {
  const statusLabel = humanize(app.status)
  return (
    <div className="rounded-control border border-line bg-surface2 px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-txt">
            {statusLabel} · submitted {formatDateTime(app.created_at)}
          </p>
          <p className="mt-1 text-xs text-muted">
            Reviewed {app.reviewed_at ? formatDateTime(app.reviewed_at) : 'not yet'}{app.monthly_income_band ? ` · income ${app.monthly_income_band}` : ''}
          </p>
        </div>
        <Badge tone={app.status === 'approved' ? 'primary' : app.status === 'denied' ? 'warning' : 'neutral'}>
          {statusLabel}
        </Badge>
      </div>
      <p className="mt-2 whitespace-pre-wrap text-sm text-txt">{app.hardship_summary}</p>
      {app.review_note ? <p className="mt-2 text-xs text-muted">{app.review_note}</p> : null}
      {app.funded_sponsorship_id ? (
        <div className="mt-2 inline-flex items-center gap-2 rounded-full bg-success/10 px-3 py-1 text-xs text-success">
          <ShieldCheck size={13} /> Funded by a sponsor claim
        </div>
      ) : null}
    </div>
  )
}
