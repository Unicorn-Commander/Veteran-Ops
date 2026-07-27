/**
 * Shared, session-scoped store for "build case from records" candidates.
 *
 * Why this exists: GET /analysis/case-candidates can take a while and costs a
 * credit. Navigating off /build-case used to unmount the page and drop the
 * in-flight work, then restart (and re-charge) on every return. This store:
 *  - keeps a single in-flight promise so the request continues in the background
 *  - caches the last good result for the session (force=true to refresh)
 *  - notifies subscribers so Shell can show a "still working" chip
 */

import { analysisApi } from './api'
import type { CaseCandidatesResult } from '../types'

const CACHE_TTL_MS = 15 * 60 * 1000 // 15 minutes — records don't change every second

type Status = 'idle' | 'loading' | 'ready' | 'error'

export interface CaseCandidatesSnapshot {
  status: Status
  data: CaseCandidatesResult | null
  error: string | null
  /** Epoch ms when the current load started (null when idle/ready). */
  startedAt: number | null
  /** Epoch ms of the last successful result. */
  readyAt: number | null
}

type Listener = (snap: CaseCandidatesSnapshot) => void

let snapshot: CaseCandidatesSnapshot = {
  status: 'idle',
  data: null,
  error: null,
  startedAt: null,
  readyAt: null,
}
let inflight: Promise<CaseCandidatesResult> | null = null
const listeners = new Set<Listener>()

function emit() {
  const snap = { ...snapshot }
  for (const l of listeners) l(snap)
}

function setSnap(partial: Partial<CaseCandidatesSnapshot>) {
  snapshot = { ...snapshot, ...partial }
  emit()
}

export function getCaseCandidatesSnapshot(): CaseCandidatesSnapshot {
  return { ...snapshot }
}

export function subscribeCaseCandidates(listener: Listener): () => void {
  listeners.add(listener)
  listener({ ...snapshot })
  return () => {
    listeners.delete(listener)
  }
}

/** True when a background load is still running (even if the page unmounted). */
export function isCaseCandidatesLoading(): boolean {
  return snapshot.status === 'loading'
}

/**
 * Ensure candidates are loaded. Safe to call from any page — but callers should
 * only invoke on explicit user action (not route mount). Default is a free
 * deterministic scan (no GPU). Pass enrich=true for optional LLM grouping.
 * - Reuses in-flight request if already loading
 * - Returns cached result if still fresh unless `force`
 * - Continues even if the caller unmounts
 */
export async function ensureCaseCandidates(
  opts: { force?: boolean; enrich?: boolean } = {},
): Promise<CaseCandidatesResult> {
  const force = opts.force === true
  const enrich = opts.enrich === true
  const now = Date.now()
  if (
    !force &&
    !enrich &&
    snapshot.status === 'ready' &&
    snapshot.data &&
    snapshot.readyAt != null &&
    now - snapshot.readyAt < CACHE_TTL_MS
  ) {
    return snapshot.data
  }
  if (inflight) return inflight

  setSnap({ status: 'loading', error: null, startedAt: Date.now() })
  inflight = analysisApi
    .caseCandidates({ enrich })
    .then((data) => {
      setSnap({
        status: 'ready',
        data,
        error: null,
        startedAt: null,
        readyAt: Date.now(),
      })
      return data
    })
    .catch((err: unknown) => {
      const message = err instanceof Error ? err.message : 'Could not read conditions from your records.'
      setSnap({
        status: 'error',
        error: message,
        startedAt: null,
      })
      throw err
    })
    .finally(() => {
      inflight = null
    })

  return inflight
}

/** Drop cache after the veteran builds a case so the next visit re-scans. */
export function invalidateCaseCandidates() {
  snapshot = {
    status: 'idle',
    data: null,
    error: null,
    startedAt: null,
    readyAt: null,
  }
  inflight = null
  emit()
}
