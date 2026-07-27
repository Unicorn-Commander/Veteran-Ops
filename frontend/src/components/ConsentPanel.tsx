import { CheckCircle2, ScrollText, ShieldAlert, ShieldCheck } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Badge, Checkbox, ErrorBlock, LoadingBlock, Panel, Spinner } from './ui'
import { useToast } from './Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { formatDateTime, humanize } from '../lib/format'
import { casesApi, type ConsentMethod, type ConsentStatus } from '../lib/caseloadApi'

const METHOD_OPTIONS: { value: ConsentMethod; label: string }[] = [
  { value: 'in_person', label: 'In person' },
  { value: 'written', label: 'Written' },
  { value: 'verbal', label: 'Verbal' },
  { value: 'portal', label: 'Portal' },
]

/** The legal-lane callout — app-assist authorization vs VA-accredited
 * representation. Load-bearing: shown on every consent surface. */
function LegalLaneNote() {
  return (
    <div
      role="note"
      className="flex items-start gap-2.5 rounded-control border border-warn/40 bg-h-amber-soft px-4 py-3 text-sm leading-relaxed"
    >
      <ShieldAlert size={17} className="mt-0.5 shrink-0 text-warn" aria-hidden />
      <div className="space-y-1 text-txt">
        <p className="font-semibold">This is permission to help — not VA representation.</p>
        <p className="text-muted">
          This authorizes your organization to help the veteran organize and prepare their claim as educational
          self-help. The veteran still drives and files their own claim. It is <strong>not</strong> VA power of
          attorney. Formally representing a veteran before the VA requires the organization to be VA-accredited and
          appointed on <strong>VA Form 21-22</strong> (VSO) or <strong>21-22a</strong> (agent/attorney) through a
          VA-accredited VSO.
        </p>
      </div>
    </div>
  )
}

