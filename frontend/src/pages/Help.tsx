import {
  Compass,
  Folder,
  Gauge,
  ScanText,
  Target,
  FileCheck2,
  Scale,
  Gift,
  Calculator,
  LifeBuoy,
  ShieldCheck,
   HelpCircle,
} from 'lucide-react'
import { type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Panel } from '../components/ui'
import { hueInk, hueSoftVar, type Hue } from '../lib/hues'

/** Help / how-it-works hub. A robust, plain-language guide to what every tool does,
 * how the app maps to the VA claim process, and the questions veterans ask most.
 * Static content, legal-lane voice: it organizes and explains, it never files,
 * represents, diagnoses, or predicts a decision. */

function ToolRow({ to, icon, name, blurb, hue }: { to: string; icon: ReactNode; name: string; blurb: string; hue: Hue }) {
  return (
    <Link
      to={to}
      className="flex items-start gap-3 rounded-control border border-line bg-surface2/40 p-3.5 transition-colors hover:border-line2 hover:bg-surface2"
    >
      <span
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg"
        style={{ background: hueSoftVar(hue), color: hueInk(hue) }}
      >
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-sm font-semibold text-txt">{name}</span>
        <span className="mt-0.5 block text-sm leading-relaxed text-muted">{blurb}</span>
      </span>
    </Link>
  )
}

function Faq({ q, children }: { q: string; children: ReactNode }) {
  return (
    <details className="group rounded-control border border-line bg-surface2/40 px-4 py-3">
      <summary className="cursor-pointer list-none text-sm font-semibold text-txt marker:content-['']">
        <span className="inline-flex items-center gap-2">
          <HelpCircle size={15} className="text-muted" /> {q}
        </span>
      </summary>
      <div className="mt-2 text-sm leading-relaxed text-muted">{children}</div>
    </details>
  )
}

