import type {
  AppealCandidatesOut,
  AppealDraftInput,
  AppealDraftOut,
  AppMeta,
  DocumentReviewQueueItem,
  DocumentReviewOut,
  ReconcileInput,
  ReconcileResult,
  WorkspacePrivacyOut,
  PiiCloudConsentOut,
  AuthConfig,
  AuthResponse,
  BillingStatus,
  CheckoutSessionInput,
  CheckoutSessionResponse,
  ConcurrentPay,
  CreditsResponse,
  GrantApplication,
  GrantApplicationInput,
  GrantApplicationReviewInput,
  AdminGrants,
  Entitlements,
  PlansResponse,
  Invite,
  InvitePreview,
  Org,
  OrgMember,
  OrgRole,
  ServiceOverrides,
  ServiceSettingsOut,
  SimpleMessage,
  TestConnectionInput,
  TestConnectionOut,
  WorkspacesResponse,
  CorrectionDraftInput,
  CorrectionPacket,
  CorrectionRouteResult,
  CorrectionSituationInput,
  RankAnalysisIn,
  RankAnalysisOut,
  RankGuidanceOut,
  DependencyGuidance,
  DependencyWorksheet,
  DependencyWorksheetInput,
  DeepDiveResult,
  DecisionStatusApplyOut,
  CaseBrief,
  DuplicateCluster,
  GamePlanOut,
  GamePlanBriefing,
  InterviewSeed,
  BackpayInput,
  BackpayResult,
  BenefitsOut,
  ChecklistInput,
  ChecklistItem,
  ClaimedCondition,
  ClaimedConditionInput,
  CombinedResult,
  BuddyDraft,
  BuddyDraftInput,
  BuddyGuidance,
  BuddySituationBrief,
  BuddySituationBriefInput,
  CpCompanion,
  CpCondition,
  Form526Packet,
  NexusDraft,
  NexusDraftInput,
  NexusGuidance,
  NexusProviderBrief,
  NexusProviderBriefInput,
  StatementDraft,
  StatementDraftInput,
  StatementGuidance,
  TdiuScreen,
  TdiuWorksheet,
  TdiuWorksheetInput,
  DecodeResult,
  ItfInput,
  ItfRecord,
  ItfResult,
  DeadlinesResult,
  ReadinessResult,
  SymptomCriteria,
  SymptomLogEntry,
  SymptomLogEntryInput,
  SymptomLogExport,
  SymptomLogImportResult,
  DocumentItem,
  DocGuidanceResponse,
  DocumentLinkInput,
  DocumentLinkResult,
  DocumentSearchResult,
  DocumentSummary,
  DocumentUpdateInput,
  DocumentUploadResult,
  ReindexResult,
  ReprocessFailedResult,
  ResetRecords,
  EvidenceInput,
  EvidenceItem,
  GapsResponse,
  GlitterCondition,
  GlitterImportResult,
  GlitterLab,
  GlitterStatus,
  GlitterVital,
  HealthStatus,
  KbCard,
  LegalDocs,
  BackfillDiagnosisResult,
  BuildCaseResult,
  CaseCandidateInput,
  CaseCandidatesResult,
  MapConditionsResponse,
  IdentitySuggestions,
  PacketData,
  PresumptivesResponse,
  ComprehensiveAnalysisResult,
  AnalysisRun,
  AnalysisPrerequisites,
  IntakeBenchmark,
  CasePictureResponse,
  AutomationStatus,
  FileReadiness,
  LandscapeScan,
  WhatsChanged,
  Profile,
  RatingEntry,
  RatingScenario,
  RecordsPrefill,
  RequestLetterInput,
  RequestLetterResponse,
  SecondariesResponse,
  User,
  VaApiKey,
  VaApplyInput,
  VaApplyResult,
  VaClaimsResult,
  VaItf,
  VaReconcileInput,
  VaReconcileResult,
  VaStatus,
  VaSyncResult,
  FormPreview,
} from '../types'

const TOKEN_KEY = 'vo_token'
const WORKSPACE_KEY = 'vo_workspace'
const API_BASE = '/api'

// ---- Token storage ----

export function getToken(): string | null {
  try {
    const current = sessionStorage.getItem(TOKEN_KEY)
    if (current) return current
    // One-time migration from the former persistent bearer storage. Keeping the
    // session in this tab preserves active users while removing the long-lived XSS
    // prize from localStorage.
    const legacy = localStorage.getItem(TOKEN_KEY)
    if (legacy) {
      sessionStorage.setItem(TOKEN_KEY, legacy)
      localStorage.removeItem(TOKEN_KEY)
    }
    return legacy
  } catch {
    return null
  }
}

// ---- Active workspace (tenant) selection ----
// The chosen workspace id is echoed on every request as `X-Workspace-Id`; the backend
// honors it only when the caller is a member (else it falls back to their personal
// workspace), so a stale/forged value can never reach another tenant's data.

export function getWorkspace(): string | null {
  try {
    return localStorage.getItem(WORKSPACE_KEY)
  } catch {
    return null
  }
}

export function setWorkspace(id: string | null): void {
  try {
    if (id) localStorage.setItem(WORKSPACE_KEY, id)
    else localStorage.removeItem(WORKSPACE_KEY)
  } catch {
    /* storage unavailable — non-fatal */
  }
}

export function setToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token)
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable (private mode) — non-fatal */
  }
}

export function clearToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* noop */
  }
}

// ---- Error type ----

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** Listeners notified when a 401 indicates the session is gone. */
type UnauthorizedHandler = () => void
let onUnauthorized: UnauthorizedHandler | null = null
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null) {
  onUnauthorized = handler
}

/** Listeners notified when a credit-gated action hits 402. The shell uses this
 * to surface a billing escape hatch without every caller inventing its own. */
type PaymentRequiredHandler = (error: ApiError) => void
let onPaymentRequired: PaymentRequiredHandler | null = null
export function setPaymentRequiredHandler(handler: PaymentRequiredHandler | null) {
  onPaymentRequired = handler
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken()
  const workspace = getWorkspace()
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  if (workspace) headers['X-Workspace-Id'] = workspace
  return { ...headers, ...(extra as Record<string, string>) }
}

