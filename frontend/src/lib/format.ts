// Small formatting helpers used across screens.

/** Format an ISO date string as a human date, gracefully handling null. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value}%`
}

/** Human file size, e.g. 1536000 -> "1.5 MB". */
export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB']
  let n = bytes
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

/** Human label for a snake_case status/kind/category value. */
export function humanize(value: string | null | undefined): string {
  if (!value) return '—'
  return titleCase(value)
}

/** Extract the best-guess display text from a loosely-typed step/gap dict
 * returned by a sibling agent's endpoint. Tries common keys first, then
 * falls back to a readable stringification so the UI never crashes on an
 * unexpected shape. */
export function dictText(step: Record<string, unknown>): string {
  const keys = ['text', 'description', 'label', 'detail', 'note', 'message', 'title']
  for (const k of keys) {
    const v = step[k]
    if (typeof v === 'string' && v.trim()) return v
  }
  const parts: string[] = []
  for (const [k, v] of Object.entries(step)) {
    if (v === null || v === undefined) continue
    if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
      parts.push(`${titleCase(k)}: ${v}`)
    }
  }
  return parts.length ? parts.join(' · ') : JSON.stringify(step)
}

/** Turn a provenance value — which the comprehension backend emits as an object
 * (a single {document_id, page, segment, …} ref) or a list of them, and older
 * payloads as a plain string — into ONE humane, plain-language source line.
 *
 * This is a crash guard as much as a formatter: rendering a provenance object (or
 * an array of them) as a raw React child throws "Objects are not valid as a React
 * child" and, with no error boundary above the route, blanks the whole app. Every
 * provenance render site MUST route through this. Prefers page numbers (what a
 * veteran can actually find); falls back to an honest source count. */
export function formatProvenance(value: unknown): string | null {
  if (value == null) return null
  if (typeof value === 'string') return value.trim() || null
  const refs = (Array.isArray(value) ? value : [value]).filter(
    (r): r is Record<string, unknown> => !!r && typeof r === 'object',
  )
  if (refs.length === 0) return null
  const pages = Array.from(
    new Set(
      refs
        .map((r) => (typeof r.page === 'number' ? r.page : null))
        .filter((p): p is number => p != null),
    ),
  ).sort((a, b) => a - b)
  if (pages.length > 0) {
    const shown = pages.slice(0, 4).map((p) => `p. ${p}`)
    const more = pages.length > 4 ? ` +${pages.length - 4} more` : ''
    return `${pages.length === 1 ? 'page' : 'pages'} ${shown.map((s) => s.replace('p. ', '')).join(', ')}${more} of your file`
  }
  return refs.length === 1 ? 'found in your records' : `found in ${refs.length} places in your file`
}

/** Read the first array found either at the top level or under one of the
 * given keys — defensive against a sibling-agent endpoint returning either a
 * bare array or a wrapped object. */
export function asArray<T>(data: unknown, ...keys: string[]): T[] {
  if (Array.isArray(data)) return data as T[]
  if (data && typeof data === 'object') {
    for (const k of keys) {
      const v = (data as Record<string, unknown>)[k]
      if (Array.isArray(v)) return v as T[]
    }
  }
  return []
}
