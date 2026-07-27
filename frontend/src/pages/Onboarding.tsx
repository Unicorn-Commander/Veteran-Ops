import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ClipboardCheck,
  Compass,
  ExternalLink,
  FileStack,
  Landmark,
  LifeBuoy,
  PartyPopper,
  Plus,
  ShieldCheck,
  Sparkles,
  Trash2,
  UploadCloud,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Checkbox, Panel, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { ExposuresEditor } from '../components/ExposuresEditor'
import { emptyServicePeriod, ServicePeriodsEditor } from '../components/ServicePeriodsEditor'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { checklistApi, conditionsApi, profileApi } from '../lib/api'
import { emptyProfile, normalizeProfile } from '../lib/profileDefaults'
import { DISCLAIMER_TEXT } from '../components/Disclaimer'
import { HUES, hueSoftVar, hueVar, type Hue } from '../lib/hues'
import type { Exposures, ServicePeriod } from '../types'

// Onboarding wizard — WAVE2-SPEC §1. Shares its service-period and exposures
// editors with Profile.tsx (see components/ServicePeriodsEditor.tsx and
// components/ExposuresEditor.tsx) rather than duplicating them. Every step
// writes only through the existing /profile, /conditions, /checklist APIs —
// no bespoke onboarding endpoint exists or is needed.

const STEPS = [
  { key: 'welcome', label: 'Welcome' },
  { key: 'situation', label: 'Where you are' },
  { key: 'service', label: 'Service history' },
  { key: 'exposures', label: 'Exposures' },
  { key: 'ratings', label: 'Current ratings' },
  { key: 'considering', label: 'Considering' },
  { key: 'bring_records', label: 'Bring your records' },
  { key: 'records', label: 'Records check' },
  { key: 'finish', label: 'Finish' },
] as const

interface QuickRating {
  name: string
  percent: number
}

interface QuickCondition {
  name: string
  body_system: string
}

interface RecordsHave {
  dd214: boolean
  strs: boolean
  cfile: boolean
  va_medical: boolean
  private_records: boolean
}

// Situation step (routing only, not persisted) — answers to the three intake
// questions and the tier they resolve to.
type VaAccountAnswer = 'yes' | 'no' | 'unsure'
type VaRatedAnswer = 'rated' | 'filed' | 'starting'
type VaRecordsAnswer = 'yes' | 'some' | 'no'
type SituationTier = 'A' | 'B' | 'C' | 'D'

const RECORD_TYPES: { key: keyof RecordsHave; label: string; blurb: string; missingText: string }[] = [
  {
    key: 'dd214',
    label: 'DD-214 (discharge paperwork)',
    blurb: 'Your certificate of release/discharge — needed for almost every claim.',
    missingText: 'Request your DD-214 / OMPF — see the Records page for the milConnect and SF-180 paths.',
  },
  {
    key: 'strs',
    label: 'Service treatment records (STRs)',
    blurb: 'In-service medical records showing treatment, diagnoses, and complaints.',
    missingText: 'Request your service treatment records (STRs) — included with your C-file/OMPF request on the Records page.',
  },
  {
    key: 'cfile',
    label: 'VA claims file (C-file)',
    blurb: "VA's complete record of everything filed and decided on your claims.",
    missingText: 'Request your VA claims file (C-file) with VA Form 20-10206 — see the Records page.',
  },
  {
    key: 'va_medical',
    label: 'VA medical records',
    blurb: 'Your treatment history at VA facilities.',
    missingText: 'Download your VA medical records via VA.gov Blue Button — see the Records page for guided steps.',
  },
  {
    key: 'private_records',
    label: 'Private / civilian medical records',
    blurb: 'Records from non-VA doctors, hospitals, or clinics who treated you.',
    missingText: 'Request records from your private providers — the Records page generates a signable request letter.',
  },
]

const PERCENTS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

