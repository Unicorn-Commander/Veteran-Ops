import { AlarmClock, AlertCircle, CalendarClock, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState, type CSSProperties, type FormEvent } from 'react'
import { EmptyState, ErrorBlock, HueBadge, LoadingBlock, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage } from '../hooks/useAsync'
import { itfApi, vaApi } from '../lib/api'
import { formatDate, humanize } from '../lib/format'
import { hueInk, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { ItfRecord, ItfResult, ItfType, VaItf } from '../types'

/** Days-remaining → urgency hue. */
function urgencyHue(days: number, expired: boolean): Hue {
  if (expired) return 'rose'
  if (days < 30) return 'rose'
  if (days < 90) return 'amber'
  return 'emerald'
}

const ITF_TYPES: ItfType[] = ['compensation', 'pension', 'survivors']

export function Itf() {
  const { toast } = useToast()
  const [data, setData] = useState<ItfResult | null>(null)
  const [vaItf, setVaItf] = useState<VaItf | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)

  const load = () =>
    itfApi
      .list()
      .then((r) => {
        setData(r)
        setError(null)
      })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false))

  useEffect(() => {
    void load()
    // Best-effort: surface the VA connector's active ITF if the veteran connected it.
    vaApi.itfActive().then(setVaItf).catch(() => setVaItf(null))
  }, [])

  const remove = async (id: string) => {
    if (!window.confirm('Remove this Intent to File reminder?')) return
    try {
      await itfApi.remove(id)
      toast('Reminder removed.', 'success')
      void load()
    } catch (e) {
      toast(errorMessage(e), 'error')
    }
  }

  return (
    <div data-section="claim" className="vo-page mx-auto w-full max-w-3xl space-y-6 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Claim tools</p>
        <h1 className="vo-page-title">Intent to File</h1>
        <p className="vo-page-sub">
          An Intent to File locks in your effective date for one year while you gather evidence — back
          pay runs from the ITF date, not the day you finally submit. Track yours here so the deadline
          never slips. Filing an ITF is free and binds you to nothing.
        </p>
      </div>

      {vaItf?.active && (
        <div className="vo-panel vo-accent flex items-start gap-3 p-4" style={hueStyle('sky') as CSSProperties}>
          <CalendarClock size={18} className="mt-0.5 shrink-0" style={{ color: hueVar('sky') }} />
          <div className="min-w-0 text-sm">
            <p className="font-semibold text-txt">VA shows an active Intent to File</p>
            <p className="mt-0.5 text-muted">
              {vaItf.type ? `${humanize(vaItf.type)} · ` : ''}
              {vaItf.expiration_date ? `expires ${formatDate(vaItf.expiration_date)}` : 'from your connected VA.gov account'}.
            </p>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-txt">Your reminders</h2>
        <button type="button" onClick={() => setShowForm((v) => !v)} className="vo-btn-secondary text-xs">
          <Plus size={13} /> Add ITF
        </button>
      </div>

      {showForm && <ItfForm onCreated={() => { setShowForm(false); void load() }} />}

      {loading ? (
        <LoadingBlock label="Loading…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={() => void load()} />
      ) : !data || data.records.length === 0 ? (
        <EmptyState
          hue="sky"
          icon={<AlarmClock size={20} />}
          title="No Intent to File tracked yet"
          description="Filed an ITF at VA.gov, by phone, or on Form 21-0966? Add its date and Rating Raider will count down your one-year window. Haven't filed one? It's usually the first step — it costs nothing and can protect an earlier effective date."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <button type="button" onClick={() => setShowForm(true)} className="vo-btn-primary text-sm">
                Track an ITF date
              </button>
              <a
                href="https://www.va.gov/resources/your-intent-to-file-a-va-claim/"
                target="_blank"
                rel="noopener noreferrer"
                className="vo-btn-secondary text-sm"
              >
                Learn on VA.gov
              </a>
            </div>
          }
        />
      ) : (
        <div className="space-y-3">
          {data.records.map((r) => (
            <ItfCard key={r.id ?? r.filed_date} rec={r} onRemove={r.id ? () => void remove(r.id as string) : undefined} />
          ))}
        </div>
      )}

      {data && (
        <p className="flex items-start gap-2 text-xs text-faint">
          <AlertCircle size={13} className="mt-0.5 shrink-0" />
          <span>{data.disclaimer}</span>
        </p>
      )}
    </div>
  )
}

function ItfCard({ rec, onRemove }: { rec: ItfRecord; onRemove?: () => void }) {
  const hue = urgencyHue(rec.days_remaining, rec.expired)
  return (
    <div className="vo-panel vo-accent flex flex-wrap items-center justify-between gap-3 p-5" style={hueStyle(hue) as CSSProperties}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-txt">{humanize(rec.type)} claim</span>
          <HueBadge hue={hue}>
            {rec.expired ? 'Window passed' : `${rec.days_remaining} days left`}
          </HueBadge>
          {rec.source === 'va' && <span className="text-xs text-faint">from VA.gov</span>}
        </div>
        <p className="mt-1 text-xs text-faint">
          Filed {formatDate(rec.filed_date)} · file by {formatDate(rec.deadline)}
          {rec.notes ? ` · ${rec.notes}` : ''}
        </p>
      </div>
      <div className="flex items-center gap-3">
        <span className="text-right">
          <span className="block text-2xl font-bold tabular-nums" style={{ color: hueInk(hue) }}>
            {rec.expired ? '—' : rec.days_remaining}
          </span>
          <span className="text-micro uppercase tracking-wide text-faint">
            {rec.expired ? 'expired' : 'days left'}
          </span>
        </span>
        {onRemove && (
          <button onClick={onRemove} className="vo-icon-btn vo-btn-ghost text-muted hover:text-danger" aria-label="Remove reminder">
            <Trash2 size={15} />
          </button>
        )}
      </div>
    </div>
  )
}

function ItfForm({ onCreated }: { onCreated: () => void }) {
  const { toast } = useToast()
  const [type, setType] = useState<ItfType>('compensation')
  const [filedDate, setFiledDate] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!filedDate) {
      toast('Enter the date you filed the ITF.', 'error')
      return
    }
    setSaving(true)
    try {
      await itfApi.create({ type, filed_date: filedDate, source: 'manual', notes: notes || null })
      toast('Reminder added.', 'success')
      onCreated()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={submit} className="vo-panel space-y-3 p-5">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="vo-label">Type</span>
          <select className="vo-input" value={type} onChange={(e) => setType(e.target.value as ItfType)}>
            {ITF_TYPES.map((t) => (
              <option key={t} value={t}>{humanize(t)}</option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="vo-label">Date filed</span>
          <input type="date" className="vo-input" value={filedDate} onChange={(e) => setFiledDate(e.target.value)} required />
        </label>
      </div>
      <label className="block text-sm">
        <span className="vo-label">Notes (optional)</span>
        <input className="vo-input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. filed online at VA.gov" />
      </label>
      <div className="flex justify-end">
        <button type="submit" disabled={saving} className="vo-btn-primary text-sm">
          {saving ? <Spinner size={14} /> : <Plus size={14} />} Add reminder
        </button>
      </div>
    </form>
  )
}
