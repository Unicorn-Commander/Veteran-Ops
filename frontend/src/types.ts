// Shared domain types mirroring the backend API contract — sourced directly
// from backend/app/schemas.py and the response construction in
// backend/app/routers/{analysis,conditions,packet,checklist}.py. If a field
// isn't returned by the router, it doesn't exist here.

export interface User {
  id: string
  email: string
  full_name: string
  email_verified: boolean
  /** Unicorn Commander profile photo (Keycloak `picture` claim); null for native
   * accounts — the UI falls back to rendered initials. */
  avatar_url: string | null
  platform_admin: boolean
  created_at: string
}

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

// ---- Tenancy / orgs / entitlements (Wave 11–12) ----

export type OrgRole = 'owner' | 'admin' | 'staff' | 'member'

export interface Workspace {
  id: string
  name: string
  kind: 'personal' | 'org'
  plan_tier: string
  status: string
  role: OrgRole
}

export interface WorkspacesResponse {
  workspaces: Workspace[]
  current_workspace_id: string
}

export interface Org {
  id: string
  name: string
  slug: string
  kind: 'personal' | 'org'
  plan_tier: string
  status: string
  role: OrgRole
  member_count: number
  seat_limit: number
}

export interface OrgMember {
  user_id: string
  email: string
  full_name: string
  role: OrgRole
  created_at: string
}

export interface Invite {
  id: string
  org_id: string
  email: string
  role: OrgRole
  status: string
  invited_by_email: string | null
  expires_at: string
  created_at: string
}

export interface InvitePreview {
  org_name: string
  role: OrgRole
  email: string
  email_matches: boolean
  status: 'pending' | 'expired' | 'accepted' | 'revoked'
  invited_by_email: string | null
}

export interface Entitlements {
  workspace_id: string
  kind: 'personal' | 'org'
  tier: string
  role: OrgRole
  features: string[]
  seat_limit: number
}

export interface SimpleMessage {
  ok: boolean
  message: string
}

// ---- Billing / plans (Wave 14) ----
// Billing is operated by the suite (Lago); in-app self-serve checkout is NOT
// live yet, so the page shows plans + a "Manage billing" link (when configured)
// or a "your account team manages this" note — never a checkout button — unless
// the API says self_serve. Individual veteran self-help is free forever; the
// paid tiers are for ORGS (VSOs, clinics, agencies).

/** One plan in GET /billing/plans. price_monthly null = "contact us";
 * seat_limit -1 = unlimited; current marks the workspace's active tier. */
export interface Plan {
  tier: string
  name: string
  price_monthly: number | null
  audience: string
  highlights: string[]
  seat_limit: number
  current: boolean
}

/** GET /billing/plans → the catalog plus how billing is managed for the caller. */
export interface PlansResponse {
  plans: Plan[]
  self_serve: boolean
  portal_url: string | null
}

/** GET /billing/status → the active workspace's plan, seat usage, and
 * included features, plus how (and whether) the caller can manage billing. */
export interface BillingStatus {
  workspace_id: string
  kind: 'personal' | 'org'
  tier: string
  plan_name: string
  seat_limit: number
  seats_used: number
  features: string[]
  self_serve: boolean
  portal_url: string | null
  manageable: boolean
}

export type CreditProduct = 'full_claim' | 'topup' | 'sponsor'

export interface CreditTransaction {
  id: string
  delta: number
  balance_after: number
  operation: string
  reference_type: string | null
  reference_id: string | null
  note: string | null
  created_at: string
}

export interface CreditsResponse {
  balance: number
  recent: CreditTransaction[]
}

export interface CheckoutSessionInput {
  product: CreditProduct
  beneficiary_email?: string | null
}

export interface CheckoutSessionResponse {
  session_id: string
  url: string
  product: CreditProduct
  amount_cents: number
  credits: number
  message: string
}

export type GrantApplicationStatus = 'pending' | 'approved' | 'denied'
export type GrantEmploymentStatus = 'employed' | 'underemployed' | 'unemployed' | 'retired' | 'student' | 'other'

export interface GrantApplicationInput {
  monthly_income_band?: string | null
  household_size?: number | null
  employment_status?: GrantEmploymentStatus | null
  hardship_summary: string
  contact_email?: string | null
}

export interface GrantApplication {
  id: string
  monthly_income_band: string | null
  household_size: number | null
  employment_status: GrantEmploymentStatus | null
  hardship_summary: string
  contact_email: string | null
  status: GrantApplicationStatus
  reviewer_user_id: string | null
  reviewed_at: string | null
  review_note: string | null
  funded_sponsorship_id: string | null
  created_at: string
  updated_at: string
}

export interface GrantPoolEntry {
  id: string
  claims_delta: number
  kind: string
  sponsorship_id: string | null
  grant_application_id: string | null
  reserved_email: string | null
  reserved_user_id: string | null
  note: string | null
  created_at: string
}

export interface GrantPool {
  available_claims: number
  earned_claims: number
  spent_claims: number
  recent: GrantPoolEntry[]
}

export interface Sponsorship {
  id: string
  checkout_session_id: string
  payment_intent_id: string | null
  beneficiary_email: string | null
  beneficiary_user_id: string | null
  amount_cents: number
  status: string
  earmark_status: string
  pool_ledger_id: string | null
  consumed_at: string | null
  created_at: string
  updated_at: string
}

export interface AdminGrants {
  pool: GrantPool
  applications: GrantApplication[]
  sponsorships: Sponsorship[]
}

export interface GrantApplicationReviewInput {
  status: GrantApplicationStatus
  review_note?: string | null
}

export interface AuthConfig {
  sso_enabled: boolean
  sso_label: string
  password_login_enabled: boolean
  registration_open: boolean
  registration_mode: 'open' | 'bootstrap' | 'closed'
  email_enabled: boolean
  password_reset_enabled: boolean
}

// ---- Profile (veteran_profiles) ----

export interface ServicePeriod {
  branch: string
  component: string
  start_date: string | null
  end_date: string | null
  discharge_character: string
}

export interface Exposures {
  burn_pits: boolean
  agent_orange: boolean
  gulf_war: boolean
  radiation: boolean
  camp_lejeune: boolean
  mustard_gas: boolean
  pow: boolean
  pow_internment_days?: number | null
  other: string
  locations: string[]
}

export const EMPTY_EXPOSURES: Exposures = {
  burn_pits: false,
  agent_orange: false,
  gulf_war: false,
  radiation: false,
  camp_lejeune: false,
  mustard_gas: false,
  pow: false,
  pow_internment_days: null,
  other: '',
  locations: [],
}

// Identity + household used to pre-fill the veteran's own official VA forms.
// NO SSN by design — the veteran hand-writes it on the signed form.
// Inner fields are optional (not `| null`): the API may omit them and the form
// inputs bind them directly, so `string | undefined` keeps strict tsc happy while
// runtime null is still harmless.
export interface MailingAddress {
  street?: string
  unit?: string
  city?: string
  state?: string
  zip?: string
  country?: string
}

export type DependentRelationship = 'spouse' | 'child' | 'stepchild' | 'parent'

export interface Dependent {
  relationship: DependentRelationship
  full_name?: string
  date_of_birth?: string
  marriage_date?: string
  marriage_location?: string
  in_school?: boolean
  seriously_disabled?: boolean
}

export interface VeteranIdentity {
  full_name?: string
  date_of_birth?: string
  phone?: string
  email?: string
  address: MailingAddress // backend defaults this (never null); UI helpers materialize it
  va_file_number?: string // optional, sensitive; draft-only
  place_of_birth?: string
}

export interface Profile {
  id?: string
  service_periods: ServicePeriod[]
  combat_service: boolean
  // Optional/nullable: backend defaults these to null (bool | None); the onboarding
  // wizard and some default-profile literals don't set them, and the enumerator
  // treats absence as "not a concurrent-pay candidate."
  receives_military_retired_pay?: boolean | null
  combat_related_disability?: boolean | null
  /** Chapter 61 / medical retirement (not length-of-service only). */
  medically_retired?: boolean | null
  /** Medical separation without retirement (e.g. PEB sep). */
  medically_separated?: boolean | null
  exposures: Exposures
  current_combined_rating: number | null
  state: string | null
  notes: string | null
  identity?: VeteranIdentity | null
  dependents?: Dependent[] | null
}

// ---- Identity suggestions from imported records (GET /profile/identity-suggestions)
// Best-effort, local-model extraction of the veteran's OWN identity from their
// uploaded documents. A suggestion surface only — the veteran clicks "Use these" to
// fill the profile form, then saves. NO SSN is ever present (backend guarantee).
export interface IdentitySuggestionSource {
  /** Null when the field was seeded from the signed-in account (not a PDF). */
  document_id: string | null
  title: string | null
  doc_type: DocType | null
  doc_date: string | null
}

export interface IdentitySuggestions {
  has_suggestions: boolean
  identity: VeteranIdentity
  dependents: Dependent[]
  /** field name (full_name | date_of_birth | phone | address | dependents) → source doc */
  sources: Record<string, IdentitySuggestionSource>
  disclaimer: string
}

// ---- Benefits directory (/benefits) ----

export type BenefitCategory = 'federal' | 'state' | 'commercial'
export type BenefitConfidence = 'established' | 'varies'

export interface BenefitItem {
  id: string
  name: string
  description: string
  category: BenefitCategory
  min_rating: number
  requires_pt: boolean
  states: string[]
  source_name: string
  source_url: string
  confidence: BenefitConfidence
  effective_date?: string | null
  verified_as_of?: string | null
}

export interface BenefitsOut {
  verified_as_of: string
  federal: BenefitItem[]
  state: BenefitItem[]
  commercial: BenefitItem[]
}

// ---- Claimed conditions ----

export type ClaimType = 'direct' | 'secondary' | 'presumptive' | 'increase'
export type ConditionStatus =
  | 'considering'
  | 'gathering_evidence'
  | 'ready_to_file'
  | 'filed'
  | 'decided'
