import {
  ArrowRight,
  CheckCircle2,
  Coins,
  ExternalLink,
  Info,
  Landmark,
  ListChecks,
  Scale,
  ShieldCheck,
  UserCog,
} from 'lucide-react'
import { type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorBlock, LoadingBlock, Panel } from '../components/ui'
import { useAsync } from '../hooks/useAsync'
import { concurrentPayApi } from '../lib/api'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { ConcurrentPay, ConcurrentPayProgram } from '../types'

// /concurrent-pay — CRDP (§1414) / CRSC (§1413a), the "Ongoing" journey stage for
// a military retiree who also draws VA compensation. It compares recorded facts
// with basic program criteria and shows a rough CRDP restoration ceiling. DFAS and
// the branch decide; this UI never turns the comparison into a determination.

const HUE: Hue = 'cyan'

// USD, whole dollars — a rough monthly figure, not a precise award amount.
const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

function concurrentPaySteps(data: ConcurrentPay): string[] {
  if (!data.retired_pay_known) {
    return ['Update your profile with whether you receive military retired pay. Add combat-related details only if they are accurate.']
  }
  if (!data.receives_retired_pay) {
    return ['Check the retired-pay answer in your profile. If it is correct, keep this page as a general program reference.']
  }

  const steps = [
    'Compare your Retiree Account Statement with the CRDP information on DFAS, and contact DFAS if an entry is unclear.',
  ]
  if (data.crsc.likely_fits) {
    steps.push('Review DD Form 2860 and the evidence list with your branch CRSC office or a free accredited VSO before applying.')
  } else if (data.crsc.status === 'needs_combat_related') {
    steps.push('If the combat-related answer in your profile is incomplete, correct it and review the CRSC categories with your branch office.')
  } else {
    steps.push('Review the CRSC criteria and application instructions before deciding whether the program is relevant to your records.')
  }
  if (data.must_elect) {
    steps.push('Ask DFAS or your branch office to compare the gross amounts and tax treatment before making an election.')
  }
  return steps
}

