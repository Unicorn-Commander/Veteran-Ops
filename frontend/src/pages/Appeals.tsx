import {
  AlertTriangle,
  ExternalLink,
  FileSearch,
  Gavel,
  Info,
  ListPlus,
  Printer,
  Scale,
  ShieldCheck,
} from 'lucide-react'
import { type CSSProperties, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Checkbox, EmptyState, ErrorBlock, LoadingBlock, Panel, Spinner } from '../components/ui'
import { FilledFormPanel } from '../components/FilledFormPanel'
import { useToast } from '../components/Toast'
import { errorMessage, useAsync } from '../hooks/useAsync'
import { appealsApi } from '../lib/api'
import { formatDate } from '../lib/format'
import { hueInk, hueLabel, hueSoftVar, hueStyle, hueVar, type Hue } from '../lib/hues'
import type { AppealCandidate, AppealDraftInput, AppealLane, DecodeOption } from '../types'

// /appeals — WAVE7 Track A. Appeals draft assist (Supplemental Claim / HLR /
// Board). After a denial the decoder surfaced — or for any claimed condition —
// help the veteran DRAFT a decision-review response, then hand it to the print
// view. Educational self-help only: Veteran-Ops is not a VA-accredited rep,
// does not file or appeal anything, and never renders a medical opinion. The
// veteran's own words pass through VERBATIM. Endpoint shapes reconciled against
// backend/app/routers/appeals.py (routers are truth). Follows Buddy/Form526.

const HUE: Hue = 'fuchsia'
/** What the print view reads out of sessionStorage (kept local to both files). */
const APPEAL_DRAFT_KEY = 'vo_appeal_draft'

/** Stable identity for a candidate across selection / per-contention maps. */
function candKey(c: AppealCandidate): string {
  return `${c.source}:${c.condition_id ?? ''}:${c.document_id ?? ''}:${c.name}`
}

interface ContentionState {
  statement: string
  /** title → applies? (undefined ⇒ checked by default). */
  evidence: Record<string, boolean>
}

