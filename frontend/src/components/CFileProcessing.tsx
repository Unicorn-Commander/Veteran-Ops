import { Cloud, Layers, Lock, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { useWorkspace } from '../context/WorkspaceContext'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { adminServicesApi } from '../lib/api'
import { Panel, Spinner } from './ui'
import { useToast } from './Toast'

/** The three C-file processing modes, composed from the two per-workspace backend
 * primitives (the privacy toggle + the PII→cloud consent gate):
 *   privacy → privacy_mode = true                     (records stay on local models)
 *   hybrid  → privacy_mode = false, consent = false   (frontier reasoning; record TEXT stays local)
 *   quality → privacy_mode = false, consent = true    (frontier may read your record text)
 */
type CFileMode = 'privacy' | 'hybrid' | 'quality'

const MODES: {
  id: CFileMode
  label: string
  icon: typeof Lock
  blurb: string
}[] = [
  {
    id: 'privacy',
    label: 'Privacy',
    icon: Lock,
    blurb: 'Everything about your records stays on the local models your operator controls. Nothing leaves the fleet.',
  },
  {
    id: 'hybrid',
    label: 'Hybrid',
    icon: Layers,
    blurb: 'Best-quality models help reason over public rating law (38 CFR) and plan your claim — but your record text still stays on the local model.',
  },
  {
    id: 'quality',
    label: 'Quality',
    icon: Cloud,
    blurb: 'Whole-file comprehension may send your record text to a trusted cloud model for the most thorough read. Requires your explicit consent below.',
  },
]

function modeFrom(privacyEffective: boolean, consented: boolean): CFileMode {
  if (privacyEffective) return 'privacy'
  return consented ? 'quality' : 'hybrid'
}

/** Per-workspace privacy + C-file reading-mode control (Phase 3). Combines the
 * simple "keep my data on local models" toggle (deliverable) with the finer
 * quality / privacy / hybrid selector, both bound to the documented endpoints
 * (PUT /admin/services/workspace-privacy and /pii-cloud-consent). Editable by the
 * workspace owner/admin — a veteran on their personal workspace flips their own. */
export function CFileProcessing() {
  const { toast } = useToast()
  const { current } = useWorkspace()
  const canEdit = current?.role === 'owner' || current?.role === 'admin'

  const {
    data: privacy,
    loading: pLoading,
    error: pError,
    reload: reloadPrivacy,
  } = useAsync(() => adminServicesApi.getWorkspacePrivacy())
  const { data: consent, loading: cLoading, reload: reloadConsent } = useAsync(() =>
    adminServicesApi.getPiiCloudConsent(),
  )
  const [saving, setSaving] = useState(false)

  const loading = pLoading || cLoading
  const privacyEffective = privacy?.effective ?? true
  const consented = consent?.consented ?? false
  const mode = modeFrom(privacyEffective, consented)

  async function applyMode(next: CFileMode) {
    if (!canEdit || saving || next === mode) return
    setSaving(true)
    try {
      if (next === 'privacy') {
        await adminServicesApi.setWorkspacePrivacy(true)
      } else {
        await adminServicesApi.setWorkspacePrivacy(false)
        await adminServicesApi.setPiiCloudConsent(next === 'quality')
      }
      toast('C-file processing mode saved', 'success')
      await Promise.all([reloadPrivacy(), reloadConsent()])
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Panel
      hue="emerald"
      title="How your C-file is read"
      subtitle="Keep your records on local models, or allow best-quality cloud reasoning — your choice, per workspace"
    >
      <div className="space-y-4 p-5">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Spinner size={20} />
          </div>
        ) : pError ? (
          <p className="text-sm text-danger">{errorMessage(pError)}</p>
        ) : (
          <>
            {/* Deliverable #1 — the plain "keep my data local" toggle. */}
            <div className="flex items-start justify-between gap-3 rounded-control border border-line bg-surface2 px-4 py-3.5">
              <div>
                <p className="text-sm font-medium text-txt">Keep my data on local models (privacy mode)</p>
                <p className="mt-0.5 text-xs text-muted">
                  When on, anything that touches your records stays on the local model — it never goes to a cloud model.
                </p>
              </div>
              <button
                type="button"
                onClick={() => applyMode(privacyEffective ? 'hybrid' : 'privacy')}
                disabled={!canEdit || saving}
                className={`relative inline-flex h-6 w-10 shrink-0 items-center rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                  privacyEffective ? 'border-brand/50 bg-brand/20' : 'border-line bg-surface2'
                }`}
                role="switch"
                aria-checked={privacyEffective}
                aria-label="Privacy mode"
              >
                <span
                  className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
                    privacyEffective ? 'translate-x-[1.35rem]' : 'translate-x-[0.2rem]'
                  }`}
                />
              </button>
            </div>

            {/* Deliverable #5 — the quality / privacy / hybrid selector. */}
            <div>
              <p className="vo-label-micro mb-2 px-0.5">C-file reading mode</p>
              <div className="grid grid-cols-3 gap-1 rounded-control border border-line bg-surface2 p-1">
                {MODES.map((m) => {
                  const Icon = m.icon
                  const active = mode === m.id
                  return (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => applyMode(m.id)}
                      disabled={!canEdit || saving}
                      aria-pressed={active}
                      className={`flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                        active ? 'bg-brand text-white' : 'text-muted hover:text-txt'
                      }`}
                    >
                      <Icon size={14} /> {m.label}
                    </button>
                  )
                })}
              </div>
              <p className="mt-2 px-0.5 text-xs leading-relaxed text-muted">{MODES.find((m) => m.id === mode)?.blurb}</p>
            </div>

            {/* The explicit PII→cloud consent record, surfaced when Quality is active. */}
            {mode === 'quality' && (
              <div className="flex items-start gap-2.5 rounded-control border border-warn/40 bg-h-amber-soft px-4 py-3 text-xs leading-relaxed text-txt/90">
                <ShieldAlert size={15} className="mt-0.5 shrink-0 text-warning" />
                <span>
                  You've consented to your record text being processed by a trusted cloud model for the highest-fidelity
                  whole-file read. This consent is recorded and audited, and every actual send is logged. Switch back to
                  Privacy or Hybrid any time to stop future sends.
                </span>
              </div>
            )}

            {!canEdit && (
              <p className="text-xs text-faint">
                An owner or admin of this workspace manages how the C-file is read.
              </p>
            )}
          </>
        )}
      </div>
    </Panel>
  )
}
