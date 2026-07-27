import {
  ExternalLink,
  FileText,
  Flower2,
  GraduationCap,
  HeartHandshake,
  Info,
  Users,
} from 'lucide-react'
import { type CSSProperties, type ReactNode } from 'react'
import { Panel } from '../components/ui'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'

// /survivors — the "Survivors" journey stage. A PLAIN EXPLAINER of the benefits a
// veteran's family may be eligible for after they pass: DIC, Survivors Pension,
// burial benefits, and Chapter 35 education. This is a different set of forms and
// eligibility rules from a veteran's own claim. Legal lane: inform and prepare,
// never "you qualify" — the VA decides survivor eligibility, and a VSO helps a
// survivor file at no cost. Static content (no estimate, no determination); mirrors
// the hue-driven Panel layout of the other guide pages.

const HUE: Hue = 'pink'

interface SurvivorBenefit {
  name: string
  icon: ReactNode
  what: string
  form: string
  formTitle: string
  href: string
}

const BENEFITS: SurvivorBenefit[] = [
  {
    name: 'DIC — Dependency and Indemnity Compensation',
    icon: <HeartHandshake size={18} />,
    what:
      'A tax-free payment VA may provide to an eligible spouse, child, or parent after a service member dies in the ' +
      'line of duty, a veteran dies from a service-related condition, or certain total-disability timing rules are met.',
    form: 'VA Form 21P-534EZ',
    formTitle: 'Application for DIC, Survivors Pension, and/or Accrued Benefits',
    href: 'https://www.va.gov/find-forms/about-form-21p-534ez/',
  },
  {
    name: 'Survivors Pension',
    icon: <Users size={18} />,
    what:
      'A tax-free, needs-based benefit for some surviving spouses or unmarried dependent children of deceased ' +
      'wartime veterans, subject to service, income, net-worth, and relationship rules.',
    form: 'VA Form 21P-534EZ',
    formTitle: 'Application for DIC, Survivors Pension, and/or Accrued Benefits',
    href: 'https://www.va.gov/pension/survivors-pension/',
  },
  {
    name: 'Burial benefits',
    icon: <Flower2 size={18} />,
    what:
      'For eligible cases, support may include a burial or transportation allowance, a plot or interment allowance, ' +
      'or burial in a VA national cemetery. Some allowances have filing deadlines.',
    form: 'VA Form 21P-530EZ',
    formTitle: 'Application for Burial Benefits',
    href: 'https://www.va.gov/burials-memorials/veterans-burial-allowance/',
  },
  {
    name: 'Chapter 35 — survivors’ & dependents’ education (DEA)',
    icon: <GraduationCap size={18} />,
    what:
      'Education and training benefits for the spouse and children of a veteran who died from — or is permanently ' +
      'and totally disabled by — a service-connected condition. (The Fry Scholarship may apply for service deaths ' +
      'after Sept 10, 2001.)',
    form: 'VA Form 22-5490',
    formTitle: 'Dependents’ Application for VA Education Benefits',
    href: 'https://www.va.gov/education/survivor-dependent-benefits/',
  },
]