/** The condition's real VA disposition (distinct from the veteran's own
 * workflow `status`). Older rows/clients default to 'unknown'. */
export type VaConditionStatus =
  | 'unknown'
  | 'service_connected'
  | 'denied'
  | 'pending'

export interface ClaimedCondition {
  id: string
  name: string
  body_system: string | null
  diagnostic_code: string | null
  claim_type: ClaimType
  secondary_to: string | null
  current_rating: number | null
  target_rating: number | null
  status: ConditionStatus
  va_status: VaConditionStatus
  onset_date: string | null
  in_service_event: string | null
  nexus_notes: string | null
  dbq_form: string | null
  notes: string | null
  created_at: string
  updated_at: string
}

export type ClaimedConditionInput = Omit<
  ClaimedCondition,
  'id' | 'created_at' | 'updated_at'
>

// ---- Evidence ----

export type EvidenceKind =
  | 'diagnosis'
  | 'service_record'
  | 'nexus_letter'
  | 'dbq'
  | 'lay_statement'
  | 'continuity'
  | 'treatment_record'
  | 'other'

export type EvidenceStatus = 'have' | 'need' | 'requested' | 'not_applicable'

export interface EvidenceItem {
  id: string
  condition_id: string
  document_id: string | null
  kind: EvidenceKind
  title: string
  status: EvidenceStatus
  source: string | null
  file_ref: string | null
  notes: string | null
  rationale?: EvidenceRationale | null
  citations?: EvidenceCitation[]
  created_at: string
  updated_at: string
}

export type EvidenceInput = Omit<
  EvidenceItem,
  'id' | 'condition_id' | 'document_id' | 'created_at' | 'updated_at'
>

export interface EvidenceRationale {
  elements: string[]
  why: string
}

export interface EvidenceCitation {
  document_id: string
  source_title: string
  quote: string
  char_start: number
  char_end: number
  page: number | null
  chunk_index: number
  note: string | null
  selected: boolean
}

// ---- Gaps (GET /conditions/{id}/gaps → GapsOut) ----

export interface GapItem {
  kind: EvidenceKind
  label: string
  detail: string | null
  source: string | null
}

export interface GapsResponse {
  condition_id: string
  gaps: GapItem[]
  dbq_form: string | null
  checklist: ChecklistItem[]
}

// ---- Checklist ----

export interface ChecklistItem {
  id: string
  condition_id: string | null
  text: string
  category: string | null
  done: boolean
  sort: number
  created_at: string
}

export type ChecklistInput = Omit<ChecklistItem, 'id' | 'created_at'>

// ---- Rating engine ----

export interface RatingEntry {
  label: string
  percent: number
  side?: 'left' | 'right' | null
  group?: string | null
}

export type RatingStep = Record<string, unknown>

export interface SmcFlag {
  code?: string
  label?: string
  description?: string
  [key: string]: unknown
}

export interface CombinedResult {
  combined: number
  raw: number
  steps: RatingStep[]
  bilateral_factor_applied: boolean
  smc_flags: SmcFlag[]
}

export interface RatingScenario {
  id: string
  name: string
  entries: RatingEntry[]
  result: CombinedResult
  created_at: string
}

// ---- KB cards ----

export type KbCardType = 'rating_criteria' | 'rule' | 'presumptive' | 'dbq' | 'process'

export interface KbCard {
  id: string
  card_type: KbCardType
  title: string
  body_system: string | null
  diagnostic_code: string | null
  source: string
  source_name: string | null
  source_url: string | null
  effective_date: string | null
  verified_as_of: string | null
  content: string
  data: Record<string, unknown> | null
}

// ---- Analysis (routers/analysis.py) ----

/** One tier of a diagnostic code's criteria (RatingTierOut). */
export interface RatingTier {
  percent: number
  criteria: string
  evidence_needed: string[]
}

/** POST /analysis/map-conditions item (MappingItemOut). */
export interface ConditionMapping {
  name: string
  diagnostic_code: string | null
  body_system: string | null
  tiers: RatingTier[]
  under_rated: boolean
  rationale: string | null
  source: string
  card_title: string | null
  suggested_discussion_tier: number | null
  caveat: string
}

export interface MapConditionsResponse {
  items: ConditionMapping[]
  disclaimer: string
}

/** POST /analysis/secondaries item (SecondaryItemOut). */
export interface SecondarySuggestion {
  primary: string
  secondary: string
  rationale: string
  source: string
  dbq: string | null
}

export interface SecondariesResponse {
  items: SecondarySuggestion[]
  disclaimer: string
}

/** GET /analysis/presumptives item (PresumptiveItemOut). */
export interface PresumptiveMatch {
  condition: string
  program: string
  rationale: string
  source: string
  matched_reason: string | null
  conditions: string[]
}

export interface PresumptivesResponse {
  matches: PresumptiveMatch[]
  disclaimer: string
}

// ---- Comprehensive analysis (POST /analysis/comprehensive) ----
// The headline action of the Analysis Center: one heavy pass that runs the
// specialist firm, the plain-language briefing, the rating deep dive, and the
// whole-C-file comprehension, then returns a consolidated summary.

/** Which sub-analyses actually ran in this comprehensive pass. */
export interface ComprehensiveRan {
  mapping?: boolean
  firm: boolean
  briefing: boolean
  deep_dive: boolean
  comprehension: boolean
}

/** Consolidated headline counts from a comprehensive run. */
export interface ComprehensiveSummary {
  conditions: number
  pathways: number
  deep_dive_findings: number
  new_findings: number
  case_picture_ready: boolean
  /** Enrichment completeness when assemble succeeded: full | partial | minimal. */
  quality?: 'full' | 'partial' | 'minimal'
  /** Short labels for enrichment steps that did not finish. */
  quality_notes?: string[]
  /** True when quality is partial or minimal (status still completed). */
  degraded?: boolean
}

export interface ComprehensiveAnalysisResult {
  status: 'complete'
  ran: ComprehensiveRan
  summary: ComprehensiveSummary
}

export interface AnalysisPrerequisiteItem {
  key: string
  label: string
  detail: string
  route: string
}

export interface AnalysisPrerequisites {
  ready: boolean
  conditions: number
  ready_documents: number
  processing_documents: number
  failed_documents: number
  missing: AnalysisPrerequisiteItem[]
}

// ---- Background comprehensive run (POST /analysis/comprehensive/start + poll) ----
// The comprehensive pass now runs as a BACKGROUND job so a big C-file can't time
// out: start it, then poll GET /analysis/comprehensive/runs/{id} for live, per-step
// progress. Per-step `seconds` is the real wall-clock burden of reading the file —
// a headline the Analysis Center surfaces prominently.

/** One step of a comprehensive run. `label` is rendered as-is; `detail` is a short
 * human note ("12 findings (3 new)", "cached"); `seconds` is per-step wall-clock
 * once the step is terminal (null while pending/running). */
export interface AnalysisStep {
  key: string
  label: string
  status: 'pending' | 'running' | 'complete' | 'failed'
  seconds: number | null
  detail: string | null
}

/** GET /analysis/comprehensive/{latest,runs,runs/{id}} → one run. `ran`/`summary`
 * are null until the run has produced them; on `failed`, `error` is set. */
export interface AnalysisRun {
  id: string
  status: 'queued' | 'leased' | 'running' | 'retryable' | 'completed' | 'complete' | 'failed' | 'cancelled'
  steps: AnalysisStep[]
  ran: ComprehensiveRan | null
  summary: ComprehensiveSummary | null
  error: string | null
  started_at: string | null
  finished_at: string | null
  total_seconds: number | null
  attempt_count: number
  max_attempts: number
  next_attempt_at: string | null
  lease_expires_at: string | null
  cancel_requested: boolean
  created_at: string | null
}

/** GET /analysis/intake-benchmark → approximate cost of document intake, paired
 * with per-run step timing to show the full time-to-complete-a-file. All timing
 * fields are approximate and can be null on an empty/older backend. */
export interface IntakeBenchmark {
  documents: number
  ready: number
  failed: number
  processing: number
  duplicates: number
  total_bytes: number
  total_processing_seconds: number | null
  wall_clock_seconds: number | null
  avg_seconds_per_doc: number | null
  first_uploaded_at: string | null
  last_ready_at: string | null
}

// ---- Case Picture / whole-C-file comprehension (GET /analysis/case-picture) ----
// The richest analysis: everything read from the veteran's entire C-file, assembled
// into one picture — a timeline, a condition roster with the three service-connection
// elements, contradictions, coverage gaps, and how completely the file could be read.

/** One provenance reference the backend stamps on a fact — where in the file it
 * came from. The comprehension map-reduce emits these as objects (a single ref on
 * timeline/contradiction items, a list of refs on a roster condition), NOT plain
 * strings; older payloads may still carry a string. Render via formatProvenance()
 * — never as a raw React child, or React throws on the object. */
export interface ProvenanceRef {
  document_id?: string | null
  segment?: number | null
  page?: number | null
  char_start?: number | null
  char_end?: number | null
}
export type Provenance = string | ProvenanceRef | ProvenanceRef[] | null

export interface CasePictureTimelineEvent {
  date: string | null
  kind: string
  label: string
  provenance: Provenance
}

/** One service-connection element (current diagnosis / in-service event). */
export interface ScElement {
  present: boolean
  basis: string | null
}

/** The nexus element additionally records whether it meets VA's linkage standard. */
export interface ScNexusElement extends ScElement {
  meets_standard: boolean | null
}

export interface CasePictureScElements {
  current_diagnosis: ScElement
  nexus: ScNexusElement
  in_service_event: ScElement
}

export interface CasePictureCondition {
  name: string
  diagnostic_code: string | null
  rating_percent: number | null
  decision: string | null
  provenance: Provenance
  sc_elements: CasePictureScElements
  missing_elements: string[]
}

export interface CasePictureContradiction {
  note: string
  provenance: Provenance
}

