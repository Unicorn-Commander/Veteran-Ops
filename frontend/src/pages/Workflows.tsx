import { type CSSProperties, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  ChevronDown,
  Compass,
  ExternalLink,
  Quote,
  ShieldCheck,
} from 'lucide-react'
import { AppealLaneChooser } from '../components/AppealLaneChooser'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar } from '../lib/hues'
import {
  LANE_NOTE,
  WORKFLOW_TIERS,
  workflowsByTier,
  type TierMeta,
  type Workflow,
  type WorkflowStep,
} from '../lib/workflows'

// /workflows — the "defined workflows" hub. A veteran who has never touched
// Claude Code picks the situation that sounds like them and gets walked, in
// order, to the built feature(s) that serve it. This surface WIRES existing
// pages into guided flows; it builds no engines of its own.
//
// Legal lane: every flow organizes and educates, then routes to VA.gov self-file
// or a free accredited VSO. Nothing here files, diagnoses, represents, or
// predicts a VA decision. The sensitive flows carry a visible "your call" note.

export function Workflows() {
  // Accordion: one flow open at a time keeps the hub scannable.
  const [openId, setOpenId] = useState<string | null>(null)

  return (
    <div data-section="home" className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Start here</p>
        <h1 className="vo-page-title">Guided workflows</h1>
        <p className="vo-page-sub">
          Pick the situation that sounds like you. Each guide puts the related tools in a useful order — from
          documenting an Intent to File through reviewing a decision. Rating Raider keeps the work organized; you
          review, decide, and file every step, and a free VSO can help.
        </p>
      </div>

      <LegalLaneNote />

      {WORKFLOW_TIERS.map((meta) => (
        <TierSection key={meta.tier} meta={meta} openId={openId} onToggle={setOpenId} />
      ))}

      {/* Cross-link to the cradle-to-grave map for veterans who’d rather see the
          whole path than pick one situation. */}
      <Link
        to="/journey"
        className="group flex items-center gap-3 rounded-2xl border border-line bg-surface/50 px-5 py-4 transition-colors hover:border-line2"
      >
        <span
          aria-hidden
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar('violet'), color: hueInk('violet') }}
        >
          <Compass size={17} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-txt">Not sure which fits? See your whole VA journey</span>
          <span className="block text-xs text-muted">The full path, cradle to grave — we’ll point to where you are.</span>
        </span>
        <ArrowRight size={16} className="shrink-0 text-faint transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden="true" />
      </Link>

      <p className="px-1 text-xs leading-relaxed text-faint">
        These workflows organize and prepare your claim — they are not legal advice or a prediction of any VA
        decision. You review, decide, and file everything yourself, and a VA-accredited Veterans Service Officer
        (VSO) can help at no cost.
      </p>
    </div>
  )
}

function TierSection({
  meta,
  openId,
  onToggle,
}: {
  meta: TierMeta
  openId: string | null
  onToggle: (id: string | null) => void
}) {
  const workflows = workflowsByTier(meta.tier)
  const headingId = `workflow-tier-${meta.tier}`
  return (
    <section className="space-y-3" aria-labelledby={headingId}>
      <div className="px-1">
        <h2 id={headingId} className="text-heading text-txt">{meta.label}</h2>
        <p className="mt-0.5 text-sm text-muted">{meta.blurb}</p>
      </div>
      <div className="space-y-3">
        {workflows.map((w) => (
          <WorkflowCard key={w.id} workflow={w} open={openId === w.id} onToggle={() => onToggle(openId === w.id ? null : w.id)} />
        ))}
      </div>
    </section>
  )
}

