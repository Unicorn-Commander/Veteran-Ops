import { useEffect, useState } from 'react'
import { ErrorBlock } from '../components/ui'
import { DisclaimerFooterBlock, Letterhead, PrintDocStyles } from '../components/PrintDoc'
import { PrintShell } from '../components/PrintShell'
import { strategyApi } from '../lib/api'
import { errorMessage } from '../hooks/useAsync'
import type { CaseBrief as CaseBriefType, CoachMove, OutstandingItem } from '../types'

/**
 * Printable case brief one-pager — educational handoff for the veteran or a VSO.
 * Loads GET /strategy/case-brief (falls back to coach.case_brief on full plan).
 * Standalone print chrome (no Shell), same pattern as StrategyPrint.
 */

function moveTitle(m: CoachMove | Record<string, unknown> | null | undefined): string {
  if (!m || typeof m !== 'object') return ''
  const t = (m as CoachMove).title
  return typeof t === 'string' ? t : ''
}

function moveWhy(m: CoachMove | Record<string, unknown> | null | undefined): string {
  if (!m || typeof m !== 'object') return ''
  const w = (m as CoachMove).why
  return typeof w === 'string' ? w : ''
}

export function CaseBrief() {
  const [brief, setBrief] = useState<CaseBriefType | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    strategyApi
      .caseBrief()
      .then((b) => {
        if (!cancelled) {
          setBrief(b)
          setError(null)
        }
      })
      .catch(async (err) => {
        // Older backends: pull case_brief from the full plan if present.
        try {
          const plan = await strategyApi.get()
          const fallback = plan.coach?.case_brief
          if (!cancelled && fallback) {
            setBrief(fallback)
            setError(null)
            return
          }
        } catch {
          /* use original error */
        }
        if (!cancelled) setError(errorMessage(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (loading) {
    return (
      <PrintShell backTo="/strategy" backLabel="Back to Claim Plan">
        <p className="text-sm text-muted">Building your case brief…</p>
      </PrintShell>
    )
  }

  if (error || !brief) {
    return (
      <PrintShell backTo="/strategy" backLabel="Back to Claim Plan">
        <ErrorBlock message={error ?? 'Case brief unavailable.'} />
      </PrintShell>
    )
  }

  const first = brief.do_this_first
  const then = brief.then ?? []
  const outstanding = brief.outstanding_top ?? []
  const sc = brief.service_connected ?? []
  const denied = brief.denied ?? []
  const cautions = brief.cautions ?? []
  const snap = (brief.snapshot || {}) as Record<string, unknown>

  return (
    <PrintShell backTo="/strategy" backLabel="Back to Claim Plan">
      <PrintDocStyles />
      <article className="rr-doc">
        <Letterhead />
        <h1 className="text-2xl font-bold text-txt">{brief.title || 'Case brief — for you or a VSO'}</h1>
        {brief.profile_summary && (
          <p className="rr-sans mt-2 text-sm leading-relaxed text-muted">{brief.profile_summary}</p>
        )}

        {(snap.current_combined != null || snap.conditions_total != null) && (
          <section className="mt-6">
            <p className="rr-rule-label text-muted">Snapshot</p>
            <div className="rr-sans mt-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
              {snap.current_combined != null && (
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-faint">Current combined</p>
                  <p className="font-semibold text-txt">{String(snap.current_combined)}%</p>
                </div>
              )}
              {snap.conditions_total != null && (
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-faint">Conditions tracked</p>
                  <p className="font-semibold text-txt">{String(snap.conditions_total)}</p>
                </div>
              )}
              {snap.denied_count != null && (
                <div>
                  <p className="text-[11px] uppercase tracking-wide text-faint">Denied on file</p>
                  <p className="font-semibold text-txt">{String(snap.denied_count)}</p>
                </div>
              )}
            </div>
          </section>
        )}

        {sc.length > 0 && (
          <section className="mt-8">
            <p className="rr-rule-label text-muted">Service-connected</p>
            <ul className="rr-sans mt-2 space-y-1 text-sm text-txt">
              {sc.map((c, i) => (
                <li key={i}>
                  {c.name || 'Condition'}
                  {c.rating != null ? ` · ${c.rating}%` : ''}
                  {c.dc ? ` · DC ${c.dc}` : ''}
                </li>
              ))}
            </ul>
          </section>
        )}

        {denied.length > 0 && (
          <section className="mt-8">
            <p className="rr-rule-label text-muted">Denied / prior denials on file</p>
            <ul className="rr-sans mt-2 space-y-1 text-sm text-txt">
              {denied.map((c, i) => (
                <li key={i}>
                  {c.name || 'Condition'}
                  {c.dc ? ` · DC ${c.dc}` : ''}
                </li>
              ))}
            </ul>
          </section>
        )}

        {first && moveTitle(first) && (
          <section className="mt-8">
            <p className="rr-rule-label text-muted">Do this first</p>
            <h2 className="mt-2 text-lg font-semibold text-txt">{moveTitle(first)}</h2>
            {moveWhy(first) && (
              <p className="rr-sans mt-1 text-sm leading-relaxed text-muted">{moveWhy(first)}</p>
            )}
          </section>
        )}

        {then.length > 0 && (
          <section className="mt-8">
            <p className="rr-rule-label text-muted">Then</p>
            <ol className="rr-sans mt-2 list-decimal space-y-2 pl-5 text-sm text-txt">
              {then.map((m, i) => (
                <li key={i} className="leading-relaxed">
                  <strong>{moveTitle(m)}</strong>
                  {moveWhy(m) ? ` — ${moveWhy(m)}` : ''}
                </li>
              ))}
            </ol>
          </section>
        )}

        {outstanding.length > 0 && (
          <section className="mt-8">
            <p className="rr-rule-label text-muted">Outstanding</p>
            <ul className="rr-sans mt-2 space-y-2 text-sm text-txt">
              {outstanding.map((o: OutstandingItem, i) => (
                <li key={o.id || i} className="leading-relaxed">
                  <strong>{o.title}</strong>
                  {o.why ? ` — ${o.why}` : ''}
                  {o.severity ? (
                    <span className="ml-1 text-xs uppercase tracking-wide text-faint">({o.severity})</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        )}

        {cautions.length > 0 && (
          <section className="mt-8">
            <p className="rr-rule-label text-muted">Cautions to weigh (educational)</p>
            <ul className="rr-sans mt-2 list-disc space-y-1 pl-5 text-sm text-txt">
              {cautions.map((c, i) => (
                <li key={i}>
                  {c.title || 'Caution'}
                  {c.reg ? ` · ${c.reg}` : ''}
                </li>
              ))}
            </ul>
          </section>
        )}

        {brief.tdiu && typeof brief.tdiu === 'object' && (
          <section className="mt-8">
            <p className="rr-rule-label text-muted">TDIU screen</p>
            <p className="rr-sans mt-2 text-sm leading-relaxed text-txt">
              {(brief.tdiu as { why?: string; what_it_is?: string }).why ||
                (brief.tdiu as { what_it_is?: string }).what_it_is ||
                'TDIU education available on Claim Plan — not a determination of entitlement.'}
            </p>
          </section>
        )}

        <DisclaimerFooterBlock
          text={
            brief.disclaimer ||
            'Educational self-help organization of the veteran’s own records. Not legal advice; not a VA determination. Veteran-Ops does not file claims.'
          }
        />
      </article>
    </PrintShell>
  )
}