export interface CasePictureCoverageGap {
  condition: string | null
  missing_elements: string[]
  note: string | null
}

/** How completely the C-file could be read (the read-completeness banner). */
export interface CasePictureReadCompleteness {
  segments_total: number
  segments_read: number
  segments_failed: number
  pages_total: number
  pages_read: number
  pages_unreadable: number
  truncated: boolean
  complete: boolean
  note: string | null
}

export interface CasePictureGroundingExcerpt {
  document_id: string
  excerpt: string
  char_start: number
}

/** The assembled picture. The three inventories are catalogued spans whose item
 * shape the backend owns; the UI shows their counts and leaves the items opaque. */
export interface CasePicture {
  timeline: CasePictureTimelineEvent[]
  condition_roster: CasePictureCondition[]
  exam_inventory: unknown[]
  nexus_inventory: unknown[]
  decision_inventory: unknown[]
  contradictions: CasePictureContradiction[]
  coverage_gaps: CasePictureCoverageGap[]
  read_completeness: CasePictureReadCompleteness | null
  grounding_excerpts: CasePictureGroundingExcerpt[]
}

export interface CasePictureResponse {
  status: 'ready' | 'not_generated'
  generated_at: string | null
  picture: CasePicture | null
}

// "What's changed since you were rated" — dated VA regulatory changes that took effect
// AFTER the veteran's rating and touch their conditions/exposures. Facts are curated +
// cited (never AI); only the per-item person-specific read is model-generated.
export interface WhatsChangedItem {
  id: string
  status: 'changed' | 'proposed'
  effective_date: string
  title: string
  summary: string
  action_hint: string
  source_url: string
  confidence: 'established' | 'emerging'
  matched_by: 'condition' | 'exposure'
  matched_detail: string
  action_signal: 'review' | 'watch' | 'check_eligibility'
}

export interface WhatsChanged {
  rating_date: string | null
  rating_date_source: string | null
  needs_rating_date: boolean
  items: WhatsChangedItem[]
}

// File-readiness delta — "what you still need to file," aggregated from the gap engine.
export interface FileReadinessNeed {
  label: string
  detail: string
  how: string
  route: string
  kind: string
  conditions: string[]
}
export interface FileReadinessCondition {
  condition_id: string
  name: string
  ready: boolean
  still_needs: string[]
}
/** Slim blocker for checklist UIs — label + where to fix it. */
export interface FileReadinessBlocker {
  label: string
  route: string
  how: string
}
/** Static pro-se handoff — prepare packet, veteran/VSO files. We never e-file. */
export interface FileReadinessHandoff {
  va_gov_claim_url: string
  vso_url: string
  itf_url: string
  form526_route: string
  packet_note: string
}
export interface FileReadiness {
  total_conditions: number
  ready_conditions: number
  all_ready: boolean
  has_conditions: boolean
  still_needed: FileReadinessNeed[]
  per_condition: FileReadinessCondition[]
  /** 0–100 share of conditions with core evidence identified. */
  file_ready_score: number
  blockers: FileReadinessBlocker[]
  handoff: FileReadinessHandoff
  disclaimer: string
}

// Deep landscape scan — model-suggested secondary-connection LEADS beyond the curated
// map. Framed as hypotheses to research with a provider, never established facts.
export interface LandscapeLead {
  secondary: string
  primary: string
  mechanism: string
  strength: 'well_documented' | 'plausible' | 'emerging'
  discuss: string
}

export interface LandscapeScan {
  leads: LandscapeLead[]
  disclaimer: string
}

// ---- Automation status (GET /analysis/automation-status) ----
// Plain-language "what we've automated for you": what ran automatically, what's
// available, and the on/off state + description of each background automation.

export interface AutomationDeepDive {
  last_run: string | null
  has_new_findings: boolean
  auto_on_intake: boolean
}

export interface AutomationComprehension {
  available: boolean
  generated_at: string | null
  auto_on_intake: boolean
}

export interface AutomationVerification {
  flagged_docs: number
  enabled: boolean
}

export interface AutomationCrossRead {
  disagreement_pages: number
}

export interface AutomationReviewQueue {
  pending: number
}

export interface AutomationItem {
  key: string
  on: boolean
  label: string
  plain: string
}

export interface AutomationStatus {
  deep_dive: AutomationDeepDive
  comprehension: AutomationComprehension
  verification: AutomationVerification
  cross_read: AutomationCrossRead
  review_queue: AutomationReviewQueue
  automations: AutomationItem[]
}

// ---- Build case from records (routers/analysis.py) ----

export interface CaseCandidate {
  name: string
  aliases: string[]
  mention_count: number
  document_ids: string[]
  diagnostic_code: string | null
  body_system: string | null
  claim_type: string
  note: string | null
  already_claimed: boolean
}

export interface CaseCandidatesResult {
  candidates: CaseCandidate[]
  documents_scanned: number
  distinct_mentions: number
  existing_conditions: number
  disclaimer: string
}

export interface CaseCandidateInput {
  name: string
  diagnostic_code?: string | null
  body_system?: string | null
  claim_type?: string
  note?: string | null
  document_ids?: string[]
}

export interface BuildCaseResult {
  created: ClaimedCondition[]
  skipped_existing: string[]
  evidence_linked: number
  /** True when build-case successfully enqueued (or attached to) a comprehensive run. */
  comprehensive_started?: boolean
  comprehensive_run_id?: string | null
}

export interface BackfillDiagnosisResult {
  conditions_updated: number
  evidence_added: number
  skipped_existing: number
}

// ---- Packet (GET /packet/{condition_id} — routers/packet.py) ----

export interface PacketDcCard {
  title: string
  diagnostic_code: string | null
  source: string
  content: string
  tiers: RatingTier[]
}

export interface PacketCondition {
  id: string
  name: string
  body_system: string | null
  diagnostic_code: string | null
  claim_type: ClaimType
  status: ConditionStatus
  current_rating: number | null
  onset_date: string | null
  in_service_event: string | null
  nexus_notes: string | null
}

export interface PacketEvidence {
  id: string
  document_id?: string | null
  kind: EvidenceKind
  title: string
  status: EvidenceStatus
  source: string | null
  notes: string | null
  rationale?: EvidenceRationale | null
  citations?: EvidenceCitation[]
}

/** Glitter Mane check-in (routers/glitter.py: {id, mood, energy, pain, symptoms, note, created_at}). */
export interface ContinuityCheckin {
  id?: string
  mood?: number | string | null
  energy?: number | string | null
  pain?: number | string | null
  symptoms?: string | null
  note?: string | null
  created_at?: string | null
  [key: string]: unknown
}

/** A passage from the veteran's OWN uploaded records that mentions this
 * condition (routers/packet.py evidence_excerpts). Their text verbatim — where
 * to point the rater — never an interpretation. */
export interface PacketExcerpt {
  document_id: string
  source: string
  excerpt: string
  chunk_index: number
}

export interface PacketEvidenceIndexItem {
  id: string
  title: string
  kind: EvidenceKind
  status: EvidenceStatus
  source: string | null
  notes: string | null
  document_id: string | null
  rationale: EvidenceRationale | null
  citations: EvidenceCitation[]
}

export interface PacketData {
  veteran: { name: string }
  condition: PacketCondition
  dc_card: PacketDcCard | null
  evidence_have: PacketEvidence[]
  evidence_missing: PacketEvidence[]
  /** Optional — older backends omit it; render only when present & non-empty. */
  evidence_excerpts?: PacketExcerpt[]
  evidence_index?: PacketEvidenceIndexItem[]
  gaps: GapItem[]
  continuity: ContinuityCheckin[]
  lay_statement_prompts: string[]
  dbq: string | null
  disclaimer: string
}

// ---- Filing lanes ----

export interface FilingLane {
  key?: string
  title: string
  source?: string
  content: string
  [key: string]: unknown
}

// ---- Admin service settings (overrides) ----

export interface ServiceOverrides {
  llm_base_url?: string | null
  llm_api_key?: string | null
  llm_model?: string | null
  reasoning_model?: string | null
  embeddings_base_url?: string | null
  embeddings_api_key?: string | null
  embeddings_model?: string | null
  reranker_base_url?: string | null
  reranker_model?: string | null
  ocr_base_url?: string | null
  ocr_model?: string | null
  ocr_engine?: string | null
  center_deep_url_default?: string | null
  center_deep_url_unicorncommander?: string | null
  privacy_mode?: boolean | null
}

/** Response body of GET/PUT /admin/services/settings. Secrets are never
 * returned (redacted to null); the `*_set` booleans say whether one is set. */
export interface ServiceSettingsOut extends ServiceOverrides {
  llm_api_key_set?: boolean
  embeddings_api_key_set?: boolean
}

export interface TestConnectionInput {
  overrides: Partial<ServiceOverrides>
}

export interface TestConnectionOut {
  ok: boolean
  message: string
  detail?: string | null
}

// ---- Health ----

export interface HealthStatus {
  status: string
  [key: string]: unknown
}

// ---- Records requests (routers/records.py — WAVE2-SPEC §2) ----
// Reconciled against the real backend/app/routers/records.py + schemas.py
// (RecordsPrefillOut / RequestLetterIn / RequestLetterOut) — routers are truth.

export interface RecordsPrefillData {
  full_name?: string
  email?: string
  service_periods?: ServicePeriod[]
  branches?: string[]
  discharge_characters?: string[]
  state?: string | null
  purpose?: string
  records_requested?: string[]
  [key: string]: unknown
}

/** GET /records/sf180 and /records/va-20-10206 — a worksheet, not a filled
 * official form; `note` is the "prepared for your signature" reminder. */
export interface RecordsPrefill {
  form: string
  form_title: string
  form_url: string
  prefill: RecordsPrefillData
  guidance: string[]
  note: string
}

export interface RequestLetterInput {
  provider_name: string
  address?: string | null
  condition_ids: string[]
}

