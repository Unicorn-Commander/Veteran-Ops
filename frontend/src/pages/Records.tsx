import { ExternalLink, HeartHandshake, ListChecks, Mail, Printer, Sparkles } from 'lucide-react'
import { useState, type CSSProperties, type FormEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Panel, Skeleton, Spinner } from '../components/ui'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { checklistApi, conditionsApi, recordsApi } from '../lib/api'
import { hueStyle, type Hue } from '../lib/hues'
import type { ClaimedCondition } from '../types'

// /records — WAVE2-SPEC §2. Records requests are self-help automation: Rating
// Raider PRE-FILLS, the veteran signs/submits. It never files or mails
// anything on the veteran's behalf. Endpoint shapes reconciled against the
// real backend/app/routers/records.py (routers are truth).

async function addToChecklist(text: string): Promise<void> {
  await checklistApi.create({ text, category: 'records' })
}

export function Records() {
  const { toast } = useToast()

  const addChecklistItem = async (text: string) => {
    try {
      await addToChecklist(text)
      toast('Added to your checklist.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <div data-section="records" className="vo-page mx-auto w-full max-w-4xl space-y-5 p-4 pb-16 sm:p-6">
      <div className="vo-section-band">
        <p className="vo-caption mb-1">Records requests</p>
        <h1 className="vo-page-title">Records requests</h1>
        <p className="vo-page-sub">
          Get the records that back your claim — Rating Raider prepares each request for your signature. You review,
          sign, and submit it yourself.
        </p>
      </div>

      <VsoBanner />

      <SectionNav
        items={[
          { id: 'rec-dd214', label: 'DD-214 / OMPF', hue: 'emerald' },
          { id: 'rec-cfile', label: 'C-file', hue: 'amber' },
          { id: 'rec-bluebutton', label: 'Blue Button', hue: 'sky' },
          { id: 'rec-str', label: 'STRs', hue: 'cyan' },
          { id: 'rec-private', label: 'Private records', hue: 'violet' },
        ]}
      />

      <div id="rec-dd214" className="scroll-mt-24">
      <Panel hue="emerald" title="DD-214 / Official Military Personnel File (OMPF)">
        <div className="space-y-4 p-5">
          <p className="text-sm text-muted">
            Your discharge paperwork and full personnel file — needed for almost every claim to establish service
            dates, branch, and discharge character.
          </p>
          <GuidedSteps
            steps={[
              'Sign into milConnect with a DS Logon, ID.me, or Login.gov account.',
              'Go to Correspondence/Documentation → DPRIS, and request your DD-214 / separation documents.',
              'For older or more complete records the online system doesn’t have, use eVetRecs or mail the SF-180 worksheet below to the National Personnel Records Center (NPRC).',
            ]}
          />
          <ActionRow
            primary={
              <Link to="/records/sf180" className="vo-btn-primary text-sm">
                <Printer size={14} /> Build SF-180 worksheet
              </Link>
            }
            secondary={
              <>
                <a href="https://milconnect.dmdc.osd.mil/" target="_blank" rel="noreferrer" className="vo-btn-secondary text-sm">
                  Open milConnect <ExternalLink size={13} />
                </a>
                <a
                  href="https://www.archives.gov/veterans/military-service-records"
                  target="_blank"
                  rel="noreferrer"
                  className="vo-btn-secondary text-sm"
                >
                  eVetRecs / NPRC <ExternalLink size={13} />
                </a>
              </>
            }
            checklist={() => void addChecklistItem('Request my DD-214 / OMPF (milConnect or SF-180 to NPRC).')}
          />
        </div>
      </Panel>
      </div>

      <div id="rec-cfile" className="scroll-mt-24">
      <Panel hue="amber" title="VA claims file (C-file)">
        <div className="space-y-4 p-5">
          <p className="text-sm text-muted">
            VA's complete record of everything filed and decided on your claims — every rating decision, exam, and
            piece of correspondence. Useful for spotting errors (see Corrections) and understanding past denials.
          </p>
          <ActionRow
            primary={
              <Link to="/records/va20-10206" className="vo-btn-primary text-sm">
                <Printer size={14} /> Build VA Form 20-10206 worksheet
              </Link>
            }
            secondary={
              <a
                href="https://www.va.gov/records/get-military-service-records/"
                target="_blank"
                rel="noreferrer"
                className="vo-btn-secondary text-sm"
              >
                VA.gov guidance <ExternalLink size={13} />
              </a>
            }
            checklist={() => void addChecklistItem('Request my VA claims file (C-file) with VA Form 20-10206.')}
          />
        </div>
      </Panel>
      </div>

      <div id="rec-bluebutton" className="scroll-mt-24">
      <Panel hue="sky" title="VA medical records (Blue Button)">
        <div className="space-y-4 p-5">
          <p className="text-sm text-muted">
            Your VA treatment history — visit notes, labs, medications — pulled straight from VA.gov. No form needed.
          </p>
          <GuidedSteps
            steps={[
              'Log into VA.gov with your verified account.',
              'Go to Medical Records → Download Blue Button report.',
              'Choose a date range and the content types you need (notes, labs, VA medications).',
              'Generate and download the report — bring it to your provider or attach it as evidence.',
            ]}
          />
          <ActionRow
            primary={
              <a href="https://www.va.gov/health-care/download-medical-records/" target="_blank" rel="noreferrer" className="vo-btn-primary text-sm">
                Open Blue Button on VA.gov <ExternalLink size={13} />
              </a>
            }
            checklist={() => void addChecklistItem('Download my VA medical records via VA.gov Blue Button.')}
          />
        </div>
      </Panel>
      </div>

      <div id="rec-str" className="scroll-mt-24">
      <Panel hue="cyan" title="Service treatment records (STRs)">
        <div className="space-y-3 p-5">
          <p className="text-sm text-muted">
            In-service medical records — treatment, diagnoses, complaints. These come bundled with your OMPF/DD-214
            request above, not as a separate request.
          </p>
          <button
            onClick={() => void addChecklistItem('Confirm STRs are included when my DD-214 / OMPF request comes back.')}
            className="vo-btn-secondary text-sm"
          >
            <ListChecks size={14} /> Add to checklist
          </button>
        </div>
      </Panel>
      </div>

      <div id="rec-private" className="scroll-mt-24">
      <RequestLetterCard />
      </div>
    </div>
  )
}

/** Slim sticky anchor-nav — chips scroll to each records-type Panel below
 * (targets carry scroll-mt-24 to clear the shared Shell topbar). */
function SectionNav({ items }: { items: { id: string; label: string; hue: Hue }[] }) {
  return (
    <nav
      aria-label="Jump to section"
      className="vo-no-print sticky top-16 z-30 -mx-1 flex flex-wrap gap-1.5 rounded-full border border-line bg-surface/90 px-2 py-1.5 backdrop-blur"
    >
      {items.map((it) => (
        <a key={it.id} href={`#${it.id}`} className="vo-chip-hue no-underline" style={hueStyle(it.hue) as CSSProperties}>
          {it.label}
        </a>
      ))}
    </nav>
  )
}

/** Warm, human framing — this is help, not a legal disclaimer wall. */
function VsoBanner() {
  return (
    <div
      className="vo-card vo-accent relative flex items-start gap-3.5 overflow-hidden p-5"
      style={{ '--hue': 'var(--hue-orange)', '--hue-soft': 'var(--hue-orange-soft)' } as React.CSSProperties}
    >
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: 'var(--hue-orange-soft)', color: 'var(--hue-orange)' }}
      >
        <HeartHandshake size={20} />
      </div>
      <div>
        <h2 className="text-sm font-semibold text-txt">Free help is available at every step</h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          A VA-accredited Veterans Service Officer (VSO) — VFW, DAV, The American Legion, or your state/county
          veterans office — can prepare and submit any of these requests for you at no cost. Every form on this page
          is prepared for your signature; you (or your VSO, acting on your behalf) submit it.
        </p>
        <a
          href="https://www.va.gov/get-help-from-accredited-representative/"
          target="_blank"
          rel="noreferrer"
          className="mt-2.5 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
        >
          Find a VSO near you <ExternalLink size={13} />
        </a>
      </div>
    </div>
  )
}