export function Appeals() {
  const navigate = useNavigate()
  const { toast } = useToast()
  const { data, loading, error, reload } = useAsync(() => appealsApi.candidates())

  const [lane, setLane] = useState<AppealLane>('supplemental_claim')
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [perCont, setPerCont] = useState<Record<string, ContentionState>>({})
  const [building, setBuilding] = useState(false)

  const candidates = data?.candidates ?? []
  const lanes = data?.lanes ?? []

  const chosen = useMemo(
    () => candidates.filter((c) => selected[candKey(c)]),
    [candidates, selected],
  )

  const evidenceApplies = (key: string, title: string): boolean => perCont[key]?.evidence[title] !== false

  const toggleSelected = (c: AppealCandidate) => {
    const key = candKey(c)
    setSelected((s) => ({ ...s, [key]: !s[key] }))
  }

  const setStatement = (key: string, statement: string) =>
    setPerCont((p) => ({ ...p, [key]: { statement, evidence: p[key]?.evidence ?? {} } }))

  const toggleEvidence = (key: string, title: string) =>
    setPerCont((p) => ({
      ...p,
      [key]: {
        statement: p[key]?.statement ?? '',
        evidence: { ...p[key]?.evidence, [title]: !(p[key]?.evidence[title] !== false) },
      },
    }))

  const buildInput = (): AppealDraftInput | null => {
    if (chosen.length === 0) return null
    // One decision_date drives the deadline — take the first selected letter's.
    const decision_date = chosen.map((c) => c.decision_date).find((d) => !!d) ?? null
    return {
      lane,
      decision_date,
      contentions: chosen.map((c) => {
        const key = candKey(c)
        const st = perCont[key]
        return {
          name: c.name,
          diagnostic_code: c.diagnostic_code,
          missing_elements: c.missing_elements,
          new_evidence_titles: c.new_evidence.filter((e) => evidenceApplies(key, e.title)).map((e) => e.title),
          veteran_statement: (st?.statement ?? '').trim() || null,
        }
      }),
    }
  }

  const goToPrint = async () => {
    const input = buildInput()
    if (!input) {
      toast('Pick at least one condition to respond to first.', 'error')
      return
    }
    setBuilding(true)
    try {
      const draft = await appealsApi.draft(input)
      sessionStorage.setItem(APPEAL_DRAFT_KEY, JSON.stringify(draft))
      navigate('/appeals/print')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBuilding(false)
    }
  }

  const ink = hueInk(HUE)
  const label = hueLabel(HUE)

  return (
    <div
      data-section="insight"
      className="vo-page mx-auto w-full max-w-5xl space-y-5 p-4 pb-16 sm:p-6"
      style={hueStyle(HUE) as CSSProperties}
    >
      <div className="vo-section-band">
        <p className="vo-caption mb-1" style={{ color: label }}>
          Decision review · Supplemental Claim · Higher-Level Review · Board Appeal
        </p>
        <h1 className="vo-page-title">Appeal a denial</h1>
        <p className="vo-page-sub">
          Draft a decision-review response for a denied condition — or start a Supplemental Claim for any condition you're
          claiming. Rating Raider assembles it from what you pick; your own words go in exactly as you write them, and you
          (or a free VSO) file it.
        </p>
      </div>

      <LegalLaneBanner />

      <FilledFormPanel
        formId="20-0995"
        hue={HUE}
        title="Download the pre-filled 20-0995 Supplemental Claim (review & sign)"
      />

      {loading ? (
        <LoadingBlock label="Finding decisions you could respond to…" />
      ) : error || !data ? (
        <ErrorBlock message={error ?? 'Could not load your appeal candidates.'} onRetry={reload} />
      ) : candidates.length === 0 ? (
        <Panel hue={HUE}>
          <EmptyState
            hue={HUE}
            icon={<FileSearch size={24} />}
            title="Nothing to respond to yet"
            description="Decode a VA decision letter to pull in any denied conditions, or add the conditions you're claiming — then you can draft a Supplemental Claim, Higher-Level Review, or Board Appeal here."
            action={
              <div className="flex flex-wrap items-center justify-center gap-2">
                <Link to="/decode" className="vo-btn-primary">
                  Decode a decision letter
                </Link>
                <Link to="/conditions" className="vo-btn-secondary">
                  Add your conditions
                </Link>
              </div>
            }
          />
        </Panel>
      ) : (
        <>
          <LanePicker lanes={lanes} lane={lane} onPick={setLane} ink={ink} label={label} />

          <Panel
            hue={HUE}
            title="Which conditions are you responding to?"
            subtitle={`${chosen.length} selected of ${candidates.length}`}
          >
            <div className="space-y-4 p-5">
              {candidates.map((c) => {
                const key = candKey(c)
                const isSel = !!selected[key]
                return (
                  <CandidateCard
                    key={key}
                    c={c}
                    selected={isSel}
                    onToggle={() => toggleSelected(c)}
                    statement={perCont[key]?.statement ?? ''}
                    onStatement={(v) => setStatement(key, v)}
                    evidenceApplies={(title) => evidenceApplies(key, title)}
                    onToggleEvidence={(title) => toggleEvidence(key, title)}
                    ink={ink}
                    label={label}
                  />
                )
              })}
            </div>
          </Panel>

          <div className="flex flex-col items-center gap-2 pt-1">
            <button onClick={goToPrint} disabled={chosen.length === 0 || building} className="vo-btn-primary">
              {building ? <Spinner size={16} className="text-white" /> : <Printer size={16} />}
              Build my response to review &amp; sign
            </button>
            <p className="text-xs text-faint">
              Opens a clean, letterhead draft. You review it, sign it, and file it — Veteran-Ops never does.
            </p>
          </div>

          <p className="px-1 text-xs italic leading-relaxed text-faint">{data.disclaimer}</p>
        </>
      )}
    </div>
  )
}

function LanePicker({
  lanes,
  lane,
  onPick,
  ink,
  label,
}: {
  lanes: DecodeOption[]
  lane: AppealLane
  onPick: (l: AppealLane) => void
  ink: string
  label: string
}) {
  return (
    <Panel hue={HUE} title="Pick your lane" subtitle="Three ways to ask VA to review a decision (educational)">
      <div className="grid gap-3 p-5 sm:grid-cols-3">
        {lanes.map((l) => {
          const active = l.key === lane
          return (
            <button
              key={l.key}
              type="button"
              aria-pressed={active}
              onClick={() => onPick(l.key as AppealLane)}
              className="rounded-control border p-4 text-left transition-colors"
              style={{
                borderColor: active ? hueVar(HUE) : 'var(--border)',
                background: active ? hueSoftVar(HUE) : 'var(--surface2)',
              }}
            >
              <div className="flex items-center gap-2">
                <Scale size={15} style={{ color: active ? ink : 'var(--muted)' }} />
                <span className="text-sm font-semibold text-txt">{l.title}</span>
              </div>
              <p className="mt-1.5 text-xs font-medium" style={{ color: label }}>
                {l.when}
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-muted">{l.detail}</p>
            </button>
          )
        })}
      </div>
    </Panel>
  )
}