export function Onboarding() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const [step, setStep] = useState(0)
  const [submitting, setSubmitting] = useState(false)

  // Preload any existing profile (this wizard is also reachable from Settings
  // as "restart guided setup" on an account that already has data — never
  // blindly overwrite it with blank wizard state).
  const { data: existingProfile } = useAsync(() => profileApi.get().catch(() => emptyProfile()))
  const [preloaded, setPreloaded] = useState(false)
  const [existingRating, setExistingRating] = useState<number | null>(null)
  const [existingState, setExistingState] = useState<string | null>(null)
  const [existingNotes, setExistingNotes] = useState<string | null>(null)

  // Step 2: service history
  const base = emptyProfile()
  const [periods, setPeriods] = useState<ServicePeriod[]>([])
  const [combatService, setCombatService] = useState(false)

  // Step 3: exposures
  const [exposures, setExposures] = useState<Exposures>(base.exposures)
  const [locationsText, setLocationsText] = useState('')

  useEffect(() => {
    if (existingProfile && !preloaded) {
      const norm = normalizeProfile(existingProfile)
      setPeriods(norm.service_periods)
      setCombatService(norm.combat_service)
      setExposures(norm.exposures)
      setLocationsText(norm.exposures.locations.join(', '))
      setExistingRating(norm.current_combined_rating)
      setExistingState(norm.state)
      setExistingNotes(norm.notes)
      setPreloaded(true)
    }
  }, [existingProfile, preloaded])

  // Step 4: current ratings
  const [alreadyRated, setAlreadyRated] = useState<boolean | null>(null)
  const [quickRatings, setQuickRatings] = useState<QuickRating[]>([])

  // Step 5: considering claiming
  const [quickConditions, setQuickConditions] = useState<QuickCondition[]>([])

  // Step 6: records check
  const [recordsHave, setRecordsHave] = useState<RecordsHave>({
    dd214: false,
    strs: false,
    cfile: false,
    va_medical: false,
    private_records: false,
  })

  // Step 2 (situation): pure guidance/routing — these answers gate nothing and
  // aren't persisted to the backend; they only tailor the "Your path" panel so
  // we meet the veteran where they are. Kept in wizard state so they survive
  // back/next navigation within onboarding.
  const [vaAccount, setVaAccount] = useState<VaAccountAnswer | null>(null)
  const [vaRated, setVaRated] = useState<VaRatedAnswer | null>(null)
  const [vaRecords, setVaRecords] = useState<VaRecordsAnswer | null>(null)

  const goNext = () => setStep((s) => Math.min(s + 1, STEPS.length - 1))
  const goBack = () => setStep((s) => Math.max(s - 1, 0))

  const finish = async () => {
    setSubmitting(true)
    try {
      await profileApi.update({
        service_periods: periods,
        combat_service: combatService,
        exposures: {
          ...exposures,
          locations: locationsText.split(',').map((s) => s.trim()).filter(Boolean),
        },
        // Not edited in this wizard — carry over whatever was already there
        // rather than wiping it (this wizard is also used to redo setup).
        current_combined_rating: existingRating,
        state: existingState,
        notes: existingNotes,
      })

      let anyCondition = false
      for (const r of quickRatings) {
        if (!r.name.trim()) continue
        await conditionsApi.create({
          name: r.name.trim(),
          claim_type: 'increase',
          status: 'considering',
          current_rating: r.percent,
        })
        anyCondition = true
      }
      for (const c of quickConditions) {
        if (!c.name.trim()) continue
        await conditionsApi.create({
          name: c.name.trim(),
          body_system: c.body_system.trim() || null,
          claim_type: 'direct',
          status: 'considering',
        })
        anyCondition = true
      }

      for (const rt of RECORD_TYPES) {
        if (!recordsHave[rt.key]) {
          await checklistApi.create({ text: rt.missingText, category: 'records' })
        }
      }

      if (anyCondition) {
        const existing = await checklistApi.list().catch(() => [])
        if (!existing.some((i) => i.category === 'itf')) {
          await checklistApi.create({
            text: 'Consider filing a VA Intent to File (VA Form 21-0966) — it can lock in an earlier effective date while you gather evidence.',
            category: 'itf',
          })
        }
      }

      // Seed the journey override from the "where you are" answers so Home /
      // Journey land on a sensible stage instead of ignoring the wizard.
      try {
        const stage =
          vaRated === 'rated' || alreadyRated === true
            ? 'rated'
            : vaRated === 'filed'
              ? 'filed_waiting'
              : vaRated === 'starting'
                ? 'never_filed'
                : null
        if (stage) localStorage.setItem('vo_journey_stage', stage)
      } catch {
        /* storage may be blocked — journey auto-detect still works */
      }

      toast('Your claim is set up.', 'success')
      navigate('/', { replace: true })
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="vo-page mx-auto w-full max-w-3xl space-y-6 p-4 pb-16 sm:p-6" data-section="settings">
      <div className="vo-page-head vo-section-band">
        <h1 className="vo-page-title">Set up your claim</h1>
        <p className="vo-page-sub">About 5 minutes. You can change anything later in Profile or Conditions.</p>
      </div>

      <ProgressBar step={step} />

      {/* Key by step so each screen slides in fresh — one question at a time. */}
      <div key={step} className="vo-step-enter">
        {step === 0 && <WelcomeStep />}
        {step === 1 && (
          <SituationStep
            account={vaAccount}
            setAccount={setVaAccount}
            rated={vaRated}
            setRated={setVaRated}
            records={vaRecords}
            setRecords={setVaRecords}
            onSkip={goNext}
          />
        )}
        {step === 2 && (
          <Panel hue="teal" title="Service history" subtitle="Add each period of service">
            <div className="p-5">
              <ServicePeriodsEditor
                periods={periods}
                combatService={combatService}
                onAdd={() => setPeriods((p) => [...p, emptyServicePeriod()])}
                onUpdate={(idx, patch) => setPeriods((p) => p.map((x, i) => (i === idx ? { ...x, ...patch } : x)))}
                onRemove={(idx) => setPeriods((p) => p.filter((_, i) => i !== idx))}
                onCombatServiceChange={setCombatService}
              />
            </div>
          </Panel>
        )}
        {step === 3 && (
          <Panel hue="amber" title="Exposures" subtitle="Used to screen for presumptive conditions">
            <div className="p-5">
              <ExposuresEditor
                exposures={exposures}
                locationsText={locationsText}
                onExposureChange={(key, value) => setExposures((e) => ({ ...e, [key]: value }))}
                onLocationsTextChange={setLocationsText}
              />
            </div>
          </Panel>
        )}
        {step === 4 && (
          <RatingsStep
            alreadyRated={alreadyRated}
            setAlreadyRated={setAlreadyRated}
            ratings={quickRatings}
            setRatings={setQuickRatings}
          />
        )}
        {step === 5 && <ConsideringStep conditions={quickConditions} setConditions={setQuickConditions} />}
        {step === 6 && <BringRecordsStep />}
        {step === 7 && <RecordsCheckStep recordsHave={recordsHave} setRecordsHave={setRecordsHave} />}
        {step === 8 && (
          <FinishStep
            periods={periods}
            quickRatings={quickRatings}
            quickConditions={quickConditions}
            recordsHave={recordsHave}
          />
        )}
      </div>

      <div className="flex items-center justify-between gap-3 border-t border-line pt-5">
        <button onClick={goBack} disabled={step === 0 || submitting} className="vo-btn-secondary">
          <ArrowLeft size={15} /> Back
        </button>
        <span className="text-xs font-medium tabular-nums text-faint" aria-hidden="true">
          {step + 1} / {STEPS.length}
        </span>
        {step < STEPS.length - 1 ? (
          <button onClick={goNext} className="vo-btn-primary group">
            {STEPS[step].key === 'bring_records' ? "I'll do this later" : 'Continue'}
            <ArrowRight size={15} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
          </button>
        ) : (
          <button onClick={() => void finish()} disabled={submitting} className="vo-btn-primary">
            {submitting ? <Spinner size={16} className="text-white" /> : <CheckCircle2 size={15} />}
            Finish setup
          </button>
        )}
      </div>
    </div>
  )
}

