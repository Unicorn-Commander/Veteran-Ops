import {
  ArrowRight,
  CheckCircle2,
  Chrome,
  Clipboard,
  Clock3,
  Download,
  Landmark,
  LockKeyhole,
  MousePointerClick,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Panel } from '../components/ui'

const EXTENSION_ZIP = '/valor-va-connect-extension.zip'

export function VaSync() {
  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">VA data</p>
        <h1 className="vo-page-title">Connect your VA data</h1>
        <p className="vo-page-sub">
          Bring in what VA.gov shows for your own ratings and claims, then review it before anything is added to your
          workspace. This is read-only self-help: Veteran-Ops does not submit forms, change VA.gov, or file anything
          for you.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel
          hue="violet"
          title="Paste"
          subtitle="Works today"
          action={<StatusPill icon={<CheckCircle2 size={12} />} label="Available" tone="ok" />}
        >
          <div className="space-y-4 p-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-h-violet-soft text-h-violet">
              <Clipboard size={19} />
            </div>
            <p className="text-sm leading-relaxed text-muted">
              Paste an export from VA Connect, or data you already copied from your own VA.gov screen. You choose which
              ratings, conditions, or service details to import.
            </p>
            <Link to="/va-import" className="vo-btn-primary w-full justify-center text-sm">
              Open paste import <ArrowRight size={15} />
            </Link>
          </div>
        </Panel>

        <Panel
          hue="sky"
          title="Browser extension"
          subtitle="Download and load in Chrome"
          action={<StatusPill icon={<MousePointerClick size={12} />} label="Click to read" tone="info" />}
        >
          <div className="space-y-4 p-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-h-sky-soft text-h-sky">
              <Chrome size={19} />
            </div>
            <p className="text-sm leading-relaxed text-muted">
              The extension reads the VA.gov page you are viewing only when you click its button. It does not read
              passwords, cookies, or background tabs, and it shows a preview before sending data to the import page.
            </p>
            <a href={EXTENSION_ZIP} download className="vo-btn-secondary w-full justify-center text-sm">
              <Download size={15} /> Download extension zip
            </a>
            <ol className="space-y-2 text-sm text-muted">
              <li className="flex gap-2">
                <span className="font-semibold text-txt">1.</span>
                <span>Unzip the download on your computer.</span>
              </li>
              <li className="flex gap-2">
                <span className="font-semibold text-txt">2.</span>
                <span>Open Chrome, go to chrome://extensions, and turn on Developer mode.</span>
              </li>
              <li className="flex gap-2">
                <span className="font-semibold text-txt">3.</span>
                <span>Choose Load unpacked and select the unzipped folder.</span>
              </li>
            </ol>
          </div>
        </Panel>

        <Panel
          hue="amber"
          title="Automatic API sync"
          subtitle="Coming soon"
          action={<StatusPill icon={<Clock3 size={12} />} label="Pending VA access" tone="wait" />}
        >
          <div className="space-y-4 p-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-h-amber-soft text-h-amber">
              <LockKeyhole size={19} />
            </div>
            <p className="text-sm leading-relaxed text-muted">
              Direct VA API sync is gated on VA production access. It is not configurable in this build. When available,
              it will still be read-only and veteran-consented, with review before anything is imported.
            </p>
            <div className="rounded-control border border-line bg-surface2 px-4 py-3 text-sm text-muted">
              Use paste import or the browser extension for now.
            </div>
          </div>
        </Panel>
      </div>

      <Panel hue="teal" title="How this stays in the legal lane">
        <div className="grid gap-3 p-5 text-sm text-muted sm:grid-cols-3">
          <InfoPoint icon={<Landmark size={15} />} title="Your record">
            Reads or imports only VA.gov data you can already see in your own account.
          </InfoPoint>
          <InfoPoint icon={<MousePointerClick size={15} />} title="Your click">
            The extension runs only after you click; paste import uses only what you provide.
          </InfoPoint>
          <InfoPoint icon={<CheckCircle2 size={15} />} title="Your review">
            Nothing is added to your workspace until you choose what to keep.
          </InfoPoint>
        </div>
      </Panel>
    </div>
  )
}

function StatusPill({ icon, label, tone }: { icon: ReactNode; label: string; tone: 'ok' | 'info' | 'wait' }) {
  const cls =
    tone === 'ok'
      ? 'bg-h-emerald-soft text-success'
      : tone === 'info'
        ? 'bg-h-sky-soft text-h-sky'
        : 'bg-h-amber-soft text-warn'
  return (
    <span className={`vo-chip ${cls}`}>
      {icon}
      {label}
    </span>
  )
}

function InfoPoint({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="rounded-control border border-line bg-surface2 p-4">
      <p className="mb-1 flex items-center gap-1.5 font-semibold text-txt">
        {icon}
        {title}
      </p>
      <p className="leading-relaxed">{children}</p>
    </div>
  )
}