function CandidateCard({
  c,
  selected,
  onToggle,
  statement,
  onStatement,
  evidenceApplies,
  onToggleEvidence,
  ink,
  label,
}: {
  c: AppealCandidate
  selected: boolean
  onToggle: () => void
  statement: string
  onStatement: (v: string) => void
  evidenceApplies: (title: string) => boolean
  onToggleEvidence: (title: string) => void
  ink: string
  label: string
}) {
  const win = c.appeal_window
  return (
    <div
      className="rounded-control border p-4"
      style={{ borderColor: selected ? hueVar(HUE) : 'var(--border)', background: 'var(--surface2)' }}
    >
      <Checkbox
        checked={selected}
        onChange={onToggle}
        label={
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-txt">{c.name}</span>
            {c.source === 'decoded_letter' ? (
              <span className="vo-chip-hue" style={hueStyle('rose') as CSSProperties}>
                Denied
              </span>
            ) : (
              <span className="vo-chip-hue" style={hueStyle('sky') as CSSProperties}>
                Claimed condition
              </span>
            )}
            {c.diagnostic_code && <span className="text-xs text-faint">DC {c.diagnostic_code}</span>}
          </span>
        }
        description={
          <span>
            {c.decision_date && <>Decision dated {formatDate(c.decision_date)}. </>}
            {win?.deadline && (
              <span style={{ color: win.expired ? hueInk('rose') : undefined }}>
                One-year window {win.expired ? 'closed' : 'ends'} {formatDate(win.deadline)}
                {typeof win.days_remaining === 'number' && !win.expired && ` · ${win.days_remaining} days left`}.
              </span>
            )}
            {c.source === 'condition' && 'Draft a Supplemental Claim with new and relevant evidence.'}
          </span>
        }
      />

      {selected && (
        <div className="mt-3 space-y-3 border-t border-line pt-3">
          {c.missing_elements.length > 0 && (
            <p className="flex items-start gap-2 text-xs text-muted">
              <Info size={13} className="mt-0.5 shrink-0" style={{ color: ink }} />
              <span>
                VA said this was missing:{' '}
                <span className="font-medium text-txt">{c.missing_elements.join(', ')}</span>. Your new evidence and
                statement should speak to that.
              </span>
            </p>
          )}

          {c.new_evidence.length > 0 ? (
            <div>
              <p className="mb-1.5 flex items-center gap-1.5 text-micro font-semibold uppercase tracking-wide" style={{ color: label }}>
                <ListPlus size={12} /> New &amp; relevant evidence to include
              </p>
              <div className="space-y-1.5">
                {c.new_evidence.map((e) => (
                  <Checkbox
                    key={e.title}
                    checked={evidenceApplies(e.title)}
                    onChange={() => onToggleEvidence(e.title)}
                    label={
                      <span>
                        {e.title} <span className="text-xs text-faint">({e.kind.replace(/_/g, ' ')})</span>
                      </span>
                    }
                  />
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-faint">
              No matching evidence marked "have" yet. Add it under this condition and mark it "have" so it lands here.
            </p>
          )}

          <label className="block text-sm">
            <span className="vo-label">Your statement (in your own words)</span>
            <textarea
              className="vo-input min-h-[120px] resize-y leading-relaxed"
              value={statement}
              onChange={(e) => onStatement(e.target.value)}
              placeholder={
                'Tell VA, in your own words, what they should know — what happened in service, how this affects you now, ' +
                'and what the new evidence shows. This goes onto the form exactly as you write it.'
              }
            />
            <span className="mt-1 block text-xs text-faint">
              Your words go in verbatim — never rewritten. Keep it true and first-hand.
            </span>
          </label>
        </div>
      )}
    </div>
  )
}

/** Prominent legal-lane note: never filed for you; a VSO helps for free; no
 * medical opinion is ever produced here. */
function LegalLaneBanner() {
  return (
    <div className="vo-card vo-accent relative flex items-start gap-3.5 overflow-hidden p-5" style={hueStyle(HUE) as CSSProperties}>
      <div
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full"
        style={{ background: hueSoftVar(HUE), color: hueInk(HUE) }}
      >
        <Gavel size={20} />
      </div>
      <div>
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-txt">
          <ShieldCheck size={15} style={{ color: hueInk(HUE) }} /> Prepared for your review and signature — never filed for you
        </h2>
        <p className="mt-1 text-sm leading-relaxed text-muted">
          Veteran-Ops is educational self-help software — not a VA-accredited representative. It does not file or appeal
          anything for you and never renders a medical opinion. It drafts a response from what you select, in your own
          words. You file it at VA.gov, or a VA-accredited VSO — VFW, DAV, The American Legion, or your state/county
          veterans office — helps you appeal for free. You never have to pay to appeal a VA decision.
        </p>
        <a
          href="https://www.va.gov/get-help-from-accredited-representative/"
          target="_blank"
          rel="noreferrer"
          className="mt-2.5 inline-flex items-center gap-1 text-sm font-semibold text-brand hover:text-brand-hover"
        >
          Find a VSO near you <ExternalLink size={13} />
        </a>
        <p className="mt-2 flex items-start gap-1.5 text-xs text-faint">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" /> Deadlines have exceptions — confirm your one-year window
          with a VSO.
        </p>
      </div>
    </div>
  )
}
