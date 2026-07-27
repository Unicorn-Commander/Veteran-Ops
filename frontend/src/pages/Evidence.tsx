import { ClipboardList, ClipboardX, ChevronDown, Eye, FileText, Pin } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { DocumentViewer } from '../components/DocumentViewer'
import { EmptyState, ErrorBlock, HueBadge, LoadingBlock, Panel, cx } from '../components/ui'
import { EVIDENCE_KIND_ICONS } from '../components/evidenceIcons'
import { useToast } from '../components/Toast'
import { useAsync } from '../hooks/useAsync'
import { conditionsApi, documentsApi, evidenceApi } from '../lib/api'
import { EVIDENCE_STATUS_HUES, hueFor } from '../lib/hues'
import { humanize } from '../lib/format'
import { errorMessage } from '../hooks/useAsync'
import type {
  ClaimedCondition,
  DocumentItem,
  EvidenceCitation,
  EvidenceItem,
  EvidenceKind,
  EvidenceStatus,
} from '../types'

interface Row extends EvidenceItem {
  conditionName: string
}

type ViewerFocus = {
  char_start: number
  char_end: number
  quote: string
  page?: number | null
  note?: string | null
}

async function loadAllEvidence(): Promise<Row[]> {
  const conditions = await conditionsApi.list().catch(() => [] as ClaimedCondition[])
  const lists = await Promise.all(
    conditions.map((c) => evidenceApi.list(c.id).catch(() => [] as EvidenceItem[]))
  )
  const rows: Row[] = []
  conditions.forEach((c, i) => {
    for (const item of lists[i]) rows.push({ ...item, conditionName: c.name })
  })
  return rows
}

const KINDS: EvidenceKind[] = [
  'diagnosis', 'service_record', 'nexus_letter', 'dbq', 'lay_statement', 'continuity', 'treatment_record', 'other',
]
const STATUSES: EvidenceStatus[] = ['have', 'need', 'requested', 'not_applicable']

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cx(
        'min-h-10 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors',
        active ? 'border-brand bg-brand-soft text-brand' : 'border-line bg-surface2 text-muted hover:text-txt'
      )}
    >
      {children}
    </button>
  )
}