/** A numbered mini-journey — steps connected by a rail so the whole thing
 * reads as one guided path rather than a loose list. */
function GuidedSteps({ steps }: { steps: string[] }) {
  return (
    <ol className="space-y-0 text-sm text-txt">
      {steps.map((s, i) => (
        <li key={i} className="relative flex gap-3 pb-4 last:pb-0">
          {i < steps.length - 1 && (
            <span
              aria-hidden
              className="absolute left-[9px] top-6 h-[calc(100%-0.75rem)] w-px"
              style={{ background: 'var(--border-2)' }}
            />
          )}
          <span className="relative z-10 mt-0.5 flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full bg-surface2 text-[10px] font-bold text-muted ring-4 ring-surface">
            {i + 1}
          </span>
          <span className="pt-px leading-relaxed">{s}</span>
        </li>
      ))}
    </ol>
  )
}

/** Action hierarchy: one clear primary (usually the worksheet builder), then
 * secondary external links (marked with the external-link icon), then the
 * quiet "add to checklist" affordance. */
function ActionRow({
  primary,
  secondary,
  checklist,
}: {
  primary: ReactNode
  secondary?: ReactNode
  checklist: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {primary}
      {secondary}
      <button onClick={checklist} className="vo-btn-ghost text-sm">
        <ListChecks size={14} /> Add to checklist
      </button>
    </div>
  )
}

