import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckSquare,
  ClipboardList,
  Download,
  ChevronDown,
  Eye,
  FileText,
  FlaskConical,
  Plus,
  Printer,
  Pin,
  Save,
  Search,
  Square,
  Trash2,
} from 'lucide-react'
import { useState, type CSSProperties, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { DocumentViewer } from '../components/DocumentViewer'
import { KbFreshnessNote } from '../components/KbFreshnessNote'
import { RuleChangeBanner } from '../components/RuleChangeBanner'
import { Checkbox, EmptyState, ErrorBlock, HueBadge, LoadingBlock, Panel, Spinner, cx } from '../components/ui'
import { StatusPipeline } from '../components/StatusPipeline'
import { EVIDENCE_KIND_ICONS } from '../components/evidenceIcons'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { conditionsApi, documentsApi, evidenceApi, glitterApi } from '../lib/api'
import { CLAIM_TYPE_HUES, EVIDENCE_STATUS_HUES, hueInk, hueStyle, type Hue } from '../lib/hues'
import { humanize } from '../lib/format'
import type {
  ClaimedCondition,
  ClaimType,
  ConditionStatus,
  EvidenceCitation,
  EvidenceItem,
  EvidenceKind,
  EvidenceStatus,
  GapsResponse,
  GlitterLab,
  GlitterVital,
  VaConditionStatus,
} from '../types'
import type { DocumentItem } from '../types'

const CLAIM_TYPES: ClaimType[] = ['direct', 'secondary', 'presumptive', 'increase']
const STATUSES: ConditionStatus[] = ['considering', 'gathering_evidence', 'ready_to_file', 'filed', 'decided']
// The condition's real VA disposition (distinct from the workflow status above).
const VA_STATUS_OPTIONS: { value: VaConditionStatus; label: string }[] = [
  { value: 'unknown', label: 'Not yet claimed' },
  { value: 'service_connected', label: 'Service-connected' },
  { value: 'denied', label: 'Denied' },
  { value: 'pending', label: 'Claim pending' },
]
const EVIDENCE_KINDS: EvidenceKind[] = [
  'diagnosis', 'service_record', 'nexus_letter', 'dbq', 'lay_statement', 'continuity', 'treatment_record', 'other',
]
const EVIDENCE_STATUSES: EvidenceStatus[] = ['have', 'need', 'requested', 'not_applicable']

type ViewerFocus = {
  char_start: number
  char_end: number
  quote: string
  page?: number | null
  note?: string | null
}

export function ConditionDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { toast } = useToast()

  const {
    data: condition,
    loading,
    error,
    reload,
    setData: setCondition,
  } = useAsync(() => conditionsApi.get(id!), [id])

  const {
    data: evidence,
    loading: evidenceLoading,
    error: evidenceError,
    reload: reloadEvidence,
    setData: setEvidence,
  } = useAsync(() => evidenceApi.list(id!), [id])

  const [saving, setSaving] = useState(false)
  const [gaps, setGaps] = useState<GapsResponse | null>(null)
  const [analyzing, setAnalyzing] = useState(false)
  const [showEvidenceForm, setShowEvidenceForm] = useState(false)
  const [showGlitterImport, setShowGlitterImport] = useState(false)
  const [viewerDoc, setViewerDoc] = useState<DocumentItem | null>(null)
  const [viewerFocus, setViewerFocus] = useState<ViewerFocus | null>(null)
  // Optional: offer to pull objective measurements (labs/vitals) as evidence
  // when the veteran's Glitter Mane bridge is live. Hidden entirely otherwise.
  const { data: glitterStatus } = useAsync(() => glitterApi.status().catch(() => null), [])
  const glitterReady = !!glitterStatus?.enabled && !!glitterStatus?.reachable

  if (loading) return <LoadingBlock label="Loading condition…" />
  if (error || !condition) {
    return (
      <div className="p-6">
        <ErrorBlock message={error ?? 'Condition not found.'} onRetry={reload} />
        <div className="mt-3 text-center">
          <Link to="/conditions" className="inline-flex items-center gap-1 text-sm font-semibold text-brand">
            <ArrowLeft size={14} /> Back to conditions
          </Link>
        </div>
      </div>
    )
  }

  const setField = <K extends keyof ClaimedCondition>(key: K, value: ClaimedCondition[K]) =>
    setCondition((prev) => (prev ? { ...prev, [key]: value } : prev))

  const save = async () => {
    if (!condition) return
    setSaving(true)
    try {
      const updated = await conditionsApi.update(condition.id, {
        name: condition.name,
        body_system: condition.body_system,
        diagnostic_code: condition.diagnostic_code,
        claim_type: condition.claim_type,
        secondary_to: condition.secondary_to,
        current_rating: condition.current_rating,
        target_rating: condition.target_rating,
        status: condition.status,
        va_status: condition.va_status,
        onset_date: condition.onset_date,
        in_service_event: condition.in_service_event,
        nexus_notes: condition.nexus_notes,
        dbq_form: condition.dbq_form,
        notes: condition.notes,
      })
      setCondition(updated)
      toast('Condition saved.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  const removeCondition = async () => {
    if (!condition) return
    if (!window.confirm(`Remove "${condition.name}" and its evidence tracking?`)) return
    try {
      await conditionsApi.remove(condition.id)
      toast('Condition removed.', 'success')
      navigate('/conditions', { replace: true })
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const analyzeGaps = async () => {
    setAnalyzing(true)
    try {
      const result = await conditionsApi.gaps(condition.id)
      setGaps(result)
      // The backend persists the mapped DBQ onto the condition when it was
      // unset — reflect that in the form so the field doesn't look stale.
      if (result.dbq_form && !condition.dbq_form) setField('dbq_form', result.dbq_form)
      const n = result.gaps.length
      toast(
        n === 0
          ? 'No gaps found.'
          : `Found ${n} gap${n === 1 ? '' : 's'} — added to your checklist.`,
        'info',
      )
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setAnalyzing(false)
    }
  }

  const openEvidenceDocument = async (item: EvidenceItem, focus: ViewerFocus | null = null) => {
    if (!item.document_id) return
    try {
      setViewerDoc(await documentsApi.get(item.document_id))
      setViewerFocus(focus)
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div data-section="claim" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="flex items-center justify-between gap-3">
        <Link to="/conditions" className="inline-flex items-center gap-1 text-sm font-medium text-muted hover:text-txt">
          <ArrowLeft size={14} /> Conditions
        </Link>
        <div className="flex gap-2">
          <Link to={`/conditions/${condition.id}/packet`} className="vo-btn-primary text-sm">
            <Printer size={14} /> Build packet
          </Link>
          <button onClick={() => void removeCondition()} className="vo-btn-danger min-h-10 text-sm">
            <Trash2 size={14} /> Remove
          </button>
        </div>
      </div>

      <div className="vo-section-band flex flex-wrap items-center gap-2">
        <h1 className="vo-page-title">{condition.name}</h1>
        <HueBadge hue={CLAIM_TYPE_HUES[condition.claim_type] ?? 'violet'}>{humanize(condition.claim_type)}</HueBadge>
      </div>
      <KbFreshnessNote hue="amber" />
      <RuleChangeBanner diagnosticCode={condition.diagnostic_code} />

      <div className="vo-card overflow-x-auto p-4">
        <StatusPipeline status={condition.status} showLabels />
      </div>

      <SectionNav
        items={[
          { id: 'cd-details', label: 'Details', hue: 'emerald' },
          { id: 'cd-gaps', label: 'Evidence gaps', hue: 'amber' },
          { id: 'cd-evidence', label: 'Evidence', hue: 'teal' },
        ]}
      />

      {/* Editable fields */}
      <div id="cd-details" className="scroll-mt-24">
      <Panel hue="emerald" title="Details">
        <div className="grid gap-3 p-5 sm:grid-cols-2">
          <label className="text-sm">
            <span className="vo-label">Name</span>
            <input className="vo-input" value={condition.name} onChange={(e) => setField('name', e.target.value)} />
          </label>
          <label className="text-sm">
            <span className="vo-label">Body system</span>
            <input
              className="vo-input"
              value={condition.body_system ?? ''}
              onChange={(e) => setField('body_system', e.target.value || null)}
              placeholder="e.g. Musculoskeletal"
            />
          </label>
          <label className="text-sm">
            <span className="vo-label">Diagnostic code</span>
            <input
              className="vo-input"
              value={condition.diagnostic_code ?? ''}
              onChange={(e) => setField('diagnostic_code', e.target.value || null)}
              placeholder="e.g. 5257"
            />
          </label>
          <label className="text-sm">
            <span className="vo-label">Claim type</span>
            <select className="vo-input" value={condition.claim_type} onChange={(e) => setField('claim_type', e.target.value as ClaimType)}>
              {CLAIM_TYPES.map((t) => (
                <option key={t} value={t}>{humanize(t)}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="vo-label">Status</span>
            <select className="vo-input" value={condition.status} onChange={(e) => setField('status', e.target.value as ConditionStatus)}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>{humanize(s)}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="vo-label">VA status</span>
            <select
              className="vo-input"
              value={condition.va_status ?? 'unknown'}
              onChange={(e) => setField('va_status', e.target.value as VaConditionStatus)}
            >
              {VA_STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            <span className="vo-label">Onset date</span>
            <input
              type="date"
              className="vo-input"
              value={condition.onset_date ?? ''}
              onChange={(e) => setField('onset_date', e.target.value || null)}
            />
          </label>
          <label className="text-sm">
            <span className="vo-label">Current rating (%)</span>
            <input
              type="number"
              min={0}
              max={100}
              className="vo-input"
              value={condition.current_rating ?? ''}
              onChange={(e) => setField('current_rating', e.target.value === '' ? null : Number(e.target.value))}
            />
          </label>
          <label className="text-sm">
            <span className="vo-label">Target rating (%)</span>
            <input
              type="number"
              min={0}
              max={100}
              className="vo-input"
              value={condition.target_rating ?? ''}
              onChange={(e) => setField('target_rating', e.target.value === '' ? null : Number(e.target.value))}
            />
          </label>
          <label className="text-sm sm:col-span-2">
            <span className="vo-label">In-service event</span>
            <textarea
              className="vo-input min-h-[70px]"
              value={condition.in_service_event ?? ''}
              onChange={(e) => setField('in_service_event', e.target.value || null)}
              placeholder="What happened in service that relates to this condition"
            />
          </label>
          <label className="text-sm sm:col-span-2">
            <span className="vo-label">Nexus notes</span>
            <textarea
              className="vo-input min-h-[70px]"
              value={condition.nexus_notes ?? ''}
              onChange={(e) => setField('nexus_notes', e.target.value || null)}
              placeholder="Your notes on the link between service and this condition — discuss with your provider"
            />
          </label>
          <label className="text-sm sm:col-span-2">
            <span className="vo-label">DBQ form</span>
            <input
              className="vo-input"
              value={condition.dbq_form ?? ''}
              onChange={(e) => setField('dbq_form', e.target.value || null)}
              placeholder="e.g. 21-0960M-14"
            />
          </label>
          <label className="text-sm sm:col-span-2">
            <span className="vo-label">Notes</span>
            <textarea
              className="vo-input min-h-[70px]"
              value={condition.notes ?? ''}
              onChange={(e) => setField('notes', e.target.value || null)}
            />
          </label>
        </div>
        <div className="flex justify-end border-t border-line px-5 py-4">
          <button onClick={() => void save()} disabled={saving} className="vo-btn-primary">
            {saving ? <Spinner size={16} className="text-white" /> : <Save size={15} />}
            Save changes
          </button>
        </div>
      </Panel>
      </div>

      {/* Gap analysis */}
      <div id="cd-gaps" className="scroll-mt-24">
      <Panel
        hue="amber"
        title="Evidence gaps"
        subtitle="Deterministic check against what your claim type needs"
        action={
          <button onClick={() => void analyzeGaps()} disabled={analyzing} className="vo-btn-secondary text-sm">
            {analyzing ? <Spinner size={14} /> : <Search size={14} />}
            Analyze gaps
          </button>
        }
      >
        <div className="p-5">
          {!gaps ? (
            <p className="text-sm text-muted">Run the analysis to see what evidence this claim type typically needs.</p>
          ) : gaps.gaps.length === 0 ? (
            <p className="text-sm text-success">No gaps found — your evidence looks complete for this claim type.</p>
          ) : (
            <ul className="space-y-2.5">
              {gaps.gaps.map((gap, i) => (
                <li key={i} className="flex items-start gap-2.5 rounded-control border border-warn/30 bg-h-amber-soft px-3.5 py-2.5 text-sm">
                  <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" />
                  <div>
                    <p className="font-medium text-txt">{gap.label}</p>
                    {gap.detail && <p className="mt-0.5 text-txt">{gap.detail}</p>}
                    {gap.source && <p className="mt-0.5 text-xs text-faint">{gap.source}</p>}
                  </div>
                </li>
              ))}
            </ul>
          )}
          {gaps?.dbq_form && (
            <div className="vo-accent mt-4 rounded-card border border-[color-mix(in_oklab,var(--hue-violet)_25%,transparent)] bg-h-violet-soft p-4" style={{ '--hue': 'var(--hue-violet)', '--hue-soft': 'var(--hue-violet-soft)' } as CSSProperties}>
              <div className="mb-1.5 flex items-center gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-surface text-h-violet">
                  <ClipboardList size={14} />
                </span>
                <h3 className="text-sm font-semibold" style={{ color: hueInk('violet') }}>Suggested DBQ</h3>
                <span className="vo-chip border-[color-mix(in_oklab,var(--hue-violet)_25%,transparent)] bg-surface text-[11px] text-h-violet">{gaps.dbq_form}</span>
              </div>
              <p className="mt-1 text-xs text-muted">
                Ask your provider to complete this Disability Benefits Questionnaire.
              </p>
            </div>
          )}
          {gaps && gaps.checklist.length > 0 && (
            <div className="mt-4 rounded-control border border-line bg-surface2 p-4">
              <h3 className="mb-2 text-sm font-semibold text-txt">Checklist for this condition</h3>
              <ul className="space-y-1.5">
                {gaps.checklist.map((item) => (
                  <li key={item.id} className="flex items-start gap-2 text-sm">
                    {item.done ? (
                      <CheckSquare size={15} className="mt-0.5 shrink-0 text-success" />
                    ) : (
                      <Square size={15} className="mt-0.5 shrink-0 text-faint" />
                    )}
                    <span className={item.done ? 'text-muted line-through' : 'text-txt'}>{item.text}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </Panel>
      </div>

      {/* Evidence list */}
      <div id="cd-evidence" className="scroll-mt-24">
      <Panel
        hue="teal"
        title="Evidence"
        action={
          <>
            {glitterReady && (
              <button
                onClick={() => setShowGlitterImport((s) => !s)}
                className="vo-btn-ghost text-sm"
              >
                <Download size={14} /> Import from Glitter Mane
              </button>
            )}
            <button onClick={() => setShowEvidenceForm((s) => !s)} className="vo-btn-secondary text-sm">
              <Plus size={14} /> Add evidence
            </button>
          </>
        }
      >
        <div className="p-5">
          {showGlitterImport && glitterReady && (
            <GlitterEvidenceImport
              conditionId={condition.id}
              onImported={() => {
                setShowGlitterImport(false)
                reloadEvidence()
              }}
            />
          )}
          {showEvidenceForm && (
            <EvidenceForm
              conditionId={condition.id}
              onCreated={(item) => {
                setEvidence((prev) => [item, ...(prev ?? [])])
                setShowEvidenceForm(false)
              }}
            />
          )}
          {evidenceError ? (
            <ErrorBlock message={evidenceError} onRetry={reloadEvidence} />
          ) : evidenceLoading || !evidence ? (
            <LoadingBlock label="Loading evidence…" />
          ) : evidence.length === 0 ? (
            <EmptyState
              icon={<ClipboardList size={20} />}
              title="No evidence tracked yet"
              description="Add diagnoses, service records, DBQs, or lay statements as you gather them."
              action={
                <button onClick={() => setShowEvidenceForm(true)} className="vo-btn-primary text-sm">
                  <Plus size={15} /> Add evidence
                </button>
              }
            />
          ) : (
            <ul className="mt-3 space-y-2">
              {evidence.map((item) => (
                <EvidenceRow
                  key={item.id}
                  item={item}
                  onUpdated={(updated) => setEvidence((prev) => (prev ?? []).map((e) => (e.id === updated.id ? updated : e)))}
                  onDeleted={(id) => setEvidence((prev) => (prev ?? []).filter((e) => e.id !== id))}
                onViewDocument={(focus) => void openEvidenceDocument(item, focus ?? null)}
              />
            ))}
          </ul>
          )}
        </div>
      </Panel>
      </div>
      <DocumentViewer
        doc={viewerDoc}
        focus={viewerFocus}
        onClose={() => {
          setViewerDoc(null)
          setViewerFocus(null)
        }}
      />
    </div>
  )
}

/** Slim sticky anchor-nav for long condition-detail pages — chips scroll the
 * page to each Panel below (each target carries scroll-mt-24 to clear the
 * shared Shell topbar). Colored per this page's claim hue family. */
function SectionNav({ items }: { items: { id: string; label: string; hue: Hue }[] }) {
  return (
    <nav
      aria-label="Jump to section"
      className="vo-no-print sticky top-16 z-30 -mx-1 flex flex-wrap gap-1.5 rounded-full border border-line bg-surface/90 px-2 py-1.5 backdrop-blur"
    >
      {items.map((it) => (
        <a key={it.id} href={`#${it.id}`} className="vo-chip-hue no-underline" style={hueStyle(it.hue) as CSSProperties}>
          {it.label}
        </a>
      ))}
    </nav>
  )
}

/** Optional flow: pull objective measurements (labs + vitals) from the
 * veteran's Glitter Mane record and attach the selected ones to THIS condition
 * as evidence. These raw, dated, provider-authored values are exactly what the
 * VA rating schedule is scored on (BP, eGFR, A1c, FEV1…). No AI interpretation
 * crosses the bridge — only the measurements the veteran already owns. */
function GlitterEvidenceImport({
  conditionId,
  onImported,
}: {
  conditionId: string
  onImported: () => void
}) {
  const { toast } = useToast()
  const { data: labs, loading: labsLoading, error: labsError, reload: reloadLabs } = useAsync(
    () => glitterApi.labs().catch(() => [] as GlitterLab[]),
    []
  )
  const { data: vitals, loading: vitalsLoading, error: vitalsError, reload: reloadVitals } = useAsync(
    () => glitterApi.vitals().catch(() => [] as GlitterVital[]),
    []
  )
  const [selLabs, setSelLabs] = useState<Set<string>>(new Set())
  const [selVitals, setSelVitals] = useState<Set<string>>(new Set())
  const [importing, setImporting] = useState(false)

  const loading = labsLoading || vitalsLoading
  const error = labsError || vitalsError
  const total = (labs?.length ?? 0) + (vitals?.length ?? 0)
  const selectedCount = selLabs.size + selVitals.size

  const toggle = (set: React.Dispatch<React.SetStateAction<Set<string>>>, id: string) =>
    set((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const runImport = async () => {
    if (selectedCount === 0) return
    setImporting(true)
    try {
      const result = await glitterApi.importEvidence({
        condition_id: conditionId,
        lab_ids: Array.from(selLabs),
        vital_ids: Array.from(selVitals),
      })
      toast(
        `Imported ${result.imported} measurement${result.imported === 1 ? '' : 's'} as evidence.`,
        'success'
      )
      onImported()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="mb-4 rounded-pane border border-line bg-surface2/60 p-4">
      <div className="mb-1 flex items-center gap-2">
        <Download size={15} className="text-muted" aria-hidden />
        <h3 className="text-heading font-semibold text-txt">Import from Glitter Mane</h3>
      </div>
      <p className="mb-3 text-xs leading-relaxed text-muted">
        Pick the labs and vitals that support this claim. They attach as
        provider-sourced evidence (marked “Glitter Mane”) — the dated values VA
        raters look for. Nothing is interpreted; only your own measurements move.
      </p>

      {loading ? (
        <LoadingBlock label="Loading your measurements…" />
      ) : error ? (
        <ErrorBlock
          message={error}
          onRetry={() => {
            reloadLabs()
            reloadVitals()
          }}
        />
      ) : total === 0 ? (
        <EmptyState
          icon={<FlaskConical size={20} />}
          title="No labs or vitals found"
          description="Add measurements in Glitter Mane and they'll show up here to import."
          hue="teal"
        />
      ) : (
        <div className="space-y-4">
          {(labs?.length ?? 0) > 0 && (
            <MeasureGroup icon={<FlaskConical size={13} />} label="Labs">
              {labs!.map((l) => (
                <Checkbox
                  key={l.id}
                  checked={selLabs.has(l.id)}
                  onChange={() => toggle(setSelLabs, l.id)}
                  label={measureTitle(l.name, l.value, l.unit, l.taken_on)}
                  description={l.reference_range ? `Reference: ${l.reference_range}` : undefined}
                />
              ))}
            </MeasureGroup>
          )}
          {(vitals?.length ?? 0) > 0 && (
            <MeasureGroup icon={<Activity size={13} />} label="Vitals">
              {vitals!.map((v) => (
                <Checkbox
                  key={v.id}
                  checked={selVitals.has(v.id)}
                  onChange={() => toggle(setSelVitals, v.id)}
                  label={measureTitle(humanize(v.type), v.value, v.unit, v.taken_on)}
                />
              ))}
            </MeasureGroup>
          )}
          <div className="flex items-center justify-end gap-2 border-t border-line pt-3">
            <span className="mr-auto text-xs text-muted">{selectedCount} selected</span>
            <button
              onClick={runImport}
              disabled={selectedCount === 0 || importing}
              className="vo-btn-primary text-sm"
            >
              {importing ? <Spinner size={15} /> : <Download size={14} />}
              Import as evidence
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

/** One labeled group of measurement checkboxes (Labs / Vitals). */
function MeasureGroup({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 vo-label-micro">
        <span aria-hidden className="text-faint">{icon}</span>
        {label}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

/** Compact "name: value unit — date" line used in the measurement picker. */
function measureTitle(
  name: string,
  value?: string | null,
  unit?: string | null,
  takenOn?: string | null
): string {
  let s = name
  if (value) s += `: ${value}${unit ? ` ${unit}` : ''}`
  if (takenOn) s += ` — ${takenOn.slice(0, 10)}`
  return s
}

function EvidenceForm({ conditionId, onCreated }: { conditionId: string; onCreated: (item: EvidenceItem) => void }) {
  const { toast } = useToast()
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<EvidenceKind>('diagnosis')
  const [status, setStatus] = useState<EvidenceStatus>('need')
  const [submitting, setSubmitting] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!title.trim()) return
    setSubmitting(true)
    try {
      const item = await evidenceApi.create(conditionId, { title: title.trim(), kind, status })
      onCreated(item)
      setTitle('')
      toast('Evidence added.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={submit} className="mb-4 flex flex-wrap items-end gap-3 rounded-control border border-line bg-surface2 p-4">
      <label className="min-w-[200px] flex-1 text-sm">
        <span className="vo-label">Title</span>
        <input className="vo-input" value={title} onChange={(e) => setTitle(e.target.value)} required autoFocus />
      </label>
      <label className="text-sm">
        <span className="vo-label">Kind</span>
        <select className="vo-input" value={kind} onChange={(e) => setKind(e.target.value as EvidenceKind)}>
          {EVIDENCE_KINDS.map((k) => (
            <option key={k} value={k}>{humanize(k)}</option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="vo-label">Status</span>
        <select className="vo-input" value={status} onChange={(e) => setStatus(e.target.value as EvidenceStatus)}>
          {EVIDENCE_STATUSES.map((s) => (
            <option key={s} value={s}>{humanize(s)}</option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={submitting} className="vo-btn-primary">
        {submitting ? <Spinner size={16} className="text-white" /> : <Plus size={15} />}
        Add
      </button>
    </form>
  )
}

function EvidenceRow({
  item,
  onUpdated,
  onDeleted,
  onViewDocument,
}: {
  item: EvidenceItem
  onUpdated: (item: EvidenceItem) => void
  onDeleted: (id: string) => void
  onViewDocument: (focus?: ViewerFocus | null) => void
}) {
  const { toast } = useToast()
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const citations = item.citations ?? []
  const selectedCitation = citations.find((c) => c.selected) ?? citations[0] ?? null
  const rationale = item.rationale ?? null

  const changeStatus = async (status: EvidenceStatus) => {
    setBusy(true)
    try {
      const updated = await evidenceApi.update(item.id, { status })
      onUpdated(updated)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  const pinCitation = async (citation: EvidenceCitation, note: string) => {
    try {
      const updated = await evidenceApi.pinCitation(item.id, {
        quote: citation.quote,
        char_start: citation.char_start,
        char_end: citation.char_end,
        page: citation.page,
        chunk_index: citation.chunk_index,
        note: note.trim() || null,
      })
      onUpdated(updated)
      toast('Citation pinned.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const remove = async () => {
    try {
      await evidenceApi.remove(item.id)
      onDeleted(item.id)
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const Icon = EVIDENCE_KIND_ICONS[item.kind] ?? FileText
  return (
    <li className="rounded-control border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface2 text-muted">
            <Icon size={15} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-txt">{item.title}</p>
            <p className="text-xs text-faint">{humanize(item.kind)}</p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <select
            className="vo-input py-1.5 text-xs"
            value={item.status}
            disabled={busy}
            onChange={(e) => void changeStatus(e.target.value as EvidenceStatus)}
          >
            {EVIDENCE_STATUSES.map((s) => (
              <option key={s} value={s}>{humanize(s)}</option>
            ))}
          </select>
          <HueBadge hue={EVIDENCE_STATUS_HUES[item.status] ?? 'indigo'}>{humanize(item.status)}</HueBadge>
          {item.document_id && (
            <button
              onClick={() => onViewDocument(selectedCitation ? {
                char_start: selectedCitation.char_start,
                char_end: selectedCitation.char_end,
                quote: selectedCitation.quote,
                page: selectedCitation.page,
                note: selectedCitation.note,
              } : null)}
              className="vo-btn-secondary text-xs"
              aria-label="View source document"
              title="View source document"
            >
              <Eye size={13} /> Source
            </button>
          )}
          <button
            onClick={() => setExpanded((v) => !v)}
            className="vo-btn-secondary text-xs"
            aria-expanded={expanded}
          >
            <ChevronDown size={13} className={cx('transition-transform', expanded && 'rotate-180')} />
            {expanded ? 'Hide' : 'Why this is evidence'}
          </button>
          <button onClick={() => void remove()} className="vo-icon-btn vo-btn-ghost text-muted hover:text-danger" aria-label="Remove evidence">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-line px-4 py-4">
          <div className="space-y-4">
            <div>
              <p className="vo-label-micro mb-1.5">Why this counts</p>
              {rationale ? (
                <div className="rounded-control border border-line bg-surface2 p-3 text-sm text-txt">
                  <p className="font-medium text-txt">{humanize(item.kind)}</p>
                  <p className="mt-1 text-xs uppercase tracking-wide text-faint">
                    {rationale.elements.length > 0 ? rationale.elements.join(' · ') : 'General support'}
                  </p>
                  <p className="mt-2 text-sm leading-relaxed text-txt">{rationale.why}</p>
                </div>
              ) : (
                <p className="text-sm text-muted">No rationale available yet.</p>
              )}
            </div>

            <div>
              <p className="vo-label-micro mb-1.5">In your records</p>
              {citations.length === 0 ? (
                <p className="text-sm text-muted">No matching citation found yet for this evidence item.</p>
              ) : (
                <ul className="space-y-2">
                  {citations.map((citation) => (
                    <CitationCard
                      key={`${citation.document_id}-${citation.chunk_index}-${citation.char_start}`}
                      citation={citation}
                      selected={citation.selected}
                      onOpen={() => onViewDocument({
                        char_start: citation.char_start,
                        char_end: citation.char_end,
                        quote: citation.quote,
                        page: citation.page,
                        note: citation.note,
                      })}
                      onPin={(note) => void pinCitation(citation, note)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </li>
  )
}

function CitationCard({
  citation,
  selected,
  onOpen,
  onPin,
}: {
  citation: EvidenceCitation
  selected: boolean
  onOpen: () => void
  onPin: (note: string) => void
}) {
  const [note, setNote] = useState(citation.note ?? '')

  return (
    <li className={cx('rounded-control border p-3', selected ? 'border-brand bg-brand-soft/30' : 'border-line bg-surface2')}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-txt">{citation.source_title}</p>
            {typeof citation.page === 'number' && <HueBadge hue="teal">p. {citation.page}</HueBadge>}
            {selected && <HueBadge hue="emerald">Selected</HueBadge>}
          </div>
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-txt">{citation.quote}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button type="button" onClick={onOpen} className="vo-btn-secondary text-xs">
            <Eye size={13} /> Open
          </button>
          <button type="button" onClick={() => onPin(note)} className="vo-btn-primary text-xs">
            <Pin size={13} /> Pin
          </button>
        </div>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]">
        <label className="text-xs">
          <span className="vo-label-micro mb-1">Optional note</span>
          <input className="vo-input py-1.5 text-sm" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why you're using this quote" />
        </label>
        <div className="text-xs text-faint">
          <p>Quote location: chars {citation.char_start} to {citation.char_end}</p>
          <p>Chunk {citation.chunk_index}</p>
        </div>
      </div>
    </li>
  )
}