async function parseError(res: Response): Promise<ApiError> {
  let detail: unknown
  let message = `Request failed (${res.status})`
  try {
    const data = await res.json()
    detail = data
    if (typeof data?.detail === 'string') message = data.detail
    else if (typeof data?.detail?.message === 'string') message = data.detail.message
    else if (Array.isArray(data?.detail) && data.detail[0]?.msg)
      message = data.detail.map((d: { msg: string }) => d.msg).join(', ')
    else if (typeof data?.message === 'string') message = data.message
  } catch {
    /* non-JSON error body */
  }
  return new ApiError(res.status, message, detail)
}

interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  notifyPaymentRequired?: boolean
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { body, headers, notifyPaymentRequired, ...rest } = opts

  let init: RequestInit = { ...rest }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = authHeaders({ 'Content-Type': 'application/json', ...headers })
  } else {
    init.headers = authHeaders(headers)
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, init)
  } catch {
    throw new ApiError(0, 'Cannot reach Rating Raider. Please check your connection and try again.')
  }

  if (res.status === 401) {
    onUnauthorized?.()
    throw await parseError(res)
  }
  if (res.status === 402) {
    const err = await parseError(res)
    if (notifyPaymentRequired) onPaymentRequired?.(err)
    throw err
  }
  if (!res.ok) throw await parseError(res)

  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

/** Multipart POST — used only by document upload, where a JSON body won't do. */
async function requestForm<T>(path: string, form: FormData, notifyPaymentRequired = false): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { method: 'POST', body: form, headers: authHeaders() })
  } catch {
    throw new ApiError(0, 'Cannot reach Rating Raider. Please check your connection and try again.')
  }
  if (res.status === 401) {
    onUnauthorized?.()
    throw await parseError(res)
  }
  if (res.status === 402) {
    const err = await parseError(res)
    if (notifyPaymentRequired) onPaymentRequired?.(err)
    throw err
  }
  if (!res.ok) throw await parseError(res)
  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

/** GET a binary endpoint and save it as a file download (used for the filled
 * 21-526EZ PDF — the shared `request` helper JSON-parses, which a PDF isn't). */
async function downloadBlob(path: string, filename: string): Promise<void> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() })
  } catch {
    throw new ApiError(0, 'Cannot reach Rating Raider. Please check your connection and try again.')
  }
  if (res.status === 401) {
    onUnauthorized?.()
    throw await parseError(res)
  }
  if (!res.ok) throw await parseError(res)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function fetchBlob(path: string): Promise<Blob> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() })
  } catch {
    throw new ApiError(0, 'Cannot reach Rating Raider. Please check your connection and try again.')
  }
  if (res.status === 401) {
    onUnauthorized?.()
    throw await parseError(res)
  }
  if (!res.ok) throw await parseError(res)
  return res.blob()
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function qs(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') usp.set(k, String(v))
  }
  const s = usp.toString()
  return s ? `?${s}` : ''
}

// ---- Auth ----

export const auth = {
  config: () => request<AuthConfig>('/auth/config'),
  register: (body: { email: string; password: string; full_name: string }) =>
    request<AuthResponse>('/auth/register', { method: 'POST', body }),
  login: (body: { email: string; password: string }) =>
    request<AuthResponse>('/auth/login', { method: 'POST', body }),
  me: () => request<User>('/auth/me'),
  // Email verification
  requestVerification: () =>
    request<SimpleMessage>('/auth/verify-email/request', { method: 'POST', body: {} }),
  confirmVerification: (token: string) =>
    request<SimpleMessage>('/auth/verify-email/confirm', { method: 'POST', body: { token } }),
  // Password reset (both unauthenticated)
  forgotPassword: (email: string) =>
    request<SimpleMessage>('/auth/password/forgot', { method: 'POST', body: { email } }),
  resetPassword: (token: string, password: string) =>
    request<SimpleMessage>('/auth/password/reset', { method: 'POST', body: { token, password } }),
}

// ---- Workspaces / tenancy (Wave 11) ----
export const workspacesApi = {
  list: () => request<WorkspacesResponse>('/workspaces'),
}

// ---- Organizations / teams (Wave 12) ----
// Management endpoints act on the ACTIVE workspace ("current"): switch to a team
// (setWorkspace) before calling them. Callers degrade gracefully on 404 (older backend).
export const orgsApi = {
  list: () => request<Org[]>('/orgs'),
  create: (name: string) => request<Org>('/orgs', { method: 'POST', body: { name } }),
  current: () => request<Org>('/orgs/current'),
  rename: (name: string) => request<Org>('/orgs/current', { method: 'PATCH', body: { name } }),
  members: () => request<OrgMember[]>('/orgs/current/members'),
  setMemberRole: (userId: string, role: OrgRole) =>
    request<OrgMember>(`/orgs/current/members/${userId}`, { method: 'PATCH', body: { role } }),
  removeMember: (userId: string) =>
    request<void>(`/orgs/current/members/${userId}`, { method: 'DELETE' }),
  invites: () => request<Invite[]>('/orgs/current/invites'),
  invite: (email: string, role: OrgRole) =>
    request<Invite>('/orgs/current/invites', { method: 'POST', body: { email, role } }),
  revokeInvite: (inviteId: string) =>
    request<void>(`/orgs/current/invites/${inviteId}`, { method: 'DELETE' }),
}

// ---- Invitations: preview + accept by token (Wave 12) ----
export const invitesApi = {
  preview: (token: string) => request<InvitePreview>(`/invites${qs({ token })}`),
  accept: (token: string) =>
    request<Org>(`/invites/accept${qs({ token })}`, { method: 'POST', body: {} }),
}

// ---- Entitlements: active-workspace tier/role/features (Wave 12) ----
export const entitlementsApi = {
  get: () => request<Entitlements>('/entitlements'),
}

// ---- Billing / plans (Wave 14) ----
// Read-only from the UI: the plan catalog + the active workspace's status.
// In-app checkout isn't live — the page links to the suite's billing portal
// (Lago) when configured. The service-only POST /billing/tenant-tier is NOT
// exposed here; it's for the billing service, not the app.
export const billingApi = {
  plans: () => request<PlansResponse>('/billing/plans'),
  status: () => request<BillingStatus>('/billing/status'),
  checkoutSession: (body: CheckoutSessionInput) =>
    request<CheckoutSessionResponse>('/billing/checkout-session', { method: 'POST', body }),
}

