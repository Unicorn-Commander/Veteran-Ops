import { ArrowRight, CheckCircle2, FileStack, Sparkles, UserRound } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Checkbox, EmptyState, ErrorBlock, LoadingBlock, Spinner } from '../components/ui'
import { CreditLimitNotice } from '../components/CreditLimitNotice'
import { useToast } from '../components/Toast'
import { errorMessage } from '../hooks/useAsync'
import { ApiError, analysisApi, profileApi } from '../lib/api'
import {
  ensureCaseCandidates,
  getCaseCandidatesSnapshot,
  invalidateCaseCandidates,
  subscribeCaseCandidates,
} from '../lib/caseCandidatesStore'
import { isEmptyProfile, normalizeProfile } from '../lib/profileDefaults'
import { hueInk, hueStyle } from '../lib/hues'
import type { CaseCandidate, CaseCandidatesResult } from '../types'

/** /build-case — bridge from "records were read" to "here's my case".
 *
 * IMPORTANT: navigating here does NOT start GPU work. The veteran clicks
 * "Scan records" (fast deterministic grouping). Optional "Improve grouping"
 * uses the local LLM (credit). Cached results reuse for 15 minutes.
 */
export function BuildCase() {
  const { toast } = useToast()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const initial = getCaseCandidatesSnapshot()
  const [data, setData] = useState<CaseCandidatesResult | null>(initial.data)
  // Only show loading if a scan is already in flight (started by a prior click).
  const [loading, setLoading] = useState(initial.status === 'loading')
  const [error, setError] = useState<string | null>(initial.error)
  const [creditError, setCreditError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(initial.data?.candidates.filter((c) => !c.already_claimed).map((c) => c.name) ?? []),
  )
  const [building, setBuilding] = useState(false)
  const [startComprehensive, setStartComprehensive] = useState(true)
  const [profileEmpty, setProfileEmpty] = useState(false)
  const preferName = (searchParams.get('q') || '').trim()

  useEffect(() => {
    return subscribeCaseCandidates((snap) => {
      if (snap.status === 'loading') {
        setLoading(true)
        setError(null)
        return
      }
      if (snap.status === 'ready' && snap.data) {
        setData(snap.data)
        const open = snap.data.candidates.filter((c) => !c.already_claimed).map((c) => c.name)
        const next = new Set(open)
        if (preferName) {
          const match = open.find(
            (n) => n.toLowerCase() === preferName.toLowerCase() || n.toLowerCase().includes(preferName.toLowerCase()),
          )
          if (match) next.add(match)
        }
        setSelected(next)
        setLoading(false)
        setError(null)
        setCreditError(null)
        return
      }
      if (snap.status === 'error') {
        setLoading(false)
        setError((prev) => prev ?? snap.error)
      }
      if (snap.status === 'idle') {
        setLoading(false)
      }
    })
  }, [preferName])

  useEffect(() => {
    if (!preferName) return
    const next = new URLSearchParams(searchParams)
    if (!next.has('q')) return
    next.delete('q')
    setSearchParams(next, { replace: true })
  }, [preferName, searchParams, setSearchParams])

  /** Explicit scan only — never on route mount. enrich=false is free / no GPU. */
  const load = useCallback(
    async (opts: { force?: boolean; enrich?: boolean } = {}) => {
      setLoading(true)
      setError(null)
      setCreditError(null)
      try {
        const res = await ensureCaseCandidates({
          force: opts.force === true,
          enrich: opts.enrich === true,
        })
        setData(res)
        const open = res.candidates.filter((c) => !c.already_claimed).map((c) => c.name)
        const next = new Set(open)
        if (preferName) {
          const match = open.find(
            (n) => n.toLowerCase() === preferName.toLowerCase() || n.toLowerCase().includes(preferName.toLowerCase()),
          )
          if (match) next.add(match)
        }
        setSelected(next)
      } catch (e) {
        if (e instanceof ApiError && e.status === 402) {
          setCreditError(e.message)
          setData(null)
        } else {
          setError(errorMessage(e))
        }
      } finally {
        setLoading(false)
      }
    },
    [preferName],
  )

  // Hydrate from session cache only — do NOT start a new scan on mount.
  useEffect(() => {
    const snap = getCaseCandidatesSnapshot()
    if (snap.status === 'ready' && snap.data) {
      setData(snap.data)
      setSelected(new Set(snap.data.candidates.filter((c) => !c.already_claimed).map((c) => c.name)))
    }
  }, [])

  useEffect(() => {
    void profileApi
      .get()
      .then((p) => setProfileEmpty(isEmptyProfile(normalizeProfile(p))))
      .catch(() => setProfileEmpty(false))
  }, [])

  const toggle = (name: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })

  const selectable = useMemo(() => (data?.candidates ?? []).filter((c) => !c.already_claimed), [data])
  const chosen = useMemo(() => selectable.filter((c) => selected.has(c.name)), [selectable, selected])
  /** Everything the scanner found is already on the case — do not trap on "0 & continue". */
  const allAlreadyOnCase =
    !!data &&
    data.candidates.length > 0 &&
    selectable.length === 0 &&
    (data.existing_conditions > 0 || data.candidates.every((c) => c.already_claimed))

  const continueAlreadyPopulated = () => {
    if (profileEmpty) {
      navigate('/profile?start=1&from=build-case')
      return
    }
    if (startComprehensive) {
      navigate('/analysis')
      return
    }
    navigate('/strategy')
  }

  const build = async () => {
    if (chosen.length === 0) {
      // Defensive: empty selection with a populated case should never dead-end.
      if (allAlreadyOnCase || (data && data.existing_conditions > 0)) {
        continueAlreadyPopulated()
      }
      return
    }
    setBuilding(true)
    try {
      const res = await analysisApi.buildCase(
        chosen.map((c) => ({
          name: c.name,
          diagnostic_code: c.diagnostic_code,
          body_system: c.body_system,
          claim_type: c.claim_type,
          note: c.note,
          document_ids: c.document_ids,
        })),
        true,
        startComprehensive,
      )
      invalidateCaseCandidates()
      const analysisNote = res.comprehensive_started
        ? ' Full analysis started in the background.'
        : startComprehensive
          ? ' Full analysis could not start yet (add a readable record if needed).'
          : ''
      toast(
        `Added ${res.created.length} condition${res.created.length === 1 ? '' : 's'}` +
          (res.evidence_linked
            ? ` and linked ${res.evidence_linked} record${res.evidence_linked === 1 ? '' : 's'} as evidence`
            : '') +
          '.' +
          analysisNote,
        'success',
      )
      if (profileEmpty) {
        navigate('/profile?start=1&from=build-case')
      } else if (startComprehensive) {
        navigate(res.comprehensive_started ? '/analysis' : '/analysis?need=start')
      } else {
        navigate('/strategy')
      }
    } catch (e) {
      toast(errorMessage(e), 'error')
      setBuilding(false)
    }
  }

  const idle = !loading && !error && !creditError && !data

  return (
    <div className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6" data-section="build-case">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">From your records</p>
        <h1 className="vo-page-title">Populate your case from records</h1>
        <p className="vo-page-sub">
          Rating Raider suggests conditions your uploaded documents name. Confirm which to add — nothing is claimed
          until you say so. <strong className="font-semibold text-txt">Scanning only starts when you click the button</strong>{' '}
          (not when you open this page).
        </p>
        <p className="mt-2 text-xs leading-relaxed text-faint">
          Self-help software: you organize and prepare; you or a free VSO file. Rating Raider never e-files for you.
        </p>
      </div>

      <div
        className="vo-card vo-accent flex flex-wrap items-start gap-3 p-4"
        style={hueStyle('violet') as CSSProperties}
      >
        <span
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: 'var(--hue-violet-soft)', color: hueInk('violet') }}
        >
          <UserRound size={18} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-txt">
            {profileEmpty ? 'Also pull name & DOB for your profile' : 'Profile details from records'}
          </p>
          <p className="text-sm text-muted">
            Name, birth date, phone, and address suggestions live on Profile — scan and confirm there (not auto-saved).
            Email comes from your account when records do not include it.
          </p>
        </div>
        <Link to="/profile?start=1" className="vo-btn-secondary shrink-0 text-sm">
          Open profile suggestions
        </Link>
      </div>

      {loading ? (
        <div className="space-y-3">
          <LoadingBlock label="Reading conditions mentioned in your records…" />
          <p className="text-center text-xs text-muted" role="status">
            You can leave this page — a scan in progress continues in the background.
          </p>
        </div>
      ) : creditError ? (
        <CreditLimitNotice />
      ) : error ? (
        <ErrorBlock message={error} onRetry={() => void load({ force: true })} />
      ) : idle ? (
        <EmptyState
          hue="sky"
          icon={<FileStack size={20} />}
          title="Scan your records when you are ready"
          description="This finds condition names already in your processed documents (fast, no GPU). Optional AI grouping is a separate step after results appear."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <button type="button" onClick={() => void load({ force: true })} className="vo-btn-primary text-sm">
                <Sparkles size={15} /> Scan records for conditions
              </button>
              <Link to="/documents" className="vo-btn-secondary text-sm">
                Go to Documents
              </Link>
              <Link to="/conditions" className="vo-btn-ghost text-sm">
                Add manually
              </Link>
            </div>
          }
        />
      ) : !data || data.candidates.length === 0 ? (
        <EmptyState
          hue="sky"
          icon={<FileStack size={20} />}
          title="No conditions found in your records yet"
          description="Once documents finish processing, condition names they mention show up here. If everything is processed and this is empty, add conditions manually."
          action={
            <div className="flex flex-wrap gap-2">
              <Link to="/documents" className="vo-btn-primary text-sm">
                Go to Documents
              </Link>
              <Link to="/conditions" className="vo-btn-secondary text-sm">
                Add a condition manually
              </Link>
              <button type="button" onClick={() => void load({ force: true })} className="vo-btn-ghost text-sm">
                Scan again
              </button>
            </div>
          }
        />
      ) : (
        <>
          <div
            className="vo-card flex flex-wrap items-center gap-x-6 gap-y-2 p-4 text-sm"
            style={hueStyle('sky') as CSSProperties}
          >
            <span className="flex items-baseline gap-1.5">
              <span className="text-base font-bold tabular-nums" style={{ color: hueInk('sky') }}>
                {data.documents_scanned}
              </span>
              <span className="text-muted">records read</span>
            </span>
            <span className="flex items-baseline gap-1.5">
              <span className="text-base font-bold tabular-nums" style={{ color: hueInk('sky') }}>
                {data.candidates.length}
              </span>
              <span className="text-muted">suggested conditions</span>
            </span>
            {data.existing_conditions > 0 && (
              <span className="flex items-baseline gap-1.5">
                <span className="text-base font-bold tabular-nums" style={{ color: hueInk('emerald') }}>
                  {data.existing_conditions}
                </span>
                <span className="text-muted">already on your list</span>
              </span>
            )}
            <div className="ml-auto flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void load({ force: true, enrich: false })}
                className="text-xs font-semibold text-brand hover:underline"
              >
                Rescan (fast)
              </button>
              <button
                type="button"
                onClick={() => void load({ force: true, enrich: true })}
                className="text-xs font-semibold text-muted hover:underline"
                title="Optional — uses local AI and a credit to merge synonym spellings"
              >
                Improve grouping (AI)
              </button>
            </div>
          </div>

          {allAlreadyOnCase ? (
            <div
              className="vo-card vo-accent space-y-3 p-4"
              style={hueStyle('emerald') as CSSProperties}
              role="status"
            >
              <p className="text-sm font-semibold text-txt">Your case is already populated</p>
              <p className="text-xs leading-relaxed text-muted">
                Every condition found in your records is already on your list
                {data.existing_conditions > 0 ? ` (${data.existing_conditions} on file)` : ''}. Nothing new to
                check — continue to analysis or your claim plan. You can still add conditions manually later.
              </p>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={continueAlreadyPopulated} className="vo-btn-primary min-h-11 text-sm">
                  Continue to {profileEmpty ? 'profile' : startComprehensive ? 'analysis' : 'claim plan'}
                  <ArrowRight size={15} />
                </button>
                <Link to="/conditions" className="vo-btn-secondary min-h-11 text-sm">
                  Open conditions list
                </Link>
                <Link to="/strategy" className="vo-btn-ghost min-h-11 text-sm">
                  Claim plan
                </Link>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted">
              Check the ones that match your situation. Uncheck anything wrong. Suggestions come from your
              documents — they are not diagnoses or a prediction of what VA will grant.
            </p>
          )}

          <div className="space-y-2">
            {data.candidates.map((c) => (
              <CandidateRow
                key={c.name}
                candidate={c}
                checked={selected.has(c.name)}
                onToggle={() => toggle(c.name)}
              />
            ))}
          </div>

          <div className="vo-sticky-mobile-footer sticky z-10 space-y-2 rounded-control border border-line bg-surface/95 p-3 shadow-lg backdrop-blur">
            {!allAlreadyOnCase && (
              <Checkbox
                checked={startComprehensive}
                onChange={() => setStartComprehensive((v) => !v)}
                label="Run full analysis after I confirm conditions"
                description="Starts the whole-file analysis in the background once your case is populated (you can keep working)."
              />
            )}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-sm text-muted">
                {allAlreadyOnCase
                  ? `${data.candidates.length} already on your list — nothing new to add`
                  : `${chosen.length} of ${selectable.length} selected to add`}
              </span>
              {allAlreadyOnCase ? (
                <button
                  type="button"
                  onClick={continueAlreadyPopulated}
                  className="vo-btn-primary shrink-0 min-h-11"
                >
                  Continue to {profileEmpty ? 'profile' : startComprehensive ? 'analysis' : 'claim plan'}
                  <ArrowRight size={15} />
                </button>
              ) : (
                <button
                  type="button"
                  onClick={() => void build()}
                  disabled={building || chosen.length === 0}
                  className="vo-btn-primary shrink-0 min-h-11"
                >
                  {building ? <Spinner size={15} /> : <Sparkles size={15} />}
                  Confirm {chosen.length} & continue
                  <ArrowRight size={15} />
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function CandidateRow({
  candidate: c,
  checked,
  onToggle,
}: {
  candidate: CaseCandidate
  checked: boolean
  onToggle: () => void
}) {
  const claimTypeLabel =
    c.claim_type === 'secondary' ? 'may be secondary' : c.claim_type === 'presumptive' ? 'may be presumptive' : null
  if (c.already_claimed) {
    return (
      <div className="flex items-center gap-3 rounded-control border border-line bg-surface2/50 px-4 py-3 opacity-70">
        <CheckCircle2 size={16} className="shrink-0 text-success" />
        <span className="text-sm font-medium text-txt">{c.name}</span>
        <span className="text-micro text-faint">already on your list</span>
      </div>
    )
  }
  return (
    <Checkbox
      checked={checked}
      onChange={onToggle}
      label={
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-txt">{c.name}</span>
          {c.diagnostic_code && <span className="text-micro text-faint">DC {c.diagnostic_code}</span>}
          {claimTypeLabel && (
            <span className="vo-chip-hue" style={hueStyle('violet') as CSSProperties}>
              {claimTypeLabel}
            </span>
          )}
          <span className="text-micro text-muted">
            {c.mention_count} mention{c.mention_count === 1 ? '' : 's'} · {c.document_ids.length} record
            {c.document_ids.length === 1 ? '' : 's'}
          </span>
        </span>
      }
      description={
        <>
          {c.note && <span className="block">{c.note}</span>}
          {c.aliases?.length > 1 && (
            <span className="block text-faint">Also as: {c.aliases.slice(0, 4).join(', ')}</span>
          )}
        </>
      }
    />
  )
}
