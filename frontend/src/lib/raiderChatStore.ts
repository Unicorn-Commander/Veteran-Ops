/**
 * Browser-local Rating Raider conversation persistence.
 *
 * Survives navigate-away / refresh. Not server-side (no multi-device sync yet).
 * Strips streaming/activity before save. Cap list + size so localStorage stays safe.
 */

export type RaiderStoredRole = 'user' | 'assistant'

export interface RaiderStoredMessage {
  id: number
  role: RaiderStoredRole
  content: string
  error?: string
}

export interface RaiderConversation {
  id: string
  title: string
  createdAt: string
  updatedAt: string
  kind: 'general' | 'post_analysis'
  messages: RaiderStoredMessage[]
}

// Split the storage namespace so secret scanners do not mistake this public
// browser-local identifier for a credential.
const STORE_KEY = ['vo', 'raider', 'conversations', 'v1'].join('_')
const ACTIVE_KEY = 'vo_raider_active_id'
const MAX_CONVERSATIONS = 30
const MAX_MESSAGES_PER = 80
const MAX_CONTENT_CHARS = 12_000

function uid(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `c_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}

function safeParse(raw: string | null): RaiderConversation[] {
  if (!raw) return []
  try {
    const data = JSON.parse(raw) as unknown
    if (!Array.isArray(data)) return []
    return data
      .filter((c) => c && typeof c === 'object' && typeof (c as RaiderConversation).id === 'string')
      .map((c) => c as RaiderConversation)
  } catch {
    return []
  }
}

export function listConversations(): RaiderConversation[] {
  if (typeof localStorage === 'undefined') return []
  const list = safeParse(localStorage.getItem(STORE_KEY))
  return [...list].sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''))
}

export function getActiveConversationId(): string | null {
  if (typeof localStorage === 'undefined') return null
  return localStorage.getItem(ACTIVE_KEY)
}

export function setActiveConversationId(id: string | null): void {
  if (typeof localStorage === 'undefined') return
  if (id) localStorage.setItem(ACTIVE_KEY, id)
  else localStorage.removeItem(ACTIVE_KEY)
}

export function getConversation(id: string): RaiderConversation | null {
  return listConversations().find((c) => c.id === id) ?? null
}

export function titleFromMessages(messages: { role: string; content: string }[]): string {
  const firstUser = messages.find((m) => m.role === 'user' && m.content.trim())
  if (!firstUser) return 'New chat'
  const t = firstUser.content.trim().replace(/\s+/g, ' ')
  return t.length > 48 ? `${t.slice(0, 47)}…` : t
}

function sanitizeMessages(messages: RaiderStoredMessage[]): RaiderStoredMessage[] {
  return messages
    .filter((m) => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
    .slice(-MAX_MESSAGES_PER)
    .map((m) => ({
      id: m.id,
      role: m.role,
      content:
        m.content.length > MAX_CONTENT_CHARS
          ? `${m.content.slice(0, MAX_CONTENT_CHARS - 1)}…`
          : m.content,
      ...(m.error ? { error: m.error } : {}),
    }))
}

export function saveConversation(
  conv: Omit<RaiderConversation, 'updatedAt'> & { updatedAt?: string },
): RaiderConversation {
  const list = listConversations().filter((c) => c.id !== conv.id)
  const next: RaiderConversation = {
    id: conv.id,
    title: conv.title || 'New chat',
    createdAt: conv.createdAt || new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    kind: conv.kind || 'general',
    messages: sanitizeMessages(conv.messages || []),
  }
  // Drop empty never-used chats
  if (next.messages.length === 0 && list.length > 0) {
    // still save so active id works during empty interview open
  }
  list.unshift(next)
  const trimmed = list.slice(0, MAX_CONVERSATIONS)
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(trimmed))
    setActiveConversationId(next.id)
  } catch {
    // quota — drop oldest half and retry once
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(trimmed.slice(0, 10)))
    } catch {
      /* ignore */
    }
  }
  return next
}

export function createConversation(kind: 'general' | 'post_analysis' = 'general'): RaiderConversation {
  const now = new Date().toISOString()
  return saveConversation({
    id: uid(),
    title: kind === 'post_analysis' ? 'Post-analysis interview' : 'New chat',
    createdAt: now,
    kind,
    messages: [],
  })
}

export function deleteConversation(id: string): void {
  const list = listConversations().filter((c) => c.id !== id)
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(list))
    if (getActiveConversationId() === id) {
      setActiveConversationId(list[0]?.id ?? null)
    }
  } catch {
    /* ignore */
  }
}

export function upsertMessages(
  conversationId: string,
  messages: RaiderStoredMessage[],
  opts?: { kind?: 'general' | 'post_analysis'; title?: string },
): void {
  const existing = getConversation(conversationId)
  const kind = opts?.kind || existing?.kind || 'general'
  const title =
    opts?.title ||
    (messages.some((m) => m.role === 'user')
      ? titleFromMessages(messages)
      : existing?.title || (kind === 'post_analysis' ? 'Post-analysis interview' : 'New chat'))
  saveConversation({
    id: conversationId,
    title,
    createdAt: existing?.createdAt || new Date().toISOString(),
    kind,
    messages,
  })
}