export const creditsApi = {
  get: () => request<CreditsResponse>('/credits'),
  grantApplications: () => request<GrantApplication[]>('/credits/grant-applications'),
  submitGrantApplication: (body: GrantApplicationInput) =>
    request<GrantApplication>('/credits/grant-applications', { method: 'POST', body }),
  adminGrants: () => request<AdminGrants>('/credits/admin/grant-applications'),
  reviewGrantApplication: (id: string, body: GrantApplicationReviewInput) =>
    request<GrantApplication>(`/credits/admin/grant-applications/${id}`, { method: 'PATCH', body }),
}

// Full-page redirect into the Keycloak (uchub) SSO login. The API contract
// only defines the keycloak endpoints (no /auth/config), so the button is
// always shown; if SSO isn't configured server-side, the redirect 404s
// gracefully back to the callback's error state rather than crashing.
export function ssoLoginUrl(): string {
  return `${API_BASE}/auth/keycloak`
}

// ---- Profile ----

export const profileApi = {
  get: () => request<Profile>('/profile'),
  update: (body: Profile) => request<Profile>('/profile', { method: 'PUT', body }),
  /** GET /profile/identity-suggestions — best-effort identity the intake pipeline
   * read from the veteran's uploaded records, aggregated into one proposal to
   * pre-fill the profile form. Callers degrade silently on 404 (older backend). */
  identitySuggestions: () => request<IdentitySuggestions>('/profile/identity-suggestions'),
  /** GET /profile/location-suggestions — deployment/exposure places found in records. */
  locationSuggestions: () =>
    request<{ locations: string[]; disclaimer: string }>('/profile/location-suggestions'),
  /** POST /profile/reextract-identity — re-scan the veteran's uploaded records for
   * their identity in the background; poll identitySuggestions() for the refresh. */
  reextractIdentity: () => request<SimpleMessage>('/profile/reextract-identity', { method: 'POST' }),
  /** POST /profile/apply-ratings-from-records — apply VA decision percents onto
   * conditions and optional profile combined rating (veteran-initiated). */
  applyRatingsFromRecords: () =>
    request<{
      updated: number
      created: number
      combined: number | null
      message: string
    }>('/profile/apply-ratings-from-records', { method: 'POST' }),
}

// ---- Benefits directory ----

export const benefitsApi = {
  get: (params: { rating?: number; state?: string } = {}) =>
    request<BenefitsOut>(`/benefits${qs(params)}`),
}

// ---- Conditions ----

export const conditionsApi = {
  list: () => request<ClaimedCondition[]>('/conditions'),
  create: (body: Partial<ClaimedConditionInput>) =>
    request<ClaimedCondition>('/conditions', { method: 'POST', body }),
  get: (id: string) => request<ClaimedCondition>(`/conditions/${id}`),
  update: (id: string, body: Partial<ClaimedConditionInput>) =>
    request<ClaimedCondition>(`/conditions/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/conditions/${id}`, { method: 'DELETE' }),
  gaps: (id: string) => request<GapsResponse>(`/conditions/${id}/gaps`),
  /** GET /conditions/duplicates — similar-name clusters for cleanup. */
  duplicates: () => request<{ clusters: DuplicateCluster[]; note?: string }>('/conditions/duplicates'),
  /** POST /conditions/park-duplicates — mark park_ids as decided (file cleanup). */
  parkDuplicates: (body: {
    park_ids: string[]
    keep_id?: string | null
    keep_name?: string | null
  }) =>
    request<{ parked: number; park_ids: string[]; note?: string }>('/conditions/park-duplicates', {
      method: 'POST',
      body,
    }),
}

// ---- Evidence ----

export const evidenceApi = {
  list: (conditionId: string) => request<EvidenceItem[]>(`/conditions/${conditionId}/evidence`),
  create: (conditionId: string, body: Partial<EvidenceInput>) =>
    request<EvidenceItem>(`/conditions/${conditionId}/evidence`, { method: 'POST', body }),
  update: (id: string, body: Partial<EvidenceInput>) =>
    request<EvidenceItem>(`/evidence/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/evidence/${id}`, { method: 'DELETE' }),
  pinCitation: (id: string, body: {
    quote: string
    char_start: number
    char_end: number
    page?: number | null
    chunk_index: number
    note?: string | null
  }) => request<EvidenceItem>(`/evidence/${id}/citation`, { method: 'POST', body }),
  clearCitation: (id: string) => request<void>(`/evidence/${id}/citation`, { method: 'DELETE' }),
}

// ---- Checklist ----

export const checklistApi = {
  list: (params: { condition_id?: string; done?: string } = {}) =>
    request<ChecklistItem[]>(`/checklist${qs(params)}`),
  create: (body: Partial<ChecklistInput>) =>
    request<ChecklistItem>('/checklist', { method: 'POST', body }),
  toggle: (id: string, done: boolean) =>
    request<ChecklistItem>(`/checklist/${id}`, { method: 'PATCH', body: { done } }),
  remove: (id: string) => request<void>(`/checklist/${id}`, { method: 'DELETE' }),
}

// ---- Rating engine ----

export const ratingApi = {
  calculate: (entries: RatingEntry[]) =>
    request<CombinedResult>('/rating/calculate', { method: 'POST', body: { entries } }),
  /** POST /rating/backpay — deterministic educational estimate (routers/
   * rating.py BackpayIn → rating/backpay.py compute_backpay()). */
  backpay: (body: BackpayInput) =>
    request<BackpayResult>('/rating/backpay', { method: 'POST', body }),
  scenarios: {
    list: () => request<RatingScenario[]>('/rating/scenarios'),
    create: (body: { name: string; entries: RatingEntry[] }) =>
      request<RatingScenario>('/rating/scenarios', { method: 'POST', body }),
    remove: (id: string) => request<void>(`/rating/scenarios/${id}`, { method: 'DELETE' }),
  },
}

// ---- KB ----

