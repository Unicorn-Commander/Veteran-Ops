import { Check, FileText, PencilLine, RefreshCw, Sparkles, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from './ui'
import { useToast } from './Toast'
import { useAsync } from '../hooks/useAsync'
import { ApiError, profileApi } from '../lib/api'
import type {
  Dependent,
  DocType,
  IdentitySuggestions,
  IdentitySuggestionSource,
  MailingAddress,
  VeteranIdentity,
} from '../types'

const DISMISS_KEY = 'vo_identity_suggestion_dismissed'
const POLL_DELAY_MS = 12000
const MAX_POLL_ATTEMPTS = 8

const DOC_TYPE_LABELS: Record<DocType, string> = {
  rating_decision: 'rating decision',
  decision_letter: 'decision letter',
  str: 'service treatment record',
  dbq: 'DBQ',
  treatment_record: 'treatment record',
  private_medical_opinion: 'private medical opinion',
  lay_statement: 'lay statement',
  service_record: 'service record',
  other: 'document',
}

function sourceLabel(src: IdentitySuggestionSource | undefined): string {
  if (!src) return ''
  if (src.title) return src.title
  if (!src.document_id && !src.doc_type) return 'your account'
  return src.doc_type ? DOC_TYPE_LABELS[src.doc_type] : 'your records'
}

async function loadIdentitySuggestions(): Promise<IdentitySuggestions | null> {
  try {
    return await profileApi.identitySuggestions()
  } catch (error) {
    // An older backend may not ship this optional endpoint yet. Other failures
    // need a visible, retryable state so a connection problem is never mistaken
    // for "we found nothing."
    if (error instanceof ApiError && error.status === 404) return null
    throw error
  }
}

function emptyIdentity(): VeteranIdentity {
  return {
    full_name: '',
    date_of_birth: '',
    phone: '',
    email: '',
    address: {},
    va_file_number: '',
    place_of_birth: '',
  }
}

/** A caption line naming the document a proposed value came from — provenance
 * stays visible next to the field even once it's editable. */
function SourceNote({ source }: { source?: IdentitySuggestionSource }) {
  const from = sourceLabel(source)
  if (!from) return null
  return (
    <span className="mt-0.5 flex items-center gap-1 text-[11px] text-muted">
      <FileText size={11} className="shrink-0" aria-hidden="true" />
      from your {from}
    </span>
  )
}

/** One proposed value the veteran can EDIT before accepting — never all-or-
 * nothing. The value is pre-filled from what intake read, the provenance stays
 * visible, and nothing is committed until they choose "Use these". */
function EditableField({
  label,
  value,
  onChange,
  source,
  type = 'text',
  placeholder,
  inputMode,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  source?: IdentitySuggestionSource
  type?: string
  placeholder?: string
  inputMode?: 'text' | 'numeric' | 'tel'
}) {
  return (
    <label className="flex min-w-0 flex-col gap-1 rounded-control border border-line bg-surface2 p-3">
      <span className="vo-label">{label}</span>
      <input
        type={type}
        inputMode={inputMode}
        className="vo-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
      <SourceNote source={source} />
    </label>
  )
}

/**
 * "We found this in your records" — a dismissible panel that offers the identity
 * the intake pipeline read from the veteran's uploaded documents (GET
 * /profile/identity-suggestions), so they don't have to type name / DOB / address
 * by hand. "Use these" fills the profile form (the parent still saves); nothing is
 * committed here. An older backend's 404 becomes the warm scan state; other
 * failures stay visible and retryable. Social Security numbers are never included
 * in the suggestion payload.
 */
export function RecordsIdentitySuggestion({
  onUse,
}: {
  onUse: (suggestions: IdentitySuggestions) => void
}) {
  const { toast } = useToast()
  const { data, loading, error, reload } = useAsync(loadIdentitySuggestions, [])
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === '1'
    } catch {
      return false
    }
  })
  const [scanning, setScanning] = useState(false)
  const scanLockRef = useRef(false)
  const pollTimerRef = useRef<number | null>(null)
  const mountedRef = useRef(true)
  const pollRef = useRef<(attempt: number) => Promise<void>>(async () => {})

  // Editable working copy of the proposal — seeded from what intake read, but the
  // veteran can change any field before accepting (edit-before-accept; nothing is
  // "true" until they adopt it). Re-seeds whenever a fresh scan lands (new `data`).
  const [identity, setIdentity] = useState<VeteranIdentity>(emptyIdentity)
  const [deps, setDeps] = useState<Dependent[]>([])
  useEffect(() => {
    if (data?.has_suggestions) {
      setIdentity({ ...emptyIdentity(), ...data.identity, address: { ...(data.identity.address ?? {}) } })
      setDeps(data.dependents ?? [])
    }
  }, [data])

  const setField = <K extends keyof VeteranIdentity>(key: K, value: VeteranIdentity[K]) =>
    setIdentity((prev) => ({ ...prev, [key]: value }))
  const setAddr = <K extends keyof MailingAddress>(key: K, value: MailingAddress[K]) =>
    setIdentity((prev) => ({ ...prev, address: { ...prev.address, [key]: value } }))
  const removeDep = (idx: number) => setDeps((prev) => prev.filter((_, i) => i !== idx))

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      scanLockRef.current = false
      if (pollTimerRef.current !== null) window.clearTimeout(pollTimerRef.current)
    }
  }, [])

  const finishScan = (message?: string, tone: 'success' | 'error' | 'info' = 'success') => {
    scanLockRef.current = false
    if (!mountedRef.current) return
    setScanning(false)
    reload()
    if (message) toast(message, tone)
  }

  const schedulePoll = (attempt: number) => {
    if (!mountedRef.current) return
    pollTimerRef.current = window.setTimeout(() => {
      pollTimerRef.current = null
      void pollRef.current(attempt)
    }, POLL_DELAY_MS)
  }

  pollRef.current = async (attempt: number) => {
    if (!mountedRef.current || !scanLockRef.current) return
    try {
      const fresh = await profileApi.identitySuggestions()
      if (!mountedRef.current || !scanLockRef.current) return
      if (fresh.has_suggestions) {
        finishScan('Scan complete. Review the details before using them.')
        return
      }
      if (attempt < MAX_POLL_ATTEMPTS) {
        schedulePoll(attempt + 1)
        return
      }
      finishScan(
        "The scan finished, but it didn't find profile details to suggest. You can enter them manually or try another record.",
        'info',
      )
    } catch {
      if (attempt < MAX_POLL_ATTEMPTS) {
        schedulePoll(attempt + 1)
        return
      }
      finishScan("We couldn't check the scan results. Check your connection, then try the scan again.", 'error')
    }
  }

  // Kick a background re-scan of the veteran's uploaded records, then poll the
  // suggestions endpoint until it fills in (the sweep runs the local model per doc).
  const scan = async () => {
    if (scanLockRef.current) return
    scanLockRef.current = true
    setScanning(true)
    try {
      await profileApi.reextractIdentity()
      if (!mountedRef.current) return
      toast('Scanning your records. This may take a minute or two.', 'info')
      schedulePoll(1)
    } catch {
      scanLockRef.current = false
      if (!mountedRef.current) return
      setScanning(false)
      toast("We couldn't start the scan. Check your connection, then try again.", 'error')
    }
  }

  // Auto-start one scan when the panel loads empty (session-scoped) so veterans
  // don't have to discover the button — still never writes profile until Use these.
  useEffect(() => {
    if (dismissed || loading || data === undefined) return
    if (data && data.has_suggestions) return
    if (scanning || scanLockRef.current) return
    try {
      if (sessionStorage.getItem('vo_identity_auto_scan') === '1') return
      sessionStorage.setItem('vo_identity_auto_scan', '1')
    } catch {
      /* ignore */
    }
    void scan()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot on first empty load
  }, [dismissed, loading, data])

  if (dismissed) return null

  if (loading && !data) {
    return (
      <Panel hue="violet" title="Pull your info from your records">
        <LoadingBlock label="Checking your records for profile details…" />
      </Panel>
    )
  }

  if (error) {
    return (
      <Panel hue="violet" title="Pull your info from your records" bodyClassName="p-4">
        <ErrorBlock
          message={`We couldn't check your records for profile details. ${error} Check your connection, then try again.`}
          onRetry={reload}
        />
      </Panel>
    )
  }

  // No suggestions yet (e.g. records uploaded before this feature) → offer to scan.
  if (!data || !data.has_suggestions) {
    const checking = scanning || loading
    return (
      <Panel hue="violet" title="Pull your info from your records">
        <div className="p-4">
          <EmptyState
            hue="violet"
            icon={<FileText size={20} />}
            title="No profile details suggested yet"
            description={
              checking
                ? 'Rating Raider is checking your uploaded records. You can leave this page; the scan will continue.'
                : 'Scan uploaded VA letters, your DD-214, and other records for name, birth date, and address suggestions. Social Security numbers are not included in suggestions.'
            }
            action={
              <button onClick={scan} disabled={checking} aria-busy={checking} className="vo-btn-primary" type="button">
                {checking ? <Spinner size={15} /> : <Sparkles size={15} aria-hidden="true" />}
                {scanning ? 'Scanning your records…' : loading ? 'Checking scan results…' : 'Scan my records'}
              </button>
            }
          />
          <span className="sr-only" aria-live="polite">{checking ? 'Record scan in progress.' : ''}</span>
        </div>
      </Panel>
    )
  }

  const { sources } = data

  const cancelPendingScan = () => {
    scanLockRef.current = false
    if (pollTimerRef.current !== null) {
      window.clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
    setScanning(false)
  }

  const dismiss = () => {
    cancelPendingScan()
    try {
      localStorage.setItem(DISMISS_KEY, '1')
    } catch {
      /* storage unavailable — non-fatal, hide for this session */
    }
    setDismissed(true)
  }

  // Accept the veteran's EDITED copy (not the raw proposal) — they've reviewed and
  // adjusted each field, so this is what fills the profile form. The parent still
  // saves; nothing is committed here.
  const use = () => {
    onUse({ ...data, identity, dependents: deps })
    // Once applied there's nothing left to offer — clear it away like a dismiss.
    dismiss()
  }

  return (
    <Panel
      hue="violet"
      title="We found this in your records"
      subtitle="From documents and your account — edit anything, then use them"
      action={
        <button
          onClick={dismiss}
          className="vo-icon-btn vo-btn-ghost shrink-0"
          aria-label="Dismiss suggestions"
          type="button"
        >
          <X size={16} aria-hidden="true" />
        </button>
      }
    >
      <div className="space-y-4 p-5">
        {loading && (
          <p className="text-xs text-muted" role="status" aria-live="polite">
            Refreshing record suggestions…
          </p>
        )}
        <p className="flex items-start gap-2 text-xs leading-relaxed text-muted">
          <PencilLine size={14} className="mt-0.5 shrink-0 text-h-violet" aria-hidden="true" />
          <span>
            To save you typing, we pre-filled these from records you uploaded.{' '}
            <strong className="text-txt">Change anything that's wrong</strong> — nothing is filled into your profile
            until you choose <strong className="text-txt">Use these</strong>, and you still review and save. This
            suggestion tool does not extract or save Social Security numbers.
          </span>
        </p>

        <div className="grid gap-2 sm:grid-cols-2">
          <EditableField
            label="Full legal name"
            value={identity.full_name ?? ''}
            onChange={(v) => setField('full_name', v)}
            source={sources.full_name}
            placeholder="As it appears on your VA records"
          />
          <EditableField
            label="Date of birth"
            value={identity.date_of_birth ?? ''}
            onChange={(v) => setField('date_of_birth', v)}
            source={sources.date_of_birth}
            type="date"
          />
          <EditableField
            label="Phone"
            value={identity.phone ?? ''}
            onChange={(v) => setField('phone', v)}
            source={sources.phone}
            type="tel"
            inputMode="tel"
            placeholder="(555) 555-5555"
          />
          <EditableField
            label="Email"
            value={identity.email ?? ''}
            onChange={(v) => setField('email', v)}
            source={sources.email}
            type="email"
            placeholder="you@example.com"
          />
        </div>

        {/* Mailing address — one provenance source, but each part is separately
            editable so a mis-read line never forces rejecting the whole address. */}
        <div className="rounded-control border border-line bg-surface2 p-3">
          <span className="vo-label">Mailing address</span>
          <div className="mt-1.5 grid gap-2 sm:grid-cols-6">
            <input
              className="vo-input sm:col-span-6"
              value={identity.address.street ?? ''}
              onChange={(e) => setAddr('street', e.target.value)}
              placeholder="Street"
              aria-label="Street"
            />
            <input
              className="vo-input sm:col-span-3"
              value={identity.address.city ?? ''}
              onChange={(e) => setAddr('city', e.target.value)}
              placeholder="City"
              aria-label="City"
            />
            <input
              className="vo-input sm:col-span-1"
              value={identity.address.state ?? ''}
              onChange={(e) => setAddr('state', e.target.value.toUpperCase().slice(0, 2))}
              placeholder="ST"
              aria-label="State"
              maxLength={2}
            />
            <input
              className="vo-input sm:col-span-2"
              inputMode="numeric"
              value={identity.address.zip ?? ''}
              onChange={(e) => setAddr('zip', e.target.value)}
              placeholder="ZIP"
              aria-label="ZIP"
            />
          </div>
          <SourceNote source={sources.address} />
        </div>

        {deps.length > 0 && (
          <div className="rounded-control border border-line bg-surface2 p-3">
            <span className="vo-label">Dependents</span>
            <ul className="mt-1 space-y-1">
              {deps.map((dep, i) => (
                <li key={i} className="flex items-center justify-between gap-2 text-sm text-txt">
                  <span className="min-w-0 truncate">
                    <span className="font-medium">{dep.full_name || 'Unnamed dependent'}</span>
                    <span className="text-muted"> — {dep.relationship}</span>
                    {dep.date_of_birth && <span className="tabular-nums text-muted"> · {dep.date_of_birth}</span>}
                  </span>
                  <button
                    onClick={() => removeDep(i)}
                    className="vo-icon-btn vo-btn-ghost shrink-0 text-danger hover:bg-danger-soft"
                    aria-label={`Remove ${dep.full_name || 'dependent'}`}
                    type="button"
                  >
                    <Trash2 size={14} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
            <SourceNote source={sources.dependents} />
            <p className="mt-1.5 text-[11px] text-muted">
              Remove any that don't belong. You can add details and edit each one in your profile after you use these.
            </p>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3 pt-1">
          <button onClick={use} className="vo-btn-primary" type="button">
            <Check size={15} aria-hidden="true" /> Use these
          </button>
          <button onClick={dismiss} className="vo-btn-secondary text-sm" type="button">
            No thanks
          </button>
          <button onClick={scan} disabled={scanning || loading} aria-busy={scanning || loading} className="vo-btn-ghost text-sm" type="button">
            {scanning || loading ? <Spinner size={13} /> : <RefreshCw size={13} aria-hidden="true" />}
            {scanning ? 'Re-scanning…' : loading ? 'Refreshing…' : 'Re-scan records'}
          </button>
          <span className="sr-only" aria-live="polite">{scanning ? 'Record scan in progress.' : ''}</span>
          <span className="text-xs text-muted">Edit any field above, then Use these to fill your profile.</span>
        </div>
      </div>
    </Panel>
  )
}