function ProgressBar({ step }: { step: number }) {
  return (
    <div>
      <ol
        className="flex items-center gap-1.5"
        aria-label={`Setup progress: step ${step + 1} of ${STEPS.length}, ${STEPS[step].label}`}
      >
        {STEPS.map((s, i) => {
          const done = i < step
          const current = i === step
          return (
            <li
              key={s.key}
              className="flex flex-1 flex-col items-center gap-1.5"
              aria-current={current ? 'step' : undefined}
            >
              <div className="relative h-1.5 w-full overflow-hidden rounded-full" style={{ background: 'var(--border)' }}>
                <div
                  className="absolute inset-y-0 left-0 rounded-full transition-all duration-500 ease-out"
                  style={{
                    width: done || current ? '100%' : '0%',
                    background: done
                      ? hueVar('violet')
                      : `linear-gradient(90deg, ${hueVar('violet')}, ${hueVar('fuchsia')})`,
                    boxShadow: current ? `0 0 8px ${hueVar('violet')}` : undefined,
                  }}
                />
              </div>
              <span
                className={`hidden items-center gap-1 text-center text-micro transition-colors duration-300 sm:flex ${
                  current ? 'font-semibold text-txt' : done ? 'text-muted' : 'text-faint'
                }`}
              >
                {done && <Check size={11} className="animate-scale-in text-h-violet" aria-hidden="true" />}
                {s.label}
              </span>
            </li>
          )
        })}
      </ol>
      {/* Mobile: labels are hidden, so name the step here. */}
      <p className="mt-2 text-center text-xs font-medium text-muted sm:hidden">
        Step {step + 1} of {STEPS.length} — {STEPS[step].label}
      </p>
    </div>
  )
}

/** The three phases of the overall process — the through-line the whole app is
 * organized around. Individual claims live inside "Take action". */