export const kbApi = {
  cards: (params: { type?: string; body_system?: string; q?: string } = {}) =>
    request<KbCard[]>(`/kb/cards${qs(params)}`),
  card: (id: string) => request<KbCard>(`/kb/cards/${id}`),
  dbq: (condition: string) => request<KbCard[]>(`/kb/dbq${qs({ condition })}`),
}

// ---- Analysis ----

// Both POST bodies take {names: [...]}; an empty list means "use my claimed
// conditions" (AnalysisMapIn / SecondariesIn in backend/app/schemas.py).
export const analysisApi = {
  /** GET cached rating-floor mapping (no compute / no credit). Empty items if never run. */
  getMapConditions: () => request<MapConditionsResponse>('/analysis/map-conditions'),
  /** POST map — uses cache unless force=true (first run or refresh). Saves results. */
  mapConditions: (names: string[] = [], force = false) =>
    request<MapConditionsResponse>(`/analysis/map-conditions${force ? '?force=true' : ''}`, {
      method: 'POST',
      body: { names },
      notifyPaymentRequired: true,
    }),
  secondaries: (names: string[] = []) =>
    request<SecondariesResponse>('/analysis/secondaries', {
      method: 'POST',
      body: { names },
      notifyPaymentRequired: true,
    }),
  presumptives: () => request<PresumptivesResponse>('/analysis/presumptives'),
  comprehensivePrerequisites: () =>
    request<AnalysisPrerequisites>('/analysis/comprehensive/prerequisites'),
  /** POST /analysis/comprehensive — the heavy, one-button full pass (SYNCHRONOUS
   * legacy path; can time out on a big C-file). Kept for back-compat — the
   * Analysis Center now uses startComprehensive() + polling below. */
  comprehensive: () =>
    request<ComprehensiveAnalysisResult>('/analysis/comprehensive', {
      method: 'POST',
      notifyPaymentRequired: true,
    }),
  /** POST /analysis/comprehensive/start — durably enqueue the full pass
   * (202, no request timeout). Returns the AnalysisRun immediately (status
   * "queued", steps pending); poll comprehensiveRun(id) for live progress. */
  startComprehensive: (idempotencyKey: string = crypto.randomUUID()) =>
    request<AnalysisRun>('/analysis/comprehensive/start', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      notifyPaymentRequired: true,
    }),
  /** GET /analysis/comprehensive/runs/{id} — poll one run for live per-step progress. */
  comprehensiveRun: (id: string) => request<AnalysisRun>(`/analysis/comprehensive/runs/${id}`),
  /** Cooperative cancellation; a leased/running worker observes it via heartbeat. */
  cancelComprehensive: (id: string) =>
    request<AnalysisRun>(`/analysis/comprehensive/runs/${id}/cancel`, { method: 'POST' }),
  /** GET /analysis/comprehensive/latest — the most recent run, or null. Used on
   * page load to resume an in-flight run or show the last completed one. */
  latestRun: () => request<AnalysisRun | null>('/analysis/comprehensive/latest'),
  /** GET /analysis/comprehensive/runs — recent runs newest-first (benchmark history). */
  runs: (limit = 10) => request<AnalysisRun[]>(`/analysis/comprehensive/runs${qs({ limit })}`),
  /** GET /analysis/intake-benchmark — approximate document-intake cost (labeled
   * approximate in the UI); pairs with run timings for full time-to-complete. */
  intakeBenchmark: () => request<IntakeBenchmark>('/analysis/intake-benchmark'),
  /** GET /analysis/case-picture — the cached whole-C-file picture (timeline,
   * condition roster with service-connection elements, contradictions, coverage
   * gaps, read-completeness). status is not_generated until a comprehensive run;
   * the whole body may be null on an older/empty backend. */
  casePicture: () => request<CasePictureResponse | null>('/analysis/case-picture'),
  /** GET /analysis/automation-status — plain-language state of every background
   * automation (deep dive, comprehension, verification, cross-read, review queue). */
  automationStatus: () => request<AutomationStatus>('/analysis/automation-status'),
  /** GET /analysis/file-readiness — deterministic "what you still need to file" delta
   * (grouped needs + how to fix + which conditions). No AI, safe on page load. */
  fileReadiness: () => request<FileReadiness>('/analysis/file-readiness'),
  /** GET /analysis/whats-changed — dated VA regulatory changes that took effect AFTER
   * the veteran's rating and touch their conditions/exposures (deterministic, no AI). */
  whatsChanged: () => request<WhatsChanged>('/analysis/whats-changed'),
  /** POST /analysis/whats-changed/{id}/assess — on-demand person-specific read of one
   * change (the only AI step; local model, PII on-fleet). */
  whatsChangedAssess: (id: string) =>
    request<{ assessment: string }>(`/analysis/whats-changed/${encodeURIComponent(id)}/assess`, {
      method: 'POST',
      notifyPaymentRequired: true,
    }),
  /** POST /analysis/landscape-scan — model-suggested secondary LEADS beyond the curated
   * map (on-demand AI; local by default). Hypotheses to research, never facts. */
  landscapeScan: () =>
    request<LandscapeScan>('/analysis/landscape-scan', { method: 'POST', notifyPaymentRequired: true }),
  /** GET /analysis/case-candidates — conditions the veteran's own records name.
   * Default (enrich=false): deterministic alias grouping only — free, no GPU.
   * enrich=true: optional local-LLM merge (costs a credit). */
  caseCandidates: (opts?: { enrich?: boolean }) =>
    request<CaseCandidatesResult>(
      `/analysis/case-candidates${opts?.enrich ? '?enrich=true' : ''}`,
      { notifyPaymentRequired: !!opts?.enrich },
    ),
  /** POST /analysis/build-case — create claimed conditions from confirmed
   * candidates, optionally linking their source docs as evidence. When
   * startComprehensive is true, best-effort enqueue the full analysis after build. */
  buildCase: (
    candidates: CaseCandidateInput[],
    linkEvidence = true,
    startComprehensive = false,
  ) =>
    request<BuildCaseResult>('/analysis/build-case', {
      method: 'POST',
      body: {
        candidates,
        link_evidence: linkEvidence,
        start_comprehensive: startComprehensive,
      },
      notifyPaymentRequired: true,
    }),
  /** POST /analysis/backfill-diagnosis-evidence — for conditions created before
   * diagnosis auto-identification, add a 'have' diagnosis evidence item where a
   * clinical source record names the condition. Idempotent. */
  backfillDiagnosisEvidence: () =>
    request<BackfillDiagnosisResult>('/analysis/backfill-diagnosis-evidence', {
      method: 'POST',
    }),
}

