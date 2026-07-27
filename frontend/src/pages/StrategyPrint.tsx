import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ErrorBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { formatDate } from '../lib/format'
import { GAME_PLAN_KEY } from './Strategy'
import type { GamePlanOut, GamePlanPathway } from '../types'

// Standalone print view for the Battle Plan. Same pattern as Form526Print.tsx /
// BuddyPrint.tsx: no Shell chrome, one print button, a refined-letterhead
// document. The assembled plan is handed over via sessionStorage (GAME_PLAN_KEY)
// by pages/Strategy.tsx. Educational only — every estimated combined rating is
// printed WITH its basis label (§4.25 math on the veteran's own targets, not a
// prediction), and the disclaimer + VSO referral close the document. Rating
// Raider never files, represents, or renders a medical opinion.

const IMPACT_PRINT_LABELS: Record<string, string> = {
  high: 'High impact',
  medium: 'Medium',
  low: 'Low',
}

function readPlan(): GamePlanOut | null {
  try {
    const raw = sessionStorage.getItem(GAME_PLAN_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as GamePlanOut
    if (!parsed?.snapshot) return null
    return parsed
  } catch {
    return null
  }
}

function Section({ children }: { children: ReactNode }) {
  return <section className="mt-8">{children}</section>
}

function SectionLabel({ n, title }: { n: number; title: string }) {
  return (
    <p className="rr-rule-label text-muted">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface2 text-[10px] text-muted">
        {n}
      </span>
      {title}
    </p>
  )
}

function SnapshotLine({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <p className="rr-sans text-[11px] uppercase tracking-wide text-faint">{label}</p>
      <p className="mt-0.5 text-sm text-txt">{value}</p>
    </div>
  )
}

/** Estimated combined rating — always printed WITH its basis. When null, the
 * basis stands in for the number; a number is never printed alone. */
function EstimateLine({ pathway: p }: { pathway: GamePlanPathway }) {
  return (
    <div className="mt-2 border-l-2 border-line2 pl-3">
      {p.estimated_combined !== null && (
        <p className="text-sm text-txt">
          <strong>Estimated combined rating: {p.estimated_combined}%</strong>{' '}
          <span className="rr-sans text-xs uppercase tracking-wide text-faint">— estimate only</span>
        </p>
      )}
      <p className="rr-sans mt-0.5 text-xs italic leading-relaxed text-muted">{p.estimated_combined_basis}</p>
    </div>
  )
}

function PathwayBlock({ pathway: p, i }: { pathway: GamePlanPathway; i: number }) {
  return (
    <div className="mt-5 border-t border-line pt-4 first:mt-3 first:border-t-0 first:pt-0">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[17px] font-semibold text-txt">
          {i + 1}. {p.title}
        </h3>
        {p.recommended && (
          <span className="rr-sans text-xs font-semibold uppercase tracking-wide text-muted">Recommended</span>
        )}
      </div>
      <p className="rr-sans mt-1 text-sm text-muted">{p.summary}</p>

      <EstimateLine pathway={p} />

      {p.steps.length > 0 && (
        <ol className="rr-sans mt-3 list-decimal space-y-1 pl-5 text-sm text-txt">
          {p.steps.map((step, si) => (
            <li key={si} className="leading-relaxed">
              {step}
            </li>
          ))}
        </ol>
      )}

      {p.included_conditions.length > 0 && (
        <p className="rr-sans mt-2 text-sm text-txt">
          <strong>Conditions in this path:</strong> {p.included_conditions.join(', ')}
        </p>
      )}

      {p.tradeoff && (
        <p className="rr-sans mt-1.5 text-sm text-muted">
          <strong>Trade-off:</strong> {p.tradeoff}
        </p>
      )}
    </div>
  )
}

function GamePlanBody({ plan }: { plan: GamePlanOut }) {
  const s = plan.snapshot
  const itf = s.active_itf
  return (
    <div className="rr-doc">
      <PrintDocStyles />
      <Letterhead />
      <h1 className="text-[26px] font-bold leading-tight tracking-tight text-txt">Your VA Claim Plan</h1>
      <p className="rr-sans mt-1.5 text-sm text-muted">
        Educational strategy assembled from your own records — options to consider, not a prediction of any outcome.
        Any estimated combined rating is simple §4.25 math on the target ratings you entered. You decide your path, and a
        free VSO can file it with you. Veteran-Ops never files, represents you, or renders a medical opinion.
      </p>

      <Section>
        <SectionLabel n={1} title="Snapshot" />
        <div className="rr-sans mt-3 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
          <SnapshotLine label="Current combined" value={s.current_combined === null ? 'Not set' : `${s.current_combined}%`} />
          <SnapshotLine label="Conditions" value={s.conditions_total} />
          <SnapshotLine label="Ready to file" value={s.ready_count} />
          <SnapshotLine label="Need evidence" value={s.needs_evidence_count} />
          <SnapshotLine label="Denied" value={s.denied_count} />
        </div>
        {itf ? (
          <p className="rr-sans mt-3 text-sm text-txt">
            <strong>Active Intent to File{itf.type ? ` (${itf.type})` : ''}:</strong>{' '}
            {itf.deadline ? `protects your effective date through ${formatDate(itf.deadline)}` : 'on record'}
            {typeof itf.days_remaining === 'number' ? ` (${itf.days_remaining} days remaining)` : ''}.
          </p>
        ) : (
          <p className="rr-sans mt-3 text-sm text-muted">
            No active Intent to File on record. Filing one locks in your effective date (and back pay) for a year.
          </p>
        )}
      </Section>

      <Section>
        <SectionLabel n={2} title="Pathways to consider" />
        {plan.pathways.length > 0 ? (
          plan.pathways.map((p, i) => <PathwayBlock key={p.key} pathway={p} i={i} />)
        ) : (
          <p className="rr-sans mt-3 text-sm text-muted">No pathways to suggest yet.</p>
        )}
      </Section>

      <Section>
        <SectionLabel n={3} title="Priority actions" />
        {plan.priority_actions.length > 0 ? (
          <ol className="rr-sans mt-3 space-y-3 text-sm">
            {plan.priority_actions.map((a, i) => (
              <li key={i} className="border-b border-line pb-3 last:border-b-0">
                <p className="text-txt">
                  <strong>
                    {i + 1}. {a.title}
                  </strong>{' '}
                  <span className="text-xs uppercase tracking-wide text-faint">
                    — {IMPACT_PRINT_LABELS[a.impact] ?? a.impact}
                  </span>
                </p>
                <p className="mt-0.5 text-muted">{a.why}</p>
                {a.condition_name && <p className="mt-0.5 text-xs text-faint">Related to {a.condition_name}</p>}
              </li>
            ))}
          </ol>
        ) : (
          <p className="rr-sans mt-3 text-sm text-muted">No outstanding actions right now.</p>
        )}
      </Section>

      <Section>
        <SectionLabel n={4} title="Get free help" />
        <p className="rr-sans mt-3 text-sm text-txt">{plan.vso_referral}</p>
        <p className="rr-sans mt-2 text-xs italic leading-relaxed text-muted">{plan.source_note}</p>
      </Section>

      <DisclaimerFooterBlock text={plan.disclaimer} />
    </div>
  )
}

export function StrategyPrint() {
  const plan = readPlan()
  if (!plan) {
    return (
      <div data-section="insight">
        <PrintShell backTo="/strategy" backLabel="Back to Claim Plan">
          <div className="mx-auto max-w-xl py-10">
            <ErrorBlock message="No Claim Plan to show yet — open your Claim Plan and review it first." />
            <p className="mt-4 text-center text-sm text-muted">
              <Link to="/strategy" className="font-semibold text-brand hover:text-brand-hover">
                Open your Claim Plan
              </Link>
            </p>
          </div>
        </PrintShell>
      </div>
    )
  }
  return (
    <div data-section="insight">
      <PrintShell backTo="/strategy" backLabel="Back to Claim Plan">
        <GamePlanBody plan={plan} />
      </PrintShell>
    </div>
  )
}