export function ConcurrentPay() {
  const { data, error, loading, reload } = useAsync(() => concurrentPayApi.screen())

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)
  const nextSteps = data ? concurrentPaySteps(data) : []

  return (
    <div
      data-section="insight"
      className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          Concurrent pay · CRDP &amp; CRSC · 10 U.S.C. §1414 / §1413a
        </p>
        <h1 className="vo-page-title">Concurrent pay</h1>
        <p className="vo-page-sub">
          Some military retirees waive retired pay when they receive VA disability compensation. CRDP and CRSC may
          restore part or all of that waived pay when their separate requirements are met. This screen compares the
          facts in your profile with basic program criteria; DFAS and your branch make every determination.
        </p>
      </div>

      {loading && !data && (
        <div className="flex min-h-[24rem] items-center justify-center">
          <LoadingBlock label="Reading your concurrent-pay options…" />
        </div>
      )}
      {error && !data && (
        <ErrorBlock
          message={`We couldn't read your concurrent-pay review. ${error} Check your connection, then try again.`}
          onRetry={reload}
        />
      )}
      {!loading && !error && !data && (
        <EmptyState
          hue={HUE}
          icon={<Coins size={20} />}
          title="No concurrent-pay review is available yet"
          description="Add your current rating and military retired-pay details to your profile, then return here to compare CRDP and CRSC."
          action={
            <Link to="/profile" className="vo-btn-primary">
              Update your profile
            </Link>
          }
        />
      )}

      {data && (
        <>
          {error && (
            <ErrorBlock
              message={`We couldn't refresh this review. The information below is the last version we loaded. ${error}`}
              onRetry={reload}
            />
          )}
          {loading && (
            <p className="text-sm text-muted" role="status" aria-live="polite">
              Refreshing your concurrent-pay review…
            </p>
          )}

          {!data.retired_pay_known && <NeedsProfileNote />}

          {data.retired_pay_known && data.receives_retired_pay === false && (
            <div className="vo-card vo-accent flex items-start gap-3.5 p-5">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface2 text-muted">
                <Info size={20} />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-txt">These are for military retirees</h2>
                <p className="mt-1 text-sm leading-relaxed text-muted">
                  Your profile currently says you don't receive military retired pay, which is a basic requirement
                  for both programs. If that entry changes, return here for a new comparison. The cards below still
                  explain each program.
                </p>
              </div>
            </div>
          )}

          {data.estimate && (
            <div
              className="vo-card vo-accent flex items-start gap-3.5 p-5"
              style={hueStyle(HUE) as CSSProperties}
            >
              <div
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full"
                style={{ background: hueSoftVar(HUE), color: ink }}
              >
                <Coins size={22} />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-2">
                  <h2 className="text-sm font-semibold text-txt">Illustrative CRDP ceiling</h2>
                  <span
                    className="rounded-full px-2 py-0.5 text-micro font-bold uppercase tracking-wide"
                    style={{ background: hueSoftVar(HUE), color: ink }}
                  >
                    Rough estimate · DFAS decides
                  </span>
                </div>
                <p className="mt-1 text-2xl font-bold tabular-nums text-txt">
                  Up to about {usd.format(data.estimate.monthly_ceiling)}
                  <span className="text-sm font-medium text-muted"> / month</span>
                </p>
                <p className="mt-1.5 text-sm leading-relaxed text-muted">
                  This upper-bound illustration uses the published single-veteran VA compensation rate for the
                  rating in your profile. Actual CRDP depends on your retired-pay calculation and applicable limits;
                  DFAS determines the amount.
                </p>
              </div>
            </div>
          )}

          <div className="grid gap-5 lg:grid-cols-2">
            <ProgramCard program={data.crdp} icon={<Landmark size={18} />} />
            <ProgramCard program={data.crsc} icon={<ShieldCheck size={18} />} />
          </div>

          {data.must_elect && (
            <div
              className="vo-card vo-accent flex items-start gap-3.5 p-5"
              style={hueStyle(HUE) as CSSProperties}
            >
              <div
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
                style={{ background: hueSoftVar(HUE), color: ink }}
              >
                <Scale size={20} />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-txt">DFAS may ask you to elect one</h2>
                <p className="mt-1 text-sm leading-relaxed text-muted">
                  CRDP and CRSC are not paid at the same time. If DFAS and your branch confirm both, compare the gross
                  amounts, tax treatment, and covered disabilities before an election or open-season change.
                </p>
              </div>
            </div>
          )}

          {nextSteps.length > 0 && (
            <Panel hue={HUE} title="What to verify next" subtitle="Practical checks — not an eligibility decision">
              <div className="p-5">
                <ul className="space-y-2.5 text-sm text-txt">
                  {nextSteps.map((step, i) => (
                    <li key={i} className="flex gap-2.5">
                      <span
                        aria-hidden
                        className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold tabular-nums"
                        style={{ background: hueSoftVar(HUE), color: ink }}
                      >
                        {i + 1}
                      </span>
                      <span className="leading-relaxed">{step}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </Panel>
          )}

          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <a
              href="https://www.dfas.mil/RetiredMilitary/disability/comparison/"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-10 items-center gap-1 rounded-control px-1 text-xs font-semibold text-brand hover:text-brand-hover"
            >
              DFAS: CRDP vs CRSC comparison <ExternalLink size={12} aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
            <a
              href="https://www.dfas.mil/RetiredMilitary/disability/Apply-for-CRSC/"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-10 items-center gap-1 rounded-control px-1 text-xs font-semibold text-brand hover:text-brand-hover"
            >
              DFAS: how to apply for CRSC <ExternalLink size={12} aria-hidden="true" />
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          </div>

          <div
            className="rounded-control border-l-2 px-4 py-3 text-xs leading-relaxed"
            style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
          >
            <p className="italic text-muted">
              DFAS and your branch decide whether CRDP or CRSC applies and what is payable. This screen only compares
              facts in your profile with selected criteria. Any dollar figure is a rough estimate, and Rating Raider
              never applies, elects, or files for you.
            </p>
            <p className="mt-2 font-medium text-txt">
              A free VA-accredited VSO or your branch's CRSC office can help compare the programs and prepare DD Form
              2860. Confirm tax questions with a qualified tax professional.
            </p>
          </div>
        </>
      )}
    </div>
  )
}

/** Prompt shown when the profile doesn't record whether the veteran draws retired
 * pay — the fact that gates both programs. Links to the profile to fill it in. */
function NeedsProfileNote() {
  const ink = hueInk(HUE)
  return (
    <div className="vo-card vo-accent flex items-start gap-3.5 p-5" style={hueStyle(HUE) as CSSProperties}>
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar(HUE), color: ink }}
      >
        <UserCog size={20} />
      </div>
      <div>
        <h2 className="text-sm font-semibold text-txt">Tell us if you're a military retiree</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          These programs generally require military retired pay. Add whether you receive it, and whether a disability
          may be combat-related, so this screen can compare the facts you provide with the basic criteria. The cards
          below still explain each program.
        </p>
        <Link
          to="/profile"
          className="group mt-3 inline-flex min-h-10 items-center gap-1 rounded-control px-1 text-sm font-semibold"
          style={{ color: ink }}
        >
          Update your profile
          <ArrowRight size={14} className="transition-transform duration-200 ease-out group-hover:translate-x-0.5" />
        </Link>
      </div>
    </div>
  )
}