function WorkflowCard({ workflow, open, onToggle }: { workflow: Workflow; open: boolean; onToggle: () => void }) {
  const { hue, icon: Icon, title, triggers, whatItDoes, lane, steps, refs, laneChooser, comingSoon } = workflow
  const ink = hueInk(hue)
  const panelId = `wf-${workflow.id}`

  return (
    <div
      className="vo-card vo-accent overflow-hidden p-0"
      style={{
        ...(hueStyle(hue) as CSSProperties),
        ...(open ? { borderColor: hueVar(hue), boxShadow: `0 0 0 1px ${hueVar(hue)}` } : {}),
      }}
    >
      {/* Header — always visible: icon, title, the veteran's trigger, what it
          does, and the Start toggle. The whole header is the control. */}
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`${open ? 'Hide' : 'Open'} ${title} workflow`}
        className="flex w-full items-start gap-3.5 p-4 text-left focus-visible:ring-inset sm:p-5"
      >
        <span
          aria-hidden
          className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar(hue), color: ink }}
        >
          <Icon size={19} />
        </span>

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-base font-semibold text-txt">{title}</span>
            {lane === 'red' && (
              <span className="vo-chip border-line text-micro text-muted">Your call</span>
            )}
            {comingSoon && <span className="vo-chip border-line text-micro text-muted">Coming soon</span>}
          </span>

          {/* The trigger — the veteran's own words. */}
          <span className="mt-1.5 flex items-start gap-1.5">
            <Quote size={12} className="mt-1 shrink-0 text-faint" aria-hidden />
            <span className="text-sm italic leading-relaxed text-muted">“{triggers[0]}”</span>
          </span>

          <span className="mt-1.5 block text-sm leading-relaxed text-txt">{whatItDoes}</span>
        </span>

        <span
          className="mt-0.5 flex shrink-0 items-center gap-1 text-sm font-semibold"
          style={{ color: ink }}
        >
          <span className="hidden sm:inline">{open ? 'Hide' : 'Start'}</span>
          <ChevronDown
            size={17}
            className="transition-transform duration-200"
            style={{ transform: open ? 'rotate(180deg)' : undefined }}
            aria-hidden
          />
        </span>
      </button>

      {/* Expanded flow: ordered steps as a checklist of links, then refs, then
          (for workflow 3) the guided appeal-lane chooser. */}
      {open && (
        <div id={panelId} role="region" aria-label={`${title} steps`} className="space-y-4 border-t border-line px-4 pb-5 pt-4 sm:px-5">
          {LANE_NOTE[lane] && (
            <p className="flex items-start gap-1.5 text-xs leading-relaxed text-faint">
              <ShieldCheck size={13} className="mt-0.5 shrink-0" style={{ color: hueLabel(hue) }} />
              {LANE_NOTE[lane]}
            </p>
          )}

          {/* The second trigger phrase, if any, so more veterans recognize themselves. */}
          {triggers.length > 1 && (
            <p className="text-xs italic leading-relaxed text-muted">Also sounds like: “{triggers[1]}”</p>
          )}

          <ol className="space-y-2.5">
            {steps.map((step, i) => (
              <StepRow key={step.label} step={step} index={i} primary={i === 0} hue={workflow.hue} />
            ))}
          </ol>

          {laneChooser && <AppealLaneChooser hue={hue} />}

          {refs && refs.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 border-t border-line pt-3">
              <span className="text-micro font-semibold uppercase tracking-wide text-faint">Forms &amp; regs</span>
              {refs.map((r) => (
                <span key={r} className="vo-chip border-line text-micro text-muted">
                  {r}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** One ordered step — a numbered row that links an existing route (first step is
 * the primary CTA), or an honest external pointer when nothing is built. */
function StepRow({
  step,
  index,
  primary,
  hue,
}: {
  step: WorkflowStep
  index: number
  primary: boolean
  hue: Workflow['hue']
}) {
  const ink = hueInk(hue)

  const body = (
    <>
      <span
        aria-hidden
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums"
        style={{ background: hueSoftVar(hue), color: ink }}
      >
        {index + 1}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-txt">{step.label}</span>
        <span className="block text-xs leading-relaxed text-muted">{step.detail}</span>
      </span>
      {step.route ? (
        <ArrowRight
          size={15}
          className="mt-0.5 shrink-0 transition-transform duration-200 ease-out group-hover:translate-x-0.5"
          style={{ color: primary ? ink : 'var(--muted)' }}
          aria-hidden
        />
      ) : (
        <ExternalLink size={14} className="mt-0.5 shrink-0 text-muted" aria-hidden />
      )}
    </>
  )

  const className =
    'group flex items-start gap-3 rounded-control border p-3 transition-colors ' +
    (primary ? '' : 'hover:border-line2')

  const style: CSSProperties = primary
    ? { borderColor: hueVar(hue), background: hueSoftVar(hue) }
    : { borderColor: 'var(--border)', background: 'var(--surface-2)' }

  if (step.route) {
    return (
      <li>
        <Link to={step.route} className={className} style={style}>
          {body}
        </Link>
      </li>
    )
  }
  // No built route — honest off-app pointer (never a dead internal link).
  return (
    <li>
      <a href={step.externalHref} target="_blank" rel="noreferrer" className={className} style={style}>
        {body}
        <span className="sr-only"> (opens in a new tab)</span>
      </a>
    </li>
  )
}

/** Compact, always-visible legal-lane note for the whole hub — mirrors the
 * Appeals page's banner voice (organize, don't file; VSOs are free). */
function LegalLaneNote() {
  return (
    <div className="vo-card vo-accent flex items-start gap-3.5 p-5" style={hueStyle('violet') as CSSProperties}>
      <span
        aria-hidden
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar('violet'), color: hueInk('violet') }}
      >
        <ShieldCheck size={20} />
      </span>
      <div>
        <h2 className="text-sm font-semibold text-txt">Prepared for you — never filed for you</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          Rating Raider is educational self-help software, not a VA-accredited representative. Every workflow
          organizes your own evidence and explains what the rules say — it never diagnoses, predicts a rating, or
          files anything for you. You file at VA.gov, or a free accredited VSO (VFW, DAV, American Legion, your
          state/county office) files with you at no cost.
        </p>
        <a
          href="https://www.va.gov/get-help-from-accredited-representative/"
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex min-h-10 items-center gap-1 rounded-control px-2 text-sm font-semibold text-brand hover:bg-surface2 hover:text-brand-hover"
        >
          Find a VSO near you <ExternalLink size={13} aria-hidden="true" />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </div>
    </div>
  )
}
