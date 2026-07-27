/**
 * Session-scoped "analyze after this upload batch finishes" state.
 *
 * Documents used to keep opt-in + pending IDs only in React state. Leaving the
 * page dropped the request, so full analysis never started (or the banner
 * vanished even when the backend job was still running). This store:
 *  - persists pending doc IDs + run id in sessionStorage
 *  - keeps a single background poller (mounted from Shell) that starts the
 *    comprehensive run once every pending doc leaves uploaded/processing
 *  - notifies UI subscribers so Documents / Analysis can show status
 */

import { analysisApi, documentsApi } from './api'
import { errorMessage } from '../hooks/useAsync'

const STORAGE_KEY = 'vo_deferred_analysis_v1'
const POLL_MS = 3000

export type DeferredAnalysisPhase =
  | 'idle'
  | 'waiting' // opted in; waiting for batch to finish processing
  | 'starting'
  | 'running' // comprehensive run enqueued / in flight
  | 'error'

export interface DeferredAnalysisSnapshot {
  phase: DeferredAnalysisPhase
  /** Document ids that must settle before we start analysis. */
  pendingIds: string[]
  runId: string | null
  error: string | null
  /** Checkbox preference for the next upload (not necessarily waiting). */
  optIn: boolean
}

type Listener = (snap: DeferredAnalysisSnapshot) => void

interface Stored {
  pendingIds: string[]
  runId: string | null
  optIn: boolean
  error: string | null
  phase: DeferredAnalysisPhase
}

function readStored(): Stored | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Stored
    if (!parsed || typeof parsed !== 'object') return null
    return {
      pendingIds: Array.isArray(parsed.pendingIds) ? parsed.pendingIds.map(String) : [],
      runId: parsed.runId ? String(parsed.runId) : null,
      optIn: Boolean(parsed.optIn),
      error: parsed.error ? String(parsed.error) : null,
      phase: (parsed.phase as DeferredAnalysisPhase) || 'idle',
    }
  } catch {
    return null
  }
}

function writeStored(s: Stored) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(s))
  } catch {
    /* private mode / quota */
  }
}

function loadInitial(): DeferredAnalysisSnapshot {
  const s = readStored()
  if (!s) {
    return { phase: 'idle', pendingIds: [], runId: null, error: null, optIn: false }
  }
  // Resume waiting/running after navigation; drop stale "starting".
  let phase = s.phase
  if (phase === 'starting') phase = s.pendingIds.length ? 'waiting' : s.runId ? 'running' : 'idle'
  if (phase === 'running' && !s.runId) phase = 'idle'
  if (phase === 'waiting' && s.pendingIds.length === 0) phase = 'idle'
  return {
    phase,
    pendingIds: s.pendingIds,
    runId: s.runId,
    error: s.error,
    optIn: s.optIn,
  }
}

let snapshot: DeferredAnalysisSnapshot = loadInitial()
const listeners = new Set<Listener>()
let pollTimer: number | null = null
let starting = false

function emit() {
  const snap = { ...snapshot, pendingIds: [...snapshot.pendingIds] }
  writeStored({
    pendingIds: snap.pendingIds,
    runId: snap.runId,
    optIn: snap.optIn,
    error: snap.error,
    phase: snap.phase,
  })
  for (const l of listeners) l(snap)
}

function setSnap(partial: Partial<DeferredAnalysisSnapshot>) {
  snapshot = {
    ...snapshot,
    ...partial,
    pendingIds: partial.pendingIds ? [...partial.pendingIds] : snapshot.pendingIds,
  }
  emit()
}

export function getDeferredAnalysisSnapshot(): DeferredAnalysisSnapshot {
  return { ...snapshot, pendingIds: [...snapshot.pendingIds] }
}

export function subscribeDeferredAnalysis(listener: Listener): () => void {
  listeners.add(listener)
  listener(getDeferredAnalysisSnapshot())
  return () => {
    listeners.delete(listener)
  }
}

/** Checkbox on Documents — preference for the *next* upload. */
export function setAnalyzeAfterUploadOptIn(optIn: boolean) {
  setSnap({ optIn })
}

/**
 * After an opted-in upload batch is accepted, watch these document ids.
 * Clears any previous wait for a new batch.
 */
export function armDeferredAnalysis(documentIds: string[]) {
  const ids = [...new Set(documentIds.filter(Boolean))]
  if (ids.length === 0) return
  starting = false
  setSnap({
    phase: 'waiting',
    pendingIds: ids,
    runId: null,
    error: null,
    optIn: true,
  })
  ensureDeferredAnalysisPoller()
}

export function clearDeferredAnalysis() {
  starting = false
  setSnap({ phase: 'idle', pendingIds: [], runId: null, error: null })
  stopPoller()
}

async function tick() {
  if (snapshot.phase === 'running' && snapshot.runId) {
    // Optional: check if run finished so we can clear the banner later.
    try {
      const run = await analysisApi.comprehensiveRun(snapshot.runId)
      if (run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled') {
        // Keep runId so UI can still deep-link; mark idle so we don't re-start.
        setSnap({ phase: 'idle', pendingIds: [] })
        stopPoller()
      }
    } catch {
      /* keep waiting */
    }
    return
  }

  if (snapshot.phase !== 'waiting' || snapshot.pendingIds.length === 0 || starting) return

  const ids = new Set(snapshot.pendingIds)
  let rows
  try {
    rows = await documentsApi.list()
  } catch {
    return
  }
  const batch = rows.filter((d) => ids.has(d.id))
  // Wait until we can see every id (list may lag right after upload).
  if (batch.length < ids.size) return
  if (batch.some((d) => d.status === 'uploaded' || d.status === 'processing')) return

  // Nothing ready → don't start analysis; clear wait.
  if (!batch.some((d) => d.status === 'ready')) {
    setSnap({ phase: 'idle', pendingIds: [], error: null })
    stopPoller()
    return
  }

  starting = true
  setSnap({ phase: 'starting', error: null })
  try {
    const run = await analysisApi.startComprehensive()
    setSnap({
      phase: 'running',
      pendingIds: [],
      runId: run.id,
      error: null,
    })
  } catch (err) {
    setSnap({
      phase: 'error',
      pendingIds: [],
      runId: null,
      error: errorMessage(err),
    })
    stopPoller()
  } finally {
    starting = false
  }
}

function stopPoller() {
  if (pollTimer != null) {
    window.clearInterval(pollTimer)
    pollTimer = null
  }
}

/** Idempotent — Shell calls this while the user is signed in. */
export function ensureDeferredAnalysisPoller() {
  if (typeof window === 'undefined') return
  if (pollTimer != null) return
  if (snapshot.phase !== 'waiting' && snapshot.phase !== 'running' && snapshot.phase !== 'starting') {
    return
  }
  void tick()
  pollTimer = window.setInterval(() => {
    void tick()
  }, POLL_MS)
}

/** Call from Shell on auth mount so a pending wait resumes after refresh. */
export function resumeDeferredAnalysisIfNeeded() {
  if (snapshot.phase === 'waiting' || snapshot.phase === 'running' || snapshot.phase === 'starting') {
    ensureDeferredAnalysisPoller()
  }
}