export interface RequestLetterResponse {
  letter: string
  provider_name: string
  conditions: string[]
  evidence: EvidenceItem[]
  note: string
}

// ---- Document intake (routers/documents.py — WAVE2-SPEC §4) ----
// Reconciled against the real backend/app/routers/documents.py + schemas.py.

export type DocumentStatus = 'uploaded' | 'processing' | 'ready' | 'failed' | 'duplicate'
export type DocType =
  | 'rating_decision'
  | 'decision_letter'
  | 'str'
  | 'dbq'
  | 'treatment_record'
  | 'private_medical_opinion'
  | 'lay_statement'
  | 'service_record'
  | 'other'

/** One doc-type's plain-language "what to upload" guidance (GET
 * /documents/upload-guidance). Educational self-help only — never an outcome
 * promise. Mirrors backend schemas.DocTypeGuidanceOut. */
export interface DocTypeGuidance {
  label: string
  what_it_is: string
  what_to_upload: string[]
  why_it_helps: string
}

/** GET /documents/upload-guidance — the full doc-type → guidance map. Keys are
 * DocType values (plus any future backend addition), so read defensively. */
export interface DocGuidanceResponse {
  guidance: Record<string, DocTypeGuidance>
}

export interface DocConditionMention {
  name: string
  rating_percent?: number | null
  diagnostic_code?: string | null
  decision?: 'granted' | 'denied' | 'deferred' | null
  /** VA's official contention-classification taxonomy, stamped
   * deterministically by intake/classify.py attach_va_classifications()
   * (null when the vendored dataset has no hit). */
  va_classification?: string | null
  va_classification_code?: string | null
}

export interface DocSuggestedLink {
  condition_id?: string | null
  name: string
  match?: string | null
}

// ---- CCD (VA Health Summary — C-CDA XML), parsed deterministically by
// backend/app/intake/ccd.py; attached as extracted.ccd on the detail shape.

export interface CcdProblem {
  name: string
  code?: string | null
  code_system?: string | null
  onset_date?: string | null
  resolved_date?: string | null
  status?: string | null
}

export interface CcdMedication {
  name: string
  dose?: string | null
  dose_unit?: string | null
  start_date?: string | null
  end_date?: string | null
  status?: string | null
}

export interface CcdAllergy {
  substance: string
  reaction?: string | null
  severity?: string | null
}

export interface CcdImmunization {
  name: string
  date?: string | null
}

export interface CcdObservation {
  name: string
  value?: string | null
  unit?: string | null
  date?: string | null
  reference_range?: string
}

export interface CcdEncounter {
  description?: string | null
  date?: string | null
  location?: string | null
}

export interface CcdParsed {
  title?: string | null
  doc_date?: string | null
  problems: CcdProblem[]
  medications: CcdMedication[]
  allergies: CcdAllergy[]
  immunizations: CcdImmunization[]
  vitals: CcdObservation[]
  labs: CcdObservation[]
  encounters: CcdEncounter[]
}

export interface DocumentExtracted {
  doc_type?: DocType | null
  doc_date?: string | null
  title?: string | null
  summary?: string | null
  conditions_mentioned?: DocConditionMention[]
  is_va_decision?: boolean
  suggested_links?: DocSuggestedLink[]
  rating_summary?: DocConditionMention[]
  /** Present only when the document was a parseable C-CDA (VA Health
   * Summary) — the deterministic, no-AI extraction path. */
  ccd?: CcdParsed | null
  [key: string]: unknown
}

/** DocumentOut (list/summary — GET /documents). No `extracted` here; only
 * GET /documents/{id} (DocumentDetailOut) includes it. */
export interface DocumentItem {
  id: string
  filename: string
  content_type: string | null
  size_bytes: number
  sha256: string
  status: DocumentStatus
  doc_type: DocType | null
  doc_date: string | null
  title: string | null
  summary: string | null
  page_offsets?: number[] | null
  condition_id: string | null
  /** Set when this document duplicates another (the other's id). With
   * status==='duplicate' it was auto-skipped as identical content; with
   * status==='ready' it's a borderline near-match kept and softly flagged. */
  duplicate_of?: string | null
  review_status?: string | null
  /** Claim-relevance ('relevant'|'unclear'|'off_topic'). When `relevance_flagged`
   * is true, this document looks like it may not belong to the claim (e.g. a stray
   * receipt) and the UI offers a gentle "review / delete" — a suggestion only;
   * evidentiary doc types are never flagged and nothing is auto-removed. */
  relevance?: string | null
  relevance_flagged?: boolean
  relevance_reason?: string | null
  error: string | null
  created_at: string
  updated_at: string
  /** Only populated once the detail endpoint has been fetched (see Documents.tsx). */
  extracted?: DocumentExtracted | null
  text_content?: string | null
}

export interface DocumentUpdateInput {
  doc_type?: DocType
  title?: string
  doc_date?: string | null
  condition_id?: string | null
}

/** One retrieved excerpt from the veteran's OWN records (DocumentSearchHit).
 * `excerpt` is their uploaded text verbatim — evidence surfaced, not interpreted. */
export interface DocumentSearchHit {
  document_id: string
  filename: string
  title: string | null
  doc_type: DocType | null
  doc_date: string | null
  chunk_index: number
  char_start: number
  char_end: number
  excerpt: string
}

/** GET /documents/search (DocumentSearchOut). `semantic` = embedding ranking vs
 * the keyword fallback, so the UI can be honest about match quality. */
export interface DocumentSearchResult {
  query: string
  semantic: boolean
  hits: DocumentSearchHit[]
}

/** Per-file result of POST /documents (DocumentUploadItem). */
export interface DocumentUploadItem {
  filename: string
  accepted: boolean
  duplicate: boolean
  document?: DocumentItem | null
  existing_document_id?: string | null
  detail?: string | null
}

export interface DocumentUploadResult {
  items: DocumentUploadItem[]
}

export interface DocumentLinkInput {
  condition_id: string
  kind: EvidenceKind
}

export interface DocumentLinkResult {
  document: DocumentItem
  evidence: EvidenceItem
}

/** GET /documents/summary (routers/documents.py DocumentsSummaryOut) — counts
 * for the dashboard nudge + Documents page header strip. `processing`/
 * `queued` are convenience mirrors of by_status.processing / by_status.uploaded
 * (uploaded == queued, not yet picked up); by_status/by_type omit zero-count
 * keys (server groups by actual rows), so always read with `?? 0`. by_type
 * keys are doc_type strings OR the literal "unclassified" for null doc_type —
 * not narrowed to DocType. */
export interface DocumentSummary {
  total: number
  by_status: Partial<Record<DocumentStatus, number>>
  by_type: Record<string, number>
  processing: number
  queued: number
}

/** POST /documents/reprocess-failed (routers/documents.py ReprocessFailedOut)
 * — re-queues every status=failed document back to `uploaded`. Field is
 * `requeued`, NOT `count` — reconciled against the real router. */
export interface ReprocessFailedResult {
  requeued: number
}

/** POST /documents/reindex — (re)build the search index for ready docs that
 * predate document-RAG (no chunks) or were chunked during an embeddings outage
 * (chunks without vectors). `queued` docs are re-chunked + re-embedded from
 * their already-stored text; `already_indexed` were fully searchable already. */
export interface ReindexResult {
  queued: number
  already_indexed: number
  skipped_no_text: number
}

/** POST /documents/reset → counts of everything wiped. DESTRUCTIVE + IRREVERSIBLE:
 * permanently deletes ALL uploaded documents and everything derived from them.
 * Preserves the account, profile, ITF deadlines, symptom logs, VA connections, and
 * prior analysis-run history. Requires {confirm:true} (the backend 400s otherwise). */
export interface ResetRecords {
  documents: number
  facts: number
  chunks: number
  conditions: number
  evidence: number
  citations: number
  scenarios: number
  checklist: number
  caches: number
}

// ---- Document review queue (Phase 3 — extract-verify + OCR cross-read) ----

/** GET /documents/review-queue — one flagged document awaiting the veteran's
 * reconcile. Nothing here was silently accepted as fact. */
export interface DocumentReviewQueueItem {
  id: string
  filename: string
  title: string | null
  doc_type: DocType | null
  doc_date: string | null
  review_status: string | null
  fields_pending: number
  missing_conditions: number
  crossread_pages_flagged: number
  created_at: string
}

/** One reconcilable disagreement: the machine's value vs. what the record (or the
 * other OCR engine) actually shows, with the quote that motivated the flag. */
export interface ReviewField {
  field_id: string
  index: number
  condition: string | null
  field: string
  extracted_value: number | string | null
  candidate_value: number | string | null
  status: string // disputed | unsupported
  span: string | null
  source: string // verify | crossread
}

/** GET /documents/{id}/review — the disagreements the veteran resolves. */
export interface DocumentReviewOut {
  document_id: string
  review_status: string | null
  fields: ReviewField[]
  missing_conditions: Array<Record<string, unknown>>
  crossread: Record<string, unknown> | null
}

/** The veteran's chosen value for one flagged field. value=null clears it. */
export interface ReconcileResolution {
  field_id: string
  value: number | string | null
}

export interface ReconcileInput {
  resolutions: ReconcileResolution[]
  dismiss_missing?: string[]
  /** Mark entire document reviewed — clears remaining fields and notes. */
  clear_document?: boolean
}

export interface ReconcileResult {
  document_id: string
  review_status: string | null
  applied: number
  conditions_mentioned: Array<Record<string, unknown>>
}

// ---- Per-workspace privacy + PII→cloud consent (Phase 3) ----

/** GET/PUT /admin/services/workspace-privacy — this workspace's privacy choice.
 * `privacy_mode` is the raw column (null = inherit the global/env default);
 * `effective` is the value actually applied after resolution. */
export interface WorkspacePrivacyOut {
  workspace_id: string
  privacy_mode: boolean | null
  effective: boolean
}

/** GET/PUT /admin/services/pii-cloud-consent — this workspace's consent to let
 * the C-file quality mode send record text to a frontier model (privacy off only). */
