import {
  Loader2,
  RefreshCw,
  Save,
  ShieldAlert,
  XCircle,
} from 'lucide-react'
import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { adminServicesApi } from '../lib/api'
import type { ServiceOverrides } from '../types'

function FieldRow({
  label,
  hint,
  secret,
  configured,
  value,
  onChange,
}: {
  label: string
  hint?: string
  secret?: boolean
  configured?: boolean
  value: string | null | undefined
  onChange: (v: string | null) => void
}) {
  const secretPlaceholder = configured ? 'Configured — leave blank to keep' : 'Not set'
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-muted">
        {label}
        {hint && <span className="ml-1 font-normal text-faint">— {hint}</span>}
        {secret && configured && (
          <span className="ml-1 font-normal text-success">— configured</span>
        )}
      </label>
      <div className="flex items-center gap-2">
        <input
          type={secret ? 'password' : 'text'}
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value || null)}
          placeholder={secret ? secretPlaceholder : 'Use env default'}
          className="flex-1 rounded-control border border-line bg-surface2 px-3 py-2 text-sm text-txt placeholder-faint outline-none transition-[border,box-shadow] focus:border-brand/50 focus:ring-2 focus:ring-brand/20"
        />
        {value !== null && value !== undefined && (
          <button
            onClick={() => onChange(null)}
            className="vo-btn-ghost shrink-0 text-xs text-muted hover:text-txt"
          >
            Clear
          </button>
        )}
      </div>
    </div>
  )
}