export function Evidence() {
  const { data, loading, error, reload, setData } = useAsync(loadAllEvidence)
  const [kindFilter, setKindFilter] = useState<string>('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [viewerDoc, setViewerDoc] = useState<DocumentItem | null>(null)
  const [viewerFocus, setViewerFocus] = useState<ViewerFocus | null>(null)
  const { toast } = useToast()

  const filtered = useMemo(() => {
    if (!data) return []
    return data.filter((r) => (!kindFilter || r.kind === kindFilter) && (!statusFilter || r.status === statusFilter))
  }, [data, kindFilter, statusFilter])

  const grouped = useMemo(() => {
    const map = new Map<string, Row[]>()
    for (const row of filtered) {
      const list = map.get(row.conditionName) ?? []
      list.push(row)
      map.set(row.conditionName, list)
    }
    return map
  }, [filtered])

  const hasFilters = kindFilter !== '' || statusFilter !== ''

  const openCitation = async (citation: EvidenceCitation | null, documentId?: string | null) => {
    const targetId = citation?.document_id ?? documentId
    if (!targetId) return
    try {
      setViewerDoc(await documentsApi.get(targetId))
      setViewerFocus(
        citation
          ? {
              char_start: citation.char_start,
              char_end: citation.char_end,
              quote: citation.quote,
              page: citation.page,
              note: citation.note,
            }
          : null
      )
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div data-section="claim" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Claim tracking</p>
        <h1 className="vo-page-title">Evidence organizer</h1>
        <p className="vo-page-sub">Every piece of evidence across every condition, in one place.</p>
      </div>

      <div className="space-y-3">
        <div>
          <p className="vo-label-micro mb-1.5">Kind</p>
          <div className="flex flex-wrap gap-2">
            <FilterChip active={kindFilter === ''} onClick={() => setKindFilter('')}>
              All kinds
            </FilterChip>
            {KINDS.map((k) => (
              <FilterChip key={k} active={kindFilter === k} onClick={() => setKindFilter(k)}>
                {humanize(k)}
              </FilterChip>
            ))}
          </div>
        </div>
        <div>
          <p className="vo-label-micro mb-1.5">Status</p>
          <div className="flex flex-wrap gap-2">
            <FilterChip active={statusFilter === ''} onClick={() => setStatusFilter('')}>
              All statuses
            </FilterChip>
            {STATUSES.map((s) => (
              <FilterChip key={s} active={statusFilter === s} onClick={() => setStatusFilter(s)}>
                {humanize(s)}
              </FilterChip>
            ))}
          </div>
        </div>
      </div>

      {loading ? (
        <LoadingBlock label="Gathering evidence across conditions…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={reload} />
      ) : grouped.size === 0 ? (
        <EmptyState
          icon={hasFilters ? <ClipboardX size={20} /> : <ClipboardList size={20} />}
          title={hasFilters ? 'No evidence matches these filters' : 'No evidence found'}
          description={
            hasFilters
              ? 'Try clearing a filter above.'
              : 'Add conditions and evidence items to start organizing what you have.'
          }
          action={
            hasFilters ? (
              <button
                onClick={() => {
                  setKindFilter('')
                  setStatusFilter('')
                }}
                className="vo-btn-secondary text-sm"
              >
                Clear filters
              </button>
            ) : (
              <div className="flex flex-wrap justify-center gap-2">
                <Link to="/build-case" className="vo-btn-primary text-sm">
                  Populate case from records
                </Link>
                <Link to="/conditions" className="vo-btn-secondary text-sm">
                  Go to conditions
                </Link>
              </div>
            )
          }
        />
      ) : (
        <div className="space-y-5">
          {Array.from(grouped.entries()).map(([conditionName, rows]) => (
            <Panel key={conditionName} hue={hueFor(conditionName)} title={conditionName}>
              <div className="space-y-3 p-4">
                {rows.map((r) => (
                  <EvidenceCard
                    key={r.id}
                    item={r}
                    onOpenCitation={openCitation}
                    onUpdate={(updated) =>
                      setData((prev) => (prev ?? []).map((x) => (x.id === updated.id ? { ...updated, conditionName: x.conditionName } : x)))
                    }
                    onDelete={(id) => setData((prev) => (prev ?? []).filter((x) => x.id !== id))}
                  />
                ))}
              </div>

              <div className="border-t border-line px-5 py-3">
                <Link
                  to={`/conditions/${rows[0]?.condition_id}`}
                  className="text-xs font-semibold text-brand hover:text-brand-hover"
                >
                  Open condition →
                </Link>
              </div>
            </Panel>
          ))}
        </div>
      )}
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

function EvidenceCard({
  item,
  onOpenCitation,
  onUpdate,
  onDelete,
}: {
  item: Row
  onOpenCitation: (citation: EvidenceCitation | null, documentId?: string | null) => void
  onUpdate: (item: Row) => void
  onDelete: (id: string) => void
}) {
  const { toast } = useToast()
  const [expanded, setExpanded] = useState(false)
  const citations = item.citations ?? []
  const selectedCitation = citations.find((c) => c.selected) ?? citations[0] ?? null
  const rationale = item.rationale ?? null
  const Icon = EVIDENCE_KIND_ICONS[item.kind] ?? FileText

  const changeStatus = async (status: EvidenceStatus) => {
    try {
      const updated = await evidenceApi.update(item.id, { status })
      onUpdate({ ...updated, conditionName: item.conditionName })
    } catch (err) {
      toast(errorMessage(err), 'error')
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
      onUpdate({ ...updated, conditionName: item.conditionName })
      toast('Citation pinned.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  const remove = async () => {
    try {
      await evidenceApi.remove(item.id)
      onDelete(item.id)
      toast('Evidence removed.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div className="rounded-control border border-line bg-surface2">
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface text-muted">
            <Icon size={15} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-txt">{item.title}</p>
            <p className="text-xs text-faint">
              {humanize(item.kind)}
              {item.source ? ` · ${item.source}` : ''}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <select className="vo-input py-1.5 text-xs" value={item.status} onChange={(e) => void changeStatus(e.target.value as EvidenceStatus)}>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{humanize(s)}</option>
            ))}
          </select>
          <HueBadge hue={EVIDENCE_STATUS_HUES[item.status] ?? 'indigo'}>{humanize(item.status)}</HueBadge>
          {item.document_id && (
            <button
              type="button"
              onClick={() => onOpenCitation(selectedCitation, item.document_id)}
              className="vo-btn-secondary text-xs"
            >
              <Eye size={13} /> Source
            </button>
          )}
          <button type="button" onClick={() => setExpanded((v) => !v)} className="vo-btn-secondary text-xs">
            <ChevronDown size={13} className={cx('transition-transform', expanded && 'rotate-180')} />
            {expanded ? 'Hide' : 'Why this is evidence'}
          </button>
          <button type="button" onClick={() => void remove()} className="vo-icon-btn vo-btn-ghost text-muted hover:text-danger" aria-label="Remove evidence">
            <ClipboardX size={14} />
          </button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-line px-4 py-4">
          <div className="space-y-4">
            <div>
              <p className="vo-label-micro mb-1.5">Why this counts</p>
              {rationale ? (
                <div className="rounded-control border border-line bg-surface p-3">
                  <p className="text-sm font-medium text-txt">{rationale.elements.join(' · ') || 'General support'}</p>
                  <p className="mt-1 text-sm leading-relaxed text-txt">{rationale.why}</p>
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
                      onOpen={() => onOpenCitation(citation, item.document_id)}
                      onPin={(note) => void pinCitation(citation, note)}
                    />
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
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
    <li className={cx('rounded-control border p-3', selected ? 'border-brand bg-brand-soft/30' : 'border-line bg-surface')}>
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