export interface PiiCloudConsentOut {
  workspace_id: string
  consented: boolean
  consent_at: string | null
  consent_by: string | null
}

// ---- Glitter Mane bridge (routers/glitter.py) ----

export interface GlitterStatus {
  enabled: boolean
  configured?: boolean
  reachable: boolean
  detail?: string | null
}

/** GM's own condition shape, from glitter-mane/backend/app/routers/conditions.py
 * (per the glitter.py router docstring): {id, name, status, diagnosed_on, notes, created_at}. */
export interface GlitterCondition {
  id: string
  name: string
  status?: string | null
  diagnosed_on?: string | null
  notes?: string | null
  created_at?: string | null
  [key: string]: unknown
}

export interface GlitterImportResult {
  imported: number
  skipped: string[]
  conditions: { id: string; name: string }[]
}

/** GM lab result (routers/glitter.py /labs): raw, provider-authored measurement —
 * the objective severity evidence VA ratings turn on. No AI interpretation. */
export interface GlitterLab {
  id: string
  name: string
  value?: string | null
  unit?: string | null
  reference_range?: string | null
  taken_on?: string | null
  notes?: string | null
  source?: string | null
  confidence?: number | string | null
}

/** GM vital sign (routers/glitter.py /vitals): e.g. blood pressure — rated directly. */
export interface GlitterVital {
  id: string
  type: string
  value?: string | null
  unit?: string | null
  taken_on?: string | null
  notes?: string | null
  source?: string | null
  confidence?: number | string | null
}

// ---- VA Lighthouse connection (routers/va.py + va/normalize.py — wave 3) ----
// Reconciled against backend/app/routers/va.py, schemas.py (VaStatusOut,
// VaSyncOut, VaApplyIn/Out, VaClaimsOut, VaItfOut) and va/normalize.py.
// Routers are truth: everything runs on the veteran's OWN VA.gov-consented
// sign-in; the two writes (ITF; local apply) require explicit confirmation.

export type VaApiKey = 'verification' | 'claims'

export interface VaConnectionStatus {
  api: VaApiKey
  label: string
  scopes: string[]
  connected_at: string | null
  last_sync_at: string | null
  needs_reconnect: boolean
}

/** GET /va/status — never 503s; enabled=false means the feature isn't
 * configured on this server at all. */
export interface VaStatus {
  enabled: boolean
  connected: boolean
  scopes: string[]
  last_sync: string | null
  needs_reconnect: boolean
  connections: VaConnectionStatus[]
}

/** normalize.normalize_service_history() item — the profile shape plus
 * read-only extras VA returns. */
export interface VaServicePeriod {
  branch: string
  component: string
  start_date: string | null
  end_date: string | null
  discharge_character: string
  pay_grade?: string | null
  separation_reason?: string | null
  deployments?: { start_date: string | null; end_date: string | null; location: string | null }[]
}

/** normalize.normalize_disability_rating() individual rating. */
export interface VaIndividualRating {
  name: string | null
  diagnostic_code: string | null
  percent: number | null
  effective_date: string | null
  rating_end_date: string | null
  decision: string | null
  static: boolean | null
}

/** normalize.normalize_pt() — VA's booleans pass through as-is (may be null). */
export interface VaPtStatus {
  permanent_and_total?: boolean | null
  pension_award?: boolean | null
  total_disability?: boolean | null
  total_disability_effective_date?: string | null
}

/** normalize.build_suggestions() — PREVIEW ONLY; nothing applies until the
 * veteran picks items and POSTs /va/apply. */
export interface VaSuggestionConditionUpdate {
  action: 'update_rating' | 'create'
  condition_id: string | null
  condition_name?: string | null
  current_rating?: number | null
  name: string | null
  diagnostic_code: string | null
  percent: number
  effective_date: string | null
}

export interface VaSuggestions {
  profile_updates: {
    service_periods?: VaServicePeriod[]
    current_combined_rating?: { from: number | null; to: number }
  }
  condition_updates: VaSuggestionConditionUpdate[]
}

/** POST /va/sync → VaSyncOut. */
export interface VaSyncResult {
  synced_at: string
  service_periods: VaServicePeriod[]
  ratings: VaIndividualRating[]
  combined: number | null
  combined_effective_date: string | null
  pt_status: VaPtStatus
  veteran_status: string | null
  suggestions: VaSuggestions
  disclaimer: string
}

/** POST /va/apply body (VaApplyIn) — only what the veteran checked. */
export interface VaApplyInput {
  service_periods: boolean
  combined_rating: boolean
  condition_updates: { condition_id: string; percent: number }[]
  condition_creates: { name: string; diagnostic_code?: string | null; percent?: number | null }[]
}

export interface VaApplyResult {
  profile_updated: boolean
  updated: ClaimedCondition[]
  created: ClaimedCondition[]
}

/** GET /va/claims item (normalize.normalize_claim). phase is VA.gov's 5-step
 * number derived from status; null when the status string is unknown. */
export interface VaClaimEvent {
  type: string | null
  date: string | null
  phase?: number | string | null
  filename?: string | null
}

export interface VaClaim {
  id: string | null
  status: string | null
  phase: number | null
  claim_type: string | null
  date_filed: string | null
  min_est_date: string | null
  max_est_date: string | null
  open: boolean | null
  documents_needed: boolean | null
  development_letter_sent: boolean | null
  decision_letter_sent: boolean | null
  requested_decision: boolean | null
  events: VaClaimEvent[]
}

export interface VaClaimsResult {
  claims: VaClaim[]
}

/** GET /va/itf/active and POST /va/itf → VaItfOut. */
export interface VaItf {
  active: boolean
  id?: string | null
  type?: string | null
  status?: string | null
  creation_date?: string | null
  expiration_date?: string | null
}

// ---- Back-pay estimator (POST /rating/backpay — routers/rating.py +
// rating/backpay.py). Deterministic education-only math; the response always
// carries assumptions[] and not_modeled[].

export interface BackpayDependents {
  spouse: boolean
  children_under_18: number
  /** children 18–23 in a qualifying school program */
  children_in_school: number
  parents: number
  /** spouse receives Aid and Attendance */
  spouse_aa: boolean
}

export interface BackpayPeriodInput {
  /** The EFFECTIVE date of the award — §3.31 is applied server-side. */
  from_date: string
  to_date?: string | null
  combined_percent: number
  dependents: BackpayDependents
}

export interface BackpayInput {
  periods: BackpayPeriodInput[]
  payment_already_received?: BackpayPeriodInput[]
  end_date?: string | null
}

export interface BackpayMonth {
  month: string
  percent: number | null
  rate: number | null
  received: number | null
  net: number | null
  rate_year: number
  note: string
}

export interface BackpayYearSubtotal {
  entitled: number
  received: number
  net: number
}

export interface BackpayResult {
  total: number
  entitled_total: number
  received_total: number
  months: BackpayMonth[]
  by_year_subtotals: Record<string, BackpayYearSubtotal>
  excluded_months: string[]
  rate_years_covered: number[]
  rate_sources: Record<string, unknown>
  assumptions: string[]
  not_modeled: string[]
}

// ---- Legal (GET /api/legal — LegalOut, no auth) ----

export interface LegalDocs {
  terms: string
  privacy: string
}

export interface AppMeta {
  name: string
  version: string
  disclaimer: string
  va_enabled: boolean
  billing_self_serve: boolean
  /** SPA terms/privacy page (prefer for VA portal); relative or absolute. */
  legal_url?: string
  /** JSON source of truth for terms/privacy markdown. */
  legal_api_url?: string
  kb_stale: boolean | null
  kb_verified_as_of: string | null
  kb_status: 'current' | 'stale' | 'unknown'
  release_id?: string | null
  rule_version?: string | null
  rule_content_sha256?: string | null
}

// ---- Decision-letter decoder (WAVE4-DECODER-SPEC — the LOCKED DecodeOut shape,
// backend/app/decoder/). Educational cross-check only: the VA's official combined
// evaluation printed on the letter CONTROLS; every next-step surfaces a free VSO.
// Reconciled field-for-field against the spec's payload — additive only.

export type DecodeOutcome = 'granted' | 'denied' | 'deferred'

/** The three service-connection elements a denial can be missing. Kept as a
 * plain string[] on the wire for resilience; DECODE_MISSING_LABELS gives the
 * human label with a humanize() fallback for anything off this list. */
export type DecodeMissingElement = 'current_disability' | 'in_service_event' | 'nexus'

/** One contention's outcome (DecodeOut.decisions[]). `plain`/`missing_elements`
 * come from the grounded LLM pass; percent/DC/date are never asserted unless the
 * extraction surfaced them, so every one of these can be null. */
export interface DecodeDecision {
  name: string
  diagnostic_code: string | null
  decision: DecodeOutcome | null
  rating_percent: number | null
  effective_date: string | null
  va_classification: string | null
  va_classification_code: number | null
  /** null on the LLM-down fallback path (grant/deny grid from intake extraction). */
  plain: string | null
  /** Denials only — subset of DecodeMissingElement values. */
  missing_elements: string[]
  /** denied→supplemental_claim; deferred→awaiting; granted→null (or increase_or_effective_date). */
  next_step: string | null
}

/** §4.25 educational cross-check of the VA-stated combined vs our recompute from
 * the granted percents. `matches` is null when either side is unknown. */
export interface DecodeCombinedCheck {
  va_stated: number | null
  computed: number | null
  matches: boolean | null
  note: string
}

/** Appeal window = decision_date + 1 year. All three null when the decision date
 * wasn't detected in the letter. `days_remaining` is a signed int (negative = past). */
export interface DecodeAppealWindow {
  deadline: string | null
  days_remaining: number | null
  expired: boolean | null
}

/** One AMA decision-review lane (DecodeOut.options[]) — always the same three
 * (supplemental_claim / higher_level_review / board_appeal), grounded in the KB. */