// ---- Packet ----

export const packetApi = {
  get: (conditionId: string) => request<PacketData>(`/packet/${conditionId}`),
}

// ---- Filing ----

export const filingApi = {
  lanes: () => request<KbCard[] | { lanes: KbCard[] }>('/filing/lanes'),
}

// ---- Records requests (routers/records.py — WAVE2-SPEC §2) ----
// Prefill worksheets never submit anything for the veteran — GET only, plus a
// deterministic letter template.
export const recordsApi = {
  sf180: () => request<RecordsPrefill>('/records/sf180?prefill=1'),
  va20_10206: () => request<RecordsPrefill>('/records/va-20-10206?prefill=1'),
  requestLetter: (body: RequestLetterInput) =>
    request<RequestLetterResponse>('/records/request-letter', { method: 'POST', body }),
}

// ---- Document intake (routers/documents.py — WAVE2-SPEC §4) ----
export const documentsApi = {
  list: (params: { status?: string; doc_type?: string } = {}) =>
    request<DocumentItem[]>(`/documents${qs(params)}`),
  /** GET /documents/{id} — the only endpoint that returns `extracted`. */
  get: (id: string) => request<DocumentItem>(`/documents/${id}`),
  /** GET /documents/upload-guidance — plain-language "what to upload" per doc
   * type (educational self-help, no outcome promises). Callers should degrade
   * gracefully if it 404s (older backend). */
  uploadGuidance: () => request<DocGuidanceResponse>('/documents/upload-guidance'),
  file: (id: string) => fetchBlob(`/documents/${id}/file`),
  downloadFile: async (id: string, filename: string, blob?: Blob) => {
    if (blob) {
      saveBlob(blob, filename)
      return
    }
    await downloadBlob(`/documents/${id}/file?download=1`, filename)
  },
  upload: (files: File[]) => {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    return requestForm<DocumentUploadResult>('/documents', form, true)
  },
  update: (id: string, body: DocumentUpdateInput) =>
    request<DocumentItem>(`/documents/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/documents/${id}`, { method: 'DELETE' }),
  reprocess: (id: string) =>
    request<DocumentItem>(`/documents/${id}/reprocess`, { method: 'POST', notifyPaymentRequired: true }),
  /** GET /documents/review-queue — documents flagged by extract-verify / OCR
   * cross-read for the veteran to reconcile. Degrade silently if 404 (older backend). */
  reviewQueue: () => request<DocumentReviewQueueItem[]>('/documents/review-queue'),
  /** GET /documents/{id}/review — the specific disagreements on one flagged doc. */
  review: (id: string) => request<DocumentReviewOut>(`/documents/${id}/review`),
  /** POST /documents/{id}/reconcile — the veteran writes the corrected tuple and/or
   * dismisses a missed-condition note; the flag clears when nothing remains pending. */
  reconcile: (id: string, body: ReconcileInput) =>
    request<ReconcileResult>(`/documents/${id}/reconcile`, { method: 'POST', body }),
  /** POST /documents/review-queue/bulk-reconcile — veteran-confirmed bulk resolve. */
  bulkReconcile: (body: {
    mode: 'accept_record' | 'accept_extracted' | 'accept_agreed' | 'clear_all'
    dismiss_all_missing?: boolean
  }) =>
    request<{
      documents_touched: number
      fields_applied: number
      fields_skipped: number
      resolved_documents: number
      disclaimer: string
    }>('/documents/review-queue/bulk-reconcile', { method: 'POST', body }),
  link: (id: string, body: DocumentLinkInput) =>
    request<DocumentLinkResult>(`/documents/${id}/link`, { method: 'POST', body }),
  /** GET /documents/summary — dashboard nudge + Documents header strip.
   * Callers should catch/degrade silently if the endpoint 404s (older
   * backend). */
  summary: () => request<DocumentSummary>('/documents/summary'),
  /** POST /documents/reprocess-failed — re-queue every failed document. */
  reprocessFailed: () =>
    request<ReprocessFailedResult>('/documents/reprocess-failed', {
      method: 'POST',
      notifyPaymentRequired: true,
    }),
  /** POST /documents/reprocess-ocr — force a RE-OCR of every ready document that
   * still has its file, so existing records are re-read through the current OCR
   * pipeline (page preprocessing + the cross-read engine). Costs one credit per
   * re-read. Returns { requeued }. */
  reprocessOcr: () =>
    request<ReprocessFailedResult>('/documents/reprocess-ocr', {
      method: 'POST',
      notifyPaymentRequired: true,
    }),
  /** POST /documents/reindex — make older / outage-degraded records searchable
   * (re-chunk + re-embed ready docs that aren't fully vector-indexed). No
   * re-OCR. Callers degrade silently if the endpoint 404s (older backend). */
  reindex: () => request<ReindexResult>('/documents/reindex', { method: 'POST' }),
  /** POST /documents/reset — DESTRUCTIVE + IRREVERSIBLE right-to-erasure +
   * cold-benchmark reset. Permanently deletes ALL uploaded documents and
   * everything derived from them (facts, chunks, conditions, evidence, citations,
   * rating scenarios, checklist items, analysis caches). Preserves the account,
   * profile, ITF deadlines, symptom logs, VA connections, and prior analysis-run
   * history. Sends {confirm:true} — the backend 400s without it. */
  reset: () =>
    request<ResetRecords>('/documents/reset', { method: 'POST', body: { confirm: true } }),
  /** GET /documents/search — semantic (or keyword-fallback) search over the
   * veteran's OWN uploaded records; returns verbatim excerpts. Callers degrade
   * silently if the endpoint 404s (older backend). */
  search: (q: string, params: { k?: number; document_id?: string } = {}) =>
    request<DocumentSearchResult>(
      `/documents/search${qs({
        q,
        k: params.k != null ? String(params.k) : undefined,
        document_id: params.document_id,
      })}`,
    ),
}

