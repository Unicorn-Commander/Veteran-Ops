import { AlertTriangle, ArrowRight, Download, Folder, Layers, Plus, X } from 'lucide-react'
import { useEffect, useState, type CSSProperties, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { KbFreshnessNote } from '../components/KbFreshnessNote'
import { Checkbox, EmptyState, ErrorBlock, HueBadge, LoadingBlock, Panel, Spinner } from '../components/ui'
import { StatusPipeline } from '../components/StatusPipeline'
import { useToast } from '../components/Toast'
import { useAsync, errorMessage } from '../hooks/useAsync'
import { conditionsApi, glitterApi } from '../lib/api'
import { CLAIM_TYPE_HUES, VA_STATUS_BADGES, VA_STATUS_HUES, hueStyle } from '../lib/hues'
import { humanize } from '../lib/format'
import type { ClaimedCondition, ClaimType, DuplicateCluster, GlitterCondition } from '../types'

const CLAIM_TYPES: ClaimType[] = ['direct', 'secondary', 'presumptive', 'increase']

export function Conditions() {
  const { toast } = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const { data, loading, error, reload, setData } = useAsync(() => conditionsApi.list())
  const { data: glitterStatus } = useAsync(() => glitterApi.status().catch(() => null))
  const {
    data: dupePayload,
    loading: dupeLoading,
    reload: reloadDupes,
    setData: setDupePayload,
  } = useAsync(() => conditionsApi.duplicates().catch(() => ({ clusters: [] as DuplicateCluster[], note: '' })))
  const [showForm, setShowForm] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [name, setName] = useState('')
  const [claimType, setClaimType] = useState<ClaimType>('direct')
  const [creating, setCreating] = useState(false)
  const [parkingKey, setParkingKey] = useState<string | null>(null)
  const [forceShowDupes, setForceShowDupes] = useState(false)

  // Deep link from suite import CTAs: /conditions?import=glitter opens the panel.
  useEffect(() => {
    if (searchParams.get('import') !== 'glitter') return
    setShowImport(true)
    const next = new URLSearchParams(searchParams)
    next.delete('import')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  // Deep link from Claim Plan coach: /conditions?dupes=1 focuses the cleanup panel.
  useEffect(() => {
    if (searchParams.get('dupes') !== '1') return
    setForceShowDupes(true)
    const next = new URLSearchParams(searchParams)
    next.delete('dupes')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  // Deep link from review-queue: /conditions?add=Name pre-fills the add form.
  useEffect(() => {
    const add = searchParams.get('add')
    if (!add?.trim()) return
    setName(add.trim())
    setShowForm(true)
    const next = new URLSearchParams(searchParams)
    next.delete('add')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  const clusters = dupePayload?.clusters ?? []
  const showDupesPanel = clusters.length > 0 || forceShowDupes

  const parkCluster = async (cluster: DuplicateCluster) => {
    const parkIds = cluster.park_ids ?? []
    if (parkIds.length === 0) {
      toast('No rows to park in this cluster.', 'info')
      return
    }
    setParkingKey(cluster.key)
    try {
      const res = await conditionsApi.parkDuplicates({
        park_ids: parkIds,
        keep_id: cluster.keep_id ?? undefined,
        keep_name: cluster.keep_name ?? undefined,
      })
      toast(
        res.parked > 0
          ? `Parked ${res.parked} duplicate${res.parked === 1 ? '' : 's'}. File cleanup only — not a VA action.`
          : 'Nothing was parked.',
        res.parked > 0 ? 'success' : 'info',
      )
      await reload()
      const next = await conditionsApi.duplicates().catch(() => ({ clusters: [] as DuplicateCluster[] }))
      setDupePayload(next)
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setParkingKey(null)
    }
  }

  const createCondition = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setCreating(true)
    try {
      const created = await conditionsApi.create({ name: name.trim(), claim_type: claimType, status: 'considering' })
      setData((prev) => [created, ...(prev ?? [])])
      setName('')
      setClaimType('direct')
      setShowForm(false)
      toast('Condition added.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div data-section="claim" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="vo-caption mb-1">Claim tracking</p>
          <h1 className="vo-page-title">Conditions</h1>
          <p className="vo-page-sub">Track each condition you're claiming and its evidence.</p>
        </div>
        <div className="flex gap-2">
          {glitterStatus?.enabled && glitterStatus.reachable && (
            <button type="button" onClick={() => setShowImport((s) => !s)} className="vo-btn-secondary">
              <Download size={15} /> Import from Glitter Mane
            </button>
          )}
          <button type="button" onClick={() => setShowForm((s) => !s)} className="vo-btn-primary">
            {showForm ? <X size={15} /> : <Plus size={15} />}
            {showForm ? 'Cancel' : 'Add condition'}
          </button>
        </div>
      </div>
      <KbFreshnessNote hue="emerald" />

      {showDupesPanel && (
        <DuplicatesPanel
          clusters={clusters}
          note={dupePayload?.note}
          loading={dupeLoading}
          parkingKey={parkingKey}
          onPark={(c) => void parkCluster(c)}
          onRefresh={() => void reloadDupes()}
        />
      )}

      {showImport && (
        <GlitterImportPanel
          onImported={(imported) => {
            setData((prev) => [...imported, ...(prev ?? [])])
            setShowImport(false)
            void reloadDupes()
          }}
          onClose={() => setShowImport(false)}
        />
      )}

      {showForm && (
        <form onSubmit={createCondition} className="vo-card flex flex-wrap items-end gap-3 p-5">
          <label className="min-w-[220px] flex-1 text-sm">
            <span className="vo-label">Condition name</span>
            <input
              autoFocus
              className="vo-input"
              placeholder="e.g. Tinnitus, Left knee strain"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </label>
          <label className="text-sm">
            <span className="vo-label">Claim type</span>
            <select className="vo-input" value={claimType} onChange={(e) => setClaimType(e.target.value as ClaimType)}>
              {CLAIM_TYPES.map((t) => (
                <option key={t} value={t}>{humanize(t)}</option>
              ))}
            </select>
          </label>
          <button type="submit" disabled={creating} className="vo-btn-primary">
            {creating ? <Spinner size={16} className="text-white" /> : <Plus size={15} />}
            Add
          </button>
        </form>
      )}

      {loading ? (
        <LoadingBlock label="Loading conditions…" />
      ) : error ? (
        <ErrorBlock message={error} onRetry={reload} />
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon={<Folder size={20} />}
          title="No conditions yet"
          description="Populate from your records, or add the first condition you're thinking about claiming."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Link to="/build-case" className="vo-btn-primary text-sm">
                Populate case from records
              </Link>
              <button type="button" onClick={() => setShowForm(true)} className="vo-btn-secondary text-sm">
                <Plus size={15} /> Add manually
              </button>
            </div>
          }
        />
      ) : (
        <div
          className="vo-panel vo-accent overflow-hidden"
          style={{ '--hue': 'var(--hue-emerald)', '--hue-soft': 'var(--hue-emerald-soft)' } as React.CSSProperties}
        >
          <div className="divide-y divide-line">
            {data.map((c) => (
              <ConditionRow key={c.id} condition={c} />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/** Similar-name clusters from C-file extract — park extras so Claim Plan stays readable. */
function DuplicatesPanel({
  clusters,
  note,
  loading,
  parkingKey,
  onPark,
  onRefresh,
}: {
  clusters: DuplicateCluster[]
  note?: string
  loading: boolean
  parkingKey: string | null
  onPark: (c: DuplicateCluster) => void
  onRefresh: () => void
}) {
  return (
    <Panel
      hue="amber"
      title={
        <span className="inline-flex items-center gap-2">
          <Layers size={16} aria-hidden />
          Possible duplicate conditions
        </span>
      }
      subtitle="Educational file cleanup — parking does not change VA status or file a claim."
      action={
        <button type="button" onClick={onRefresh} className="vo-btn-ghost text-xs" disabled={loading}>
          Refresh
        </button>
      }
    >
      <div className="space-y-3 px-5 py-4">
        {note && <p className="text-xs leading-relaxed text-muted">{note}</p>}
        {loading && clusters.length === 0 ? (
          <p className="text-sm text-muted">Checking for similar names…</p>
        ) : clusters.length === 0 ? (
          <p className="text-sm text-muted">No duplicate clusters right now.</p>
        ) : (
          clusters.map((c) => (
            <div
              key={c.key}
              className="rounded-control border border-line bg-surface/60 p-4"
              style={hueStyle('amber') as CSSProperties}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-txt">
                    {c.title || `Similar names · keep “${c.keep_name || 'primary'}”`}
                  </p>
                  {c.body && <p className="mt-1 text-xs leading-relaxed text-muted">{c.body}</p>}
                  <p className="mt-2 text-xs text-txt">
                    <span className="font-semibold">Keep:</span> {c.keep_name || '—'}
                    {(c.park_names?.length ?? 0) > 0 && (
                      <>
                        {' · '}
                        <span className="font-semibold">Park:</span> {c.park_names!.join(', ')}
                      </>
                    )}
                  </p>
                </div>
                <button
                  type="button"
                  className="vo-btn-primary shrink-0 text-sm"
                  disabled={parkingKey === c.key || (c.park_ids?.length ?? 0) === 0}
                  onClick={() => onPark(c)}
                >
                  {parkingKey === c.key ? <Spinner size={14} className="text-white" /> : null}
                  Park duplicates
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </Panel>
  )
}

/** WAVE2-SPEC §5 — /conditions gains an import flow when the Glitter Mane
 * bridge is configured+reachable: list GM conditions, multi-select, POST
 * /glitter/import-conditions. Fully optional; hidden entirely otherwise. */
function GlitterImportPanel({
  onImported,
  onClose,
}: {
  onImported: (imported: ClaimedCondition[]) => void
  onClose: () => void
}) {
  const { toast } = useToast()
  const { data, loading, error } = useAsync(() => glitterApi.conditions().catch(() => [] as GlitterCondition[]))
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [importing, setImporting] = useState(false)

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const runImport = async () => {
    if (selected.size === 0) return
    setImporting(true)
    try {
      const result = await glitterApi.importConditions(Array.from(selected))
      // The import endpoint returns lightweight {id, name} pairs, not full
      // ClaimedCondition rows — refetch each so the list renders correctly.
      const full = await Promise.all(result.conditions.map((c) => conditionsApi.get(c.id).catch(() => null)))
      onImported(full.filter((c): c is ClaimedCondition => c !== null))
      toast(`Imported ${result.imported} condition${result.imported === 1 ? '' : 's'} from Glitter Mane.`, 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div
      className="vo-card vo-accent space-y-3 p-5"
      style={{ '--hue': 'var(--hue-teal)', '--hue-soft': 'var(--hue-teal-soft)' } as React.CSSProperties}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-txt">Import from Glitter Mane</h2>
        <button type="button" onClick={onClose} className="vo-icon-btn vo-btn-ghost" aria-label="Close">
          <X size={15} />
        </button>
      </div>
      {loading ? (
        <p className="text-sm text-muted">Loading your Glitter Mane conditions…</p>
      ) : error ? (
        <p className="text-sm text-danger">{error}</p>
      ) : !data || data.length === 0 ? (
        <p className="text-sm text-muted">No conditions found in Glitter Mane.</p>
      ) : (
        <>
          <div className="space-y-1.5">
            {data.map((c) => (
              <Checkbox
                key={c.id}
                checked={selected.has(c.id)}
                onChange={() => toggle(c.id)}
                label={c.name}
                description={c.status ? humanize(c.status) : undefined}
              />
            ))}
          </div>
          <button type="button" onClick={() => void runImport()} disabled={selected.size === 0 || importing} className="vo-btn-primary text-sm">
            {importing ? <Spinner size={15} className="text-white" /> : <Download size={14} />}
            Import selected ({selected.size})
          </button>
        </>
      )}
    </div>
  )
}

function ConditionRow({ condition }: { condition: ClaimedCondition }) {
  const gapFlag = condition.status === 'gathering_evidence' || condition.status === 'considering'
  return (
    <Link
      to={`/conditions/${condition.id}`}
      className="flex flex-col gap-3 px-5 py-4 transition-colors hover:bg-surface2 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="truncate text-sm font-semibold text-txt">{condition.name}</h3>
          {condition.diagnostic_code && (
            <span className="text-xs text-faint">DC {condition.diagnostic_code}</span>
          )}
          {gapFlag && (
            <span className="inline-flex items-center gap-1 rounded-full border border-warn/25 bg-h-amber-soft px-2 py-0.5 text-micro font-medium text-warn">
              <AlertTriangle size={10} /> Gaps possible
            </span>
          )}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <HueBadge hue={CLAIM_TYPE_HUES[condition.claim_type] ?? 'violet'}>{humanize(condition.claim_type)}</HueBadge>
          {(condition.va_status === 'denied' || condition.va_status === 'service_connected') && (
            <HueBadge hue={VA_STATUS_HUES[condition.va_status]}>{VA_STATUS_BADGES[condition.va_status]}</HueBadge>
          )}
          {condition.body_system && <span className="text-xs text-muted">{condition.body_system}</span>}
        </div>
        <div className="mt-2">
          <StatusPipeline status={condition.status} compact />
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-4">
        <div className="text-right text-sm">
          <div className="font-semibold tabular-nums text-txt">
            {condition.current_rating ?? '—'}% → {condition.target_rating ?? '—'}%
          </div>
          <div className="text-xs text-faint">current → target</div>
        </div>
        <ArrowRight size={16} className="hidden shrink-0 text-faint sm:block" />
      </div>
    </Link>
  )
}