const PROCESS_PHASES = [
  { icon: FileStack, label: 'Get organized', desc: 'Bring in your records and service history' },
  { icon: Compass, label: 'See where you stand', desc: 'Rating Raider maps your situation and options' },
  { icon: ClipboardCheck, label: 'Take action', desc: 'Pursue claims, appeals, and increases — your call' },
] as const

function WelcomeStep() {
  return (
    <Panel hue="violet">
      <div className="flex flex-col gap-5 p-6 sm:p-8">
        <div className="text-center">
          <h2 className="text-heading text-txt">Welcome to Rating Raider</h2>
          <p className="mx-auto mt-2.5 max-w-lg text-body text-muted">
            Rating Raider helps you get organized and figure out where you stand with the VA — filing a claim is one
            part of that, not the whole thing. Nothing here gets filed or sent anywhere; it's your own organized
            record, and you can edit any of it later.
          </p>
        </div>

        <div className="grid gap-2.5 sm:grid-cols-3">
          {PROCESS_PHASES.map((phase, i) => {
            const Icon = phase.icon
            return (
              <div key={phase.label} className="rounded-control border border-line bg-surface2 p-3.5">
                <div className="flex items-center gap-2">
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-h-violet-soft text-h-violet">
                    <Icon size={15} />
                  </span>
                  <span className="text-micro font-semibold uppercase tracking-wide text-faint tabular-nums">
                    {i + 1}
                  </span>
                </div>
                <p className="mt-2 text-sm font-semibold text-txt">{phase.label}</p>
                <p className="mt-0.5 text-xs leading-snug text-muted">{phase.desc}</p>
              </div>
            )
          })}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <Link to="/documents" className="vo-btn-primary min-h-11 text-sm">
            <UploadCloud size={15} /> Upload my records
          </Link>
          <Link to="/profile?start=1" className="vo-btn-secondary min-h-11 text-sm">
            Set up profile
            <ArrowRight size={15} />
          </Link>
        </div>
        <p className="text-xs text-muted">
          Or use <span className="font-semibold text-txt">Continue</span> below to answer a few quick questions and
          let Rating Raider get a head start.
        </p>

        <div className="flex items-start gap-2.5 rounded-control border border-line bg-surface2 px-4 py-3.5 text-left text-xs leading-relaxed text-muted">
          <ShieldCheck size={16} className="mt-0.5 shrink-0 text-faint" />
          <span>{DISCLAIMER_TEXT}</span>
        </div>
      </div>
    </Panel>
  )
}

/** Resolve the three intake answers to one guidance tier. Priority is
 * deliberate:
 *  - D (upload-first floor) leads for a brand-new veteran with nothing on hand
 *    ("just starting" + no records) — it's the friendliest, always-works path
 *    and reassures them a VA account isn't required.
 *  - C leads when there's still no VA.gov account and they aren't in the D case
 *    — you can't pull anything until an account exists, so that's step one.
 *  - A (connected + rated) → fastest path is to sync what VA already has.
 *  - B is the remaining "has an account, still building" case.
 * The document-upload path is shown in EVERY tier regardless (universal floor).
 */
function deriveTier(
  account: VaAccountAnswer | null,
  rated: VaRatedAnswer | null,
  records: VaRecordsAnswer | null
): SituationTier | null {
  if (!account || !rated) return null
  const hasAccount = account === 'yes'
  const noRecords = records === 'no'
  if (rated === 'starting' && noRecords) return 'D'
  if (!hasAccount) return 'C'
  if (rated === 'rated') return 'A'
  return 'B'
}

interface RadioOption<T extends string> {
  value: T
  label: string
  hint?: string
}

/** Radio-card group matching the app's picker style (see Appeals.tsx): a
 * bordered button per option that fills with its hue when chosen. */
