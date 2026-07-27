import {
  Activity,
  AlertCircle,
  Download,
  Pencil,
  Plus,
  Printer,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type FormEvent,
  type ReactNode,
} from 'react'
import { EmptyState, ErrorBlock, HueBadge, LoadingBlock, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage } from '../hooks/useAsync'
import { conditionsApi, symptomLogApi } from '../lib/api'
import { formatDate } from '../lib/format'
import { hueInk, hueStyle, hueVar } from '../lib/hues'
import type {
  ClaimedCondition,
  SymptomCriteria,
  SymptomLogEntry,
  SymptomLogEntryInput,
  SymptomLogExport,
} from '../types'

const HUE = 'teal' as const

/** Severity 0–10 → a quiet word + hue for the badge. */
function severityLabel(sev: number | null): { word: string; hue: 'rose' | 'amber' | 'emerald' } | null {
  if (sev === null || sev === undefined) return null
  if (sev >= 8) return { word: `Severe · ${sev}/10`, hue: 'rose' }
  if (sev >= 5) return { word: `Moderate · ${sev}/10`, hue: 'amber' }
  return { word: `Mild · ${sev}/10`, hue: 'emerald' }
}

const todayISO = () => new Date().toISOString().slice(0, 10)

export function SymptomLog() {
  const { toast } = useToast()
  const [conditions, setConditions] = useState<ClaimedCondition[]>([])
  const [conditionId, setConditionId] = useState<string>('') // '' = all
  const [entries, setEntries] = useState<SymptomLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<SymptomLogEntry | null>(null)
  const [criteria, setCriteria] = useState<SymptomCriteria | null>(null)
  const [exported, setExported] = useState<SymptomLogExport | null>(null)
  const [importing, setImporting] = useState(false)
  const [glitterEmpty, setGlitterEmpty] = useState(false)

  const load = () =>
    symptomLogApi
      .list(conditionId || undefined)
      .then((r) => {
        setEntries(r)
        setError(null)
      })
      .catch((e) => setError(errorMessage(e)))
      .finally(() => setLoading(false))

  useEffect(() => {
    conditionsApi.list().then(setConditions).catch(() => setConditions([]))
  }, [])

  useEffect(() => {
    setLoading(true)
    void load()
    setExported(null)
    // §4 criteria chips are only meaningful for a specific condition.
    if (conditionId) {
      symptomLogApi
        .criteria(conditionId)
        .then(setCriteria)
        .catch(() => setCriteria(null))
    } else {
      setCriteria(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conditionId])

  const conditionName = useMemo(
    () => conditions.find((c) => c.id === conditionId)?.name ?? null,
    [conditions, conditionId],
  )

  const remove = async (id: string) => {
    if (!window.confirm('Delete this symptom-log entry?')) return
    try {
      await symptomLogApi.remove(id)
      toast('Entry deleted.', 'success')
      void load()
    } catch (e) {
      toast(errorMessage(e), 'error')
    }
  }

  const pullFromGlitter = async () => {
    setImporting(true)
    try {
      const res = await symptomLogApi.importFromGlitter()
      if (res.imported > 0) {
        toast(`Imported ${res.imported} check-in${res.imported === 1 ? '' : 's'} from Glitter Mane.`, 'success')
        setGlitterEmpty(false)
        void load()
      } else {
        setGlitterEmpty(true)
        toast(res.detail || 'Nothing new to import from Glitter Mane.', 'info')
      }
    } catch (e) {
      setGlitterEmpty(true)
      toast(errorMessage(e), 'error')
    } finally {
      setImporting(false)
    }
  }

  const openExport = async () => {
    try {
      const res = await symptomLogApi.export(conditionId || undefined)
      setExported(res)
      // Let the print panel mount before scrolling to it.
      requestAnimationFrame(() =>
        document.getElementById('vo-lay-print')?.scrollIntoView({ behavior: 'smooth', block: 'start' }),
      )
    } catch (e) {
      toast(errorMessage(e), 'error')
    }
  }

  const startAdd = () => {
    setEditing(null)
    setShowForm(true)
  }
  const startEdit = (entry: SymptomLogEntry) => {
    setEditing(entry)
    setShowForm(true)
    requestAnimationFrame(() =>
      document.getElementById('vo-entry-form')?.scrollIntoView({ behavior: 'smooth', block: 'center' }),
    )
  }
  const closeForm = () => {
    setShowForm(false)
    setEditing(null)
  }
  const onSaved = () => {
    closeForm()
    void load()
  }

  return (
    <div data-section="claim" className="vo-page mx-auto w-full max-w-3xl space-y-6 p-4 pb-16 sm:p-6">
      <style>{PRINT_CSS}</style>

      <div className="vo-section-band vo-no-print">
        <p className="vo-caption mb-1">Claim tools</p>
        <h1 className="vo-page-title">Symptom log</h1>
        <p className="vo-page-sub">
          A dated record, in your own words, of the symptoms you live with and how they affect your
          day and your work. This is <em>your</em> lay evidence — competent and valuable. Log a flare
          the day it happens, tag the rating criteria it speaks to, and export a signed statement when
          you're ready. Nothing here is ever filed for you.
        </p>
      </div>

      {/* Controls */}
      <div className="vo-no-print flex flex-wrap items-center gap-3">
        <label className="text-sm">
          <span className="sr-only">Filter by condition</span>
          <select
            className="vo-input"
            value={conditionId}
            onChange={(e) => setConditionId(e.target.value)}
          >
            <option value="">All conditions</option>
            {conditions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {!glitterEmpty && (
            <button
              onClick={() => void pullFromGlitter()}
              disabled={importing}
              className="vo-btn-secondary text-xs"
              title="Pull your symptom check-ins from Glitter Mane"
            >
              {importing ? <Spinner size={13} /> : <Sparkles size={13} />} Pull from Glitter Mane
            </button>
          )}
          <button
            onClick={() => void openExport()}
            disabled={entries.length === 0}
            className="vo-btn-secondary text-xs"
          >
            <Download size={13} /> Export lay statement
          </button>
          <button onClick={startAdd} className="vo-btn-primary text-xs">
            <Plus size={13} /> Log symptom
          </button>
        </div>
      </div>

      {showForm && (
        <EntryForm
          id="vo-entry-form"
          editing={editing}
          conditions={conditions}
          conditionId={conditionId}
          criteria={criteria}
          onCancel={closeForm}
          onSaved={onSaved}
        />
      )}

      {/* List */}
      {loading ? (
        <LoadingBlock label="Loading…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={() => void load()} />
      ) : entries.length === 0 ? (
        <EmptyState
          hue={HUE}
          icon={<Activity size={20} />}
          title="No symptoms logged yet"
          description={
            conditionId
              ? 'Log the first entry for this condition — a bad day, a flare, or how a symptom got in the way. Small, dated notes add up to strong lay evidence.'
              : 'Start logging the symptoms you live with, the day they happen. Each dated entry becomes lay evidence you can export and sign. Track it in Glitter Mane already? Pull it in.'
          }
        />
      ) : (
        <div className="space-y-3">
          {entries.map((entry) => (
            <EntryCard
              key={entry.id}
              entry={entry}
              conditionName={conditions.find((c) => c.id === entry.condition_id)?.name ?? null}
              onEdit={() => startEdit(entry)}
              onRemove={() => void remove(entry.id)}
            />
          ))}
        </div>
      )}

      <p className="vo-no-print flex items-start gap-2 text-xs text-faint">
        <AlertCircle size={13} className="mt-0.5 shrink-0" />
        <span>
          Your symptom log is your own lay evidence. Record only what you have actually experienced —
          never exaggerate. An exported statement is prepared for <strong>your</strong> review and
          signature; it is educational self-help, not a document filed or submitted for you. A VSO can
          help you use it.
        </span>
      </p>

      {exported && (
        <ExportPanel
          data={exported}
          conditionName={conditionName}
          onClose={() => setExported(null)}
        />
      )}
    </div>
  )
}

// ── Entry card ───────────────────────────────────────────────────────────────
function EntryCard({
  entry,
  conditionName,
  onEdit,
  onRemove,
}: {
  entry: SymptomLogEntry
  conditionName: string | null
  onEdit: () => void
  onRemove: () => void
}) {
  const sev = severityLabel(entry.severity)
  return (
    <div className="vo-panel vo-accent p-5" style={hueStyle(HUE) as CSSProperties}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-txt">{entry.title}</span>
            {sev && <HueBadge hue={sev.hue}>{sev.word}</HueBadge>}
            {entry.source === 'glitter' && (
              <span
                className="vo-chip-hue inline-flex items-center gap-1"
                style={hueStyle('violet') as CSSProperties}
              >
                <Sparkles size={11} /> From Glitter Mane
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-faint">
            {formatDate(entry.entry_date)}
            {conditionName ? ` · ${conditionName}` : ''}
          </p>
        </div>
        <div className="vo-no-print flex items-center gap-1">
          <button onClick={onEdit} className="vo-icon-btn vo-btn-ghost text-muted hover:text-txt" aria-label="Edit entry">
            <Pencil size={14} />
          </button>
          <button
            onClick={onRemove}
            className="vo-icon-btn vo-btn-ghost text-muted hover:text-danger"
            aria-label="Delete entry"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-txt">{entry.symptoms}</p>

      {entry.functional_impact && (
        <p className="mt-2 text-sm leading-relaxed text-muted">
          <span className="font-medium text-txt">How it affected me: </span>
          {entry.functional_impact}
        </p>
      )}

      {entry.criteria_tags && entry.criteria_tags.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {entry.criteria_tags.map((tag) => (
            <span key={tag} className="vo-chip-hue" style={hueStyle(HUE) as CSSProperties}>
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Add / edit form ──────────────────────────────────────────────────────────
function EntryForm({
  id,
  editing,
  conditions,
  conditionId,
  criteria,
  onCancel,
  onSaved,
}: {
  id: string
  editing: SymptomLogEntry | null
  conditions: ClaimedCondition[]
  conditionId: string
  criteria: SymptomCriteria | null
  onCancel: () => void
  onSaved: () => void
}) {
  const { toast } = useToast()
  const [cond, setCond] = useState(editing?.condition_id ?? conditionId ?? '')
  const [entryDate, setEntryDate] = useState(editing?.entry_date ?? todayISO())
  const [title, setTitle] = useState(editing?.title ?? '')
  const [symptoms, setSymptoms] = useState(editing?.symptoms ?? '')
  const [severity, setSeverity] = useState<string>(
    editing?.severity !== null && editing?.severity !== undefined ? String(editing.severity) : '',
  )
  const [impact, setImpact] = useState(editing?.functional_impact ?? '')
  const [tags, setTags] = useState<string[]>(editing?.criteria_tags ?? [])
  const [saving, setSaving] = useState(false)

  const toggleTag = (tag: string) =>
    setTags((prev) => (prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag]))

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !symptoms.trim() || !entryDate) {
      toast('Add a date, a short title, and what you experienced.', 'error')
      return
    }
    const body: SymptomLogEntryInput = {
      condition_id: cond || null,
      entry_date: entryDate,
      title: title.trim(),
      symptoms: symptoms.trim(),
      severity: severity === '' ? null : Number(severity),
      functional_impact: impact.trim() || null,
      criteria_tags: tags.length ? tags : null,
    }
    setSaving(true)
    try {
      if (editing) {
        await symptomLogApi.update(editing.id, body)
        toast('Entry updated.', 'success')
      } else {
        await symptomLogApi.create(body)
        toast('Symptom logged.', 'success')
      }
      onSaved()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  // Chips come from the SELECTED condition's §4 criteria (only when it matches).
  const showChips = criteria && cond && cond === conditionId && criteria.tiers.length > 0

  return (
    <form id={id} onSubmit={submit} className="vo-panel vo-no-print space-y-4 p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-txt">{editing ? 'Edit entry' : 'Log a symptom'}</h2>
        <button type="button" onClick={onCancel} className="vo-icon-btn vo-btn-ghost text-muted" aria-label="Cancel">
          <X size={15} />
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="vo-label">Condition (optional)</span>
          <select className="vo-input" value={cond} onChange={(e) => setCond(e.target.value)}>
            <option value="">Not condition-specific</option>
            {conditions.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="vo-label">Date</span>
          <input
            type="date"
            className="vo-input"
            value={entryDate}
            max={todayISO()}
            onChange={(e) => setEntryDate(e.target.value)}
            required
          />
        </label>
      </div>

      <label className="block text-sm">
        <span className="vo-label">Title</span>
        <input
          className="vo-input"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Bad flare-up, missed work"
          maxLength={255}
          required
        />
      </label>

      <label className="block text-sm">
        <span className="vo-label">What you experienced</span>
        <textarea
          className="vo-input min-h-[96px]"
          value={symptoms}
          onChange={(e) => setSymptoms(e.target.value)}
          placeholder="Describe the symptoms in your own words — what, how often, how long."
          required
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-[160px_1fr]">
        <label className="text-sm">
          <span className="vo-label">Severity (0–10)</span>
          <input
            type="number"
            min={0}
            max={10}
            className="vo-input"
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            placeholder="optional"
          />
        </label>
        <label className="text-sm">
          <span className="vo-label">How it affected you (optional)</span>
          <input
            className="vo-input"
            value={impact}
            onChange={(e) => setImpact(e.target.value)}
            placeholder="e.g. couldn't drive, missed two shifts, avoided crowds"
          />
        </label>
      </div>

      {showChips && (
        <div>
          <p id="symptom-criteria-label" className="vo-label">Rating criteria this speaks to (tap to tag)</p>
          <p className="mb-2 text-xs text-faint">
            From the §4 schedule for {criteria!.condition_name}
            {criteria!.diagnostic_code ? ` (DC ${criteria!.diagnostic_code})` : ''}. Tag only what you
            honestly experienced.
          </p>
          <div className="space-y-2" role="group" aria-labelledby="symptom-criteria-label">
            {criteria!.tiers.map((tier) => (
              <div key={tier.percent} className="flex flex-wrap items-center gap-1.5">
                <span
                  className="text-micro font-semibold uppercase tracking-wide"
                  style={{ color: hueInk(HUE) }}
                >
                  {tier.percent}%
                </span>
                {tier.criteria.map((phrase) => {
                  const active = tags.includes(phrase)
                  return (
                    <button
                      type="button"
                      key={phrase}
                      onClick={() => toggleTag(phrase)}
                      aria-pressed={active}
                      className="vo-chip-hue cursor-pointer transition"
                      style={{
                        ...(hueStyle(HUE) as CSSProperties),
                        ...(active
                          ? { background: hueVar(HUE), color: 'white', borderColor: 'transparent' }
                          : {}),
                      }}
                    >
                      {phrase}
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="vo-btn-secondary text-sm">
          Cancel
        </button>
        <button type="submit" disabled={saving} className="vo-btn-primary text-sm">
          {saving ? <Spinner size={14} /> : editing ? <Pencil size={14} /> : <Plus size={14} />}
          {editing ? 'Save changes' : 'Log symptom'}
        </button>
      </div>
    </form>
  )
}

// ── Export / print panel ─────────────────────────────────────────────────────
function ExportPanel({
  data,
  conditionName,
  onClose,
}: {
  data: SymptomLogExport
  conditionName: string | null
  onClose: () => void
}) {
  return (
    <section id="vo-lay-print" className="vo-panel p-6" style={hueStyle(HUE) as CSSProperties}>
      <div className="vo-no-print mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-txt">Lay statement — for your review &amp; signature</h2>
          <p className="mt-0.5 text-xs text-faint">
            {data.entries_count} entr{data.entries_count === 1 ? 'y' : 'ies'}
            {conditionName ? ` · ${conditionName}` : ''}. Read it, edit anything that isn't exactly
            right, then print and sign. This is never filed for you.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => window.print()} className="vo-btn-primary text-xs">
            <Printer size={13} /> Print
          </button>
          <button onClick={onClose} className="vo-btn-ghost text-xs">
            <X size={13} /> Close
          </button>
        </div>
      </div>
      <Markdown source={data.markdown} />
    </section>
  )
}

/** Minimal, safe markdown renderer for the lay statement (headings, bold, rules,
 *  block-quote, paragraphs). No raw HTML is ever injected. */
function Markdown({ source }: { source: string }) {
  const blocks: ReactNode[] = []
  const lines = source.split('\n')
  let para: string[] = []

  const flush = (key: string) => {
    if (para.length === 0) return
    blocks.push(
      <p key={`p-${key}`} className="my-2 text-sm leading-relaxed text-txt">
        {inline(para.join(' '))}
      </p>,
    )
    para = []
  }

  lines.forEach((raw, i) => {
    const line = raw.trimEnd()
    if (line === '') {
      flush(String(i))
    } else if (line === '---') {
      flush(String(i))
      blocks.push(<hr key={`hr-${i}`} className="my-4 border-line" />)
    } else if (line.startsWith('## ')) {
      flush(String(i))
      blocks.push(
        <h3 key={`h3-${i}`} className="mt-5 text-heading text-txt">
          {inline(line.slice(3))}
        </h3>,
      )
    } else if (line.startsWith('# ')) {
      flush(String(i))
      blocks.push(
        <h2 key={`h2-${i}`} className="mt-2 text-title text-txt">
          {inline(line.slice(2))}
        </h2>,
      )
    } else if (line.startsWith('> ')) {
      flush(String(i))
      blocks.push(
        <blockquote
          key={`bq-${i}`}
          className="my-3 border-l-2 border-line pl-3 text-xs italic leading-relaxed text-muted"
        >
          {inline(line.slice(2))}
        </blockquote>,
      )
    } else if (line.startsWith('*') && line.endsWith('*') && !line.startsWith('**')) {
      flush(String(i))
      blocks.push(
        <p key={`em-${i}`} className="my-1 text-xs italic text-muted">
          {line.slice(1, -1)}
        </p>,
      )
    } else {
      para.push(line)
    }
  })
  flush('end')

  return <div className="vo-lay-body">{blocks}</div>
}

/** Render **bold** spans; everything else is plain text. */
function inline(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g)
  return parts.map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={i} className="font-semibold text-txt">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <span key={i}>{part}</span>
    ),
  )
}

// Print: show only the lay statement, hide the app chrome and all controls.
const PRINT_CSS = `
@media print {
  body * { visibility: hidden !important; }
  #vo-lay-print, #vo-lay-print * { visibility: visible !important; }
  #vo-lay-print {
    position: absolute; left: 0; top: 0; width: 100%;
    box-shadow: none !important; border: none !important; padding: 0 !important;
  }
  .vo-no-print { display: none !important; }
}
`