// ---- Decision-letter decoder (routers/documents.py — WAVE4-DECODER-SPEC) ----
// Decodes an already-uploaded VA rating decision / decision letter into plain
// English + AMA appeal lanes. Educational only; runs on the stored letter's
// text (no re-upload). Callers degrade gracefully when the endpoints 404 (older
// backend) — decodable() → empty state, getDecode() → prompt to POST /decode.
export const decoderApi = {
  /** GET /documents/decodable — every ready doc that is a VA decision. */
  decodable: () => request<DocumentItem[]>('/documents/decodable'),
  /** POST /documents/{id}/decode — runs the (LLM-backed) decode, caches server-
   * side, returns DecodeOut. Can take several seconds (local model). */
  decode: (id: string) =>
    request<DecodeResult>(`/documents/${id}/decode`, { method: 'POST', notifyPaymentRequired: true }),
  /** GET /documents/{id}/decode — the cached DecodeOut, or 404 if not yet decoded. */
  getDecode: (id: string) => request<DecodeResult>(`/documents/${id}/decode`),
}

// ---- Readiness score (routers/readiness.py — WAVE5 F1) ----
export const readinessApi = {
  get: () => request<ReadinessResult>('/readiness'),
}

// ---- Intent to File reminders (routers/itf.py — WAVE5 F2) ----
export const itfApi = {
  list: () => request<ItfResult>('/itf'),
  create: (body: ItfInput) => request<ItfRecord>('/itf', { method: 'POST', body }),
  remove: (id: string) => request<void>(`/itf/${id}`, { method: 'DELETE' }),
}

// ---- Deadline Guardian (routers/deadlines.py) ----
// One deterministic surface for every 1-year clock (ITF expiry, decision-review
// window, dependency retroactivity) computed from the veteran's own data.
export const deadlinesApi = {
  get: () => request<DeadlinesResult>('/deadlines'),
  /** POST /deadlines/notify-me — on-demand email digest of tracked deadlines. */
  notifyMe: () =>
    request<{ sent: boolean; reason: string; urgent_count: number; deadline_count: number }>(
      '/deadlines/notify-me',
      { method: 'POST' },
    ),
}

// ---- Symptom log (routers/symptomlog.py — WAVE5 F3) ----
export const symptomLogApi = {
  list: (conditionId?: string) =>
    request<SymptomLogEntry[]>(`/symptomlog${qs({ condition_id: conditionId })}`),
  create: (body: SymptomLogEntryInput) =>
    request<SymptomLogEntry>('/symptomlog', { method: 'POST', body }),
  update: (id: string, body: Partial<SymptomLogEntryInput>) =>
    request<SymptomLogEntry>(`/symptomlog/${id}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/symptomlog/${id}`, { method: 'DELETE' }),
  criteria: (conditionId?: string) =>
    request<SymptomCriteria>(`/symptomlog/criteria${qs({ condition_id: conditionId })}`),
  importFromGlitter: () =>
    request<SymptomLogImportResult>('/symptomlog/import-from-glitter', { method: 'POST' }),
  export: (conditionId?: string) =>
    request<SymptomLogExport>(`/symptomlog/export${qs({ condition_id: conditionId })}`),
}

// ---- Buddy statement builder (routers/buddy.py — WAVE5 F4) ----
export const buddyApi = {
  guidance: () => request<BuddyGuidance>('/buddy/guidance'),
  draft: (body: BuddyDraftInput) => request<BuddyDraft>('/buddy/draft', { method: 'POST', body }),
  situationBrief: (body: BuddySituationBriefInput) =>
    request<BuddySituationBrief>('/buddy/situation-brief', { method: 'POST', body }),
}

// ---- C&P exam companion (routers/cp.py — WAVE5 F5) ----
export const cpApi = {
  conditions: () => request<CpCondition[]>('/cp/conditions'),
  get: (conditionId: string) => request<CpCompanion>(`/cp/${conditionId}`),
}

// ---- 21-526EZ application packet (routers/form526.py — WAVE6 F1) ----
export const form526Api = {
  get: () => request<Form526Packet>('/form526'),
  /** GET /form526/pdf — the OFFICIAL fillable VA Form 21-526EZ (JAN 2026),
   * pre-filled with high-confidence data and streamed back as a DRAFT PDF.
   * Triggers a browser download; SSN/DOB/address/signature are left blank. */
  downloadPdf: () =>
    downloadBlob('/form526/pdf', 'VA-21-526EZ-DRAFT-review-and-sign.pdf'),
}

// ---- Official VA form fill (routers/forms.py — Wave 8) ----
// Generalizes form526Api.downloadPdf across the VA form set: preview() returns the
// AUTO_FILLED / YOU_COMPLETE labels + how many fields we'd stamp, and downloadPdf()
// streams the pre-filled official PDF as a DRAFT the veteran reviews and signs.
export const formsApi = {
  preview: (formId: string) => request<FormPreview>(`/forms/${formId}`),
  downloadPdf: (formId: string, filename: string) =>
    downloadBlob(`/forms/${formId}/pdf?download=1`, filename),
}

// ---- Nexus-letter builder (routers/nexus.py — WAVE6 F2) ----
export const nexusApi = {
  guidance: () => request<NexusGuidance>('/nexus/guidance'),
  draft: (body: NexusDraftInput) => request<NexusDraft>('/nexus/draft', { method: 'POST', body }),
  providerBrief: (body: NexusProviderBriefInput) =>
    request<NexusProviderBrief>('/nexus/provider-brief', { method: 'POST', body }),
}

// ---- Personal statement / 21-4138 (routers/statement.py — WAVE6 F3) ----
export interface StatementAssist {
  draft: string
  prompts: string[]
  has_facts: boolean
  attestation: string
  disclaimer: string
}