function RequestLetterCard() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data: conditions, loading: conditionsLoading } = useAsync(() =>
    conditionsApi.list().catch(() => [] as ClaimedCondition[])
  )
  const [providerName, setProviderName] = useState('')
  const [address, setAddress] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [submitting, setSubmitting] = useState(false)

  const toggleCondition = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!providerName.trim()) return
    if (selected.size === 0) {
      toast('Pick at least one condition this request is for.', 'error')
      return
    }
    setSubmitting(true)
    try {
      const result = await recordsApi.requestLetter({
        provider_name: providerName.trim(),
        address: address.trim() || null,
        condition_ids: Array.from(selected),
      })
      toast('Letter ready — review and print it.', 'success')
      navigate('/records/request-letter/print', { state: { letter: result.letter, providerName: providerName.trim() } })
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Panel hue="violet" title="Private / civilian medical records" subtitle="Generate a signable request letter">
      <form onSubmit={submit} className="space-y-4 p-5">
        <p className="text-sm text-muted">
          Records from doctors, hospitals, or clinics outside VA. Rating Raider drafts the request letter — you
          review, sign, and send it (or hand it to your provider's records office).
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-sm">
            <span className="vo-label">Provider / facility name</span>
            <input
              className="vo-input"
              value={providerName}
              onChange={(e) => setProviderName(e.target.value)}
              placeholder="e.g. Dr. Smith Orthopedics"
              required
            />
          </label>
          <label className="text-sm">
            <span className="vo-label">Provider address (optional)</span>
            <input className="vo-input" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="Street, city, state" />
          </label>
        </div>
        {conditionsLoading ? (
          <Skeleton className="h-8 w-full" />
        ) : conditions && conditions.length > 0 ? (
          <div>
            <span className="vo-label">Which conditions is this for? (required)</span>
            <div className="flex flex-wrap gap-2">
              {conditions.map((c) => {
                const checked = selected.has(c.id)
                return (
                  <label
                    key={c.id}
                    className={`flex cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                      checked ? 'border-brand/50 bg-brand-soft text-brand' : 'border-line bg-surface2 text-txt hover:border-line2'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleCondition(c.id)}
                      className="vo-check"
                    />
                    {c.name}
                  </label>
                )
              })}
            </div>
          </div>
        ) : (
          <p className="text-xs text-faint">
            <Link to="/conditions" className="font-semibold text-brand hover:text-brand-hover">Add a condition</Link>{' '}
            first — the letter needs at least one to reference.
          </p>
        )}
        <button type="submit" disabled={submitting || selected.size === 0} className="vo-btn-primary">
          {submitting ? <Spinner size={16} className="text-white" /> : <Mail size={15} />}
          Generate request letter
        </button>
        {!submitting && selected.size > 0 && (
          <p className="flex items-center gap-1.5 text-xs text-faint">
            <Sparkles size={12} className="text-brand" /> Ready in seconds — you'll land on a print-ready page next.
          </p>
        )}
      </form>
    </Panel>
  )
}