export function ConsentPanel({
  caseId,
  consentStatus,
  onChange,
}: {
  caseId: string
  /** The case's consent_status, so the panel reflects the parent immediately. */
  consentStatus: ConsentStatus
  /** Called after capture/revoke so the parent case can reload. */
  onChange: () => void
}) {
  const { toast } = useToast()
  const { data: consent, loading, error, reload } = useAsync(() => casesApi.getConsent(caseId), [caseId])

  const [method, setMethod] = useState<ConsentMethod>('in_person')
  const [grantedByName, setGrantedByName] = useState('')
  const [statement, setStatement] = useState('')
  const [acknowledged, setAcknowledged] = useState(false)
  const [saving, setSaving] = useState(false)
  const [confirmRevoke, setConfirmRevoke] = useState(false)
  const [revoking, setRevoking] = useState(false)

  const isGranted = consent?.status === 'granted' || consentStatus === 'granted'

  const capture = async (e: FormEvent) => {
    e.preventDefault()
    const name = grantedByName.trim()
    if (!name || !acknowledged || saving) return
    setSaving(true)
    try {
      await casesApi.captureConsent(caseId, {
        method,
        granted_by_name: name,
        statement: statement.trim() || undefined,
        acknowledged_not_poa: true,
      })
      toast('Consent recorded.', 'success')
      setGrantedByName('')
      setStatement('')
      setAcknowledged(false)
      reload()
      onChange()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  const revoke = async () => {
    setRevoking(true)
    try {
      await casesApi.revokeConsent(caseId)
      toast('Consent revoked.', 'success')
      setConfirmRevoke(false)
      reload()
      onChange()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setRevoking(false)
    }
  }

  const statusBadge = isGranted ? (
    <Badge tone="success">Consent on file</Badge>
  ) : consent?.status === 'revoked' || consentStatus === 'revoked' ? (
    <Badge tone="danger">Consent revoked</Badge>
  ) : (
    <Badge tone="warning">No consent yet</Badge>
  )

  return (
    <Panel hue="teal" title="Veteran consent" subtitle="Permission to assist" action={statusBadge}>
      <div className="space-y-4 p-5">
        <LegalLaneNote />

        {loading ? (
          <LoadingBlock label="Loading consent…" />
        ) : error ? (
          <ErrorBlock message={error} onRetry={reload} />
        ) : isGranted && consent ? (
          // ---- Granted view ----
          <div className="space-y-3">
            <div className="flex items-start gap-2.5 rounded-control border border-success/40 bg-h-emerald-soft px-4 py-3">
              <ShieldCheck size={17} className="mt-0.5 shrink-0 text-success" aria-hidden />
              <div className="min-w-0 text-sm">
                <p className="font-semibold text-txt">
                  Assist authorization on file — {humanize(consent.method)}
                </p>
                <p className="mt-0.5 text-muted">
                  Given by <strong>{consent.granted_by_name}</strong>
                  {consent.captured_by ? ` · captured by ${consent.captured_by}` : ''} ·{' '}
                  {formatDateTime(consent.granted_at)}
                </p>
                {consent.scope && <p className="mt-0.5 text-muted">Scope: {consent.scope}</p>}
              </div>
            </div>

            {consent.statement && (
              <figure className="rounded-control border border-line bg-surface2 px-4 py-3">
                <figcaption className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-faint">
                  <ScrollText size={13} /> Veteran's words (verbatim)
                </figcaption>
                <blockquote className="whitespace-pre-wrap text-sm leading-relaxed text-txt">
                  {consent.statement}
                </blockquote>
              </figure>
            )}

            <div className="flex items-center gap-2 pt-1">
              {confirmRevoke ? (
                <>
                  <span className="text-sm text-muted">Revoke this consent?</span>
                  <button onClick={() => void revoke()} disabled={revoking} className="vo-btn-danger text-sm">
                    {revoking ? <Spinner size={14} className="text-white" /> : <ShieldAlert size={14} />}
                    Confirm revoke
                  </button>
                  <button onClick={() => setConfirmRevoke(false)} className="vo-btn-ghost text-sm">
                    Cancel
                  </button>
                </>
              ) : (
                <button onClick={() => setConfirmRevoke(true)} className="vo-btn-secondary text-sm">
                  <ShieldAlert size={14} /> Revoke consent
                </button>
              )}
            </div>
          </div>
        ) : (
          // ---- Capture form ----
          <form onSubmit={capture} className="space-y-4">
            {consent?.status === 'revoked' && (
              <p className="text-sm text-muted">
                Consent was previously revoked. Capture new consent below to continue assisting.
              </p>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="block text-sm">
                <span className="vo-label">How was consent given?</span>
                <select
                  className="vo-input"
                  value={method}
                  onChange={(e) => setMethod(e.target.value as ConsentMethod)}
                >
                  {METHOD_OPTIONS.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block text-sm">
                <span className="vo-label">Veteran's name (who gave consent) *</span>
                <input
                  className="vo-input"
                  type="text"
                  value={grantedByName}
                  onChange={(e) => setGrantedByName(e.target.value)}
                  placeholder="e.g. Jordan Rivera"
                  maxLength={200}
                />
              </label>
            </div>

            <label className="block text-sm">
              <span className="vo-label">Veteran's authorization in their own words (optional)</span>
              <textarea
                className="vo-input min-h-[100px] resize-y leading-relaxed"
                value={statement}
                onChange={(e) => setStatement(e.target.value)}
                placeholder='e.g. "I give the office permission to help me gather my records and prepare my claim."'
              />
              <span className="mt-1 block text-xs text-faint">Stored verbatim — never rewritten.</span>
            </label>

            <Checkbox
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
              label={
                <>
                  I confirm I explained to the veteran that this authorizes Rating Raider to help organize their
                  claim, and is <strong>not</strong> VA-accredited representation (which requires VA Form 21-22).
                </>
              }
            />

            <button type="submit" disabled={!grantedByName.trim() || !acknowledged || saving} className="vo-btn-primary text-sm">
              {saving ? <Spinner size={15} className="text-white" /> : <CheckCircle2 size={15} />}
              Record consent
            </button>
          </form>
        )}
      </div>
    </Panel>
  )
}