export const statementApi = {
  guidance: () => request<StatementGuidance>('/statement/guidance'),
  draft: (body: StatementDraftInput) =>
    request<StatementDraft>('/statement/draft', { method: 'POST', body }),
  /** POST /statement/assist — proposes a first-person DRAFT from the veteran's own
   * recorded facts + condition prompts. The veteran edits + adopts + attests; on-demand
   * (local model), never signs/files. */
  assist: (body: { condition?: string | null }) =>
    request<StatementAssist>('/statement/assist', {
      method: 'POST',
      body,
      notifyPaymentRequired: true,
    }),
}

// ---- TDIU / Individual Unemployability (routers/tdiu.py — §4.16) ----
// Educational screen + a work-history worksheet the veteran reviews, signs, and
// files (VA Form 21-8940). TDIU is VA's determination — never promissory copy.
export const tdiuApi = {
  screen: () => request<TdiuScreen>('/tdiu'),
  worksheet: (body: TdiuWorksheetInput) =>
    request<TdiuWorksheet>('/tdiu/worksheet', { method: 'POST', body }),
}

// ---- Concurrent pay / CRDP + CRSC (routers/concurrent_pay.py — §1414 / §1413a) ----
// Read-only eligibility read for a military retiree who also draws VA compensation:
// which concurrent-receipt program likely fits, what to do, and a rough CRDP
// restoration estimate. Deterministic — DFAS and the branch decide, never promissory.
export const concurrentPayApi = {
  screen: () => request<ConcurrentPay>('/concurrent-pay'),
}

// ---- Dependency / respond to a VA action (routers/dependency.py) ----
// Add/re-add a dependent, or respond to a VA removal/reduction letter. Educational
// worksheet (VA Form 21-686c / 21-509) the veteran reviews, signs, and files — the
// app never files and never says the veteran qualifies. Hedged copy only.
export const dependencyApi = {
  guidance: () => request<DependencyGuidance>('/dependency'),
  worksheet: (body: DependencyWorksheetInput) =>
    request<DependencyWorksheet>('/dependency/worksheet', { method: 'POST', body }),
}

// ---- Appeals draft assist (routers/appeals.py — WAVE7 A) ----
// Supplemental Claim (20-0995) / Higher-Level Review (20-0996) / Board (10182)
// draft assist. Educational: the veteran files it; Veteran-Ops never does, and
// never renders a medical opinion. Callers degrade gracefully on 404 (older backend).
export const appealsApi = {
  candidates: () => request<AppealCandidatesOut>('/appeals/candidates'),
  draft: (body: AppealDraftInput) =>
    request<AppealDraftOut>('/appeals/draft', { method: 'POST', body }),
}

// ---- Military records corrections (routers/corrections.py — WAVE10) ----
// Route a discharge upgrade / DD-214 correction to the right military board
// (DRB/BCMR/PDBR) + build the application packet. Educational; the veteran files
// with the board (not VA). Stateless (no stored data). 404-degrades on older backend.
export const correctionsApi = {
  route: (situation: CorrectionSituationInput) =>
    request<CorrectionRouteResult>('/corrections/route', { method: 'POST', body: situation }),
  draft: (body: CorrectionDraftInput) =>
    request<CorrectionPacket>('/corrections/draft', { method: 'POST', body }),
  /** GET /corrections/rank — educational guidance for the officer rank /
   * promotion-correction screen (what it is, how it works, thresholds). */
  rankGuidance: () => request<RankGuidanceOut>('/corrections/rank'),
  /** POST /corrections/rank/analyze — hedged, never-promissory analysis of a
   * possible missed/never-carried-out officer promotion. The board decides. */
  rankAnalyze: (body: RankAnalysisIn) =>
    request<RankAnalysisOut>('/corrections/rank/analyze', { method: 'POST', body }),
}

// ---- Account: data portability + erasure (routers/account.py — WAVE9) ----
export const accountApi = {
  /** ZIP archive: portable JSON plus every retained user-confined original. */
  exportArchive: () => downloadBlob('/account/export/archive', 'rating-raider-my-data.zip'),
  /** Data-only fallback for very large accounts or separately stored originals. */
  exportJson: () => downloadBlob('/account/export', 'rating-raider-my-data.json'),
  /** DELETE /account — permanent, irreversible. Requires the caller to type their
   * own email (server re-checks it). 204 on success. */
  deleteAccount: (confirmEmail: string) =>
    request<void>('/account', { method: 'DELETE', body: { confirm_email: confirmEmail } }),
}

// ---- Game Plan / strategy (routers/strategy.py — WAVE8) ----
// One call assembles the whole picture: snapshot + ranked pathways + prioritized
// actions. Educational (options to consider, estimates labeled, never a prediction).
// Callers degrade gracefully on 404 (older backend) — Dashboard hides its hero.
export const strategyApi = {
  get: () => request<GamePlanOut>('/strategy'),
  briefing: () => request<GamePlanBriefing>('/strategy/briefing'),
  deepDive: () => request<DeepDiveResult>('/strategy/deepdive'),
  runDeepDive: () => request<DeepDiveResult>('/strategy/deepdive/run', { method: 'POST' }),
  /** POST /strategy/refresh — re-run the specialist firm + briefing (local model) and
   * return the enriched plan. A plain GET is LLM-free; this is the explicit re-analyze. */
  refresh: () => request<GamePlanOut>('/strategy/refresh', { method: 'POST' }),
  /** GET /strategy/decision-statuses — dry-run preview of unknown → SC/denied from letters. */
  previewDecisionStatuses: () =>
    request<DecisionStatusApplyOut>('/strategy/decision-statuses'),
  /** POST /strategy/decision-statuses/apply — persist letter statuses (opt-in write). */
  applyDecisionStatuses: (opts?: { dry_run?: boolean }) =>
    request<DecisionStatusApplyOut>(
      `/strategy/decision-statuses/apply${qs({ dry_run: opts?.dry_run === true ? 'true' : 'false' })}`,
      { method: 'POST' },
    ),
  /** GET /strategy/case-brief — printable one-pager payload (coach.case_brief). */
  caseBrief: () => request<CaseBrief>('/strategy/case-brief'),
  /** GET /strategy/interview-seed — post-analysis gap interview seed. */
  interviewSeed: () => request<InterviewSeed>('/strategy/interview-seed'),
}

