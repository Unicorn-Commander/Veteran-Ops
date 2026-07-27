import {
  Briefcase,
  CheckCircle2,
  ExternalLink,
  ListChecks,
  Plus,
  Printer,
  ShieldCheck,
  Sparkles,
  Trash2,
} from 'lucide-react'
import { useState, type CSSProperties, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { FilledFormPanel } from '../components/FilledFormPanel'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { tdiuApi } from '../lib/api'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { TdiuJob, TdiuScreen, TdiuWorksheet, TdiuWorksheetInput } from '../types'

// /tdiu — TDIU (Individual Unemployability, 38 CFR §4.16). Educational screen +
// a work-history worksheet (VA Form 21-8940) the veteran reviews, signs, and
// files. TDIU is VA's DETERMINATION — every line stays hedged: we never say the
// veteran "qualifies", "will get", or "is unemployable". The backend enforces
// this in its returned strings; the UI just doesn't add promissory copy.
// Endpoint shapes reconciled against backend/app/routers/tdiu.py. Mirrors the
// Statement.tsx builder + StatementPrint print pattern.

const HUE: Hue = 'emerald'
export const TDIU_WORKSHEET_KEY = 'vo_tdiu_worksheet'

const MAX_JOBS = 20

/** What the print view reads out of sessionStorage. */
export interface TdiuPrintState {
  worksheet: TdiuWorksheet
  veteranName: string
}

const emptyJob = (): TdiuJob => ({
  employer: '',
  job_title: '',
  dates: '',
  hours_per_week: '',
  reason_ended: '',
})

export function Tdiu() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data: screen, error: screenError, loading } = useAsync(() => tdiuApi.screen())

  const [veteranName, setVeteranName] = useState('')
  const [lastFullTimeDate, setLastFullTimeDate] = useState('')
  const [highestEarnings, setHighestEarnings] = useState('')
  const [education, setEducation] = useState('')
  const [training, setTraining] = useState('')
  const [jobs, setJobs] = useState<TdiuJob[]>([emptyJob()])
  const [howConditionsLimitWork, setHowConditionsLimitWork] = useState('')
  const [doctorRestrictions, setDoctorRestrictions] = useState('')

  const [building, setBuilding] = useState(false)

  const setJob = (index: number, patch: Partial<TdiuJob>) =>
    setJobs((prev) => prev.map((j, i) => (i === index ? { ...j, ...patch } : j)))

  const addJob = () =>
    setJobs((prev) => (prev.length >= MAX_JOBS ? prev : [...prev, emptyJob()]))

  const removeJob = (index: number) =>
    setJobs((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== index)))

  const buildBody = (): TdiuWorksheetInput => ({
    veteran_name: veteranName.trim(),
    last_full_time_date: lastFullTimeDate.trim(),
    highest_earnings: highestEarnings.trim(),
    education: education.trim(),
    training: training.trim(),
    // Drop rows the user left entirely blank; the array is optional server-side.
    jobs: jobs
      .filter((j) => Object.values(j).some((v) => v.trim() !== ''))
      .map((j) => ({
        employer: j.employer.trim(),
        job_title: j.job_title.trim(),
        dates: j.dates.trim(),
        hours_per_week: j.hours_per_week.trim(),
        reason_ended: j.reason_ended.trim(),
      })),
    how_conditions_limit_work: howConditionsLimitWork.trim(),
    doctor_restrictions: doctorRestrictions.trim(),
  })

  const generate = async (e: FormEvent) => {
    e.preventDefault()
    setBuilding(true)
    try {
      const worksheet = await tdiuApi.worksheet(buildBody())
      const state: TdiuPrintState = { worksheet, veteranName: veteranName.trim() }
      sessionStorage.setItem(TDIU_WORKSHEET_KEY, JSON.stringify(state))
      navigate('/tdiu/print')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBuilding(false)
    }
  }

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)

  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6" style={hueStyle(HUE) as CSSProperties}>
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          Individual Unemployability · 38 CFR §4.16
        </p>
        <h1 className="vo-page-title">TDIU workspace</h1>
        <p className="vo-page-sub">
          TDIU can pay at the 100% rate when service-connected conditions keep you from holding steady, gainful work —
          without a 100% schedular rating. This walks you through what it is, what evidence it turns on, and builds a
          work-history worksheet you review, sign, and file. VA decides unemployability — this never does.
        </p>
      </div>

      <FilledFormPanel formId="21-8940" hue={HUE} title="Download the pre-filled 21-8940 (review & sign)" />

      {loading && !screen && <LoadingBlock label="Loading TDIU guidance…" />}
      {screenError && !screen && <ErrorBlock message={screenError} />}

      {screen && (
        <>
          <WhereYouStand screen={screen} />

          <div className="grid gap-5 lg:grid-cols-2">
            <Panel hue={HUE} title="What TDIU is" subtitle="Individual Unemployability, in plain terms">
              <div className="space-y-4 p-5">
                <p className="text-sm leading-relaxed text-txt/90">{screen.what_it_is}</p>
                {screen.how_it_works.length > 0 && (
                  <div>
                    <p className="mb-2 text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
                      How TDIU works
                    </p>
                    <ul className="space-y-2 text-sm text-txt">
                      {screen.how_it_works.map((h, i) => (
                        <li key={i} className="flex gap-2.5">
                          <span
                            aria-hidden
                            className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                            style={{ background: hueSoftVar(HUE), color: ink }}
                          >
                            {i + 1}
                          </span>
                          <span className="leading-relaxed">{h}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </Panel>

            <Panel hue={HUE} title="What TDIU turns on" subtitle="The evidence that carries the most weight">
              <div className="p-5">
                {screen.evidence.length > 0 ? (
                  <ul className="space-y-2.5 text-sm text-txt">
                    {screen.evidence.map((ev, i) => (
                      <li key={i} className="flex gap-2.5">
                        <CheckCircle2 size={16} className="mt-0.5 shrink-0" style={{ color: ink }} />
                        <span className="leading-relaxed">{ev}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-muted">No evidence points to show.</p>
                )}
              </div>
            </Panel>
          </div>

          {screen.forms.length > 0 && (
            <Panel hue={HUE} title="The forms" subtitle="What each one is for and who fills it out">
              <div className="divide-y divide-line">
                {screen.forms.map((f, i) => (
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

          {screen.post_denial_note && (
            <div
              className="vo-card vo-accent flex items-start gap-3.5 p-5"
              style={hueStyle(HUE) as CSSProperties}
            >
              <div
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
                style={{ background: hueSoftVar(HUE), color: ink }}
              >
                <ShieldCheck size={20} />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-txt">Been denied TDIU before?</h2>
                <p className="mt-1 text-sm leading-relaxed text-muted">{screen.post_denial_note}</p>
              </div>
            </div>
          )}

          <Panel
            hue={HUE}
            title="Your work-history worksheet"
            subtitle="Fill in what you can — you review and sign the result"
          >
            <form onSubmit={generate} className="space-y-5 p-5">
              {screen.guidance_prompts.length > 0 && (
                <div
                  className="rounded-control border p-4"
                  style={{ borderColor: `color-mix(in srgb, ${hueVar(HUE)} 30%, var(--border))`, background: hueSoftVar(HUE) }}
                >
                  <p className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: ink }}>
                    <ListChecks size={13} /> What to have on hand
                  </p>
                  <ul className="mt-2 space-y-1.5 text-xs text-muted">
                    {screen.guidance_prompts.map((p, i) => (
                      <li key={i} className="flex gap-2">
                        <span aria-hidden style={{ color: ink }}>•</span>
                        <span className="leading-relaxed">{p}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <label className="text-sm">
                  <span className="vo-label">Your name</span>
                  <input
                    className="vo-input"
                    value={veteranName}
                    onChange={(e) => setVeteranName(e.target.value)}
                    placeholder="As it should appear on the worksheet"
                  />
                </label>
                <label className="text-sm">
                  <span className="vo-label">Date you last worked full-time</span>
                  <input
                    className="vo-input"
                    value={lastFullTimeDate}
                    onChange={(e) => setLastFullTimeDate(e.target.value)}
                    placeholder="e.g. March 2022"
                  />
                </label>
                <label className="text-sm">
                  <span className="vo-label">Highest gross earnings in a year</span>
                  <input
                    className="vo-input"
                    value={highestEarnings}
                    onChange={(e) => setHighestEarnings(e.target.value)}
                    placeholder="e.g. $58,000 in 2019"
                  />
                </label>
                <label className="text-sm">
                  <span className="vo-label">Education</span>
                  <input
                    className="vo-input"
                    value={education}
                    onChange={(e) => setEducation(e.target.value)}
                    placeholder="e.g. High school + 2 years college"
                  />
                </label>
                <label className="text-sm sm:col-span-2">
                  <span className="vo-label">Other training</span>
                  <input
                    className="vo-input"
                    value={training}
                    onChange={(e) => setTraining(e.target.value)}
                    placeholder="e.g. Army wheeled-vehicle mechanic; CDL"
                  />
                </label>
              </div>

              <div>
                <div className="mb-2 flex items-center justify-between">
                  <span className="vo-label mb-0">Employment history (last 5 years)</span>
                  <button
                    type="button"
                    onClick={addJob}
                    disabled={jobs.length >= MAX_JOBS}
                    className="vo-btn-secondary text-xs"
                  >
                    <Plus size={13} /> Add a job
                  </button>
                </div>
                <div className="space-y-3">
                  {jobs.map((job, i) => (
                    <div key={i} className="rounded-control border border-line bg-surface2 p-4">
                      <div className="mb-2.5 flex items-center justify-between">
                        <span className="text-[11px] font-bold uppercase tracking-wide" style={{ color: label }}>
                          Job {i + 1}
                        </span>
                        {jobs.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeJob(i)}
                            className="inline-flex items-center gap-1 text-xs font-medium text-muted hover:text-danger"
                          >
                            <Trash2 size={12} /> Remove
                          </button>
                        )}
                      </div>
                      <div className="grid gap-3 sm:grid-cols-2">
                        <label className="text-sm">
                          <span className="vo-label">Employer</span>
                          <input
                            className="vo-input"
                            value={job.employer}
                            onChange={(e) => setJob(i, { employer: e.target.value })}
                            placeholder="Company / organization"
                          />
                        </label>
                        <label className="text-sm">
                          <span className="vo-label">Job title</span>
                          <input
                            className="vo-input"
                            value={job.job_title}
                            onChange={(e) => setJob(i, { job_title: e.target.value })}
                            placeholder="e.g. Warehouse associate"
                          />
                        </label>
                        <label className="text-sm">
                          <span className="vo-label">Dates worked</span>
                          <input
                            className="vo-input"
                            value={job.dates}
                            onChange={(e) => setJob(i, { dates: e.target.value })}
                            placeholder="e.g. Jun 2018 – Mar 2022"
                          />
                        </label>
                        <label className="text-sm">
                          <span className="vo-label">Hours per week</span>
                          <input
                            className="vo-input"
                            value={job.hours_per_week}
                            onChange={(e) => setJob(i, { hours_per_week: e.target.value })}
                            placeholder="e.g. 40"
                          />
                        </label>
                        <label className="text-sm sm:col-span-2">
                          <span className="vo-label">Why it ended</span>
                          <input
                            className="vo-input"
                            value={job.reason_ended}
                            onChange={(e) => setJob(i, { reason_ended: e.target.value })}
                            placeholder="e.g. Let go after too many missed days from migraines"
                          />
                        </label>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <label className="block text-sm">
                <span className="vo-label">How your conditions limit your ability to work</span>
                <textarea
                  className="vo-input min-h-[120px] resize-y leading-relaxed"
                  value={howConditionsLimitWork}
                  onChange={(e) => setHowConditionsLimitWork(e.target.value)}
                  placeholder={
                    'In your own words: what tasks you can no longer do, the days you miss, the pace you can keep, ' +
                    'why you had to leave or scale back. Be specific and first-hand.'
                  }
                />
              </label>

              <label className="block text-sm">
                <span className="vo-label">Any work restrictions a doctor has given you</span>
                <textarea
                  className="vo-input min-h-[100px] resize-y leading-relaxed"
                  value={doctorRestrictions}
                  onChange={(e) => setDoctorRestrictions(e.target.value)}
                  placeholder="e.g. No lifting over 10 lbs; no more than 4 hours standing; frequent unscheduled breaks."
                />
              </label>

              <button type="submit" disabled={building} className="vo-btn-primary">
                {building ? <Spinner size={16} className="text-white" /> : <Printer size={15} />}
                Generate my worksheet
              </button>
              <p className="flex items-center gap-1.5 text-xs text-faint">
                <Sparkles size={12} style={{ color: ink }} /> Opens a clean, print-ready page you read, sign, and file
                — TDIU is VA's determination, not ours.
              </p>
            </form>
          </Panel>

          <div
            className="rounded-control border-l-2 px-4 py-3 text-xs leading-relaxed"
            style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
          >
            {screen.disclaimer && <p className="italic text-muted">{screen.disclaimer}</p>}
            {screen.vso_note && (
              <p className="mt-2 font-medium text-txt/85">{screen.vso_note}</p>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/** "Where you stand" — encouraging when at/near the threshold, honest-neutral
 * otherwise. Never promissory: it reflects the backend's hedged `why`. */
function WhereYouStand({ screen }: { screen: TdiuScreen }) {
  const atThreshold = screen.at_or_near_threshold
  const ink = hueInk(HUE)
  return (
    <div
      className="vo-card vo-accent flex items-start gap-3.5 p-5"
      style={atThreshold ? (hueStyle(HUE) as CSSProperties) : undefined}
    >
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={
          atThreshold
            ? { background: hueSoftVar(HUE), color: ink }
            : { background: 'var(--surface2)', color: 'var(--muted)' }
        }
      >
        <Briefcase size={20} />
      </div>
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-txt">Where you stand</h2>
          {screen.eligible_schedular && (
            <span
              className="rounded-full px-2 py-0.5 text-micro font-bold uppercase tracking-wide"
              style={{ background: hueSoftVar(HUE), color: ink }}
            >
              You may meet the §4.16(a) schedular threshold
            </span>
          )}
        </div>
        <p className="mt-1 text-sm leading-relaxed text-muted">{screen.why}</p>
      </div>
    </div>
  )
}