export function Help() {
  return (
    <div className="vo-page mx-auto w-full max-w-4xl space-y-6 p-4 sm:p-6" data-section="guide">
      <div className="vo-page-head vo-section-band">
        <h1 className="vo-page-title">Help &amp; how it works</h1>
        <p className="vo-page-sub">
          What Rating Raider does, how it maps to the VA claim process, and the questions veterans ask
          most. You are always the one driving. We organize and explain; you review, sign, and file.
        </p>
      </div>

      <Panel hue="indigo" title="How Rating Raider works" subtitle="Self-help software you operate yourself">
        <div className="space-y-3 p-5 text-sm leading-relaxed text-muted">
          <p className="text-txt">
            Think of it like tax software for your VA disability claim. It reads and organizes your own
            records, explains the rating criteria in plain language, shows you where you stand, and
            produces the paperwork. Every piece of advice is something to consider, not a decision made
            for you.
          </p>
          <p>
            Rating Raider never files a claim, never represents you, never diagnoses a condition, and
            never predicts what the VA will decide. When it is time to file, you can do it yourself on
            VA.gov, or hand your prepared packet to a free VA-accredited Veterans Service Officer.
          </p>
          <p>
            Your records never leave our own hardware. The AI that reads your file runs on machines we
            own and operate; your health information is never sent to an outside AI service.
          </p>
        </div>
      </Panel>

      <Panel hue="cyan" title="Your claim, step by step" subtitle="How the app follows the VA process">
        <ol className="space-y-4 p-5">
          {[
            ['Set up your claim', 'Add your service history and the conditions you are claiming. Guided setup walks you through it.', '/onboarding'],
            ['Bring in your records', 'Upload your file or connect your VA.gov data. Rating Raider reads every page and lines up your conditions and evidence in one place.', '/documents'],
            ['See where you stand', 'Your Claim Plan reads everything and lays out what is ready, what to strengthen first, what to weigh before filing, and what you may be missing.', '/strategy'],
            ['Build your evidence', 'Every claim needs a current diagnosis, an in-service event, and a medical link between them. Close the gaps on each condition.', '/evidence'],
            ['Produce the paperwork', 'Generate statements, nexus request letters, and forms in your own words. Review and sign them.', '/statement'],
            ['File it', 'Submit on VA.gov yourself, or take your packet to a free VSO. Rating Raider never files for you.', '/filing'],
            ['Decode the decision', 'When your rating decision arrives, run it through the decoder to understand exactly what was granted, what was denied, and why.', '/decode'],
            ['Respond to a denial', 'A denial is not the end. Most veterans file a Supplemental Claim with new evidence, and you have a year to keep your original date.', '/appeals'],
          ].map(([title, body, to], i) => (
            <li key={i} className="flex gap-4">
              <span
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm font-bold"
                style={{ background: hueSoftVar('cyan'), color: hueInk('cyan') }}
              >
                {i + 1}
              </span>
              <div className="min-w-0">
                <Link to={to as string} className="text-sm font-semibold text-txt hover:text-brand">
                  {title}
                </Link>
                <p className="mt-0.5 text-sm leading-relaxed text-muted">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </Panel>

      <Panel hue="emerald" title="What each tool does" subtitle="A quick guide to the toolbox">
        <div className="space-y-5 p-5">
          <div>
            <p className="mb-2 text-micro font-semibold uppercase tracking-wide text-faint">Understand your claim</p>
            <div className="grid gap-2.5 sm:grid-cols-2">
              <ToolRow to="/strategy" icon={<Target size={17} />} hue="fuchsia" name="Claim Plan" blurb="Your whole situation, read and explained: what to file, what to weigh, what you may be missing." />
              <ToolRow to="/conditions" icon={<Folder size={17} />} hue="emerald" name="Conditions" blurb="The conditions you are claiming, each with its readiness toward filing." />
              <ToolRow to="/readiness" icon={<Gauge size={17} />} hue="emerald" name="Readiness" blurb="How close each condition is to having the three things a claim needs." />
              <ToolRow to="/decode" icon={<ScanText size={17} />} hue="fuchsia" name="Decision decoder" blurb="Paste a VA decision letter and understand what it really said." />
            </div>
          </div>
          <div>
            <p className="mb-2 text-micro font-semibold uppercase tracking-wide text-faint">Records &amp; paperwork</p>
            <div className="grid gap-2.5 sm:grid-cols-2">
              <ToolRow to="/documents" icon={<Folder size={17} />} hue="amber" name="Documents" blurb="Upload and view your records; trace each piece of evidence to the claim it supports." />
              <ToolRow to="/application" icon={<FileCheck2 size={17} />} hue="amber" name="Application (21-526EZ)" blurb="Organize your claim into the fields the form needs." />
              <ToolRow to="/tdiu" icon={<FileCheck2 size={17} />} hue="emerald" name="TDIU" blurb="Unemployability: paid at the 100% rate when your conditions keep you from working." />
              <ToolRow to="/dependency" icon={<FileCheck2 size={17} />} hue="violet" name="Dependents (21-686c)" blurb="Add or re-add a dependent, or respond to a VA change to your dependents." />
              <ToolRow to="/corrections" icon={<Scale size={17} />} hue="orange" name="Records corrections" blurb="Fix an error in your military record, including an officer rank/promotion correction." />
            </div>
          </div>
          <div>
            <p className="mb-2 text-micro font-semibold uppercase tracking-wide text-faint">Numbers &amp; benefits</p>
            <div className="grid gap-2.5 sm:grid-cols-2">
              <ToolRow to="/calculator" icon={<Calculator size={17} />} hue="sky" name="Rating math" blurb="See how your ratings combine under the VA formula, and estimate back pay." />
              <ToolRow to="/benefits" icon={<Gift size={17} />} hue="pink" name="Benefits" blurb="What your rating unlocks, federal, state, and commercial, matched to your percentage and state." />
            </div>
          </div>
        </div>
      </Panel>

      <Panel hue="sky" title="Common questions" subtitle="Straight answers">
        <div className="space-y-2.5 p-5">
          <Faq q="Does Rating Raider file my claim for me?">
            No. It prepares everything and hands it to you. You review it, sign it, and file it yourself
            on VA.gov, or you give it to a free VA-accredited VSO to file. We never submit anything to the
            VA on your behalf.
          </Faq>
          <Faq q="Will it tell me what rating I will get?">
            No, and be wary of anything that claims it can. Rating Raider shows you the criteria and does
            the combined-rating math on the numbers you set, clearly labeled as your own estimate, not a
            prediction of the VA's decision.
          </Faq>
          <Faq q="Is my information private?">
            Yes. Your records stay on our own hardware. The AI that reads them runs on machines we own;
            your health information is never sent to an outside AI service to be processed, stored, or
            trained on.
          </Faq>
          <Faq q="Do I still need a VSO?">
            A free VA-accredited Veterans Service Officer (VFW, DAV, The American Legion, or your
            state/county veterans office) is always a good partner, especially for filing and appeals.
            Rating Raider helps you walk in organized and informed. You never have to pay for help with a
            VA claim.
          </Faq>
          <Faq q="Is the rating criteria current?">
            Every criteria-driven view shows the date it was verified, and flags you if the regulations
            may have changed since. Always confirm current criteria at eCFR or VA.gov before you file, as
            regulations change.
          </Faq>
          <Faq q="What does it cost?">
            The individual veteran self-help tools are the heart of the app. Team plans exist for VSOs,
            clinics, and agencies. Pricing is shown on the Plans &amp; billing page.
          </Faq>
        </div>
      </Panel>

      <Panel hue="rose" title="You do not have to do this alone" subtitle="Free help exists">
        <div className="space-y-2 p-5 text-sm leading-relaxed text-muted">
          <p className="flex items-start gap-2.5">
            <LifeBuoy size={16} className="mt-0.5 shrink-0 text-h-rose" />
            A free VA-accredited VSO can file and appeal with you at no cost. Find one through the VFW,
            DAV, The American Legion, or your state or county veterans office.
          </p>
          <p className="flex items-start gap-2.5">
            <ShieldCheck size={16} className="mt-0.5 shrink-0 text-h-emerald" />
            For records corrections and discharge upgrades, free legal help is available through
            law-school veterans clinics and nonprofits like the National Veterans Legal Services Program.
          </p>
          <p className="flex items-start gap-2.5">
            <Compass size={16} className="mt-0.5 shrink-0 text-h-sky" />
            In crisis? The Veterans Crisis Line is available 24/7: dial 988 then press 1.
          </p>
        </div>
      </Panel>
    </div>
  )
}