/** One program (CRDP or CRSC): core facts and a hedged profile comparison.
 * Backend `likely_fits` becomes "Worth verifying," never a determination. */
function ProgramCard({ program, icon }: { program: ConcurrentPayProgram; icon: ReactNode }) {
  const ink = hueInk(HUE)
  const label = hueLabel(HUE)
  const fits = program.likely_fits
  const comparison = fits
    ? 'Your profile matches the basic factors this screen checks. DFAS or your branch must verify every requirement.'
    : program.status === 'unknown'
      ? 'Your profile needs more information before this screen can compare the basic factors.'
      : 'Your profile does not currently match every basic factor this screen checks. Review the criteria below and correct your profile if needed.'
  const statusLabel = fits
    ? 'Worth verifying'
    : program.status === 'unknown'
      ? 'Details needed'
      : 'Review criteria'
  const isCrdp = program.program === 'CRDP'
  const facts = isCrdp
    ? {
        who: 'Generally, military retirees entitled to retired pay and VA disability compensation with a combined VA rating of at least 50%. Special rules apply to Chapter 61 and Reserve retirements.',
        how: 'CRDP may reduce part or all of the VA waiver. Applicable retired-pay limits and retirement type affect the calculation.',
        get: 'DFAS generally processes CRDP automatically after receiving VA rating information. Review your Retiree Account Statement and contact DFAS about missing or unclear entries.',
        tax: 'CRDP generally follows the tax treatment of the restored retired pay. Check your DFAS tax documents or ask a qualified tax professional.',
      }
    : {
        who: 'Military retirees with a VA-rated disability their branch determines is combat-related. Retired-pay, waiver, and service rules also apply.',
        how: 'CRSC is a separate payment tied to disabilities the branch approves as combat-related; it does not cover every service-connected disability.',
        get: 'Apply to your branch of service on DD Form 2860 with the records that support the combat-related basis. The branch—not Rating Raider—decides.',
        tax: 'CRSC payments are generally non-taxable. Confirm your own tax situation if you have questions.',
      }

  return (
    <Panel hue={HUE}>
      <div className="space-y-4 p-5">
        <div className="flex flex-col items-start gap-3 sm:flex-row sm:justify-between">
          <div className="flex min-w-0 items-start gap-2.5">
            <span
              aria-hidden
              className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
              style={{ background: hueSoftVar(HUE), color: ink }}
            >
              {icon}
            </span>
            <div className="min-w-0">
              <h2 className="text-heading text-txt">
                <span style={{ color: ink }}>{program.program}</span> — {program.full_name}
              </h2>
              <p className="mt-0.5 text-xs text-muted">{program.statute}</p>
            </div>
          </div>
          <span
            className="inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-1 text-micro font-bold uppercase tracking-wide"
            style={
              fits
                ? { borderColor: hueVar(HUE), background: hueSoftVar(HUE), color: ink }
                : { borderColor: 'var(--border)', background: 'var(--surface-2)', color: 'var(--muted)' }
            }
          >
            {fits ? <CheckCircle2 size={11} aria-hidden="true" /> : <Info size={11} aria-hidden="true" />}
            {statusLabel}
          </span>
        </div>

        <p className="text-sm leading-relaxed text-txt">{comparison}</p>

        <dl className="space-y-3 border-t border-line pt-4 text-sm">
          <Fact term="Who it's for">{facts.who}</Fact>
          <Fact term="How it works">{facts.how}</Fact>
          <Fact term={program.requires_application ? 'How to apply' : 'How to get it'}>
            {facts.get}
          </Fact>
        </dl>

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <span
            className="inline-flex max-w-full items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
            style={{ background: 'var(--surface-2)', color: 'var(--muted)' }}
          >
            {program.taxable ? <Coins size={12} aria-hidden="true" /> : <CheckCircle2 size={12} style={{ color: ink }} aria-hidden="true" />}
            {facts.tax}
          </span>
          {program.requires_application ? (
            program.form && (
              <span
                className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold"
                style={{ background: hueSoftVar(HUE), color: ink }}
              >
                <ListChecks size={12} aria-hidden="true" /> {program.form}
              </span>
            )
          ) : (
            <span
              className="inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-medium"
              style={{ color: label }}
            >
              <CheckCircle2 size={12} aria-hidden="true" /> CRDP is generally automatic
            </span>
          )}
        </div>
      </div>
    </Panel>
  )
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-[11px] font-bold uppercase tracking-wide" style={{ color: hueLabel(HUE) }}>
        {term}
      </dt>
      <dd className="mt-0.5 leading-relaxed text-txt">{children}</dd>
    </div>
  )
}