export function Survivors() {
  const ink = hueInk(HUE)
  const label = hueLabel(HUE)

  return (
    <div
      data-section="guide"
      className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          Survivors · DIC &amp; burial benefits
        </p>
        <h1 className="vo-page-title">Survivors benefits</h1>
        <p className="vo-page-sub">
          After a veteran or service member dies, family members may have separate options for DIC, survivors
          pension, burial support, or education. Each program has its own relationship, service, timing, and evidence
          rules. This page explains what to review and how to prepare; VA makes every eligibility decision.
        </p>
      </div>

      {/* Gentle framing — this is for family, and help is free. */}
      <div className="vo-card vo-accent flex items-start gap-3.5 p-5" style={hueStyle(HUE) as CSSProperties}>
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
          style={{ background: hueSoftVar(HUE), color: ink }}
        >
          <HeartHandshake size={20} />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-txt">For the people a veteran leaves behind</h2>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            You don’t have to sort this out alone or on a deadline you didn’t know about. A free VA-accredited
            Veterans Service Officer (VFW, DAV, The American Legion, or your state/county veterans office) can walk a
            survivor review these programs and prepare a filing at no cost. Rating Raider helps you understand and
            organize — it never files anything or decides eligibility.
          </p>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel hue={HUE} title="Who VA may recognize" subtitle="DIC examples — each program has its own rules">
          <div className="space-y-3 p-5 text-sm leading-relaxed text-txt">
            <p>
              <span className="font-semibold text-txt">A surviving spouse</span> — VA reviews the marriage length,
              timing, living situation, and any remarriage. A remarriage at age 55 or older may preserve DIC under
              date-specific rules.
            </p>
            <p>
              <span className="font-semibold text-txt">Children</span> — age, school attendance, marital status, and
              a disability that began before age 18 can matter, depending on the program.
            </p>
            <p>
              <span className="font-semibold text-txt">Dependent parents</span> — in some cases, a surviving parent
              whose income is below the limit (parents’ DIC is income-based).
            </p>
            <p className="text-xs text-muted">
              Exact eligibility is the VA’s to decide, and the rules have nuances — this is the general picture, not
              a determination.
            </p>
          </div>
        </Panel>

        <Panel hue={HUE} title="When DIC may apply" subtitle="Two main paths to eligibility">
          <div className="space-y-4 p-5 text-sm leading-relaxed text-txt">
            <div className="flex gap-2.5">
              <span
                aria-hidden
                className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold tabular-nums"
                style={{ background: hueSoftVar(HUE), color: ink }}
              >
                1
              </span>
              <p>
                <span className="font-semibold text-txt">Death from a service-connected condition</span> — the
                veteran died in service, or a service-connected disability caused or contributed to their death.
              </p>
            </div>
            <div className="flex gap-2.5">
              <span
                aria-hidden
                className="mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full text-[10px] font-bold tabular-nums"
                style={{ background: hueSoftVar(HUE), color: ink }}
              >
                2
              </span>
              <p>
                <span className="font-semibold text-txt">Totally disabled for the required period</span> — the
                veteran was rated totally disabled (100% or TDIU) from a service-connected condition for a set time
                before death — generally at least 10 years, or since discharge and at least 5 years, or at least 1
                year for a former prisoner of war.
              </p>
            </div>
            <p className="text-xs text-muted">
              Even the second path can bring DIC when the death itself wasn’t from the service-connected condition —
              which is why an official review of the dates and rating history matters.
            </p>
          </div>
        </Panel>
      </div>

      <Panel hue={HUE} title="The benefits & forms" subtitle="What each is, and the official VA form">
        <div className="divide-y divide-line">
          {BENEFITS.map((b) => (
            <div key={b.name} className="flex flex-wrap items-start justify-between gap-3 p-5">
              <div className="flex min-w-0 items-start gap-3">
                <span
                  aria-hidden
                  className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
                  style={{ background: hueSoftVar(HUE), color: ink }}
                >
                  {b.icon}
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-txt">{b.name}</p>
                  <p className="mt-1 text-sm leading-relaxed text-muted">{b.what}</p>
                  <p className="mt-1.5 text-xs font-medium" style={{ color: ink }}>
                    {b.form} — <span className="text-muted">{b.formTitle}</span>
                  </p>
                </div>
              </div>
              <a
                href={b.href}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-10 shrink-0 items-center gap-1 rounded-control px-1 text-xs font-semibold text-brand hover:text-brand-hover"
              >
                Official page <ExternalLink size={12} aria-hidden="true" />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </div>
          ))}
        </div>
      </Panel>

      <div className="vo-card vo-accent flex items-start gap-3.5 p-5">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-surface2 text-muted">
          <FileText size={20} />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-txt">Good to have ready before filing</h2>
          <p className="mt-1 text-sm leading-relaxed text-muted">
            The veteran’s death certificate, their DD-214 (or other separation document), your marriage certificate
            and any children’s birth certificates, and the veteran’s VA file number or Social Security number. A VSO
            can help identify what a specific application asks for.
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-2">
        <a
          href="https://www.va.gov/family-and-caregiver-benefits/survivor-compensation/"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-10 items-center gap-1 rounded-control px-1 text-xs font-semibold text-brand hover:text-brand-hover"
        >
          VA.gov survivor benefits <ExternalLink size={12} aria-hidden="true" />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
        <a
          href="https://www.va.gov/burials-memorials/"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex min-h-10 items-center gap-1 rounded-control px-1 text-xs font-semibold text-brand hover:text-brand-hover"
        >
          VA.gov burials &amp; memorials <ExternalLink size={12} aria-hidden="true" />
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      </div>

      <div
        className="rounded-control border-l-2 px-4 py-3 text-xs leading-relaxed"
        style={{ borderColor: hueVar(HUE), background: hueSoftVar(HUE) }}
      >
        <p className="flex items-start gap-2 italic text-muted">
          <Info size={13} className="mt-0.5 shrink-0" style={{ color: ink }} />
          This page explains survivor benefits to help you prepare — it is not legal advice and does not decide
          eligibility or payment. VA makes those decisions. A VA-accredited VSO can help at no cost; accredited
          attorneys or claims agents may charge fees in circumstances allowed by law.
        </p>
      </div>
    </div>
  )
}