export interface DecodeOption {
  key: string
  title: string
  form: string
  when: string
  detail: string
  source: string
}

/** POST/GET /documents/{id}/decode → DecodeOut (the LOCKED contract shape). */
export interface DecodeResult {
  document_id: string
  decoded_at: string
  decision_date: string | null
  decisions: DecodeDecision[]
  combined_check: DecodeCombinedCheck
  appeal_window: DecodeAppealWindow
  options: DecodeOption[]
  has_denials: boolean
  has_grants: boolean
  vso_referral: string
  disclaimer: string
  source_note: string
}

// ── WAVE 5 — readiness · ITF · symptom log · buddy statement · C&P companion ──

export type ReadinessBand = 'early' | 'building' | 'strong' | 'complete'

export interface ReadinessCondition {
  condition_id: string
  name: string
  claim_type: string
  score: number
  band: ReadinessBand
  missing: string[]
  satisfied: number
  total: number
}

export interface ReadinessOverall {
  score: number
  band: ReadinessBand
  label: string
  conditions_scored: number
}

export interface ReadinessResult {
  overall: ReadinessOverall
  conditions: ReadinessCondition[]
  disclaimer: string
}

export type ItfType = 'compensation' | 'pension' | 'survivors'

export interface ItfRecord {
  id: string | null
  type: string
  filed_date: string
  source: string
  notes: string | null
  deadline: string
  days_remaining: number
  expired: boolean
}

export interface ItfResult {
  records: ItfRecord[]
  active: ItfRecord | null
  disclaimer: string
}

export interface ItfInput {
  type: ItfType
  filed_date: string
  source?: 'manual' | 'va'
  notes?: string | null
}

// ── Deadline Guardian (routers/deadlines.py) ──────────────────────────────────
// Every 1-year clock the veteran has, computed from their own data, soonest-first.
export type DeadlineKind = 'itf' | 'appeal' | 'dependent'
export type DeadlineUrgency = 'overdue' | 'soon' | 'ok'

export interface Deadline {
  kind: DeadlineKind
  title: string
  /** ISO date, or null when the source date is unknown. */
  due_date: string | null
  /** Signed days remaining; negative once overdue; null when the date is unknown. */
  days_left: number | null
  urgency: DeadlineUrgency
  what_to_do: string
  related_route: string
}

export interface DeadlinesResult {
  deadlines: Deadline[]
  disclaimer: string
}

export interface SymptomLogEntry {
  id: string
  condition_id: string | null
  entry_date: string
  title: string
  symptoms: string
  severity: number | null
  functional_impact: string | null
  criteria_tags: string[] | null
  source: string
  created_at: string
  updated_at: string
}

export interface SymptomLogEntryInput {
  condition_id?: string | null
  entry_date: string
  title: string
  symptoms: string
  severity?: number | null
  functional_impact?: string | null
  criteria_tags?: string[] | null
}

export interface SymptomCriteriaTier {
  percent: number
  criteria: string[]
}

export interface SymptomCriteria {
  diagnostic_code: string | null
  condition_name: string | null
  tiers: SymptomCriteriaTier[]
}

export interface SymptomLogExport {
  markdown: string
  entries_count: number
  condition_name: string | null
}

export interface SymptomLogImportResult {
  imported: number
  entries: SymptomLogEntry[]
  detail: string | null
}

export interface BuddyGuidance {
  form: string
  form_title: string
  form_url: string
  prompts: string[]
  tips: string[]
  disclaimer: string
}

export interface BuddyDraftInput {
  witness_name: string
  witness_relationship: string
  veteran_name?: string | null
  condition?: string | null
  observations: string
  period?: string | null
}

export interface BuddyDraft {
  form: string
  form_title: string
  statement_markdown: string
  guidance: string[]
  disclaimer: string
}

/** POST /buddy/situation-brief — checklist the witness hits in their own words. */
export interface BuddySituationBriefInput {
  condition: string
  veteran_name?: string | null
  themes?: string[]
  period?: string | null
  known_facts?: string[]
}

export interface BuddySituationBrief {
  condition: string
  form: string
  form_url: string
  hit_list: string[]
  avoid: string[]
  starter_outline: string
  disclaimer: string
}

export interface CpCondition {
  id: string
  name: string
  diagnostic_code: string | null
  claim_type: string
}

export interface CpCriteriaTier {
  percent: number
  criteria: string[]
}

export interface CpCompanion {
  condition: CpCondition
  dbq: string | null
  what_to_expect: string[]
  rating_criteria: CpCriteriaTier[]
  how_to_describe: string[]
  dos: string[]
  donts: string[]
  disclaimer: string
}

// ── WAVE 6 — 21-526EZ application · nexus letter · personal statement (21-4138) ──

export interface Form526EvidenceRef {
  kind: string
  title: string
}

export interface Form526Contention {
  name: string
  diagnostic_code: string | null
  claim_type: string
  current_rating: number | null
  onset_date: string | null
  in_service_event: string | null
  secondary_to_name: string | null
  evidence_have: Form526EvidenceRef[]
  evidence_needed: Form526EvidenceRef[]
}

export interface Form526Service {
  periods: Array<Record<string, unknown>>
  combat: boolean
  exposures: string[]
}

export interface Form526Itf {
  type: string
  filed_date: string
  deadline: string
  days_remaining: number
  expired: boolean
}

export interface Form526Completeness {
  conditions: number
  with_evidence: number
  missing_evidence: number
}

export interface Form526Packet {
  veteran: { name?: string; email?: string; [key: string]: unknown }
  prepared_on: string | null
  service: Form526Service
  contentions: Form526Contention[]
  itf: Form526Itf | null
  completeness: Form526Completeness
  guidance: string[]
  disclaimer: string
  source_note: string
}

// routers/forms.py — official VA form fill preview (Wave 8)
export interface FormPreview {
  form_id: string
  edition: string
  omb: string
  title: string
  auto_filled: string[]
  you_complete: string[]
  fields_filled: number
  draft_filename: string
  disclaimer: string
}

export interface NexusGuidance {
  what_it_is: string
  why_it_matters: string
  prompts: string[]
  tips: string[]
  disclaimer: string
}

export interface NexusDraftInput {
  veteran_name?: string | null
  condition: string
  diagnostic_code?: string | null
  claim_type?: string | null
  in_service_event?: string | null
  secondary_to?: string | null
  clinical_summary?: string | null
}

export interface NexusDraft {
  title: string
  letter_markdown: string
  guidance: string[]
  disclaimer: string
}

/** POST /nexus/provider-brief — missing pieces + blank opinion scaffold for clinician. */
export interface NexusProviderBriefInput {
  condition: string
  claim_type?: string | null
  secondary_to?: string | null
  diagnostic_code?: string | null
  prior_denial_notes?: string | null
  missing_elements?: string[]
  records_to_review?: string[]
}

export interface NexusProviderBrief {
  condition: string
  title: string
  what_was_missing: string[]
  records_to_review: string[]
  opinion_scaffold: string
  blank_rationale_prompt: string
  disclaimer: string
}

export interface StatementGuidance {
  form: string
  form_title: string
  form_url: string
  prompts: string[]
  tips: string[]
  disclaimer: string
}

export interface StatementDraftInput {
  veteran_name?: string | null
  condition?: string | null
  topic: string
  statement: string
  period?: string | null
}

export interface StatementDraft {
  form: string
  form_title: string
  statement_markdown: string
  guidance: string[]
  disclaimer: string
}

// ── TDIU / Individual Unemployability (§4.16) — GET /tdiu + POST /tdiu/worksheet ──
// Educational screening + a work-history worksheet the veteran reviews, signs,
// and files. TDIU is VA's determination — the copy stays hedged and never says
// the veteran qualifies. Distinct from GamePlanTdiu (the Game Plan card shape).

export interface TdiuForm {
  form: string
  title: string
  url: string
  who: string
}

export interface TdiuScreen {
  at_or_near_threshold: boolean
  eligible_schedular: boolean
  why: string
  what_it_is: string
  how_it_works: string[]
  evidence: string[]
  forms: TdiuForm[]
  post_denial_note: string
  guidance_prompts: string[]
  disclaimer: string
  vso_note: string
}

export interface TdiuJob {
  employer: string
  job_title: string
  dates: string
  hours_per_week: string
  reason_ended: string
}

export interface TdiuWorksheetInput {
  veteran_name: string
  last_full_time_date: string
  highest_earnings: string
  education: string
  training: string
  jobs: TdiuJob[]
  how_conditions_limit_work: string
  doctor_restrictions: string
}

export interface TdiuWorksheet {
  form: string
  form_title: string
  worksheet_markdown: string
  guidance: string[]
  disclaimer: string
}

// ── Concurrent pay: CRDP (§1414) / CRSC (§1413a) — GET /concurrent-pay ──
// A read-only eligibility read for military retirees who also draw VA disability
// compensation: which concurrent-receipt program likely fits, what to do, and a
// rough CRDP restoration estimate. DFAS and the branch decide — never "you qualify".
export interface ConcurrentPayProgram {
  program: string
  full_name: string
  statute: string
  who_its_for: string
  how_it_works: string
  requires_application: boolean
  form?: string | null
  how_to_get_it: string
  taxable: boolean
  tax_note: string
  likely_fits: boolean
  status: string
  headline: string
}

export interface ConcurrentPayEstimate {
  monthly_ceiling: number
  is_estimate: boolean
  basis: string
}

export interface ConcurrentPay {
  combined_rating: number
  receives_retired_pay: boolean | null
  retired_pay_known: boolean
  combat_related: boolean
  crdp: ConcurrentPayProgram
  crsc: ConcurrentPayProgram
  must_elect: boolean
  election_note: string
  estimate?: ConcurrentPayEstimate | null
  what_to_do: string[]
  disclaimer: string
  vso_note: string
}

