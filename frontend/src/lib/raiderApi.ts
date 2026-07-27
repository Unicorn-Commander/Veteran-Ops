/** Rating Raider — the conversational CWO agent's client surface.
 *
 * The chat endpoint (POST /raider/chat) streams Server-Sent Events, which the
 * shared JSON `request()` helper in lib/api.ts can't consume: EventSource can't
 * POST a body, so we POST with `fetch` and read the response body as a stream,
 * buffering across chunks until each `data: {json}\n\n` frame is complete.
 *
 * Auth matches the rest of the app — the Bearer token + active-workspace header
 * from lib/api.ts (getToken / getWorkspace) — so the stream runs RLS-scoped to
 * the veteran and their current workspace exactly like every other call.
 */
import { ApiError, getToken, getWorkspace } from './api'

// Mirrors API_BASE in lib/api.ts — dev proxy and prod both serve the API here.
const API_BASE = '/api'

export interface RaiderChatMessage {
  role: 'user' | 'assistant'
  content: string
}

/** One parsed SSE frame from an agent turn — mirrors backend/app/raider/agent.py:
 *  - tool    : an engine started / finished running (drives the "working…" chips)
 *  - token   : a piece of the streaming answer (append it)
 *  - replace : swap the whole answer just streamed (legal-lane correction; rare)
 *  - done    : the turn is complete
 */
export type RaiderStreamEvent =
  | { type: 'tool'; name: string; status: 'start' | 'done' }
  | { type: 'token'; text: string }
  | { type: 'replace'; text: string }
  | { type: 'ui'; action: { type: 'navigate'; route: string } }
  | { type: 'done' }

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  const token = getToken()
  const workspace = getWorkspace()
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (workspace) headers['X-Workspace-Id'] = workspace
  return headers
}

/** Is the agent available? (the LLM gateway must be configured server-side.)
 * Never throws for an "off" backend — it returns `{ available: false }`; it only
 * throws (ApiError) on a network/transport failure the caller may want to retry. */
export async function raiderStatus(signal?: AbortSignal): Promise<{ available: boolean }> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/raider/status`, { headers: authHeaders(), signal })
  } catch {
    throw new ApiError(0, 'Cannot reach Rating Raider. Please check your connection and try again.')
  }
  if (!res.ok) return { available: false }
  try {
    const data = (await res.json()) as { available?: boolean }
    return { available: Boolean(data?.available) }
  } catch {
    return { available: false }
  }
}

/** Parse one SSE frame (the text between blank-line delimiters) — which may carry
 * one or more `data:` lines — into its JSON payload. Returns null for a comment,
 * heartbeat, or a frame whose payload isn't the event JSON we expect. */
function parseFrame(frame: string): RaiderStreamEvent | null {
  const dataLines = frame
    .split('\n')
    .filter((l) => l.startsWith('data:'))
    .map((l) => l.slice(5).replace(/^ /, '')) // one optional leading space per the SSE spec
  if (dataLines.length === 0) return null
  const payload = dataLines.join('\n')
  if (!payload || payload === '[DONE]') return null
  try {
    const obj = JSON.parse(payload) as RaiderStreamEvent
    return obj && typeof obj.type === 'string' ? obj : null
  } catch {
    return null
  }
}

/** Stream one assistant turn. POSTs the running conversation (send the last ~24
 * turns) and yields each parsed event as it arrives, buffering partial chunks
 * until a full `\n\n`-delimited frame is available. Pass an AbortSignal to cancel
 * (stop button / unmount) — cancellation ends the generator quietly.
 *
 * Throws ApiError on a failed handshake (network, 503 not-configured, non-2xx).
 * Once the stream is open the backend itself never 500s mid-turn — on an internal
 * error it emits a graceful token + a `done`, which flow through like any event. */
export async function* streamRaiderChat(
  messages: RaiderChatMessage[],
  signal?: AbortSignal,
): AsyncGenerator<RaiderStreamEvent> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/raider/chat`, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ messages }),
      signal,
    })
  } catch {
    if (signal?.aborted) return
    throw new ApiError(0, 'Cannot reach Rating Raider. Please check your connection and try again.')
  }

  const stream = res.body
  if (!res.ok || !stream) {
    if (res.status === 503) throw new ApiError(503, 'The assistant is not available right now.')
    throw new ApiError(res.status || 0, `Request failed (${res.status})`)
  }

  const reader = stream.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      let chunk: ReadableStreamReadResult<Uint8Array>
      try {
        chunk = await reader.read()
      } catch (err) {
        if (signal?.aborted) return // aborted read — end quietly
        throw err
      }
      if (chunk.done) break
      buffer += decoder.decode(chunk.value, { stream: true })
      // SSE frames are separated by a blank line; normalize CRLF defensively.
      buffer = buffer.replace(/\r\n/g, '\n')
      let sep = buffer.indexOf('\n\n')
      while (sep !== -1) {
        const frame = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        const event = parseFrame(frame)
        if (event) yield event
        sep = buffer.indexOf('\n\n')
      }
    }
    // Flush a trailing frame that arrived without a closing blank line.
    const tail = (buffer + decoder.decode()).trim()
    if (tail) {
      const event = parseFrame(tail)
      if (event) yield event
    }
  } finally {
    reader.releaseLock()
    // Best-effort: stop the body if the consumer broke early (abort/unmount).
    try {
      await stream.cancel()
    } catch {
      /* already closed */
    }
  }
}
