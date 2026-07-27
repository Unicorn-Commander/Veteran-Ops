// Wave 13 — ORG CASELOAD API client.
//
// The low-level `request` helper in ../lib/api is module-private, so this module
// re-implements a small typed `req()` that mirrors its header + error
// conventions exactly (Bearer token + X-Workspace-Id, JSON `detail` parsing).
// Only the NEW case/consent/note/audit endpoints live here; org + entitlement
// management still comes from `orgsApi` / `entitlementsApi` in ../lib/api.
//
// ⚖️ LEGAL LANE: a "case" is the org's file for ASSISTING a veteran with their
// claim — educational self-help. It is NOT VA power of attorney. Formally
// representing a veteran before the VA requires VA accreditation + appointment
// via VA Form 21-22 (VSO) / 21-22a (agent/attorney). Consent captured here is
// app-level assist authorization only, and the API requires
// `acknowledged_not_poa: true` or it 400s.

import { ApiError, getToken, getWorkspace } from '../lib/api'

const API_BASE = '/api'

// ---- Types ----

export type CaseStatus = 'intake' | 'active' | 'filed' | 'closed'
export type ConsentStatus = 'none' | 'granted' | 'revoked'
export type ConsentMethod = 'in_person' | 'written' | 'verbal' | 'portal'

export interface CaseAssignee {
  user_id: string
  email: string
  full_name: string
}

export interface Case {
  id: string
  veteran_name: string
  veteran_email: string | null
  veteran_phone: string | null
  status: CaseStatus
  consent_status: ConsentStatus
  summary: string | null
  assignees: CaseAssignee[]
  note_count: number
  created_at: string
  updated_at: string
}

export interface Consent {
  id: string
  case_id: string
  method: ConsentMethod
  scope: string | null
  statement: string | null
  granted_by_name: string
  captured_by: string | null
  status: 'granted' | 'revoked'
  granted_at: string
  revoked_at: string | null
}

export interface CaseNote {
  id: string
  case_id: string
  author_id: string | null
  author_email: string
  body: string
  created_at: string
}

export interface AuditEntry {
  id: string
  action: string
  entity: string | null
  entity_id: string | null
  actor_user_id: string | null
  actor_email: string
  meta: Record<string, unknown> | null
  created_at: string
}

// ---- Request bodies ----

export interface CaseCreateInput {
  veteran_name: string
  veteran_email?: string
  veteran_phone?: string
  summary?: string
}

export interface CaseUpdateInput {
  veteran_name?: string
  veteran_email?: string | null
  veteran_phone?: string | null
  status?: CaseStatus
  summary?: string | null
}

export interface ConsentInput {
  method: ConsentMethod
  granted_by_name: string
  statement?: string
  scope?: string
  acknowledged_not_poa: boolean
}

// ---- Low-level request helper (mirrors ../lib/api authHeaders + parseError) ----

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const token = getToken()
  const workspace = getWorkspace()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (workspace) headers['X-Workspace-Id'] = workspace
  return { ...headers, ...extra }
}

async function parseError(res: Response): Promise<ApiError> {
  let detail: unknown
  let message = `Request failed (${res.status})`
  try {
    const data = await res.json()
    detail = data
    if (typeof data?.detail === 'string') message = data.detail
    else if (Array.isArray(data?.detail) && data.detail[0]?.msg)
      message = data.detail.map((d: { msg: string }) => d.msg).join(', ')
    else if (typeof data?.message === 'string') message = data.message
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, message, detail)
}

interface ReqOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
}

async function req<T>(path: string, opts: ReqOptions = {}): Promise<T> {
  const { body, headers, ...rest } = opts
  const init: RequestInit = { ...rest }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = authHeaders({ 'Content-Type': 'application/json', ...(headers as Record<string, string>) })
  } else {
    init.headers = authHeaders(headers as Record<string, string>)
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, init)
  } catch {
    throw new ApiError(0, 'Cannot reach Rating Raider. Please check your connection and try again.')
  }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

// ---- Cases ----

export const casesApi = {
  list: () => req<Case[]>('/cases'),
  create: (body: CaseCreateInput) => req<Case>('/cases', { method: 'POST', body }),
  get: (id: string) => req<Case>(`/cases/${id}`),
  update: (id: string, body: CaseUpdateInput) =>
    req<Case>(`/cases/${id}`, { method: 'PATCH', body }),
  assign: (id: string, userId: string) =>
    req<Case>(`/cases/${id}/assignees`, { method: 'POST', body: { user_id: userId } }),
  unassign: (id: string, userId: string) =>
    req<void>(`/cases/${id}/assignees/${userId}`, { method: 'DELETE' }),
  getConsent: (id: string) => req<Consent | null>(`/cases/${id}/consent`),
  captureConsent: (id: string, body: ConsentInput) =>
    req<Consent>(`/cases/${id}/consent`, { method: 'POST', body }),
  revokeConsent: (id: string) =>
    req<Case>(`/cases/${id}/consent/revoke`, { method: 'POST', body: {} }),
  notes: (id: string) => req<CaseNote[]>(`/cases/${id}/notes`),
  addNote: (id: string, body: string) =>
    req<CaseNote>(`/cases/${id}/notes`, { method: 'POST', body: { body } }),
}

// ---- Org audit trail (ADMIN+) ----

export const auditApi = {
  list: (limit = 100) => req<AuditEntry[]>(`/orgs/current/audit?limit=${limit}`),
}
