import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  ListChecks,
  Plus,
  Printer,
  ShieldCheck,
  Sparkles,
  Trash2,
  Users,
} from 'lucide-react'
import { useState, type CSSProperties, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { FilledFormPanel } from '../components/FilledFormPanel'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { dependencyApi } from '../lib/api'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type {
  DependencyAction,
  DependencyDependent,
  DependencyRelationship,
  DependencyWorksheet,
  DependencyWorksheetInput,
} from '../types'

// /dependency — Dependency changes (add/re-add a dependent, or respond to a VA
// removal/reduction letter). VA Form 21-686c / 21-509. Dependency changes affect
// pay and are the veteran's OWN filing — Rating Raider prepares a worksheet the
// veteran reviews, signs, and files; it never files and never says the veteran
// "qualifies". The backend enforces the hedged copy; the UI adds none of its own.
// Endpoint shapes reconciled against backend/app/routers/dependency.py. Mirrors
// the Tdiu.tsx builder + TdiuPrint print pattern.

const HUE: Hue = 'violet'
export const DEPENDENCY_WORKSHEET_KEY = 'vo_dependency_worksheet'

const MAX_DEPENDENTS = 12

/** What the print view reads out of sessionStorage. */
export interface DependencyPrintState {
  worksheet: DependencyWorksheet
  veteranName: string
  action: DependencyAction
}

const RELATIONSHIP_OPTIONS: { value: DependencyRelationship; label: string }[] = [
  { value: 'spouse', label: 'Spouse' },
  { value: 'child', label: 'Child' },
  { value: 'stepchild', label: 'Stepchild' },
  { value: 'parent', label: 'Dependent parent' },
]

const emptyDependent = (): DependencyDependent => ({
  full_name: '',
  relationship: 'spouse',
  event: '',
  event_date: '',
  event_place: '',
  notes: '',
})

export function Dependency() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data: guidance, error: guidanceError, loading } = useAsync(() => dependencyApi.guidance())

  const [action, setAction] = useState<DependencyAction>('add')
  const [veteranName, setVeteranName] = useState('')
  const [dependents, setDependents] = useState<DependencyDependent[]>([emptyDependent()])
  const [explanation, setExplanation] = useState('')
  const [priorRemovalNote, setPriorRemovalNote] = useState('')

  const [building, setBuilding] = useState(false)

  const isRemoval = action === 'respond_to_removal'

  const setDependent = (index: number, patch: Partial<DependencyDependent>) =>
    setDependents((prev) => prev.map((d, i) => (i === index ? { ...d, ...patch } : d)))

  const addDependent = () =>
    setDependents((prev) => (prev.length >= MAX_DEPENDENTS ? prev : [...prev, emptyDependent()]))

  const removeDependent = (index: number) =>
    setDependents((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)))

  const buildBody = (): DependencyWorksheetInput => ({
    veteran_name: veteranName.trim(),
    action,
    // Drop rows where only the default relationship is set and everything else is blank.
    dependents: dependents
      .filter((d) =>
        d.full_name.trim() !== '' ||
        d.event.trim() !== '' ||
        d.event_date.trim() !== '' ||
        d.event_place.trim() !== '' ||
        d.notes.trim() !== '',
      )
      .map((d) => ({
        full_name: d.full_name.trim(),
        relationship: d.relationship,
        event: d.event.trim(),
        event_date: d.event_date.trim(),
        event_place: d.event_place.trim(),
        notes: d.notes.trim(),
      })),
    explanation: explanation.trim(),
    // Only meaningful on the removal path; send empty otherwise.
    prior_removal_note: isRemoval ? priorRemovalNote.trim() : '',
  })

  const generate = async (e: FormEvent) => {
    e.preventDefault()
    setBuilding(true)
    try {
      const worksheet = await dependencyApi.worksheet(buildBody())
      const state: DependencyPrintState = { worksheet, veteranName: veteranName.trim(), action }
      sessionStorage.setItem(DEPENDENCY_WORKSHEET_KEY, JSON.stringify(state))
      navigate('/dependency/print')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBuilding(false)
    }
  }

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)
  const steps = isRemoval ? guidance?.removal_path ?? [] : guidance?.add_path ?? []

  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6" style={hueStyle(HUE) as CSSProperties}>
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          Dependents · VA Form 21-686c
        </p>
        <h1 className="vo-page-title">Dependents &amp; VA actions</h1>
        <p className="vo-page-sub">
          Add or re-add a dependent, or respond to a VA letter proposing to remove or reduce one. Dependency changes
          affect your pay and are your own filing — this walks you through the path and builds a worksheet you review,
          sign, and file. VA decides — this never does.
        </p>
      </div>

      <FilledFormPanel formId="21-686c" hue={HUE} title="Download the pre-filled 21-686c (review & sign)" />

      {loading && !guidance && <LoadingBlock label="Loading dependency guidance…" />}
      {guidanceError && !guidance && <ErrorBlock message={guidanceError} />}

      {guidance && (
        <>
          <Panel hue={HUE} title="What this covers" subtitle="Dependency changes, in plain terms">
            <div className="p-5">
              <p className="text-sm leading-relaxed text-txt/90">{guidance.what_it_is}</p>
            </div>
          </Panel>

          {/* Action toggle — drives the guidance shown AND the submitted action. */}
          <div className="vo-panel vo-accent overflow-hidden" style={hueStyle(HUE) as CSSProperties}>
            <div className="border-b border-line px-5 py-4">
              <h2 className="text-heading text-txt">What are you doing?</h2>
              <p className="text-xs text-muted">Pick one — the steps and worksheet follow your choice.</p>
            </div>
            <div className="grid gap-3 p-5 sm:grid-cols-2" role="group" aria-label="Choose an action">
              <ActionButton
                active={action === 'add'}
                onClick={() => setAction('add')}
                title="Add or re-add a dependent"
                detail="A new spouse, child, stepchild, or dependent parent — or one VA dropped that should be back on."
              />
              <ActionButton
                active={isRemoval}
                onClick={() => setAction('respond_to_removal')}
                title="Respond to a VA removal or reduction letter"
                detail="VA proposed to remove a dependent or reduce your award and you want to respond in time."
              />
            </div>
          </div>

          {/* Timeline note — PROMINENT (amber/attention) on the removal path since
              it's about VA response deadlines; quieter accent on the add path. */}
          {guidance.timeline_note && <TimelineCallout note={guidance.timeline_note} urgent={isRemoval} />}

          {steps.length > 0 && (
            <Panel
              hue={HUE}
              title={isRemoval ? 'The path to respond' : 'The path to add a dependent'}
              subtitle="Step by step"
            >
              <div className="p-5">
                <ul className="space-y-2.5 text-sm text-txt">
                  {steps.map((s, i) => (
                    <li key={i} className="flex gap-2.5">
                      <span
                        aria-hidden
                        className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                        style={{ background: hueSoftVar(HUE), color: ink }}
                      >
                        {i + 1}
                      </span>
                      <span className="leading-relaxed">{s}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Panel>
          )}

          {guidance.evidence.length > 0 && (
            <Panel hue={HUE} title="What you'll need" subtitle="The proof VA looks for">
              <div className="p-5">
                <ul className="space-y-2.5 text-sm text-txt">
                  {guidance.evidence.map((ev, i) => (
                    <li key={i} className="flex gap-2.5">
                      <CheckCircle2 size={16} className="mt-0.5 shrink-0" style={{ color: ink }} />
                      <span className="leading-relaxed">{ev}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Panel>
          )}

          {guidance.forms.length > 0 && (
            <Panel hue={HUE} title="The forms" subtitle="What each one is for and who fills it out">
              <div className="divide-y divide-line">
                {guidance.forms.map((f, i) => (
                  <div key={i} className="flex flex-wrap items-start justify-between gap-3 p-5">
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-txt">
                        <span style={{ color: ink }}>{f.form}</span> — {f.title}
                      </p>
                      <p className="mt-1 text-xs leading-relaxed text-muted">{f.who}</p>
                    </div>
                    <a
                      href={f.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-brand hover:text-brand-hover"
                    >
                      Official form <ExternalLink size={12} />
                    </a>
                  </div>
                ))}
              </div>
            </Panel>
          )}

          <Panel
            hue={HUE}
            title="Your dependency worksheet"
            subtitle="Fill in what you can — you review and sign the result"
          >
            <form onSubmit={generate} className="space-y-5 p-5">
              {guidance.guidance_prompts.length > 0 && (
                <div
                  className="rounded-control border p-4"
                  style={{ borderColor: `color-mix(in srgb, ${hueVar(HUE)} 30%, var(--border))`, background: hueSoftVar(HUE) }}
                >
                  <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                    <ListChecks size={13} /> What to have on hand
                  </p>
                  <ul className="mt-2 space-y-1.5 text-xs text-muted">
                    {guidance.guidance_prompts.map((p, i) => (
                      <li key={i} className="flex gap-2">
                        <span aria-hidden style={{ color: ink }}>•</span>
                        <span className="leading-relaxed">{p}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Privacy reinforcement — the backend already omits SSN / VA file
                  numbers; remind the veteran those belong only on the signed form. */}
              <div
                className="flex items-start gap-2.5 rounded-control border-l-2 px-3.5 py-3 text-xs leading-relaxed text-muted"
                style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
              >
                <ShieldCheck size={15} className="mt-0.5 shrink-0" style={{ color: ink }} />
                <span>
                  Don't enter Social Security or VA file numbers here — those go only on the signed form.
                </span>
              </div>

              <label className="block text-sm sm:max-w-md">
                <span className="vo-label">Your name</span>
                <input
                  className="vo-input"
                  value={veteranName}
                  onChange={(e) => setVeteranName(e.target.value)}
                  placeholder="As it should appear on the worksheet"
                />
              </label>

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <span className="vo-label mb-0">Dependents</span>
                  <button
                    type="button"
                    onClick={addDependent}
                    disabled={dependents.length >= MAX_DEPENDENTS}
                    className="vo-btn-secondary text-xs"
                  >
                    <Plus size={13} /> Add a dependent
                  </button>
                </div>
                <div className="space-y-3">
                  {dependents.map((dep, i) => (
                    <div key={i} className="rounded-control border border-line bg-surface2 p-4">
                      <div className="mb-2.5 flex items-center justify-between">
                        <span className="text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
                          Dependent {i + 1}
                        </span>
                        {dependents.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeDependent(i)}
                            className="inline-flex items-center gap-1 text-xs font-medium text-muted hover:text-danger"
                          >
                            <Trash2 size={12} /> Remove
                          </button>
                        )}
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <label className="text-sm">
                          <span className="vo-label">Full name</span>
                          <input
                            className="vo-input"
                            value={dep.full_name}
                            onChange={(e) => setDependent(i, { full_name: e.target.value })}
                            placeholder="Their full legal name"
                          />
                        </label>
                        <label className="text-sm">
                          <span className="vo-label">Relationship</span>
                          <select
                            className="vo-input"
                            value={dep.relationship}
                            onChange={(e) =>
                              setDependent(i, { relationship: e.target.value as DependencyRelationship })
                            }
                          >
                            {RELATIONSHIP_OPTIONS.map((opt) => (
                              <option key={opt.value} value={opt.value}>
                                {opt.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="text-sm">
                          <span className="vo-label">Event</span>
                          <input
                            className="vo-input"
                            value={dep.event}
                            onChange={(e) => setDependent(i, { event: e.target.value })}
                            placeholder="e.g. Marriage, Birth, Adoption"
                          />
                        </label>
                        <label className="text-sm">
                          <span className="vo-label">Event date</span>
                          <input
                            className="vo-input"
                            value={dep.event_date}
                            onChange={(e) => setDependent(i, { event_date: e.target.value })}
                            placeholder="e.g. June 14, 2023"
                          />
                        </label>
                        <label className="text-sm sm:col-span-2">
                          <span className="vo-label">Event place</span>
                          <input
                            className="vo-input"
                            value={dep.event_place}
                            onChange={(e) => setDependent(i, { event_place: e.target.value })}
                            placeholder="e.g. Charleston County, SC"
                          />
                        </label>
                        <label className="text-sm sm:col-span-2">
                          <span className="vo-label">Notes</span>
                          <textarea
                            className="vo-input min-h-[80px] resize-y leading-relaxed"
                            value={dep.notes}
                            onChange={(e) => setDependent(i, { notes: e.target.value })}
                            placeholder="Anything that helps VA match this dependent — prior names, school status, custody, etc."
                          />
                        </label>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <label className="block text-sm">
                <span className="vo-label">
                  {isRemoval
                    ? 'Your explanation — why the dependent should stay (or the reduction is wrong)'
                    : 'Anything else VA should know'}
                </span>
                <textarea
                  className="vo-input min-h-[120px] resize-y leading-relaxed"
                  value={explanation}
                  onChange={(e) => setExplanation(e.target.value)}
                  placeholder={
                    isRemoval
                      ? 'In your own words: why this dependent still qualifies, or why the proposed change is a mistake. Be specific and first-hand.'
                      : 'In your own words: anything that helps VA understand the change you\'re reporting.'
                  }
                />
              </label>

              {isRemoval && (
                <label className="block text-sm">
                  <span className="vo-label">What the VA letter says</span>
                  <textarea
                    className="vo-input min-h-[100px] resize-y leading-relaxed"
                    value={priorRemovalNote}
                    onChange={(e) => setPriorRemovalNote(e.target.value)}
                    placeholder="e.g. The date on the letter, which dependent VA proposes to remove, and the reason given."
                  />
                </label>
              )}

              <button type="submit" disabled={building} className="vo-btn-primary">
                {building ? <Spinner size={16} className="text-white" /> : <Printer size={15} />}
                Generate my worksheet
              </button>
              <p className="flex items-center gap-1.5 text-xs text-faint">
                <Sparkles size={12} style={{ color: ink }} /> Opens a clean, print-ready page you read, sign, and file
                — VA decides dependency, not us.
              </p>
            </form>
          </Panel>

          <div
            className="rounded-control border-l-2 px-4 py-3 text-xs leading-relaxed"
            style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
          >
            {guidance.disclaimer && <p className="italic text-muted">{guidance.disclaimer}</p>}
            {guidance.vso_note && <p className="mt-2 font-medium text-txt/85">{guidance.vso_note}</p>}
          </div>
        </>
      )}
    </div>
  )
}

/** Segmented-control button for the add / respond action toggle. */
function ActionButton({
  active,
  onClick,
  title,
  detail,
}: {
  active: boolean
  onClick: () => void
  title: string
  detail: string
}) {
  const ink = hueInk(HUE)
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className="flex items-start gap-3 rounded-control border p-4 text-left transition-colors"
      style={
        active
          ? {
              borderColor: `color-mix(in srgb, ${hueVar(HUE)} 45%, var(--border))`,
              background: hueSoftVar(HUE),
            }
          : { borderColor: 'var(--line)', background: 'var(--surface2)' }
      }
    >
      <span
        aria-hidden
        className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2"
        style={{
          borderColor: active ? hueVar(HUE) : 'var(--line2)',
          background: active ? hueVar(HUE) : 'transparent',
        }}
      >
        {active && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold" style={{ color: active ? ink : 'var(--txt)' }}>
          {title}
        </span>
        <span className="mt-1 block text-xs leading-relaxed text-muted">{detail}</span>
      </span>
    </button>
  )
}

/** Timeline note — amber/attention styling when responding to a VA removal
 * (deadlines), a quieter section-hue accent when just adding. */
function TimelineCallout({ note, urgent }: { note: string; urgent: boolean }) {
  if (urgent) {
    return (
      <div
        className="flex items-start gap-3.5 rounded-control border-l-4 p-5"
        style={{
          borderColor: hueVar('amber'),
          background: hueSoftVar('amber'),
        }}
      >
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: 'color-mix(in srgb, var(--hue-amber) 20%, transparent)', color: hueInk('amber') }}
        >
          <AlertTriangle size={20} />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-txt">Watch the clock</h2>
          <p className="mt-1 text-sm leading-relaxed text-muted">{note}</p>
        </div>
      </div>
    )
  }
  return (
    <div
      className="vo-card vo-accent flex items-start gap-3.5 p-5"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}
      >
        <Users size={20} />
      </div>
      <div>
        <h2 className="text-sm font-semibold text-txt">Timing</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">{note}</p>
      </div>
    </div>
  )
}