// ── Dependency / respond to a VA action — GET /dependency + POST /dependency/worksheet ──
// Add/re-add a dependent, or respond to a VA removal/reduction letter. Dependency
// changes affect pay and are the veteran's own filing (VA Form 21-686c / 21-509).
// The app prepares a worksheet the veteran reviews, signs, and files — it never
// files and never says the veteran qualifies. Copy stays hedged.

export type DependencyAction = 'add' | 'respond_to_removal'
export type DependencyRelationship = 'spouse' | 'child' | 'stepchild' | 'parent'

export interface DependencyForm {
  form: string
  title: string
  url: string
  who: string
}

export interface DependencyGuidance {
  what_it_is: string
  add_path: string[]
  removal_path: string[]
  timeline_note: string
  evidence: string[]
  forms: DependencyForm[]
  guidance_prompts: string[]
  disclaimer: string
  vso_note: string
}

export interface DependencyDependent {
  full_name: string
  relationship: DependencyRelationship
  event: string
  event_date: string
  event_place: string
  notes: string
}

export interface DependencyWorksheetInput {
  veteran_name: string
  action: DependencyAction
  dependents: DependencyDependent[]
  explanation: string
  prior_removal_note: string
}

export interface DependencyWorksheet {
  form: string
  form_title: string
  worksheet_markdown: string
  guidance: string[]
  disclaimer: string
}

// ── WAVE 7 — Appeals draft assist (Supplemental Claim / HLR / Board) ──────────

export type AppealLane = 'supplemental_claim' | 'higher_level_review' | 'board_appeal'

export interface AppealEvidenceRef {
  kind: string
  title: string
}

/** A denial (from a decoded letter) or a claimed condition the veteran could
 * supplement/appeal. `new_evidence` = their have-status evidence that matches. */
export interface AppealCandidate {
  source: 'decoded_letter' | 'condition'
  name: string
  diagnostic_code: string | null
  decision: string | null
  missing_elements: string[]
  document_id: string | null
  condition_id: string | null
  decision_date: string | null
  appeal_window: DecodeAppealWindow | null
  new_evidence: AppealEvidenceRef[]
}

/** GET /appeals/candidates. `lanes` reuses the decoder's three AMA lanes. */
export interface AppealCandidatesOut {
  candidates: AppealCandidate[]
  lanes: DecodeOption[]
  vso_referral: string
  disclaimer: string
}

export interface AppealDraftContentionInput {
  name: string
  diagnostic_code?: string | null
  missing_elements?: string[]
  new_evidence_titles?: string[]
  veteran_statement?: string | null
}

export interface AppealDraftInput {
  lane: AppealLane
  decision_date?: string | null
  contentions: AppealDraftContentionInput[]
}

export interface AppealDraftContentionOut {
  name: string
  diagnostic_code: string | null
  missing_element_plain: string[]
  new_and_relevant_evidence: string[]
  veteran_statement: string | null
  what_this_addresses: string
}

/** POST /appeals/draft → the print-ready drafted decision-review response. */
export interface AppealDraftOut {
  lane_key: string
  lane_title: string
  lane_form: string
  prepared_on: string | null
  heading: string
  intro: string
  contentions: AppealDraftContentionOut[]
  deadline: DecodeAppealWindow | null
  lane_guidance: DecodeOption[]
  veteran_attestation: string
  signature_block: string
  vso_referral: string
  disclaimer: string
  source_note: string
}

// ── WAVE 8 — Game Plan (strategy engine) ──────────────────────────────────────

export type GamePlanImpact = 'high' | 'medium' | 'low'

export interface GamePlanSnapshot {
  current_combined: number | null
  conditions_total: number
  ready_count: number
  needs_evidence_count: number
  denied_count: number
  active_itf: { type?: string; deadline?: string | null; days_remaining?: number | null } | null
}

/** One strategic option to CONSIDER. estimated_combined is §4.25 math on the
 * veteran's OWN target ratings — educational, never a prediction (basis says so). */
export interface GamePlanPathway {
  key: string
  title: string
  summary: string
  steps: string[]
  included_conditions: string[]
  estimated_combined: number | null
  estimated_combined_basis: string
  tradeoff: string
  recommended: boolean
}

export interface GamePlanAction {
  title: string
  why: string
  category: string
  condition_name: string | null
  impact: GamePlanImpact
  link: string | null
}

/** Personalized, plain-language orientation. `generated_by` is 'local' (on-fleet
 * LLM) or 'summary' (deterministic fallback). Educational — never a prediction. */
export interface GamePlanBriefing {
  headline: string
  paragraphs: string[]
  strengths: string[]
  watch_outs: string[]
  generated_by: 'local' | 'summary'
}

export interface GamePlanConditionLine {
  id: string | null
  name: string
  claim_type: string
  status: string
  /** VA disposition — the UI badges 'denied' / 'service_connected'. Optional so
   * an older backend that omits it still type-checks (defaults to 'unknown'). */
  va_status?: VaConditionStatus
  band: string
  band_label: string
  ready: boolean
  missing: string[]
  current_rating: number | null
  target_rating: number | null
  link: string | null
}

export interface GamePlanMoney {
  current_combined: number | null
  current_monthly: number | null
  basis: string
  rate_year: number | null
}

export interface GamePlanStep {
  key: string
  title: string
  body: string
  state: 'done' | 'now' | 'upcoming'
}

export interface GamePlanFocus {
  title: string
  why: string
  link: string | null
}

/** A rating-strategy trade-off to weigh before filing ("poking the bear"):
 *  §4.14 pyramiding / §4.130 one mental rating / §3.344 reduction risk /
 *  CFS–fibro trade-offs / TDIU employment risk. Educational, never a bar. */
export interface GamePlanCaution {
  key: string
  kind: 'pyramiding' | 'reduction' | 'filing_tradeoff' | 'tdiu_employment'
  title: string
  body: string
  reg: string
  conditions: string[]
  severity: 'high' | 'medium' | 'low'
}

/** TDIU screen (§4.16) — 100% pay without a 100% rating. Educational. */
export interface GamePlanTdiu {
  eligible_schedular: boolean
  why: string
  what_it_is: string
  evidence: string[]
  note: string
  reg: string
  form: string
}

/** An under-claimed opportunity: §3.310 secondary theory, RECLAIM (denied +
 * new basis / supplemental path), or Esteban-positive separate rating.
 * Educational; each still needs its own nexus/evidence. */
export interface GamePlanOpportunity {
  key: string
  kind: 'secondary' | 'underrating' | 'reclaim'
  title: string
  body: string
  reg: string
  primary: string[]
  secondary: string
  needs_nexus: boolean
  severity: 'high' | 'medium' | 'low'
  pathway?: string | null
  form?: string | null
  attach_checklist?: string[]
}

/** Ordered coach move (do this first / then / parked). Educational next step. */
export interface CoachMove {
  id?: string
  tier?: string
  title: string
  why?: string
  link?: string | null
  category?: string | null
  condition_name?: string | null
  impact?: GamePlanImpact | string
  kind?: string
}

/** Gap / reclaim / caution / etc. item on the Outstanding queue. */
export interface OutstandingItem {
  id: string
  kind: string
  severity?: string
  title: string
  why?: string
  link?: string | null
  checklist?: string[]
  status?: string
  /** primary = show by default; more = behind expand */
  tier?: string
}

/** Per-section What / Why / Do header for Claim Plan sections. */
export interface SectionGuide {
  id: string
  title: string
  what?: string
  why?: string
  do?: string
  outstanding_ids?: string[]
  status?: string
}

/** Similar-name condition cluster for cleanup on Conditions. */
export interface DuplicateCluster {
  key: string
  family?: string
  count?: number
  keep_name?: string
  keep_id?: string | null
  keep_va_status?: string
  park_names?: string[]
  park_ids?: string[]
  title?: string
  body?: string
  severity?: string
  link?: string
}

export interface InterviewQuestion {
  id: string
  topic?: string
  question: string
  why?: string
  maps_to?: string
}

/** Deterministic post-analysis interview seed (Raider / Claim Plan CTA). */
export interface InterviewSeed {
  mode?: string
  opening?: string
  questions?: InterviewQuestion[]
  closing_hint?: string
  starter_user_message?: string
}

/** Printable one-pager structure for VSO handoff / personal brief. */
export interface CaseBrief {
  title?: string
  disclaimer?: string
  profile_summary?: string
  snapshot?: Record<string, unknown> | GamePlanSnapshot
  service_connected?: Array<{ name?: string; rating?: number | null; dc?: string | null }>
  denied?: Array<{ name?: string; dc?: string | null }>
  do_this_first?: CoachMove | null
  then?: CoachMove[]
  outstanding_top?: OutstandingItem[]
  cautions?: Array<{ title?: string; kind?: string; reg?: string }>
  tdiu?: GamePlanTdiu | Record<string, unknown> | null
  duplicates?: DuplicateCluster[]
}

/** Post-analysis coach layer on GET /strategy (1.9.31+). */
export interface GamePlanCoach {
  do_this_first?: CoachMove | null
  do_this_first_reason?: string | null
  then?: CoachMove[]
  parked?: CoachMove[]
  outstanding?: OutstandingItem[]
  /** Short scannable list (preferred for UI). */
  outstanding_primary?: OutstandingItem[]
  /** Lower priority / informational — behind "Show more". */
  outstanding_more?: OutstandingItem[]
  outstanding_count?: number
  section_guides?: SectionGuide[]
  duplicates?: DuplicateCluster[]
  interview?: InterviewSeed | null
  case_brief?: CaseBrief | null
  post_analysis_cta?: {
    title?: string
    body?: string
    interview_path?: string
    plan_path?: string
  } | null
}

