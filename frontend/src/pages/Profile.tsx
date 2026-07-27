import { Check, FileStack, Landmark, Lock, Plus, Save, ShieldCheck, Sparkles, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Checkbox, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { UserAvatar } from '../components/Avatar'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../components/Toast'
import { ExposuresEditor } from '../components/ExposuresEditor'
import { RecordsIdentitySuggestion } from '../components/RecordsIdentitySuggestion'
import { emptyServicePeriod, ServicePeriodsEditor } from '../components/ServicePeriodsEditor'
import { useAsync, errorMessage } from '../hooks/useAsync'
import { profileApi } from '../lib/api'
import { emptyProfile, normalizeProfile } from '../lib/profileDefaults'
import type {
  Dependent,
  DependentRelationship,
  IdentitySuggestions,
  MailingAddress,
  Profile as ProfileType,
  VeteranIdentity,
} from '../types'

const US_STATES = [
  'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD',
  'MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC',
  'SD','TN','TX','UT','VT','VA','WA','WV','WI','WY','DC','PR','VI','GU','AS',
]

const DEPENDENT_RELATIONSHIPS: { value: DependentRelationship; label: string }[] = [
  { value: 'spouse', label: 'Spouse' },
  { value: 'child', label: 'Child' },
  { value: 'stepchild', label: 'Stepchild' },
  { value: 'parent', label: 'Parent' },
]

function emptyAddress(): MailingAddress {
  return { street: '', unit: '', city: '', state: '', zip: '', country: 'USA' }
}

function emptyIdentity(): VeteranIdentity {
  return {
    full_name: '',
    date_of_birth: '',
    phone: '',
    email: '',
    address: emptyAddress(),
    va_file_number: '',
    place_of_birth: '',
  }
}

function emptyDependent(): Dependent {
  return {
    relationship: 'spouse',
    full_name: '',
    date_of_birth: '',
    marriage_date: '',
    marriage_location: '',
    in_school: false,
    seriously_disabled: false,
  }
}

export function Profile() {
  const { toast } = useToast()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  // Profile-first onboarding (F2): App routes a brand-new veteran here with
  // ?start=1 so their first guided step is a profile that's "already started for
  // them" — pre-filled from records, editable, and skippable.
  const welcome = params.get('start') === '1'
  const fromBuildCase = params.get('from') === 'build-case'
  const { data, loading, error, reload } = useAsync(() => profileApi.get().catch(() => emptyProfile()))
  const [form, setForm] = useState<ProfileType | null>(null)
  const [saving, setSaving] = useState(false)
  const [justSaved, setJustSaved] = useState(false)
  const [applyingRatings, setApplyingRatings] = useState(false)
  const [recordLocations, setRecordLocations] = useState<string[]>([])

  useEffect(() => {
    if (data) {
      // A fresh account's profile comes back with null fields — normalize
      // against the empty defaults so nothing downstream reads null.length.
      setForm(normalizeProfile(data))
    }
  }, [data])

  // Suggest deployment/exposure places found in uploaded records (non-destructive).
  useEffect(() => {
    let cancelled = false
    profileApi
      .locationSuggestions()
      .then((res) => {
        if (!cancelled) setRecordLocations(res.locations ?? [])
      })
      .catch(() => {
        if (!cancelled) setRecordLocations([])
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (loading || !form) {
    return (
      <div className="mx-auto w-full max-w-3xl p-6">
        <LoadingBlock label="Loading your profile…" />
      </div>
    )
  }
  if (error) {
    return (
      <div data-section="settings" className="vo-page mx-auto w-full max-w-3xl p-4 pb-16 sm:p-6">
        <ErrorBlock message={error} onRetry={reload} />
      </div>
    )
  }

  const setField = <K extends keyof ProfileType>(key: K, value: ProfileType[K]) =>
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev))

  const setExposure = <K extends keyof ProfileType['exposures']>(key: K, value: ProfileType['exposures'][K]) =>
    setForm((prev) => (prev ? { ...prev, exposures: { ...prev.exposures, [key]: value } } : prev))

  const addPeriod = () =>
    setForm((prev) => (prev ? { ...prev, service_periods: [...prev.service_periods, emptyServicePeriod()] } : prev))

  const updatePeriod = (idx: number, patch: Partial<ProfileType['service_periods'][number]>) =>
    setForm((prev) => {
      if (!prev) return prev
      const periods = prev.service_periods.map((p, i) => (i === idx ? { ...p, ...patch } : p))
      return { ...prev, service_periods: periods }
    })

  const removePeriod = (idx: number) =>
    setForm((prev) => (prev ? { ...prev, service_periods: prev.service_periods.filter((_, i) => i !== idx) } : prev))

  // Identity may be absent on an older/fresh profile — every setter builds on
  // an empty identity so the first keystroke materializes the whole object.
  const setIdentity = <K extends keyof VeteranIdentity>(key: K, value: VeteranIdentity[K]) =>
    setForm((prev) => (prev ? { ...prev, identity: { ...(prev.identity ?? emptyIdentity()), [key]: value } } : prev))

  const setAddress = <K extends keyof MailingAddress>(key: K, value: MailingAddress[K]) =>
    setForm((prev) => {
      if (!prev) return prev
      const id = prev.identity ?? emptyIdentity()
      return { ...prev, identity: { ...id, address: { ...id.address, [key]: value } } }
    })

  const addDependent = () =>
    setForm((prev) => (prev ? { ...prev, dependents: [...(prev.dependents ?? []), emptyDependent()] } : prev))

  const updateDependent = (idx: number, patch: Partial<Dependent>) =>
    setForm((prev) => {
      if (!prev) return prev
      const list = (prev.dependents ?? []).map((d, i) => (i === idx ? { ...d, ...patch } : d))
      return { ...prev, dependents: list }
    })

  const removeDependent = (idx: number) =>
    setForm((prev) => (prev ? { ...prev, dependents: (prev.dependents ?? []).filter((_, i) => i !== idx) } : prev))

  // "Use these" on the records-suggestion panel: fill the form with what intake read
  // from the veteran's documents. Only NON-EMPTY proposed values are applied (so a
  // missing field never clobbers something they already typed), existing dependents
  // are never overwritten, and the veteran still reviews + saves.
  const applySuggestions = (s: IdentitySuggestions) => {
    setForm((prev) => {
      if (!prev) return prev
      const base = prev.identity ?? emptyIdentity()
      const sa = s.identity.address ?? {}
      const nextIdentity: VeteranIdentity = {
        ...base,
        full_name: s.identity.full_name || base.full_name,
        date_of_birth: s.identity.date_of_birth || base.date_of_birth,
        phone: s.identity.phone || base.phone,
        email: s.identity.email || base.email,
        address: {
          ...base.address,
          street: sa.street || base.address.street,
          city: sa.city || base.address.city,
          state: sa.state || base.address.state,
          zip: sa.zip || base.address.zip,
        },
      }
      const haveDependents = (prev.dependents ?? []).length > 0
      return {
        ...prev,
        identity: nextIdentity,
        dependents: haveDependents ? prev.dependents : s.dependents,
      }
    })
    toast('Filled from your records — review and save.', 'success')
  }

  const save = async () => {
    if (!form) return
    setSaving(true)
    try {
      const body: ProfileType = {
        ...form,
        exposures: {
          ...form.exposures,
          locations: form.exposures.locations ?? [],
        },
      }
      const updated = await profileApi.update(body)
      setForm(normalizeProfile(updated))
      toast('Profile saved.', 'success')
      setJustSaved(true)
      window.setTimeout(() => setJustSaved(false), 2400)
      // Guided entry: don't dump them back into a loop of "complete profile"
      // — send them to the next real claim step.
      if (fromBuildCase) {
        navigate('/analysis', { replace: true })
      } else if (welcome) {
        navigate('/documents', { replace: true })
      }
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSaving(false)
    }
  }

  const identity = form.identity ?? emptyIdentity()
  const dependents = form.dependents ?? []

  return (
    <div data-section="settings" className="vo-page mx-auto w-full max-w-3xl space-y-5 p-4 pb-16 sm:p-6">
      {welcome && (
        <Panel hue="violet">
          <div className="space-y-3 p-5">
            <div className="flex items-start gap-3">
              <span
                aria-hidden
                className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-h-violet-soft text-h-violet"
              >
                <Sparkles size={18} />
              </span>
              <div className="min-w-0">
                <p className="vo-caption mb-0.5">First step</p>
                <h2 className="text-heading text-txt">Let's start with your profile</h2>
                <p className="mt-1 text-sm leading-relaxed text-muted">
                  We've started it for you — anything Rating Raider could read from records you've uploaded is
                  pre-filled below and fully editable. Review it, change what's off, and save. Nothing is filed
                  anywhere; it's your own working record, and you can finish this later.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2.5 border-t border-line pt-3">
              <p className="w-full text-xs text-muted">
                One path: save this page, then add records → populate case → run analysis. Ignore extra checklists
                on Home until those are done.
              </p>
              <button type="button" onClick={() => void save()} disabled={saving} className="vo-btn-primary text-sm">
                {saving ? <Spinner size={15} /> : <Save size={15} />}
                Save & continue to documents
              </button>
              <Link to="/build-case" className="vo-btn-secondary text-sm">
                <FileStack size={15} /> Populate case from records
              </Link>
              <Link to="/" className="vo-btn-ghost text-sm text-muted">
                Skip to dashboard
              </Link>
            </div>
          </div>
        </Panel>
      )}

      <div className="vo-section-band">
        <div className="flex items-start gap-4">
          <UserAvatar
            name={user?.full_name}
            email={user?.email}
            src={user?.avatar_url}
            size={56}
          />
          <div className="min-w-0">
            <p className="vo-caption mb-1">Preferences</p>
            <h1 className="vo-page-title">Your profile</h1>
            {(user?.full_name || user?.email) && (
              <p className="mt-1 truncate text-sm text-muted">{user?.full_name || user?.email}</p>
            )}
          </div>
        </div>
        <p className="vo-page-sub mt-3">
          Service history and exposures power your presumptive-condition screen and evidence checklists. Nothing
          here is filed anywhere — it's your working record.
        </p>
      </div>

      {/* "We found this in your records" — pre-fills identity from imported documents
          (renders nothing when there are no suggestions). */}
      <RecordsIdentitySuggestion onUse={applySuggestions} />

      <Panel hue="emerald" title="Ratings from your records" subtitle="Optional — apply decision percents you already uploaded">
        <div className="space-y-3 p-5">
          <p className="text-sm leading-relaxed text-muted">
            If a VA decision letter was processed, Rating Raider can set each condition’s current rating and
            an estimated combined rating on your profile. You review and can change anything after — nothing
            files with VA.
          </p>
          <button
            type="button"
            disabled={applyingRatings}
            className="vo-btn-primary text-sm"
            onClick={() => {
              void (async () => {
                setApplyingRatings(true)
                try {
                  const res = await profileApi.applyRatingsFromRecords()
                  toast(res.message, res.updated + res.created > 0 ? 'success' : 'info')
                  if (res.combined != null) {
                    setForm((prev) =>
                      prev ? { ...prev, current_combined_rating: res.combined } : prev,
                    )
                  }
                  await reload()
                } catch (err) {
                  toast(errorMessage(err), 'error')
                } finally {
                  setApplyingRatings(false)
                }
              })()
            }}
          >
            {applyingRatings ? <Spinner size={15} /> : <Check size={15} />}
            Apply ratings from decision records
          </button>
        </div>
      </Panel>

      {/* About you (authoritative identity for pre-filling draft VA forms) */}
      <Panel hue="violet" title="About you" subtitle="Used to pre-fill your official VA forms">
        <div className="space-y-4 p-5">
          <p className="flex items-start gap-2 text-xs leading-relaxed text-muted">
            <ShieldCheck size={14} className="mt-0.5 shrink-0 text-h-violet" />
            <span>
              This is used to pre-fill your official VA forms as a draft you review and sign. Rating Raider never
              files anything for you.
            </span>
          </p>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-sm sm:col-span-2">
              <span className="vo-label">Full legal name</span>
              <input
                className="vo-input"
                value={identity.full_name}
                onChange={(e) => setIdentity('full_name', e.target.value)}
                placeholder="As it appears on your VA records"
              />
            </label>
            <label className="text-sm">
              <span className="vo-label">Date of birth</span>
              <input
                type="date"
                className="vo-input"
                value={identity.date_of_birth}
                onChange={(e) => setIdentity('date_of_birth', e.target.value)}
              />
            </label>
            <label className="text-sm">
              <span className="vo-label">Place of birth</span>
              <input
                className="vo-input"
                value={identity.place_of_birth}
                onChange={(e) => setIdentity('place_of_birth', e.target.value)}
                placeholder="City, State"
              />
            </label>
            <label className="text-sm">
              <span className="vo-label">Phone</span>
              <input
                type="tel"
                className="vo-input"
                value={identity.phone}
                onChange={(e) => setIdentity('phone', e.target.value)}
                placeholder="(555) 555-5555"
              />
            </label>
            <label className="text-sm">
              <span className="vo-label">Email</span>
              <input
                type="email"
                className="vo-input"
                value={identity.email}
                onChange={(e) => setIdentity('email', e.target.value)}
                placeholder="you@example.com"
              />
            </label>
          </div>

          <div className="border-t border-line pt-4">
            <p className="vo-label mb-2">Mailing address</p>
            <div className="grid gap-3 sm:grid-cols-6">
              <label className="text-sm sm:col-span-4">
                <span className="vo-label">Street</span>
                <input
                  className="vo-input"
                  value={identity.address.street}
                  onChange={(e) => setAddress('street', e.target.value)}
                />
              </label>
              <label className="text-sm sm:col-span-2">
                <span className="vo-label">Unit / Apt</span>
                <input
                  className="vo-input"
                  value={identity.address.unit}
                  onChange={(e) => setAddress('unit', e.target.value)}
                  placeholder="Optional"
                />
              </label>
              <label className="text-sm sm:col-span-3">
                <span className="vo-label">City</span>
                <input
                  className="vo-input"
                  value={identity.address.city}
                  onChange={(e) => setAddress('city', e.target.value)}
                />
              </label>
              <label className="text-sm sm:col-span-1">
                <span className="vo-label">State</span>
                <select
                  className="vo-input"
                  value={identity.address.state}
                  onChange={(e) => setAddress('state', e.target.value)}
                >
                  <option value="">—</option>
                  {US_STATES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </label>
              <label className="text-sm sm:col-span-2">
                <span className="vo-label">ZIP</span>
                <input
                  className="vo-input"
                  inputMode="numeric"
                  value={identity.address.zip}
                  onChange={(e) => setAddress('zip', e.target.value)}
                  placeholder="12345"
                />
              </label>
            </div>
          </div>

          <p className="flex items-start gap-2 rounded-control border border-line bg-surface2 p-3 text-xs leading-relaxed text-muted">
            <Lock size={14} className="mt-0.5 shrink-0 text-h-violet" />
            <span>
              We never ask for or store your Social Security Number — you'll write that by hand on the form you
              sign.
            </span>
          </p>

          {/* VA file number — optional, sensitive, deliberately secondary */}
          <div className="border-t border-line pt-4">
            <label className="text-sm">
              <span className="vo-label">VA file number <span className="font-normal text-muted">(optional)</span></span>
              <input
                className="vo-input sm:max-w-xs"
                value={identity.va_file_number}
                onChange={(e) => setIdentity('va_file_number', e.target.value)}
                autoComplete="off"
                placeholder="Leave blank if unsure"
              />
            </label>
            <p className="mt-1.5 text-xs text-muted">
              Optional. Only used to pre-fill your own draft forms.
            </p>
          </div>
        </div>
      </Panel>

      {/* Dependents (VA Form 21-686c) */}
      <Panel
        hue="violet"
        title="Dependents"
        subtitle="Your household — feeds VA Form 21-686c"
        action={
          <button onClick={addDependent} className="vo-btn-secondary text-xs" type="button">
            <Plus size={14} /> Add dependent
          </button>
        }
      >
        <div className="space-y-3 p-5">
          {dependents.length === 0 && (
            <p className="text-sm text-muted">No dependents added.</p>
          )}
          {dependents.map((dep, idx) => {
            const isSpouse = dep.relationship === 'spouse'
            const isChild = dep.relationship === 'child' || dep.relationship === 'stepchild'
            return (
              <div key={idx} className="rounded-control border border-line bg-surface2 p-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className="text-sm">
                    <span className="vo-label">Relationship</span>
                    <select
                      className="vo-input"
                      value={dep.relationship}
                      onChange={(e) =>
                        updateDependent(idx, { relationship: e.target.value as DependentRelationship })
                      }
                    >
                      {DEPENDENT_RELATIONSHIPS.map((r) => (
                        <option key={r.value} value={r.value}>{r.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="text-sm">
                    <span className="vo-label">Full name</span>
                    <input
                      className="vo-input"
                      value={dep.full_name}
                      onChange={(e) => updateDependent(idx, { full_name: e.target.value })}
                    />
                  </label>
                  <label className="text-sm">
                    <span className="vo-label">Date of birth</span>
                    <input
                      type="date"
                      className="vo-input"
                      value={dep.date_of_birth}
                      onChange={(e) => updateDependent(idx, { date_of_birth: e.target.value })}
                    />
                  </label>
                  {isSpouse && (
                    <label className="text-sm">
                      <span className="vo-label">Date of marriage</span>
                      <input
                        type="date"
                        className="vo-input"
                        value={dep.marriage_date}
                        onChange={(e) => updateDependent(idx, { marriage_date: e.target.value })}
                      />
                    </label>
                  )}
                  {isSpouse && (
                    <label className="text-sm sm:col-span-2">
                      <span className="vo-label">Place of marriage</span>
                      <input
                        className="vo-input"
                        value={dep.marriage_location ?? ''}
                        onChange={(e) => updateDependent(idx, { marriage_location: e.target.value })}
                        placeholder="City, State"
                      />
                    </label>
                  )}
                </div>

                {isChild && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    <Checkbox
                      checked={dep.in_school ?? false}
                      onChange={(e) => updateDependent(idx, { in_school: e.target.checked })}
                      label="In school (age 18–23)"
                    />
                    <Checkbox
                      checked={dep.seriously_disabled ?? false}
                      onChange={(e) => updateDependent(idx, { seriously_disabled: e.target.checked })}
                      label="Permanently unable to support self"
                    />
                  </div>
                )}

                <div className="mt-3 flex justify-end">
                  <button
                    onClick={() => removeDependent(idx)}
                    className="vo-icon-btn vo-btn-ghost shrink-0 text-danger hover:bg-danger-soft"
                    aria-label="Remove dependent"
                    type="button"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </Panel>

      {/* Service periods */}
      <Panel hue="violet" title="Service periods" subtitle="Add each period of service">
        <div className="p-5">
          <ServicePeriodsEditor
            periods={form.service_periods}
            combatService={form.combat_service}
            onAdd={addPeriod}
            onUpdate={updatePeriod}
            onRemove={removePeriod}
            onCombatServiceChange={(v) => setField('combat_service', v)}
          />
        </div>
      </Panel>

      {/* Military retirement — powers concurrent pay (CRDP/CRSC) and corrections */}
      <Panel
        hue="violet"
        title="Military retirement"
        subtitle="Retiree status, medical retirement, and combat-related facts for concurrent pay"
      >
        <div className="space-y-4 p-5">
          <p className="text-xs leading-relaxed text-muted">
            Length-of-service retirees and <strong className="text-txt">medically retired</strong> (Chapter 61)
            veterans both draw military retired pay but different concurrent-pay rules may apply. Medically
            <em> separated</em> (not retired) is different — use that only if PEB/DoD separated you without
            retirement. Nothing here files with DFAS or VA.
          </p>

          <fieldset className="space-y-2">
            <legend className="vo-label">Retirement / separation path</legend>
            {(
              [
                { id: 'none', label: 'Not a military retiree (and not medically separated)' },
                { id: 'regular', label: 'Length-of-service / regular retiree' },
                { id: 'med_retired', label: 'Medically retired (Chapter 61 / medical retirement)' },
                { id: 'med_sep', label: 'Medically separated (not retired)' },
              ] as const
            ).map((opt) => {
              const selected =
                opt.id === 'none'
                  ? form.receives_military_retired_pay === false &&
                    form.medically_retired !== true &&
                    form.medically_separated !== true
                  : opt.id === 'regular'
                    ? form.receives_military_retired_pay === true && form.medically_retired !== true
                    : opt.id === 'med_retired'
                      ? form.medically_retired === true
                      : form.medically_separated === true && form.medically_retired !== true
              return (
                <label
                  key={opt.id}
                  className="flex cursor-pointer items-start gap-2.5 rounded-control border border-line bg-surface2 px-3 py-2.5 text-sm"
                >
                  <input
                    type="radio"
                    name="retirement_path"
                    className="mt-0.5"
                    checked={selected}
                    onChange={() => {
                      if (opt.id === 'none') {
                        setField('receives_military_retired_pay', false)
                        setField('medically_retired', false)
                        setField('medically_separated', false)
                      } else if (opt.id === 'regular') {
                        setField('receives_military_retired_pay', true)
                        setField('medically_retired', false)
                        setField('medically_separated', false)
                      } else if (opt.id === 'med_retired') {
                        setField('receives_military_retired_pay', true)
                        setField('medically_retired', true)
                        setField('medically_separated', false)
                      } else {
                        setField('receives_military_retired_pay', false)
                        setField('medically_retired', false)
                        setField('medically_separated', true)
                      }
                    }}
                  />
                  <span className="text-txt">{opt.label}</span>
                </label>
              )
            })}
            {form.receives_military_retired_pay == null &&
              form.medically_retired == null &&
              form.medically_separated == null && (
                <p className="text-xs text-faint">Not set yet — pick the option that fits so concurrent pay can screen correctly.</p>
              )}
          </fieldset>

          <div className="space-y-2 border-t border-line pt-3">
            <Checkbox
              checked={form.receives_military_retired_pay === true}
              onChange={() =>
                setField(
                  'receives_military_retired_pay',
                  form.receives_military_retired_pay === true ? false : true,
                )
              }
              label="I receive (or am entitled to) military retired pay"
              description="Used for CRDP / CRSC concurrent pay screening. Medically retired veterans usually check this."
            />
            <Checkbox
              checked={form.combat_related_disability === true}
              onChange={() =>
                setField(
                  'combat_related_disability',
                  form.combat_related_disability === true ? false : true,
                )
              }
              label="At least one disability is combat-related"
              description="Needed to screen CRSC (Combat-Related Special Compensation). Your branch decides combat-related under their rules."
            />
          </div>

          <div className="flex flex-wrap gap-2 pt-1">
            <Link to="/concurrent-pay" className="vo-btn-secondary min-h-9 text-xs">
              Concurrent pay (CRDP / CRSC)
            </Link>
            <Link to="/corrections" className="vo-btn-ghost min-h-9 text-xs">
              Records / rank corrections
            </Link>
          </div>
        </div>
      </Panel>

      {/* Exposures */}
      <Panel hue="violet" title="Exposures" subtitle="Used to screen for presumptive conditions">
        <div className="p-5">
          <ExposuresEditor
            exposures={form.exposures}
            locations={form.exposures.locations ?? []}
            onLocationsChange={(next) => setExposure('locations', next)}
            onExposureChange={setExposure}
            suggestedLocationsFromRecords={recordLocations}
            compact
          />
        </div>
      </Panel>

      {/* Rating + state */}
      <Panel hue="violet" title="Current status">
        <div className="grid gap-3 p-5 sm:grid-cols-2">
          <label className="text-sm">
            <span className="vo-label">Current combined rating (%)</span>
            <input
              type="number"
              min={0}
              max={100}
              step={10}
              className="vo-input"
              value={form.current_combined_rating ?? ''}
              onChange={(e) => setField('current_combined_rating', e.target.value === '' ? null : Number(e.target.value))}
            />
          </label>
          <label className="text-sm">
            <span className="vo-label">State of residence</span>
            <select
              className="vo-input"
              value={form.state ?? ''}
              onChange={(e) => setField('state', e.target.value || null)}
            >
              <option value="">—</option>
              {US_STATES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="text-sm sm:col-span-2">
            <span className="vo-label">Notes</span>
            <textarea
              className="vo-input min-h-[90px]"
              value={form.notes ?? ''}
              onChange={(e) => setField('notes', e.target.value || null)}
              placeholder="Anything you want to remember about your situation"
            />
          </label>
          <p className="flex items-start gap-2 text-xs text-muted sm:col-span-2">
            <Landmark size={14} className="mt-0.5 shrink-0 text-h-violet" />
            <span>
              Connected to VA.gov? You can{' '}
              <Link to="/va-sync" className="font-semibold text-brand hover:text-brand-hover">
                pull your official service periods and rating from VA
              </Link>{' '}
              and choose what to import — nothing changes until you confirm.
            </span>
          </p>
        </div>
      </Panel>

      <div className="flex items-center justify-between border-t border-line pt-5">
        <p className="text-xs text-muted">Nothing saves automatically — click Save profile when you're done.</p>
        <div className="flex items-center gap-3">
          {justSaved && (
            <span className="flex items-center gap-1.5 text-sm font-medium text-success">
              <Check size={15} /> Saved
            </span>
          )}
          <button onClick={() => void save()} disabled={saving} className="vo-btn-primary">
            {saving ? <Spinner size={16} className="text-white" /> : <Save size={15} />}
            Save profile
          </button>
        </div>
      </div>
    </div>
  )
}