// ---- Rating Raider interview seed (routers/raider.py) ----
export const raiderApiExtras = {
  /** GET /raider/interview-seed — same seed as strategy; used by /raider?mode=post_analysis. */
  interviewSeed: (mode?: string) =>
    request<InterviewSeed>(`/raider/interview-seed${qs(mode ? { mode } : {})}`),
}

// ---- Proactive evidence (routers/evidence.py) ----
export interface EvidenceReviewItem {
  condition: string | null
  diagnostic_code?: string | null
  evidence_type: 'nexus' | 'buddy_statement' | 'dbq'
  document_id: string
  document_title: string | null
  doc_type: string
}
export interface EvidenceOpportunity {
  condition: string
  opportunity: 'nexus' | 'buddy_statement'
  reason: string
  draft_route: string
  auto_draftable: boolean
  needs_veteran: string | null
  /** Pre-generated, printable draft from the veteran's own record (ready to sign). */
  draft?: { title: string; markdown: string } | null
}
export interface EvidenceReview {
  already_in_your_file: EvidenceReviewItem[]
  worth_adding: EvidenceOpportunity[]
  summary: string
  disclaimer: string
}
export interface AutoLinkResult {
  linked: { condition: string; evidence_type: string; document: string | null }[]
  already_linked: number
  ambiguous: { document: string | null; reason: string }[]
}
export const proactiveEvidenceApi = {
  review: () => request<EvidenceReview>('/evidence/review'),
  autoLink: () => request<AutoLinkResult>('/evidence/auto-link', { method: 'POST' }),
}

// ---- Glitter Mane bridge (routers/glitter.py) ----
export const glitterApi = {
  status: () => request<GlitterStatus>('/glitter/status'),
  conditions: () => request<GlitterCondition[]>('/glitter/conditions'),
  importConditions: (conditionIds: string[]) =>
    request<GlitterImportResult>('/glitter/import-conditions', {
      method: 'POST',
      body: { condition_ids: conditionIds },
    }),
  labs: () => request<GlitterLab[]>('/glitter/labs'),
  vitals: () => request<GlitterVital[]>('/glitter/vitals'),
  importEvidence: (payload: { condition_id: string; lab_ids?: string[]; vital_ids?: string[] }) =>
    request<GlitterImportResult>('/glitter/import-evidence', { method: 'POST', body: payload }),
}

// ---- VA Lighthouse connection (routers/va.py — wave 3) ----
// The veteran signs in AT VA.gov and consents there; every call here runs on
// their own consented token. The two writes (ITF; local apply) require
// explicit confirmation and are audited server-side.

export const vaApi = {
  /** Never 503s — enabled=false means the server isn't configured for VA. */
  status: () => request<VaStatus>('/va/status'),
  /** GET /va/connect?redirect=false → {authorize_url}; the SPA then does a
   * full-page navigation to VA's sign-in (Login.gov / ID.me). */
  connect: (api: VaApiKey) =>
    request<{ authorize_url: string }>(`/va/connect${qs({ api, redirect: 'false' })}`),
  /** api omitted disconnects every connected VA API family. */
  disconnect: (api?: VaApiKey) =>
    request<{ disconnected: string[] }>('/va/disconnect', {
      method: 'POST',
      body: api ? { api } : {},
    }),
  /** READ-ONLY preview + suggestions — nothing changes until /va/apply. */
  sync: () => request<VaSyncResult>('/va/sync', { method: 'POST' }),
  /** Applies ONLY the checked suggestions, validated against the snapshot. */
  apply: (body: VaApplyInput) => request<VaApplyResult>('/va/apply', { method: 'POST', body }),
  claims: () => request<VaClaimsResult>('/va/claims'),
  itfActive: () => request<VaItf>('/va/itf/active'),
  /** SUBMITS VA Form 0966 to VA on the veteran's consented token — the UI
   * shows exactly what will be filed and the veteran presses the button. */
  fileItf: () =>
    request<VaItf>('/va/itf', { method: 'POST', body: { type: 'compensation', confirm: true } }),
  /** POST /va/reconcile — reconcile the veteran's OWN VA record (from the VA
   * Connect extension's URL hash, or pasted in) against their conditions.
   * apply:false = a dry-run PREVIEW (nothing changes); apply:true writes the
   * matched ratings/dispositions and, when create_new, adds unmatched ones. */
  reconcile: (body: VaReconcileInput) =>
    request<VaReconcileResult>('/va/reconcile', { method: 'POST', body }),
}

// ---- Legal (GET /api/legal — no auth; plain-language markdown) ----

export const legalApi = {
  get: () => request<LegalDocs>('/legal'),
}

export const metaApi = {
  get: () => request<AppMeta>('/meta'),
}

// ---- Admin: service settings (runtime overrides) ----

export const adminServicesApi = {
  getSettings: () => request<ServiceSettingsOut>('/admin/services/settings'),
  updateSettings: (body: Partial<ServiceOverrides>) =>
    request<ServiceSettingsOut>('/admin/services/settings', { method: 'PUT', body }),
  testConnection: (body: TestConnectionInput) =>
    request<TestConnectionOut>('/admin/services/settings/test', { method: 'POST', body }),
  /** GET/PUT /admin/services/workspace-privacy — this workspace's privacy choice
   * (records-stay-local toggle). Admin/owner only; body {privacy_mode: bool|null}. */
  getWorkspacePrivacy: () =>
    request<WorkspacePrivacyOut>('/admin/services/workspace-privacy'),
  setWorkspacePrivacy: (privacy_mode: boolean | null) =>
    request<{ workspace_id: string; privacy_mode: boolean | null }>(
      '/admin/services/workspace-privacy',
      { method: 'PUT', body: { privacy_mode } },
    ),
  /** GET/PUT /admin/services/pii-cloud-consent — this workspace's consent to let the
   * C-file quality mode send record text to a frontier model (privacy off only). */
  getPiiCloudConsent: () =>
    request<PiiCloudConsentOut>('/admin/services/pii-cloud-consent'),
  setPiiCloudConsent: (consent: boolean) =>
    request<PiiCloudConsentOut>('/admin/services/pii-cloud-consent', {
      method: 'PUT',
      body: { consent },
    }),
}

// ---- Health ----

export const getHealth = () => request<HealthStatus>('/healthz')
