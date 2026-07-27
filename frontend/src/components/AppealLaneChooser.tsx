import { type CSSProperties, useId, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  FileSearch,
  Gavel,
  Info,
  ScanText,
  Scale,
} from 'lucide-react'
import { hueInk, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'

/**
 * AppealLaneChooser — the one guided decision-tree the app otherwise lacks
 * (defined-workflow #3). After a denial or a lowballed rating, veterans ask the
 * same thing over and over: "do I appeal or start over, and which way?" This walks
 * two questions — "do you have new evidence?" and "was there a VA error?" — and
 * narrows which lane to compare first: Supplemental Claim (20-0995), Higher-Level
 * Review (20-0996), or Board Appeal (10182). All three stay visible; the CHOICE is
 * the veteran's. It hands off to the existing /appeals page to draft the response.
 *
 * Legal lane (hard): present options, deadlines, and trade-offs — never predict an
 * outcome, never say "you should appeal," and never promise a result. A free
 * accredited VSO and the official VA options stay visible throughout.
 */

type Answer = 'yes' | 'no' | null
type LaneId = 'supplemental' | 'hlr' | 'board'

interface LaneDef {
  id: LaneId
  title: string
  form: string
  when: string
  detail: string
}

const LANES: LaneDef[] = [
  {
    id: 'supplemental',
    title: 'Supplemental Claim',
    form: 'VA Form 20-0995',
    when: 'You have NEW and relevant evidence',
    detail:
      'This lane is designed for new and relevant evidence, or for review based on a change in law. You can submit evidence or identify records for VA to gather.',
  },
  {
    id: 'hlr',
    title: 'Higher-Level Review',
    form: 'VA Form 20-0996',
    when: 'No new evidence; you want a possible error reviewed',
    detail:
      'A higher-level reviewer looks at the existing record for an error or difference of opinion. You may request an optional informal conference, but you cannot add new evidence.',
  },
  {
    id: 'board',
    title: 'Board Appeal',
    form: 'VA Form 10182',
    when: 'You’d rather a Veterans Law Judge decide',
    detail:
      'A Veterans Law Judge reviews the case. Direct Review uses the existing record; Evidence Submission and Hearing have specific windows for new evidence. Waits vary by docket.',
  },
]

/** Derive the lane to compare first from the two answers. Board is a preference lane
 * (want a judge), not derived — so "both no" returns null and we nudge to a VSO. */
function suggestLane(newEvidence: Answer, vaError: Answer): LaneId | null {
  if (newEvidence === 'yes') return 'supplemental'
  if (newEvidence === 'no' && vaError === 'yes') return 'hlr'
  return null
}

export function AppealLaneChooser({ hue = 'rose' }: { hue?: Hue }) {
  const [newEvidence, setNewEvidence] = useState<Answer>(null)
  const [vaError, setVaError] = useState<Answer>(null)

  const answered = newEvidence !== null && vaError !== null
  const suggested = suggestLane(newEvidence, vaError)
  // Both answered "no" — nothing derived points cleanly at Supplemental or HLR.
  const bothNo = newEvidence === 'no' && vaError === 'no'

  const ink = hueInk(hue)

  return (
    <div
      className="vo-card vo-accent space-y-5 p-5 sm:p-6"
      style={hueStyle(hue) as CSSProperties}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar(hue), color: ink }}
        >
          <Scale size={19} />
        </span>
        <div>
          <h3 className="text-heading text-txt">Compare decision-review lanes</h3>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            Two quick questions can narrow the first lane to review. All three stay visible because deadlines,
            evidence rules, and your goals can change the choice.
          </p>
        </div>
      </div>

      {/* The two questions. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Question
          n={1}
          prompt="Do you have new evidence?"
          hint="Something the VA hasn’t seen — a nexus letter, new records, a buddy statement."
          value={newEvidence}
          onChange={setNewEvidence}
          hue={hue}
        />
        <Question
          n={2}
          prompt="Do you think the VA made an error?"
          hint="You want a review of how VA applied the law or facts to the existing record."
          value={vaError}
          onChange={setVaError}
          hue={hue}
        />
      </div>

      {/* Derived nudge once both are answered. */}
      {answered && (
        <div
          className="flex items-start gap-2.5 rounded-control border px-4 py-3 text-sm"
          style={{ borderColor: `color-mix(in srgb, ${hueVar(hue)} 35%, transparent)`, background: hueSoftVar(hue) }}
          role="status"
          aria-live="polite"
        >
          <Info size={15} className="mt-0.5 shrink-0" style={{ color: ink }} aria-hidden="true" />
          {suggested ? (
            <p className="leading-relaxed text-txt">
              Based on these two answers, start by reviewing the{' '}
              <span className="font-semibold">{LANES.find((l) => l.id === suggested)?.title}</span>. It is
              highlighted below, but this is not a recommendation or eligibility decision.
            </p>
          ) : bothNo ? (
            <p className="leading-relaxed text-txt">
              With no new evidence and no error you want reviewed, these two answers do not identify a starting
              lane. Read the Board options and ask a free accredited VSO to review the decision letter with you.
            </p>
          ) : (
            <p className="leading-relaxed text-txt">Compare all three lanes below before you choose.</p>
          )}
        </div>
      )}

      {/* The three lanes — always all visible; suggested one is highlighted. */}
      <div className="grid gap-3 sm:grid-cols-3">
        {LANES.map((l) => {
          const isSuggested = answered && suggested === l.id
          return (
            <div
              key={l.id}
              className="flex flex-col rounded-control border p-4"
              style={{
                borderColor: isSuggested ? hueVar(hue) : 'var(--border)',
                background: isSuggested ? hueSoftVar(hue) : 'var(--surface-2)',
                boxShadow: isSuggested ? `inset 0 0 0 1px ${hueVar(hue)}` : undefined,
              }}
            >
              <div className="flex items-center gap-2">
                <Gavel size={15} style={{ color: isSuggested ? ink : 'var(--muted)' }} aria-hidden="true" />
                <span className="text-sm font-semibold text-txt">{l.title}</span>
              </div>
              {isSuggested && (
                <span
                  className="mt-2 inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-micro font-semibold uppercase tracking-wide"
                  style={{ border: `1px solid ${hueVar(hue)}`, background: hueSoftVar(hue), color: ink }}
                >
                  <CheckCircle2 size={11} aria-hidden="true" /> Start here to compare
                </span>
              )}
              <p className="mt-2 text-xs font-medium" style={{ color: ink }}>
                {l.when}
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">{l.detail}</p>
              <p className="mt-auto pt-2.5 text-micro font-semibold uppercase tracking-wide text-faint">{l.form}</p>
            </div>
          )
        })}
      </div>

      {/* The spine of the whole flow: the 1-year clock + lane-switching. */}
      <div className="flex items-start gap-2.5 rounded-control border border-warn/35 bg-h-amber-soft px-4 py-3 text-sm">
        <AlertTriangle size={15} className="mt-0.5 shrink-0 text-warn" aria-hidden="true" />
        <p className="leading-relaxed text-txt">
          <span className="font-semibold">For most VA benefits, the date on your decision letter starts an important
          one-year window.</span>{' '}
          Higher-Level Review and Board Appeal generally use that deadline. A Supplemental Claim can be filed later,
          but filing within one year may help maintain a potential effective date. Some deadlines are shorter; use
          your letter and VA.gov, or confirm with an accredited representative.
        </p>
      </div>

      {/* Hand off to the existing draft surface + decoder. */}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Link to="/appeals" className="vo-btn-primary group text-sm">
          Prepare a response draft
          <ArrowRight size={15} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" aria-hidden="true" />
        </Link>
        <Link to="/decode" className="vo-btn-secondary text-sm">
          <ScanText size={15} aria-hidden="true" />
          Decode the letter first
        </Link>
        <a
          href="https://www.va.gov/get-help-from-accredited-representative/"
          target="_blank"
          rel="noreferrer"
          className="vo-btn-ghost text-sm text-muted hover:text-txt"
        >
          <FileSearch size={15} aria-hidden="true" />
          Find a free VSO
          <ExternalLink size={12} aria-hidden="true" />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
        <a
          href="https://www.va.gov/decision-reviews/"
          target="_blank"
          rel="noreferrer"
          className="vo-btn-ghost text-sm text-muted hover:text-txt"
        >
          Official VA options
          <ExternalLink size={12} aria-hidden="true" />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </div>

      <p className="text-xs leading-relaxed text-faint">
        This is educational self-help, not legal advice or a prediction of any VA decision. No lane or result is
        promised. The choice of whether and how to request review is yours, and a free accredited VSO can help you
        compare the options and prepare a filing.
      </p>
    </div>
  )
}

/** One yes/no question with a hint and a pressed-state pill pair. */
function Question({
  n,
  prompt,
  hint,
  value,
  onChange,
  hue,
}: {
  n: number
  prompt: string
  hint: string
  value: Answer
  onChange: (v: Answer) => void
  hue: Hue
}) {
  const hintId = useId()
  return (
    <fieldset className="min-w-0 rounded-control border border-line bg-surface2 p-4" aria-describedby={hintId}>
      <legend className="text-sm font-semibold text-txt">
        <span className="text-faint">{n}.</span> {prompt}
      </legend>
      <p id={hintId} className="mt-1 text-xs leading-relaxed text-muted">{hint}</p>
      <div className="mt-3 flex gap-2">
        {(['yes', 'no'] as const).map((opt) => {
          const active = value === opt
          return (
            <button
              key={opt}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(active ? null : opt)}
              className="vo-chip min-h-10 flex-1 justify-center capitalize transition-colors duration-150"
              style={
                active
                  ? ({
                      borderColor: hueVar(hue),
                      background: hueSoftVar(hue),
                      color: hueInk(hue),
                    } as CSSProperties)
                  : undefined
              }
            >
              {opt}
            </button>
          )
        })}
      </div>
    </fieldset>
  )
}