function RadioCards<T extends string>({
  legend,
  hue,
  value,
  onChange,
  options,
}: {
  legend: string
  hue: Hue
  value: T | null
  onChange: (v: T) => void
  options: RadioOption<T>[]
}) {
  return (
    <fieldset>
      <legend className="mb-2.5 text-sm font-semibold text-txt">{legend}</legend>
      <div className="grid gap-2.5 sm:grid-cols-3">
        {options.map((o) => {
          const active = o.value === value
          return (
            <button
              key={o.value}
              type="button"
              role="radio"
              aria-checked={active}
              onClick={() => onChange(o.value)}
              className="rounded-control border p-3.5 text-left transition-colors"
              style={{
                borderColor: active ? hueVar(hue) : 'var(--border)',
                background: active ? hueSoftVar(hue) : 'var(--surface2)',
              }}
            >
              <span className="flex items-center gap-2">
                <span
                  aria-hidden
                  className="grid h-4 w-4 shrink-0 place-items-center rounded-full border"
                  style={{ borderColor: active ? hueVar(hue) : 'var(--border)' }}
                >
                  {active && <span className="h-2 w-2 rounded-full" style={{ background: hueVar(hue) }} />}
                </span>
                <span className="text-sm font-medium text-txt">{o.label}</span>
              </span>
              {o.hint && <span className="mt-1.5 block pl-6 text-xs leading-relaxed text-muted">{o.hint}</span>}
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}

const ACCOUNT_OPTIONS: RadioOption<VaAccountAnswer>[] = [
  { value: 'yes', label: 'Yes' },
  { value: 'no', label: 'No' },
  { value: 'unsure', label: 'Not sure' },
]

const RATED_OPTIONS: RadioOption<VaRatedAnswer>[] = [
  { value: 'rated', label: "Yes, I'm rated" },
  { value: 'filed', label: 'Filed, no decision yet' },
  { value: 'starting', label: "No, I'm just starting" },
]

const RECORDS_OPTIONS: RadioOption<VaRecordsAnswer>[] = [
  { value: 'yes', label: 'Yes, most of them' },
  { value: 'some', label: 'Some' },
  { value: 'no', label: 'Not really' },
]

/** Step 2 — "Where you are with the VA." Two required routing questions plus
 * one optional records question, then a tailored "Your path" panel. Pure
 * guidance: nothing here is saved or gates the rest of onboarding, and it's
 * fully skippable. Legal lane: we point the way and the veteran creates their
 * own VA.gov account — we never create accounts or handle credentials, and we
 * never file anything. */
function SituationStep({
  account,
  setAccount,
  rated,
  setRated,
  records,
  setRecords,
  onSkip,
}: {
  account: VaAccountAnswer | null
  setAccount: (v: VaAccountAnswer) => void
  rated: VaRatedAnswer | null
  setRated: (v: VaRatedAnswer) => void
  records: VaRecordsAnswer | null
  setRecords: (v: VaRecordsAnswer) => void
  onSkip: () => void
}) {
  const tier = deriveTier(account, rated, records)
  return (
    <Panel hue="cyan" title="Where you are with the VA" subtitle="Two quick questions so we point you at the right path">
      <div className="space-y-6 p-5">
        <div className="flex items-start gap-2.5 text-sm text-muted">
          <Compass size={16} className="mt-0.5 shrink-0 text-h-cyan" />
          <p>
            Every veteran starts somewhere different. Answer these and we'll show you the fastest next step — there's a
            path that works whether or not you have a VA account yet.
          </p>
        </div>

        <RadioCards
          legend="Do you have a VA.gov account (Login.gov or ID.me)?"
          hue="cyan"
          value={account}
          onChange={setAccount}
          options={ACCOUNT_OPTIONS}
        />
        <RadioCards
          legend="Have you already gotten any VA disability ratings or decisions?"
          hue="cyan"
          value={rated}
          onChange={setRated}
          options={RATED_OPTIONS}
        />
        <RadioCards
          legend="Do you have your records (DD-214, medical records) on hand? (optional)"
          hue="cyan"
          value={records}
          onChange={setRecords}
          options={RECORDS_OPTIONS}
        />

        {tier ? (
          <PathPanel tier={tier} />
        ) : (
          <p className="rounded-control border border-dashed border-line bg-surface2 px-4 py-3.5 text-sm text-muted">
            Pick an answer above and your personalized path shows up here.
          </p>
        )}

        <p className="flex items-start gap-2 text-xs leading-relaxed text-muted">
          <LifeBuoy size={14} className="mt-0.5 shrink-0" />
          Not sure where you fit? A free, accredited VSO (Veterans Service Officer) can help you sort it out at no cost —
          this app is educational self-help, and you always stay in control.
        </p>

        <div className="border-t border-line pt-4">
          <button type="button" onClick={onSkip} className="vo-btn-ghost text-sm text-muted">
            Skip for now
            <ArrowRight size={14} />
          </button>
          <p className="mt-1.5 text-xs text-faint">This step is just guidance — it never blocks your setup.</p>
        </div>
      </div>
    </Panel>
  )
}

/** The tailored "Your path" card. Every tier keeps the document-upload path
 * available as the universal floor — many veterans have no VA account and no
 * records, and the app must work end-to-end from uploads alone. */
function PathPanel({ tier }: { tier: SituationTier }) {
  const hue: Hue = tier === 'A' ? 'emerald' : tier === 'B' ? 'sky' : tier === 'C' ? 'amber' : 'violet'
  return (
    <div
      className="animate-slide-in rounded-control border p-5"
      style={{ borderColor: hueVar(hue), background: hueSoftVar(hue) }}
    >
      <p className="vo-label-micro mb-1" style={{ color: hueVar(hue) }}>
        Your path
      </p>

      {tier === 'A' && (
        <>
          <h3 className="text-heading text-txt">You're set up</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">
            You've got a VA.gov account and existing ratings. The fastest path is to connect VA.gov so we can pull your
            ratings and records for you — then you just review what's there.
          </p>
          <div className="mt-3.5 flex flex-wrap gap-2.5">
            <Link to="/va-sync" className="vo-btn-primary text-sm">
              <Landmark size={15} /> Connect VA.gov
            </Link>
            <Link to="/va-import" className="vo-btn-secondary text-sm">
              <ClipboardCheck size={15} /> Import VA data
            </Link>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-muted">
            Already copied your ratings from VA.gov? Import VA data organizes exactly what your VA record shows —
            it files nothing. Or download your VA Benefit Summary letter and Blue Button records and upload them
            below — either way works.
          </p>
        </>
      )}

      {tier === 'B' && (
        <>
          <h3 className="text-heading text-txt">Connect and fill in the gaps</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">
            You've got a VA.gov account but not much on file yet. Connect VA.gov to see what's there, then request any
            records you're missing.
          </p>
          <div className="mt-3.5 flex flex-wrap gap-2.5">
            <Link to="/va-sync" className="vo-btn-primary text-sm">
              <Landmark size={15} /> Connect VA.gov
            </Link>
            <Link to="/va-import" className="vo-btn-secondary text-sm">
              <ClipboardCheck size={15} /> Import VA data
            </Link>
            <Link to="/records" className="vo-btn-secondary text-sm">
              <FileStack size={15} /> Request records
            </Link>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-muted">
            If you've already pulled your ratings or claims from VA.gov, Import VA data organizes what your VA record
            shows — nothing gets filed.
          </p>
        </>
      )}

      {tier === 'C' && (
        <>
          <h3 className="text-heading text-txt">First, set up your free VA.gov account</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">
            You'll create a free VA.gov account yourself using Login.gov or ID.me — we'll walk you through it. Once
            you're signed in, you can pull your records.
          </p>
          <ol className="mt-3 space-y-1.5 text-sm text-txt">
            <PathStep n={1} hue={hue} text="Create a free Login.gov or ID.me account." />
            <PathStep n={2} hue={hue} text="Sign in at VA.gov with it." />
            <PathStep n={3} hue={hue} text="Download your records — Benefit Summary letter and Blue Button." />
          </ol>
          <div className="mt-3.5 flex flex-wrap gap-2.5">
            <a href="https://www.va.gov/" target="_blank" rel="noreferrer" className="vo-btn-primary text-sm">
              <ExternalLink size={15} /> Go to VA.gov
            </a>
          </div>
          <p className="mt-3 text-xs leading-relaxed text-muted">
            You create the account and enter your own sign-in — we only guide you and never handle your credentials.
          </p>
        </>
      )}

      {tier === 'D' && (
        <>
          <h3 className="text-heading text-txt">Start from your documents — no VA account needed</h3>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">
            No problem — you can build your whole claim from documents you upload, like your DD-214 and private medical
            records. No VA account required, and this path always works.
          </p>
          <div className="mt-3.5 flex flex-wrap gap-2.5">
            <Link to="/documents" className="vo-btn-primary text-sm">
              <UploadCloud size={15} /> Upload documents
            </Link>
          </div>
        </>
      )}

      {/* Universal floor: the upload path is available in EVERY tier. */}
      <div className="mt-4 flex flex-wrap items-center gap-x-1.5 gap-y-1 border-t border-line/60 pt-3 text-xs text-muted">
        <UploadCloud size={13} className="shrink-0" />
        <span>No VA account, no records?</span>
        <Link to="/documents" className="font-semibold text-brand hover:text-brand-hover">
          Upload what you have
        </Link>
        <span>— this always works, and you can start from nothing.</span>
      </div>
    </div>
  )
}

function PathStep({ n, hue, text }: { n: number; hue: Hue; text: string }) {
  return (
    <li className="flex items-start gap-2.5">
      <span
        aria-hidden
        className="mt-px grid h-5 w-5 shrink-0 place-items-center rounded-full text-micro font-bold text-white"
        style={{ background: hueVar(hue) }}
      >
        {n}
      </span>
      <span className="leading-relaxed text-muted">{text}</span>
    </li>
  )
}

function RatingsStep({
  alreadyRated,
  setAlreadyRated,
  ratings,
  setRatings,
}: {
  alreadyRated: boolean | null
  setAlreadyRated: (v: boolean | null) => void
  ratings: QuickRating[]
  setRatings: (updater: (prev: QuickRating[]) => QuickRating[]) => void
}) {
  return (
    <Panel hue="orange" title="Are you already rated for anything?" subtitle="Quick-add your current conditions and percentages">
      <div className="space-y-4 p-5">
        <div className="flex gap-2">
          <button
            onClick={() => setAlreadyRated(true)}
            className={alreadyRated === true ? 'vo-btn-primary text-sm' : 'vo-btn-secondary text-sm'}
            aria-pressed={alreadyRated === true}
            type="button"
          >
            Yes, I have a rating
          </button>
          <button
            onClick={() => setAlreadyRated(false)}
            className={alreadyRated === false ? 'vo-btn-primary text-sm' : 'vo-btn-secondary text-sm'}
            aria-pressed={alreadyRated === false}
            type="button"
          >
            No, not yet
          </button>
        </div>

        {alreadyRated && (
          <div className="space-y-2.5">
            {ratings.map((r, idx) => (
              <div key={idx} className="animate-slide-in flex items-center gap-2.5 rounded-control border border-line bg-surface2 p-3">
                <input
                  className="vo-input flex-1"
                  placeholder="Condition name"
                  aria-label="Condition name"
                  value={r.name}
                  onChange={(e) =>
                    setRatings((prev) => prev.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))
                  }
                />
                <select
                  className="vo-input w-28"
                  aria-label="Current rating percent"
                  value={r.percent}
                  onChange={(e) =>
                    setRatings((prev) => prev.map((x, i) => (i === idx ? { ...x, percent: Number(e.target.value) } : x)))
                  }
                >
                  {PERCENTS.map((p) => (
                    <option key={p} value={p}>{p}%</option>
                  ))}
                </select>
                <button
                  onClick={() => setRatings((prev) => prev.filter((_, i) => i !== idx))}
                  className="vo-icon-btn vo-btn-ghost text-danger hover:bg-danger-soft hover:text-danger"
                  aria-label="Remove"
                  type="button"
                >
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
            <button
              onClick={() => setRatings((prev) => [...prev, { name: '', percent: 10 }])}
              className="vo-btn-secondary text-sm"
              type="button"
            >
              <Plus size={14} /> Add a rated condition
            </button>
          </div>
        )}
      </div>
    </Panel>
  )
}

function ConsideringStep({
  conditions,
  setConditions,
}: {
  conditions: QuickCondition[]
  setConditions: (updater: (prev: QuickCondition[]) => QuickCondition[]) => void
}) {
  return (
    <Panel hue="emerald" title="What are you considering claiming?" subtitle="Quick-add conditions — you can flesh out details later">
      <div className="space-y-2.5 p-5">
        {conditions.length === 0 && (
          <p className="text-sm text-muted">Add anything you're thinking about — new or newly worsened conditions.</p>
        )}
        {conditions.map((c, idx) => (
          <div key={idx} className="animate-slide-in flex items-center gap-2.5 rounded-control border border-line bg-surface2 p-3">
            <input
              className="vo-input flex-1"
              placeholder="Condition name (e.g. Tinnitus)"
              aria-label="Condition name"
              value={c.name}
              onChange={(e) => setConditions((prev) => prev.map((x, i) => (i === idx ? { ...x, name: e.target.value } : x)))}
            />
            <input
              className="vo-input flex-1"
              placeholder="Body system (e.g. Auditory)"
              aria-label="Body system"
              value={c.body_system}
              onChange={(e) =>
                setConditions((prev) => prev.map((x, i) => (i === idx ? { ...x, body_system: e.target.value } : x)))
              }
            />
            <button
              onClick={() => setConditions((prev) => prev.filter((_, i) => i !== idx))}
              className="vo-icon-btn vo-btn-ghost text-danger hover:bg-danger-soft hover:text-danger"
              aria-label="Remove"
              type="button"
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
        <button
          onClick={() => setConditions((prev) => [...prev, { name: '', body_system: '' }])}
          className="vo-btn-secondary text-sm"
          type="button"
        >
          <Plus size={14} /> Add a condition
        </button>
      </div>
    </Panel>
  )
}

/** WAVE2-SPEC §1 addition: a dedicated invite to dump every record the
 * veteran already has straight into the document intake pipeline, rather
 * than making them recall record types one at a time. Opens in a new tab
 * (not a client-side navigate) because the wizard doesn't persist anything
 * until "Finish setup" — leaving this tab open keeps every earlier answer
 * intact while Documents does its own thing in parallel. */
function BringRecordsStep() {
  return (
    <Panel hue="amber" title="Bring your records" subtitle="Optional — you can always do this later from Documents">
      <div className="flex flex-col items-center gap-5 p-8 text-center sm:p-10">
        <div className="vo-logo-tile flex h-14 w-14 items-center justify-center rounded-2xl text-white shadow-glow">
          <UploadCloud size={26} />
        </div>
        <p className="mx-auto max-w-md text-body text-muted">
          Already have VA rating decisions, medical records, or military records — digital or scanned? Dump them
          all in Documents. Rating Raider reads each one privately on our own servers — never sent to commercial
          AI clouds — sorts them by type, and turns them into evidence you confirm. ZIPs welcome.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-2.5">
          <a href="/documents" target="_blank" rel="noreferrer" className="vo-btn-primary group text-sm">
            Open Documents
            <ArrowRight size={15} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
          </a>
        </div>
        <p className="text-xs text-faint">
          Opens in a new tab — your answers here are safe. Use "I'll do this later" below to keep going.
        </p>
      </div>
    </Panel>
  )
}

function RecordsCheckStep({
  recordsHave,
  setRecordsHave,
}: {
  recordsHave: RecordsHave
  setRecordsHave: (updater: (prev: RecordsHave) => RecordsHave) => void
}) {
  return (
    <Panel hue="lime" title="Records check" subtitle="Which of these do you already have on hand?">
      <div className="space-y-3 p-5">
        {RECORD_TYPES.map((rt) => (
          <Checkbox
            key={rt.key}
            checked={recordsHave[rt.key]}
            onChange={(e) => setRecordsHave((prev) => ({ ...prev, [rt.key]: e.target.checked }))}
            label={`I have my ${rt.label.toLowerCase()}`}
            description={rt.blurb}
          />
        ))}
        <p className="flex items-start gap-2 text-xs leading-relaxed text-muted">
          <FileStack size={14} className="mt-0.5 shrink-0" />
          Anything left unchecked gets added to your checklist with a link to the guided request flow on the Records
          page — free VSO help is available at every step there too.
        </p>
      </div>
    </Panel>
  )
}

/** Confetti pieces for the finish moment — positions/hues/delays are stable
 * per mount so re-renders don't reshuffle mid-fall. */
function Confetti() {
  const pieces = useMemo(
    () =>
      Array.from({ length: 28 }, (_, i) => ({
        left: `${(i * 37 + 13) % 100}%`,
        hue: hueVar(HUES[i % HUES.length]),
        delay: `${((i * 173) % 900) / 1000}s`,
      })),
    []
  )
  return (
    <span className="vo-confetti" aria-hidden="true">
      {pieces.map((p, i) => (
        <i key={i} style={{ '--cx': p.left, '--ch': p.hue, '--cd': p.delay } as React.CSSProperties} />
      ))}
    </span>
  )
}

function FinishStep({
  periods,
  quickRatings,
  quickConditions,
  recordsHave,
}: {
  periods: ServicePeriod[]
  quickRatings: QuickRating[]
  quickConditions: QuickCondition[]
  recordsHave: RecordsHave
}) {
  const missingCount = RECORD_TYPES.filter((rt) => !recordsHave[rt.key]).length
  const ratingsFilled = quickRatings.filter((r) => r.name.trim()).length
  const conditionsFilled = quickConditions.filter((c) => c.name.trim()).length
  return (
    <Panel hue="violet" className="relative">
      <Confetti />
      <div className="relative flex flex-col items-center gap-1 px-5 pt-8 text-center">
        <span className="vo-sparkle vo-logo-tile flex h-14 w-14 items-center justify-center rounded-2xl text-white shadow-glow">
          <PartyPopper size={24} />
        </span>
        <h2 className="mt-3 text-heading text-txt">Ready to go</h2>
        <p className="text-sm text-muted">Here's what we'll save</p>
      </div>
      <div className="relative space-y-2.5 p-5 text-sm">
        <SummaryRow icon={<ShieldCheck size={16} />} text={`${periods.length} service period${periods.length === 1 ? '' : 's'}`} />
        <SummaryRow icon={<Sparkles size={16} />} text={`${ratingsFilled} current rating${ratingsFilled === 1 ? '' : 's'}`} />
        <SummaryRow icon={<ClipboardCheck size={16} />} text={`${conditionsFilled} condition${conditionsFilled === 1 ? '' : 's'} to consider`} />
        <SummaryRow
          icon={<FileStack size={16} />}
          text={missingCount === 0 ? 'All records on hand' : `${missingCount} records checklist item${missingCount === 1 ? '' : 's'} added`}
        />
        <p className="pt-2 text-xs leading-relaxed text-muted">
          Everything saves when you click "Finish setup." You always drive — nothing is filed or submitted anywhere.
        </p>
      </div>
    </Panel>
  )
}

function SummaryRow({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="flex items-center gap-2.5 rounded-control border border-line bg-surface2 px-3.5 py-2.5">
      <span className="text-brand">{icon}</span>
      <span className="text-txt">{text}</span>
    </div>
  )
}