/** GET /strategy → the assembled Game Plan. */
export interface GamePlanOut {
  generated_at: string
  snapshot: GamePlanSnapshot
  pathways: GamePlanPathway[]
  priority_actions: GamePlanAction[]
  has_conditions: boolean
  disclaimer: string
  vso_referral: string
  source_note: string
  // Wave 9 — deeper briefing (optional/additive)
  briefing?: GamePlanBriefing | null
  condition_lines?: GamePlanConditionLine[]
  money?: GamePlanMoney | null
  process_roadmap?: GamePlanStep[]
  focus?: GamePlanFocus | null
  // Rating-strategy intelligence (optional/additive)
  cautions?: GamePlanCaution[]
  tdiu?: GamePlanTdiu | null
  opportunities?: GamePlanOpportunity[]
  // Coach layer (1.9.31+): do-this-first, outstanding, section guides
  coach?: GamePlanCoach | null
}

/** One proposed or applied va_status write from formal decision letters.
 * GET|POST /strategy/decision-statuses[ /apply ]. */
export interface DecisionStatusUpdate {
  condition_id: string | null
  name: string
  from_status: string
  to_status: string
  decision_name?: string
  set_current_rating?: number | null
}

/** Preview or apply of decision-letter statuses onto claimed conditions still
 * marked unknown. Educational organizing only — not a VA determination. */
export interface DecisionStatusApplyOut {
  dry_run: boolean
  updated: number
  updates: DecisionStatusUpdate[]
  note?: string
}

// ── Deep-dive rating orchestration ───────────────────────────────────────────

/** The deterministic reason a rating entered the deep-dive candidate space.
 * The local model can explain one of these candidates, but cannot create one. */
export type DeepDiveOrigin = 'direct' | 'increase' | 'secondary' | 'presumptive' | 'concurrent'

/** VA burden-of-proof register a theory finding carries (Phase 2b). `null` on a
 * deterministic "floor" finding — the rules are settled, not an opinion. */
export type DeepDiveConfidenceLevel =
  | 'more_likely_than_not'
  | 'at_least_as_likely'
  | 'less_likely_than_not'
  | 'insufficient_evidence'

/** One structured grounding citation on a finding (Phase 2b). Loosely typed —
 * the backend attaches source pointers (reg / card / record span) as plain
 * objects; the UI renders whatever recognizable label fields are present. */
export interface DeepDiveCitation {
  kind?: string
  ref?: string
  label?: string
  cfr?: string
  card_id?: string
  quote?: string
  [key: string]: unknown
}

export interface CandidateRating {
  diagnostic_code: string
  title: string
  body_system: string | null
  origin: DeepDiveOrigin
  seed_signal: string
  source_ref: string | null
  primary_dc: string | null
}

/** One reviewed, grounded expert finding. Resolver annotations remain visible
 * even when a lane is left out of the combined-rating projection. */
export interface DeepDiveFinding {
  specialist: string
  kind: string
  key: string
  title: string
  body: string
  severity: GamePlanImpact
  regs: string[]
  card_ids: string[]
  evidence_refs: string[]
  needs: string[]
  suggested_form: string | null
  confidence: number
  /** Phase 2b: 'floor' = the deterministic seed (confidence 1.0, no register);
   * 'theory' = an originated opinion above it (0<confidence<1, a register + cites). */
  layer?: 'floor' | 'theory'
  confidence_level?: DeepDiveConfidenceLevel | null
  citations?: DeepDiveCitation[]
  reviewed: boolean
  review_note: string | null
  seed: Record<string, unknown>
  det_body: string
  enriched: boolean
  diagnostic_code: string
  origin: DeepDiveOrigin
  rating_percent: number | null
  superseded_by: string | null
  excluded_by: string | null
  conflict_reason: string | null
  conflict_cfr: string | null
  active: boolean
}

export interface DeepDiveNotification {
  has_new_findings: boolean
  new_finding_keys: string[]
  trigger: string | null
  generated_at: string | null
}

/** Cached result returned by GET /strategy/deepdive and refreshed explicitly
 * by POST /strategy/deepdive/run. `projected_combined` is planning math, never
 * a prediction of a VA decision. */
export interface DeepDiveResult {
  generated_at: string
  candidates: CandidateRating[]
  candidates_considered: number
  findings: DeepDiveFinding[]
  projected_combined: number
  current_combined: number | null
  delta: number
  notes: string[]
  notification?: DeepDiveNotification | null
}

// ── WAVE 10 — Military records corrections (DRB / BCMR / PDBR) ─────────────────

export type CorrectionGoal =
  | 'discharge_upgrade'
  | 'narrative_reason'
  | 're_code'
  | 'records_error'
  | 'medical_rating'
export type LiberalTrigger = 'ptsd' | 'tbi' | 'mental_health' | 'mst'

export interface CorrectionSituationInput {
  goals: CorrectionGoal[]
  years_since_separation?: number | null
  general_court_martial?: boolean
  drb_denied?: boolean
  related_to?: LiberalTrigger[]
  medically_separated_2001_2009?: boolean
  dod_rating_20_or_less?: boolean
  discharge_char?: string | null
}

export interface CorrectionLiberal {
  applies: boolean
  note: string
}

export interface CorrectionAlsoConsider {
  board: string
  form: string
  when: string
}

/** POST /corrections/route → which military board + form fits this situation. */
export interface CorrectionRouteResult {
  routed: boolean
  board: string | null
  board_full: string | null
  form: string | null
  form_title: string | null
  why: string
  deadline_note: string | null
  liberal_consideration: CorrectionLiberal
  character_of_discharge_note: string | null
  also_consider: CorrectionAlsoConsider[]
  warnings: string[]
  source: string | null
  vso_referral: string
  legal_aid_referral: string
  disclaimer: string
}

export interface CorrectionRequestedItem {
  field: string
  current?: string | null
  requested?: string | null
}

export interface CorrectionDraftInput {
  situation: CorrectionSituationInput
  applicant_name?: string | null
  corrections_requested?: CorrectionRequestedItem[]
  veteran_statement?: string | null
}

export interface CorrectionEvidenceItem {
  item: string
  why: string
}

/** POST /corrections/draft → the print-ready records-correction application packet. */
export interface CorrectionPacket {
  route: CorrectionRouteResult
  prepared_on: string | null
  heading: string
  applicant_name: string | null
  corrections_requested: CorrectionRequestedItem[]
  statement_of_error_or_injustice: string
  veteran_statement: string | null
  evidence_checklist: CorrectionEvidenceItem[]
  instructions: string[]
  attestation: string
  signature_block: string
  vso_referral: string
  legal_aid_referral: string
  disclaimer: string
  source_note: string
}

// ── Officer rank / promotion correction — GET /corrections/rank + POST /corrections/rank/analyze ──
// A missed or never-carried-out officer promotion (e.g. an officer who stayed a
// 2LT/1LT past the point at which the record shows promotion should have issued)
// may be correctable through the military records-correction board. This NEVER
// promises a promotion — the board decides. Copy stays hedged; the UI renders the
// backend's strings and adds none of its own.

export type RankSelection = '1lt' | 'capt'
export type RankStrength = 'strong' | 'moderate' | 'weak' | 'needs_dates'

/** GET /corrections/rank → educational guidance for the officer-rank correction page. */
export interface RankGuidanceOut {
  what_it_is: string
  how_it_works: string[]
  prompts: string[]
  thresholds: string[]
  disclaimer: string
}

/** POST /corrections/rank/analyze body — every field optional; dates are plain
 * strings the user types (YYYY-MM-DD, YYYY-MM, or YYYY all accepted). */
export interface RankAnalysisIn {
  commission_date?: string
  date_of_rank_2lt?: string
  promoted_to_1lt?: boolean
  date_of_rank_1lt?: string
  promoted_to_capt?: boolean
  separation_date?: string
  medically_retired?: boolean
  selected_for_promotion?: RankSelection | null
  completed_captains_career_course?: boolean
  branch?: string
}

/** One grade-to-grade finding — hedged: "may be correctable", the board decides. */
export interface RankFinding {
  grade_from: string
  grade_to: string
  strength: RankStrength
  headline: string
  reasoning: string
  what_to_request: string
}

/** POST /corrections/rank/analyze → the hedged rank-correction analysis. */
export interface RankAnalysisOut {
  findings: RankFinding[]
  overall: string
  retired_grade_note: string
  board: string
  form: string
  form_title: string
  human_checklist: string[]
  non_army_note?: string | null
  vso_referral: string
  legal_aid_referral: string
  disclaimer: string
}

// ── Import from VA — reconcile (POST /va/reconcile) ───────────────────────────
// The veteran's own VA rating/claim data (delivered by the VA Connect browser
// extension in the URL hash, or pasted in) reconciled against their conditions.
// PREVIEW is a dry-run (apply:false); nothing changes until they confirm
// (apply:true). Reconciled field-for-field against the backend contract.

/** The VA disposition of a single condition on the incoming record. */
export type VaDisposition = 'service_connected' | 'denied' | 'pending'

/** One incoming VA condition (part of VaReconcileInput / the parsed import). */
export interface VaReconcileCondition {
  name: string
  percent: number | null
  effective_date: string | null
  disposition: VaDisposition
}

/** The raw payload the extension/paste-box supplies — the subset of the
 * reconcile input the caller provides before we add create_new / apply. */
export interface VaImportData {
  combined_rating: number | null
  conditions: VaReconcileCondition[]
}

/** POST /va/reconcile body. */
export interface VaReconcileInput extends VaImportData {
  create_new: boolean
  apply: boolean
}

/** A VA condition matched to one of the veteran's existing conditions. */
export interface VaReconcileMatched {
  va_name: string
  condition_id: string
  condition_name: string
  set_current_rating: number | null
  set_va_status: string
  changed: boolean
}

/** A VA condition not (yet) on the veteran's list. `created` = it was added
 * this run (only possible when create_new was true and apply ran). */
export interface VaReconcileUnmatched {
  name: string
  disposition: string
  percent: number | null
  created: boolean
}

/** POST /va/reconcile → the preview (apply:false) or applied (apply:true) result. */
export interface VaReconcileResult {
  combined_rating: number | null
  matched: VaReconcileMatched[]
  unmatched: VaReconcileUnmatched[]
  applied: boolean
}