function ToggleRow({
  label,
  hint,
  value,
  onChange,
}: {
  label: string
  hint?: string
  value: boolean | null | undefined
  onChange: (v: boolean | null) => void
}) {
  return (
    <div className="flex items-start justify-between gap-3 rounded-control border border-line bg-surface2 px-4 py-3">
      <div>
        <p className="text-sm font-medium text-txt">{label}</p>
        {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {value !== null && value !== undefined && (
          <button
            onClick={() => onChange(null)}
            className="vo-btn-ghost text-xs text-muted hover:text-txt"
          >
            Clear
          </button>
        )}
        <button
          onClick={() => onChange(value === true ? false : true)}
          className={`relative inline-flex h-6 w-10 shrink-0 cursor-pointer items-center rounded-full border transition-colors ${
            value ? 'border-brand/50 bg-brand/20' : 'border-line bg-surface2'
          }`}
          role="switch"
          aria-checked={!!value}
        >
          <span
            className={`inline-block h-4 w-4 transform rounded-full bg-white shadow-sm transition-transform ${
              value ? 'translate-x-[1.35rem]' : 'translate-x-[0.2rem]'
            }`}
          />
        </button>
      </div>
    </div>
  )
}

export function AdminServices() {
  const { user } = useAuth()
  if (!user?.platform_admin) {
    return (
      <div className="mx-auto max-w-3xl space-y-6 p-3 sm:p-6">
        <h1 className="text-lg font-bold text-txt">Service settings</h1>
        <Panel hue="amber" title="Instance operators only">
          <div className="flex items-start gap-3 p-5 text-sm text-muted">
            <ShieldAlert size={18} className="mt-0.5 shrink-0 text-warning" />
            <p>These settings affect every workspace and are available only to an allowlisted instance operator.</p>
          </div>
        </Panel>
      </div>
    )
  }
  return <AdminServicesForm />
}

function AdminServicesForm() {
  const { toast } = useToast()
  const { data, loading, error, reload } = useAsync(() => adminServicesApi.getSettings())
  const [draft, setDraft] = useState<Partial<ServiceOverrides> | null>(null)
  const [saving, setSaving] = useState(false)
  const [testResult, setTestResult] = useState<string | null>(null)

  const s = draft ?? data ?? {}

  function set(key: keyof ServiceOverrides, value: string | boolean | null) {
    setDraft((prev) => ({ ...(prev ?? data ?? {}), [key]: value }))
  }

  async function handleSave() {
    if (!draft) return
    setSaving(true)
    try {
      await adminServicesApi.updateSettings(draft)
      toast('Settings saved', 'success')
      setDraft(null)
      setTestResult(null)
      await reload()
    } catch (e) {
      toast(errorMessage(e), 'error')
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    if (!draft) return
    setTestResult(null)
    try {
      const res = await adminServicesApi.testConnection({ overrides: draft })
      setTestResult(res.ok ? res.message : `Failed: ${res.message}`)
      if (res.ok) toast(res.message, 'success')
      else toast(res.message, 'error')
    } catch (e) {
      const msg = errorMessage(e)
      setTestResult(msg)
      toast(msg, 'error')
    }
  }

  const hasDraft = draft !== null && Object.keys(draft).length > 0

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-3 sm:p-6">
      <div>
        <h1 className="text-lg font-bold text-txt">Service settings</h1>
        <p className="text-sm text-muted">
          Override environment-level service configuration at runtime.
          Changes apply without a restart. API keys are never returned by GET.
        </p>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Spinner size={20} />
        </div>
      )}
      {error && (
        <Panel hue="rose" title="Failed to load settings">
          <div className="flex items-center gap-2 p-5 text-sm text-danger">
            <XCircle size={16} />
            {errorMessage(error)}
          </div>
        </Panel>
      )}

      {!loading && !error && (
        <>
          {/* LLM Inference */}
          <Panel hue="violet" title="Inference (LLM)" subtitle="Chat completion model for the raider, strategy, and analysis">
            <div className="space-y-4 p-5">
              <FieldRow label="Base URL" hint="e.g. http://llm:8000/v1" value={s.llm_base_url} onChange={(v) => set('llm_base_url', v)} />
              <FieldRow label="API key" secret configured={data?.llm_api_key_set} value={s.llm_api_key} onChange={(v) => set('llm_api_key', v)} />
              <FieldRow label="Default model" hint="e.g. qwen3.6-35b-a3b" value={s.llm_model} onChange={(v) => set('llm_model', v)} />
              <FieldRow label="Reasoning model" hint="for PII-safe reasoning" value={s.reasoning_model} onChange={(v) => set('reasoning_model', v)} />
            </div>
          </Panel>

          {/* Embeddings */}
          <Panel hue="sky" title="Embeddings" subtitle="Vector embedding model for semantic search">
            <div className="space-y-4 p-5">
              <FieldRow label="Base URL" hint="e.g. http://embeddings:8000" value={s.embeddings_base_url} onChange={(v) => set('embeddings_base_url', v)} />
              <FieldRow label="API key" secret configured={data?.embeddings_api_key_set} value={s.embeddings_api_key} onChange={(v) => set('embeddings_api_key', v)} />
              <FieldRow label="Model" hint="e.g. bge-m3" value={s.embeddings_model} onChange={(v) => set('embeddings_model', v)} />
            </div>
          </Panel>

          {/* Reranker */}
          <Panel hue="emerald" title="Reranker" subtitle="Cross-encoder for reranking search results">
            <div className="space-y-4 p-5">
              <FieldRow label="Base URL" hint="e.g. http://reranker:8000" value={s.reranker_base_url} onChange={(v) => set('reranker_base_url', v)} />
              <FieldRow label="Model" hint="e.g. bge-reranker-v2-m3" value={s.reranker_model} onChange={(v) => set('reranker_model', v)} />
            </div>
          </Panel>

          {/* OCR */}
          <Panel hue="amber" title="OCR" subtitle="Document text extraction engine">
            <div className="space-y-4 p-5">
              <FieldRow label="Base URL" hint="e.g. http://ocr:8000" value={s.ocr_base_url} onChange={(v) => set('ocr_base_url', v)} />
              <FieldRow label="Model" value={s.ocr_model} onChange={(v) => set('ocr_model', v)} />
              <FieldRow label="Engine" hint="e.g. tesseract, markers" value={s.ocr_engine} onChange={(v) => set('ocr_engine', v)} />
            </div>
          </Panel>

          {/* Center Deep URLs */}
          <Panel hue="fuchsia" title="Center Deep URLs" subtitle="Research endpoint URLs for the deep-dive rating engine">
            <div className="space-y-4 p-5">
              <FieldRow label="Default" value={s.center_deep_url_default} onChange={(v) => set('center_deep_url_default', v)} />
              <FieldRow label="Unicorn Commander" value={s.center_deep_url_unicorncommander} onChange={(v) => set('center_deep_url_unicorncommander', v)} />
            </div>
          </Panel>

          {/* Privacy mode */}
          <Panel hue="rose" title="Privacy mode" subtitle="When ON, anything that touches a veteran's records stays on the local model you control — it never goes to a cloud model">
            <div className="p-5">
              <ToggleRow
                label="Privacy mode"
                hint="Forces PII-touching calls to the local model, even if a cloud reasoning model is configured"
                value={s.privacy_mode}
                onChange={(v) => set('privacy_mode', v)}
              />
            </div>
          </Panel>

          {/* Action bar */}
          {hasDraft && (
            <div className="sticky bottom-0 z-10 -mx-3 -mb-3 rounded-b-2xl border-t border-line bg-surface px-3 py-4 shadow-pop sm:-mx-6 sm:-mb-6 sm:px-6">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 text-sm text-muted">
                  <span className="h-2 w-2 rounded-full bg-warning" />
                  Unsaved changes
                  {testResult && (
                    <span className={`flex items-center gap-1 ${testResult.startsWith('Failed') ? 'text-danger' : 'text-success'}`}>
                      — {testResult}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={handleTest} className="vo-btn-ghost flex items-center gap-1.5 text-sm" disabled={saving}>
                    <RefreshCw size={14} />
                    Test
                  </button>
                  <button onClick={handleSave} className="vo-btn-primary flex items-center gap-1.5 text-sm" disabled={saving}>
                    {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                    Save
                  </button>
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
