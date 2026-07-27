"""Pydantic v2 request/response schemas for the whole API contract.

The ROUTERS agent imports every request/response body from here (models.py and
this file are owned by BACKEND-CORE; if a field is missing it's a spec bug — flag
it, don't fork the schema).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

ClaimType = Literal["direct", "secondary", "presumptive", "increase"]
ConditionStatus = Literal[
    "considering", "gathering_evidence", "ready_to_file", "filed", "decided"
]
# The condition's real VA disposition (what the veteran / a VA reconciliation
# recorded), distinct from `ConditionStatus` (the veteran's own workflow stage).
VaConditionStatus = Literal["unknown", "service_connected", "denied", "pending"]
EvidenceKind = Literal[
    "diagnosis",
    "service_record",
    "nexus_letter",
    "dbq",
    "lay_statement",
    "continuity",
    "treatment_record",
    "other",
]
EvidenceStatus = Literal["have", "need", "requested", "not_applicable"]
KBCardType = Literal["rating_criteria", "rule", "presumptive", "dbq", "process"]
Side = Literal["left", "right"]
BenefitCategory = Literal["federal", "state", "commercial"]
BenefitConfidence = Literal["established", "varies"]


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Auth ────────────────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    email: EmailStr
    # 72-byte cap: bcrypt silently truncates beyond 72 bytes.
    password: str = Field(min_length=8, max_length=72)
    full_name: str = Field(default="", max_length=255)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(_ORM):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    email_verified: bool = True
    # Unicorn Commander profile photo (Keycloak `picture` claim), or None for native
    # accounts — the UI falls back to rendered initials.
    avatar_url: str | None = None
    platform_admin: bool = False
    created_at: datetime


# ── Email verification + password reset (Wave 12) ────────────────────────────
class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str = Field(min_length=8, max_length=4096)


class PasswordResetIn(BaseModel):
    token: str = Field(min_length=8, max_length=4096)
    password: str = Field(min_length=8, max_length=72)


class SimpleMessage(BaseModel):
    ok: bool = True
    message: str = ""


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AuthConfigOut(BaseModel):
    """Public login capabilities. The frontend renders only actions that can finish."""

    sso_enabled: bool
    sso_label: str = "Unicorn Commander"
    password_login_enabled: bool
    registration_open: bool
    registration_mode: Literal["open", "bootstrap", "closed"]
    email_enabled: bool
    password_reset_enabled: bool


# ── Veteran profile ─────────────────────────────────────────────────────────
class ServicePeriod(BaseModel):
    branch: str = ""
    component: str = ""
    start_date: date | None = None
    end_date: date | None = None
    discharge_character: str = ""


class Exposures(BaseModel):
    burn_pits: bool = False
    agent_orange: bool = False
    gulf_war: bool = False
    radiation: bool = False
    camp_lejeune: bool = False
    pow: bool = False
    mustard_gas: bool = False
    pow_internment_days: int | None = None
    other: str = ""
    locations: list[str] = Field(default_factory=list)


# ── Veteran identity + household (authoritative data used to PRE-FILL the veteran's
# own official VA forms as a DRAFT they review and sign). LEGAL/PII LINE: we collect
# and fill name, contact, DOB, address, and dependents — never the SSN (the veteran
# hand-writes it on the signed form). VA file number is OPTIONAL and sensitive; it is
# for many veterans their SSN, so it is opt-in and only rendered onto the veteran's
# own draft, never elsewhere. ─────────────────────────────────────────────────────
class MailingAddress(BaseModel):
    street: str | None = None
    unit: str | None = None
    city: str | None = None
    state: str | None = Field(default=None, max_length=2)
    zip: str | None = Field(default=None, max_length=10)
    country: str | None = "USA"


class Dependent(BaseModel):
    """A spouse or child the dependency forms (21-686c) need. NO SSN stored — the
    veteran writes each dependent's SSN by hand on the signed form."""

    relationship: Literal["spouse", "child", "stepchild", "parent"] = "child"
    full_name: str | None = None
    date_of_birth: date | None = None
    # spouse-specific
    marriage_date: date | None = None
    marriage_location: str | None = None
    # child-specific
    in_school: bool | None = None
    seriously_disabled: bool | None = None


class VeteranIdentity(BaseModel):
    """Identifying + contact data for form-fill. NO SSN field by design."""

    full_name: str | None = None
    date_of_birth: date | None = None
    phone: str | None = None
    email: str | None = None
    address: MailingAddress = Field(default_factory=MailingAddress)
    # OPTIONAL, sensitive (often the SSN). Only ever rendered onto the veteran's own draft.
    va_file_number: str | None = None
    place_of_birth: str | None = None


class ProfileIn(BaseModel):
    """PUT /profile body — upsert (creates the row if missing)."""

    service_periods: list[ServicePeriod] = Field(default_factory=list)
    combat_service: bool = False
    receives_military_retired_pay: bool | None = None
    combat_related_disability: bool | None = None
    medically_retired: bool | None = None
    medically_separated: bool | None = None
    exposures: Exposures = Field(default_factory=Exposures)
    current_combined_rating: int | None = Field(default=None, ge=0, le=100)
    state: str | None = Field(default=None, min_length=2, max_length=2)
    notes: str | None = None
    identity: VeteranIdentity = Field(default_factory=VeteranIdentity)
    dependents: list[Dependent] = Field(default_factory=list)


class ProfileOut(_ORM):
    id: uuid.UUID
    service_periods: list[ServicePeriod] | None = None
    combat_service: bool = False
    receives_military_retired_pay: bool | None = None
    combat_related_disability: bool | None = None
    medically_retired: bool | None = None
    medically_separated: bool | None = None
    exposures: Exposures | None = None
    current_combined_rating: int | None = None
    state: str | None = None
    notes: str | None = None
    identity: VeteranIdentity | None = None
    dependents: list[Dependent] | None = None


# ── Identity suggestions from imported records (GET /profile/identity-suggestions)
# Best-effort, LOCAL-model extraction of the veteran's OWN identity from their
# uploaded documents, aggregated into ONE proposal the veteran reviews and confirms.
# Nothing here is auto-saved to profile.identity, and — by construction — NO SSN is
# ever extracted or returned (see intake/identity_extract.py). ────────────────────
class IdentitySuggestionSource(BaseModel):
    """Which imported document supplied a proposed field (so the panel can say
    'from your March 2019 rating decision'). Account-seeded fields omit document_id."""

    document_id: uuid.UUID | None = None
    title: str | None = None
    # str (not the DocType Literal, which is defined lower in this file): the value
    # comes straight from the already-validated Document.doc_type column.
    doc_type: str | None = None
    doc_date: date | None = None


class IdentitySuggestionsOut(BaseModel):
    """The aggregated proposal. `identity`/`dependents` reuse the profile shapes so
    the client can drop them straight into the profile form; `sources` maps a field
    name (full_name | date_of_birth | phone | address | dependents) to its source
    document. Empty (has_suggestions=False) when nothing was found — the UI renders
    nothing in that case."""

    has_suggestions: bool = False
    identity: VeteranIdentity = Field(default_factory=VeteranIdentity)
    dependents: list[Dependent] = Field(default_factory=list)
    sources: dict[str, IdentitySuggestionSource] = Field(default_factory=dict)
    disclaimer: str = ""


class LocationSuggestionsOut(BaseModel):
    """GET /profile/location-suggestions — places found in records."""

    locations: list[str] = Field(default_factory=list)
    disclaimer: str = ""


# ── Benefits directory ─────────────────────────────────────────────────────
class BenefitItem(BaseModel):
    id: str
    name: str
    description: str
    category: BenefitCategory
    min_rating: int = Field(ge=0, le=100)
    requires_pt: bool = False
    states: list[str] = Field(default_factory=list)
    source_name: str
    source_url: str
    confidence: BenefitConfidence
    effective_date: date | None = None
    verified_as_of: date | None = None


class BenefitsOut(BaseModel):
    verified_as_of: date
    federal: list[BenefitItem] = Field(default_factory=list)
    state: list[BenefitItem] = Field(default_factory=list)
    commercial: list[BenefitItem] = Field(default_factory=list)


# ── Claimed conditions ──────────────────────────────────────────────────────
class ConditionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    body_system: str | None = Field(default=None, max_length=64)
    diagnostic_code: str | None = Field(default=None, max_length=8)
    claim_type: ClaimType = "direct"
    secondary_to: uuid.UUID | None = None
    current_rating: int | None = Field(default=None, ge=0, le=100)
    target_rating: int | None = Field(default=None, ge=0, le=100)
    status: ConditionStatus = "considering"
    va_status: VaConditionStatus = "unknown"
    onset_date: date | None = None
    in_service_event: str | None = None
    nexus_notes: str | None = None
    dbq_form: str | None = Field(default=None, max_length=160)
    notes: str | None = None


class ConditionUpdate(BaseModel):
    """PATCH /conditions/{id} — every field optional; only provided keys change."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    body_system: str | None = Field(default=None, max_length=64)
    diagnostic_code: str | None = Field(default=None, max_length=8)
    claim_type: ClaimType | None = None
    secondary_to: uuid.UUID | None = None
    current_rating: int | None = Field(default=None, ge=0, le=100)
    target_rating: int | None = Field(default=None, ge=0, le=100)
    status: ConditionStatus | None = None
    va_status: VaConditionStatus | None = None
    onset_date: date | None = None
    in_service_event: str | None = None
    nexus_notes: str | None = None
    dbq_form: str | None = Field(default=None, max_length=160)
    notes: str | None = None


class ConditionOut(_ORM):
    id: uuid.UUID
    name: str
    body_system: str | None = None
    diagnostic_code: str | None = None
    claim_type: ClaimType
    secondary_to: uuid.UUID | None = None
    current_rating: int | None = None
    target_rating: int | None = None
    status: ConditionStatus
    va_status: VaConditionStatus = "unknown"
    onset_date: date | None = None
    in_service_event: str | None = None
    nexus_notes: str | None = None
    dbq_form: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Evidence ────────────────────────────────────────────────────────────────
class EvidenceCreate(BaseModel):
    kind: EvidenceKind = "other"
    title: str = Field(min_length=1, max_length=255)
    status: EvidenceStatus = "need"
    source: str | None = Field(default=None, max_length=255)
    file_ref: str | None = Field(default=None, max_length=512)
    notes: str | None = None


class EvidenceUpdate(BaseModel):
    kind: EvidenceKind | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: EvidenceStatus | None = None
    source: str | None = Field(default=None, max_length=255)
    file_ref: str | None = Field(default=None, max_length=512)
    notes: str | None = None


class EvidenceOut(_ORM):
    id: uuid.UUID
    condition_id: uuid.UUID
    document_id: uuid.UUID | None = None
    kind: EvidenceKind
    title: str
    status: EvidenceStatus
    source: str | None = None
    file_ref: str | None = None
    notes: str | None = None
    rationale: dict | None = None
    citations: list[dict] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EvidenceRationaleOut(BaseModel):
    elements: list[str] = Field(default_factory=list)
    why: str


class EvidenceCitationIn(BaseModel):
    quote: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    chunk_index: int = Field(ge=0)
    note: str | None = None


class EvidenceCitationOut(BaseModel):
    document_id: uuid.UUID
    source_title: str
    quote: str
    char_start: int
    char_end: int
    page: int | None = None
    chunk_index: int
    note: str | None = None
    selected: bool = False


class EvidenceWithRationaleOut(EvidenceOut):
    rationale: EvidenceRationaleOut | None = None
    citations: list[EvidenceCitationOut] = Field(default_factory=list)


# ── Checklist ───────────────────────────────────────────────────────────────
class ChecklistCreate(BaseModel):
    condition_id: uuid.UUID | None = None
    text: str = Field(min_length=1)
    category: str | None = Field(default=None, max_length=64)
    sort: int = 0


class ChecklistUpdate(BaseModel):
    """PATCH /checklist/{id} — typically just toggling `done`."""

    text: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, max_length=64)
    done: bool | None = None
    sort: int | None = None


class ChecklistOut(_ORM):
    id: uuid.UUID
    condition_id: uuid.UUID | None = None
    text: str
    category: str | None = None
    done: bool
    sort: int
    created_at: datetime


# ── Evidence-gap analysis (GET /conditions/{id}/gaps) ───────────────────────
class GapItem(BaseModel):
    """One deterministic evidence gap (rule-derived, with the KB cite)."""

    kind: EvidenceKind
    label: str
    detail: str | None = None
    source: str | None = None


class GapsOut(BaseModel):
    condition_id: uuid.UUID
    gaps: list[GapItem] = Field(default_factory=list)
    dbq_form: str | None = None
    checklist: list[ChecklistOut] = Field(default_factory=list)


# ── Rating engine (POST /rating/calculate, scenarios) ───────────────────────
class RatingEntryIn(BaseModel):
    """One disability entry for the §4.25/§4.26 engine. `side` non-null marks a
    bilateral-candidate extremity entry; `group` names its bilateral pairing."""

    label: str = ""
    percent: int = Field(ge=0, le=100)
    side: Side | None = None
    group: str | None = None


class RatingCalculateIn(BaseModel):
    entries: list[RatingEntryIn] = Field(min_length=1)


class RatingResultOut(BaseModel):
    """Serialized CombinedResult from backend/app/rating/engine.py — the server
    computes; the LLM and the client never do the math."""

    combined: int
    raw: int
    steps: list[dict] = Field(default_factory=list)
    bilateral_factor_applied: bool = False
    smc_flags: list[dict] = Field(default_factory=list)


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    entries: list[RatingEntryIn] = Field(min_length=1)


class ScenarioOut(_ORM):
    id: uuid.UUID
    name: str
    entries: list[RatingEntryIn]
    result: RatingResultOut | None = None
    created_at: datetime


# ── Knowledge base ──────────────────────────────────────────────────────────
class KBCardOut(_ORM):
    id: uuid.UUID
    card_type: KBCardType
    title: str
    body_system: str | None = None
    diagnostic_code: str | None = None
    source: str
    source_name: str | None = None
    source_url: str | None = None
    effective_date: date | None = None
    verified_as_of: date | None = None
    content: str
    data: dict | None = None


class KBRefreshSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    url: str = Field(min_length=8, max_length=2048)
    note: str | None = Field(default=None, max_length=1000)


class KBRefreshRatingCriteriaItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=512)
    content: str = Field(min_length=1)
    body_system: str | None = Field(default=None, max_length=64)
    diagnostic_code: str | None = Field(default=None, max_length=8)
    source: str | None = Field(default=None, max_length=255)
    source_name: str = Field(min_length=1, max_length=255)
    source_url: str = Field(min_length=8, max_length=2048)
    effective_date: date
    data: dict = Field(default_factory=dict)
    content_kind: Literal["criteria", "explainer"] = "criteria"
    affects_advice: bool = True


class KBRefreshBenefitItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    category: BenefitCategory
    min_rating: int = Field(ge=0, le=100)
    requires_pt: bool = False
    states: list[str] = Field(default_factory=list)
    source_name: str = Field(min_length=1, max_length=255)
    source_url: str = Field(min_length=8, max_length=2048)
    effective_date: date
    confidence: BenefitConfidence = "varies"


class KBRefreshBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["rating_criteria", "benefit"]
    items: list[KBRefreshRatingCriteriaItem | KBRefreshBenefitItem] = Field(min_length=1)
    source: KBRefreshSource
    verified_as_of: date
    batch_id: str | None = Field(default=None, min_length=1, max_length=160)
    applied_by: str | None = Field(default=None, max_length=255)


class KBRefreshDiffItem(BaseModel):
    key: str
    title: str | None = None
    action: Literal["create", "update", "unchanged"]
    changes: dict = Field(default_factory=dict)


class KBRefreshDiffOut(BaseModel):
    kind: str
    verified_as_of: date
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    items: list[KBRefreshDiffItem] = Field(default_factory=list)


class KBRefreshOut(BaseModel):
    ok: bool = True
    dry_run: bool = False
    batch_id: str
    revision_id: uuid.UUID | None = None
    diff: KBRefreshDiffOut


class KBRevisionOut(BaseModel):
    id: uuid.UUID
    batch_id: str
    kind: str
    source: dict
    verified_as_of: date
    item_count: int
    diff: dict
    applied_by: str
    created_at: datetime


class KBRefreshSignalOut(BaseModel):
    id: uuid.UUID
    topic: str
    status: str
    reason: str
    kb_verified_as_of: date
    detected_source_date: date | None = None
    detail: dict | None = None
    created_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None = None


class KBRevisionsOut(BaseModel):
    revisions: list[KBRevisionOut] = Field(default_factory=list)
    open_signals: list[KBRefreshSignalOut] = Field(default_factory=list)


class KBStatusOut(BaseModel):
    kb_verified_as_of: date
    freshness: dict | None = None
    open_signals: list[KBRefreshSignalOut] = Field(default_factory=list)


# ── Analysis (LLM+KB; every item cites its kb_cards source) ─────────────────
class AnalysisMapIn(BaseModel):
    """POST /analysis/map-conditions — empty `names` = use the user's claimed
    conditions."""

    names: list[str] = Field(default_factory=list)


class RatingTierOut(BaseModel):
    """One tier of a diagnostic code's criteria, from a kb_card's structured data."""

    percent: int = Field(ge=0, le=100)
    criteria: str
    evidence_needed: list[str] = Field(default_factory=list)


class ConditionMappingOut(BaseModel):
    name: str
    diagnostic_code: str | None = None
    body_system: str | None = None
    tiers: list[RatingTierOut] = Field(default_factory=list)
    under_rated: bool = False
    rationale: str | None = None
    source: str  # the kb_card cite, e.g. "38 CFR §4.130, DC 9411"


class AnalysisMapOut(BaseModel):
    items: list[ConditionMappingOut] = Field(default_factory=list)
    disclaimer: str


class SecondariesIn(BaseModel):
    """POST /analysis/secondaries — empty `names` = use the user's claimed
    conditions."""

    names: list[str] = Field(default_factory=list)


class SecondarySuggestionOut(BaseModel):
    primary: str
    secondary: str
    rationale: str  # "discuss with your provider" framing — educational only
    source: str


class SecondariesOut(BaseModel):
    items: list[SecondarySuggestionOut] = Field(default_factory=list)
    disclaimer: str


class PresumptiveMatchOut(BaseModel):
    """One RULE-BASED presumptive match (profile × KB lists; the LLM only phrases,
    never decides membership)."""

    condition: str
    program: str  # e.g. "PACT Act — burn pits", "Agent Orange", "Camp Lejeune"
    rationale: str
    source: str


class PresumptivesOut(BaseModel):
    matches: list[PresumptiveMatchOut] = Field(default_factory=list)
    disclaimer: str


# ── Glitter Mane seam ───────────────────────────────────────────────────────
class GlitterStatusOut(BaseModel):
    enabled: bool
    reachable: bool = False
    detail: str | None = None


class GlitterImportIn(BaseModel):
    """POST /glitter/import-conditions — Glitter Mane condition ids to copy into
    claimed_conditions."""

    condition_ids: list[str] = Field(min_length=1)


class GlitterEvidenceImportIn(BaseModel):
    """POST /glitter/import-evidence — attach selected Glitter Mane objective
    measurements (labs / vitals) to a Valor claimed condition as EvidenceItems.

    LEGAL LANE: only RAW provider-authored measurement values cross the bridge —
    never a Glitter Mane AI interpretation, imaging read, or consult opinion.
    Imported rows are severity/continuity evidence the veteran already owns.
    """

    condition_id: str
    lab_ids: list[str] = Field(default_factory=list)
    vital_ids: list[str] = Field(default_factory=list)


# ── Documents (intake pipeline) ─────────────────────────────────────────────
DocType = Literal[
    "rating_decision",
    "decision_letter",
    "str",
    "dbq",
    "treatment_record",
    "private_medical_opinion",
    "lay_statement",
    "service_record",
    "other",
]
DocumentStatus = Literal["uploaded", "processing", "ready", "failed", "duplicate"]


class DocumentOut(_ORM):
    """List/summary view of an uploaded document (no text body)."""

    id: uuid.UUID
    filename: str
    content_type: str | None = None
    size_bytes: int = 0
    sha256: str
    status: DocumentStatus
    doc_type: DocType | None = None
    doc_date: date | None = None
    title: str | None = None
    summary: str | None = None
    page_offsets: list[int] | None = None
    condition_id: uuid.UUID | None = None
    review_status: str | None = None
    # When set, this document duplicates another (the referenced document's id). With
    # status=="duplicate" it was auto-skipped as near-identical content; with
    # status=="ready" it's a borderline near-match kept and softly flagged.
    duplicate_of: uuid.UUID | None = None
    # Claim-relevance (intake.classify): 'relevant'|'unclear'|'off_topic'. When
    # `relevance_flagged` is true the document looks like it may not belong to the
    # claim (e.g. a stray receipt) and the UI can offer "review / delete" — a
    # SUGGESTION only; evidentiary doc types are never flagged and nothing is
    # auto-removed. `relevance_reason` is the short why, present only when flagged.
    relevance: str | None = None
    relevance_flagged: bool = False
    relevance_reason: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentDetailOut(DocumentOut):
    """GET /documents/{id} — full view incl. validated extraction + parsed text."""

    extracted: dict | None = None
    text_content: str | None = None


class DocumentSearchHit(BaseModel):
    """One retrieved excerpt from the veteran's OWN records (document RAG).

    LEGAL LANE: `excerpt` is the veteran's uploaded text VERBATIM — evidence
    surfaced, not interpreted. Parent-document fields let the UI cite the source.
    """

    document_id: uuid.UUID
    filename: str
    title: str | None = None
    doc_type: DocType | None = None
    doc_date: date | None = None
    chunk_index: int
    char_start: int
    char_end: int
    excerpt: str


class DocumentSearchOut(BaseModel):
    """GET /documents/search — top excerpts across the veteran's records.

    `semantic` reports whether the ranking used embeddings (meaning-based) or the
    keyword fallback, so the UI can be honest about the match quality.
    """

    query: str
    semantic: bool
    hits: list[DocumentSearchHit]


class DocumentUpdate(BaseModel):
    """PATCH /documents/{id} — the veteran corrects the machine's guess. Only
    provided keys change; condition_id=null clears the primary link."""

    doc_type: DocType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    doc_date: date | None = None
    condition_id: uuid.UUID | None = None


class DocumentUploadItem(BaseModel):
    """Per-file result of POST /documents (multi-file multipart)."""

    filename: str
    accepted: bool
    duplicate: bool = False  # sha256 dedupe: same bytes already uploaded
    document: DocumentOut | None = None
    existing_document_id: uuid.UUID | None = None
    detail: str | None = None  # human-readable rejection reason


class DocumentUploadOut(BaseModel):
    items: list[DocumentUploadItem] = Field(default_factory=list)


class DocumentLinkIn(BaseModel):
    """POST /documents/{id}/link — the veteran's explicit confirmation. This is
    the ONLY path from a suggestion to an evidence link; nothing auto-links."""

    condition_id: uuid.UUID
    kind: EvidenceKind = "other"


class DocumentLinkOut(BaseModel):
    document: DocumentOut
    evidence: EvidenceOut


# ── Extract-verify / OCR cross-read review queue (Phase 3 intake) ────────────
class ReviewFieldOut(BaseModel):
    """One reconcilable disagreement: the machine's value vs. what the source (or
    the other OCR engine) actually shows, with the quote that motivated the flag.
    field_id ("<condition-index>:<field>") is what POST /reconcile writes back."""

    field_id: str
    index: int
    condition: str | None = None
    field: str
    extracted_value: int | str | None = None
    candidate_value: int | str | None = None
    status: str  # disputed | unsupported
    span: str | None = None
    source: str  # verify | crossread


class DocumentReviewQueueItem(BaseModel):
    """One flagged document awaiting the veteran's reconcile."""

    id: uuid.UUID
    filename: str
    title: str | None = None
    doc_type: DocType | None = None
    doc_date: date | None = None
    review_status: str | None = None
    fields_pending: int = 0
    missing_conditions: int = 0
    crossread_pages_flagged: int = 0
    created_at: datetime


class DocumentReviewOut(BaseModel):
    """GET /documents/{id}/review — the disagreements the veteran resolves."""

    document_id: uuid.UUID
    review_status: str | None = None
    fields: list[ReviewFieldOut] = Field(default_factory=list)
    missing_conditions: list[dict] = Field(default_factory=list)
    crossread: dict | None = None


class DocTypeGuidanceOut(BaseModel):
    """One doc-type's plain-language 'what to upload' guidance. Educational
    self-help content only — never an outcome promise."""

    label: str
    what_it_is: str
    what_to_upload: list[str]
    why_it_helps: str


class DocGuidanceOut(BaseModel):
    """GET /documents/upload-guidance — the full doc-type -> guidance map."""

    guidance: dict[str, DocTypeGuidanceOut]


class ReconcileResolution(BaseModel):
    """The veteran's chosen value for one flagged field. value=null clears the
    field (e.g. an unsupported percent the record doesn't actually carry)."""

    field_id: str = Field(min_length=1, max_length=64)
    value: int | str | None = None


class ReconcileIn(BaseModel):
    resolutions: list[ReconcileResolution] = Field(default_factory=list, max_length=200)
    # Optional: names of "missing" conditions the veteran dismisses (acknowledged,
    # not added). Anything not listed stays as an open recall note.
    dismiss_missing: list[str] = Field(default_factory=list, max_length=200)
    # Veteran marks the whole document reviewed (clears remaining fields + missing
    # + informational OCR cross-read flags). Explicit action only.
    clear_document: bool = False


class ReconcileOut(BaseModel):
    document_id: uuid.UUID
    review_status: str | None = None
    applied: int = 0
    conditions_mentioned: list[dict] = Field(default_factory=list)


class BulkReconcileIn(BaseModel):
    """Resolve many review-queue documents in one veteran-confirmed action.

    mode:
      - accept_record: use candidate_value ("record shows") for every field
      - accept_extracted: use extracted_value ("keep machine read")
      - accept_agreed: only fields where candidate_value == extracted_value
        (high-agreement; safest bulk path)
    dismiss_all_missing: acknowledge/dismiss all "possibly missed condition" notes
    """

    mode: Literal["accept_record", "accept_extracted", "accept_agreed", "clear_all"] = "accept_agreed"
    dismiss_all_missing: bool = False


class BulkReconcileDocOut(BaseModel):
    document_id: uuid.UUID
    applied: int = 0
    skipped: int = 0
    review_status: str | None = None


class BulkReconcileOut(BaseModel):
    documents_touched: int = 0
    fields_applied: int = 0
    fields_skipped: int = 0
    resolved_documents: int = 0
    results: list[BulkReconcileDocOut] = Field(default_factory=list)
    disclaimer: str = (
        "You confirmed these values. Nothing was silently accepted. "
        "You can re-open a document and correct anything later."
    )


# ── Decision-letter decoder (WAVE4-DECODER-SPEC.md) ──────────────────────────
DecisionOutcome = Literal["granted", "denied", "deferred"]
DenialElement = Literal["current_disability", "in_service_event", "nexus"]
NextStep = Literal["supplemental_claim", "awaiting", "increase_or_effective_date"]


class DecodeDecision(BaseModel):
    """One contention as decoded from the letter (plain-English + next step)."""

    name: str | None = None
    diagnostic_code: str | None = None
    decision: DecisionOutcome | None = None
    rating_percent: int | None = None
    effective_date: date | None = None
    va_classification: str | None = None
    va_classification_code: int | None = None
    plain: str | None = None
    missing_elements: list[DenialElement] = Field(default_factory=list)
    next_step: NextStep | None = None


class DecodeCombinedCheck(BaseModel):
    va_stated: int | None = None
    computed: int | None = None
    matches: bool | None = None
    note: str


class DecodeAppealWindow(BaseModel):
    deadline: date | None = None
    days_remaining: int | None = None
    expired: bool | None = None


class DecodeOption(BaseModel):
    key: str
    title: str
    form: str
    when: str
    detail: str
    source: str


class DecodeOut(BaseModel):
    """POST/GET /documents/{id}/decode — the plain-English decode of a VA decision.

    Educational only: VA's official decision and the combined evaluation printed
    on the letter control; every denial routes to a free VSO."""

    document_id: uuid.UUID
    decoded_at: datetime
    decision_date: date | None = None
    decisions: list[DecodeDecision] = Field(default_factory=list)
    combined_check: DecodeCombinedCheck
    appeal_window: DecodeAppealWindow
    options: list[DecodeOption] = Field(default_factory=list)
    has_denials: bool = False
    has_grants: bool = False
    vso_referral: str
    disclaimer: str
    source_note: str


# ── Readiness score (WAVE5 F1) ───────────────────────────────────────────────
ReadinessBand = Literal["early", "building", "strong", "complete"]


class ReadinessConditionOut(BaseModel):
    condition_id: uuid.UUID
    name: str
    claim_type: str
    score: int
    band: ReadinessBand
    missing: list[str] = Field(default_factory=list)
    satisfied: int
    total: int


class ReadinessOverallOut(BaseModel):
    score: int
    band: ReadinessBand
    label: str
    conditions_scored: int


class ReadinessOut(BaseModel):
    overall: ReadinessOverallOut
    conditions: list[ReadinessConditionOut] = Field(default_factory=list)
    disclaimer: str


# ── Intent to File reminders (WAVE5 F2) ──────────────────────────────────────
ItfType = Literal["compensation", "pension", "survivors"]


class ItfIn(BaseModel):
    type: ItfType = "compensation"
    filed_date: date
    source: Literal["manual", "va"] = "manual"
    notes: str | None = Field(default=None, max_length=2000)


class ItfRecordOut(BaseModel):
    id: uuid.UUID | None = None  # None for a VA-surfaced (unsaved) active ITF
    type: str
    filed_date: date
    source: str
    notes: str | None = None
    deadline: date
    days_remaining: int
    expired: bool


class ItfOut(BaseModel):
    records: list[ItfRecordOut] = Field(default_factory=list)
    active: ItfRecordOut | None = None
    disclaimer: str


# ── Deadline Guardian (veteran-workflows research §cross-cutting #2) ──────────
# The 1-year clock is the spine of a VA claim; GET /deadlines surfaces every clock
# the veteran has (ITF expiry, decision-review window, dependency retroactivity)
# computed from their OWN data (see app/deadlines.py — pure, deterministic).
DeadlineKind = Literal["itf", "appeal", "dependent"]
DeadlineUrgency = Literal["overdue", "soon", "ok"]


class DeadlineOut(BaseModel):
    kind: DeadlineKind
    title: str
    due_date: date | None = None  # None when the source date is unknown
    days_left: int | None = None  # signed; negative once overdue
    urgency: DeadlineUrgency
    what_to_do: str
    related_route: str


class DeadlinesOut(BaseModel):
    deadlines: list[DeadlineOut] = Field(default_factory=list)  # soonest-first
    disclaimer: str


class DeadlineNotifyOut(BaseModel):
    """POST /deadlines/notify-me — best-effort digest send status."""

    sent: bool
    reason: str = ""
    urgent_count: int = 0
    deadline_count: int = 0


# ── Symptom log (WAVE5 F3) ───────────────────────────────────────────────────
class SymptomLogEntryIn(BaseModel):
    condition_id: uuid.UUID | None = None
    entry_date: date
    title: str = Field(min_length=1, max_length=255)
    symptoms: str = Field(min_length=1)
    severity: int | None = Field(default=None, ge=0, le=10)
    functional_impact: str | None = None
    criteria_tags: list[str] | None = None


class SymptomLogEntryUpdate(BaseModel):
    condition_id: uuid.UUID | None = None
    entry_date: date | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    symptoms: str | None = Field(default=None, min_length=1)
    severity: int | None = Field(default=None, ge=0, le=10)
    functional_impact: str | None = None
    criteria_tags: list[str] | None = None


class SymptomLogEntryOut(_ORM):
    id: uuid.UUID
    condition_id: uuid.UUID | None = None
    entry_date: date
    title: str
    symptoms: str
    severity: int | None = None
    functional_impact: str | None = None
    criteria_tags: list[str] | None = None
    source: str
    created_at: datetime
    updated_at: datetime


class SymptomCriteriaTierOut(BaseModel):
    percent: int
    criteria: list[str] = Field(default_factory=list)


class SymptomCriteriaOut(BaseModel):
    diagnostic_code: str | None = None
    condition_name: str | None = None
    tiers: list[SymptomCriteriaTierOut] = Field(default_factory=list)


class SymptomLogExportOut(BaseModel):
    markdown: str
    entries_count: int
    condition_name: str | None = None


class SymptomLogImportOut(BaseModel):
    imported: int
    entries: list[SymptomLogEntryOut] = Field(default_factory=list)
    detail: str | None = None


# ── Buddy statement builder (WAVE5 F4) ───────────────────────────────────────
class BuddyGuidanceOut(BaseModel):
    form: str
    form_title: str
    form_url: str
    prompts: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    disclaimer: str


class BuddyDraftIn(BaseModel):
    witness_name: str = Field(min_length=1, max_length=255)
    witness_relationship: str = Field(min_length=1, max_length=255)
    veteran_name: str | None = Field(default=None, max_length=255)
    condition: str | None = Field(default=None, max_length=255)
    observations: str = Field(min_length=1)
    period: str | None = Field(default=None, max_length=255)


class BuddyDraftOut(BaseModel):
    form: str
    form_title: str
    statement_markdown: str
    guidance: list[str] = Field(default_factory=list)
    disclaimer: str


class BuddySituationBriefIn(BaseModel):
    """Case-aware bullet list the witness can use in their own words.
    Deterministic; never fabricates observations."""

    condition: str = Field(min_length=1, max_length=255)
    veteran_name: str | None = Field(default=None, max_length=255)
    themes: list[str] = Field(default_factory=list, max_length=12)
    period: str | None = Field(default=None, max_length=255)
    known_facts: list[str] = Field(default_factory=list, max_length=20)


class BuddySituationBriefOut(BaseModel):
    condition: str
    form: str
    form_url: str
    hit_list: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    starter_outline: str
    disclaimer: str


# ── C&P exam companion (WAVE5 F5) ────────────────────────────────────────────
class CpConditionOut(BaseModel):
    id: uuid.UUID
    name: str
    diagnostic_code: str | None = None
    claim_type: str


class CpCriteriaTierOut(BaseModel):
    percent: int
    criteria: list[str] = Field(default_factory=list)


class CpCompanionOut(BaseModel):
    condition: CpConditionOut
    dbq: str | None = None
    what_to_expect: list[str] = Field(default_factory=list)
    rating_criteria: list[CpCriteriaTierOut] = Field(default_factory=list)
    how_to_describe: list[str] = Field(default_factory=list)
    dos: list[str] = Field(default_factory=list)
    donts: list[str] = Field(default_factory=list)
    disclaimer: str


# ── 21-526EZ application packet (WAVE6 F1) ───────────────────────────────────
class Form526EvidenceRef(BaseModel):
    kind: str
    title: str


class Form526Contention(BaseModel):
    name: str
    diagnostic_code: str | None = None
    claim_type: str
    current_rating: int | None = None
    onset_date: date | None = None
    in_service_event: str | None = None
    secondary_to_name: str | None = None
    evidence_have: list[Form526EvidenceRef] = Field(default_factory=list)
    evidence_needed: list[Form526EvidenceRef] = Field(default_factory=list)


class Form526ServiceOut(BaseModel):
    periods: list[dict] = Field(default_factory=list)
    combat: bool = False
    exposures: list[str] = Field(default_factory=list)


class Form526ItfOut(BaseModel):
    type: str
    filed_date: date
    deadline: date
    days_remaining: int
    expired: bool


class Form526Completeness(BaseModel):
    conditions: int
    with_evidence: int
    missing_evidence: int


class Form526Out(BaseModel):
    veteran: dict
    prepared_on: date | None = None
    service: Form526ServiceOut
    contentions: list[Form526Contention] = Field(default_factory=list)
    itf: Form526ItfOut | None = None
    completeness: Form526Completeness
    guidance: list[str] = Field(default_factory=list)
    disclaimer: str
    source_note: str


# ── Packet (GET /packet/{condition_id}) ──────────────────────────────────────
class PacketCitationOut(BaseModel):
    document_id: uuid.UUID
    source_title: str
    quote: str
    char_start: int
    char_end: int
    page: int | None = None
    chunk_index: int
    note: str | None = None
    selected: bool = False


class PacketEvidenceIndexOut(BaseModel):
    id: uuid.UUID
    title: str
    kind: EvidenceKind
    status: EvidenceStatus
    source: str | None = None
    notes: str | None = None
    document_id: uuid.UUID | None = None
    rationale: EvidenceRationaleOut | None = None
    citations: list[PacketCitationOut] = Field(default_factory=list)


class PacketOut(BaseModel):
    veteran: dict
    condition: dict
    dc_card: dict | None = None
    evidence_have: list[dict] = Field(default_factory=list)
    evidence_missing: list[dict] = Field(default_factory=list)
    evidence_excerpts: list[dict] = Field(default_factory=list)
    evidence_index: list[PacketEvidenceIndexOut] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    continuity: list[dict] = Field(default_factory=list)
    lay_statement_prompts: list[str] = Field(default_factory=list)
    dbq: str | None = None
    disclaimer: str


# ── Nexus-letter builder (WAVE6 F2) ──────────────────────────────────────────
class NexusGuidanceOut(BaseModel):
    what_it_is: str
    why_it_matters: str
    prompts: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    disclaimer: str


class NexusDraftIn(BaseModel):
    veteran_name: str | None = Field(default=None, max_length=255)
    condition: str = Field(min_length=1, max_length=255)
    diagnostic_code: str | None = Field(default=None, max_length=16)
    claim_type: str | None = Field(default=None, max_length=16)
    in_service_event: str | None = None
    secondary_to: str | None = Field(default=None, max_length=255)
    clinical_summary: str | None = None


class NexusDraftOut(BaseModel):
    title: str
    letter_markdown: str
    guidance: list[str] = Field(default_factory=list)
    disclaimer: str


class NexusProviderBriefIn(BaseModel):
    """Provider-facing brief: what was historically missing + blank opinion scaffold.
    Deterministic; never fills the medical opinion."""

    condition: str = Field(min_length=1, max_length=255)
    claim_type: str | None = Field(default=None, max_length=16)
    secondary_to: str | None = Field(default=None, max_length=255)
    diagnostic_code: str | None = Field(default=None, max_length=16)
    prior_denial_notes: str | None = None
    missing_elements: list[str] = Field(default_factory=list, max_length=12)
    records_to_review: list[str] = Field(default_factory=list, max_length=20)


class NexusProviderBriefOut(BaseModel):
    condition: str
    title: str
    what_was_missing: list[str] = Field(default_factory=list)
    records_to_review: list[str] = Field(default_factory=list)
    opinion_scaffold: str
    blank_rationale_prompt: str
    disclaimer: str


# ── Personal statement / VA Form 21-4138 (WAVE6 F3) ──────────────────────────
class StatementGuidanceOut(BaseModel):
    form: str
    form_title: str
    form_url: str
    prompts: list[str] = Field(default_factory=list)
    tips: list[str] = Field(default_factory=list)
    disclaimer: str


class StatementDraftIn(BaseModel):
    veteran_name: str | None = Field(default=None, max_length=255)
    condition: str | None = Field(default=None, max_length=255)
    topic: str = Field(min_length=1, max_length=255)
    statement: str = Field(min_length=1)
    period: str | None = Field(default=None, max_length=255)


class StatementDraftOut(BaseModel):
    form: str
    form_title: str
    statement_markdown: str
    guidance: list[str] = Field(default_factory=list)
    disclaimer: str


# ── Records requests (SF-180 / VA 20-10206 prefill + provider letters) ──────
class RecordsPrefillOut(BaseModel):
    """A prefilled worksheet the veteran copies onto the official form (or brings
    to a VSO). Prepared FOR THEIR SIGNATURE — the app never submits anything."""

    form: str  # "SF-180" | "VA Form 20-10206"
    form_title: str
    form_url: str
    prefill: dict
    guidance: list[str] = Field(default_factory=list)
    note: str


class RequestLetterIn(BaseModel):
    """POST /records/request-letter — deterministic template, no LLM."""

    provider_name: str = Field(min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    condition_ids: list[uuid.UUID] = Field(min_length=1)


class RequestLetterOut(BaseModel):
    letter: str
    provider_name: str
    conditions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceOut] = Field(default_factory=list)
    note: str


# ── VA Lighthouse connection (/va) ──────────────────────────────────────────
VaApiKey = Literal["verification", "claims"]


class VaConnectionStatusOut(BaseModel):
    """One per-API-family connection (Lighthouse OAuth is per-API)."""

    api: VaApiKey
    label: str
    scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None = None
    last_sync_at: datetime | None = None
    needs_reconnect: bool = False


class VaStatusOut(BaseModel):
    enabled: bool
    connected: bool = False
    scopes: list[str] = Field(default_factory=list)
    last_sync: datetime | None = None
    needs_reconnect: bool = False
    connections: list[VaConnectionStatusOut] = Field(default_factory=list)


class VaDisconnectIn(BaseModel):
    """POST /va/disconnect — api=null disconnects everything."""

    api: VaApiKey | None = None


class VaSyncOut(BaseModel):
    """POST /va/sync — normalized VA data + a diff-style PREVIEW. Nothing here
    has been applied; the veteran picks what to keep via POST /va/apply."""

    synced_at: datetime
    service_periods: list[dict] = Field(default_factory=list)
    ratings: list[dict] = Field(default_factory=list)
    combined: int | None = None
    combined_effective_date: str | None = None
    pt_status: dict = Field(default_factory=dict)
    veteran_status: str | None = None
    suggestions: dict = Field(default_factory=dict)
    disclaimer: str


class VaApplyConditionUpdate(BaseModel):
    """Set an existing claimed condition's current_rating to a VA-synced value."""

    condition_id: uuid.UUID
    percent: int = Field(ge=0, le=100)


class VaApplyConditionCreate(BaseModel):
    """Create a claimed condition from a VA-synced service-connected rating
    (claim_type=increase — it is already rated)."""

    name: str = Field(min_length=1, max_length=255)
    diagnostic_code: str | None = Field(default=None, max_length=8)
    percent: int | None = Field(default=None, ge=0, le=100)


class VaApplyIn(BaseModel):
    """POST /va/apply — the veteran's EXPLICIT pick of synced suggestions.
    Values are validated against the last /va/sync snapshot; nothing outside it
    can be applied through this endpoint."""

    service_periods: bool = False
    combined_rating: bool = False
    condition_updates: list[VaApplyConditionUpdate] = Field(default_factory=list)
    condition_creates: list[VaApplyConditionCreate] = Field(default_factory=list)


class VaApplyOut(BaseModel):
    profile_updated: bool = False
    updated: list[ConditionOut] = Field(default_factory=list)
    created: list[ConditionOut] = Field(default_factory=list)


# ── Canonical reconcile (POST /va/reconcile) ─────────────────────────────────
# Source-agnostic: the same body is produced by the browser extension, a manual
# paste, or the future Lighthouse pull. dry-run (apply=false) writes NOTHING.
VaDisposition = Literal["service_connected", "denied", "pending"]


class VaReconcileCondition(BaseModel):
    """One VA condition to reconcile against the veteran's claimed conditions."""

    name: str = Field(min_length=1, max_length=512)
    percent: int | None = Field(default=None, ge=0, le=100)
    effective_date: str | None = None
    disposition: VaDisposition


class VaReconcileIn(BaseModel):
    """POST /va/reconcile body. `apply=false` is a preview (nothing is written);
    `create_new` only takes effect together with `apply`."""

    combined_rating: int | None = Field(default=None, ge=0, le=100)
    conditions: list[VaReconcileCondition] = Field(default_factory=list)
    create_new: bool = False
    apply: bool = False


class VaReconcileMatch(BaseModel):
    va_name: str
    condition_id: str
    condition_name: str
    set_current_rating: int | None = None  # null = leave rating unchanged
    set_va_status: VaDisposition
    changed: bool


class VaReconcileUnmatched(BaseModel):
    name: str
    disposition: str
    percent: int | None = None
    created: bool = False


class VaReconcileOut(BaseModel):
    combined_rating: int | None = None
    matched: list[VaReconcileMatch] = Field(default_factory=list)
    unmatched: list[VaReconcileUnmatched] = Field(default_factory=list)
    applied: bool = False


class VaClaimOut(BaseModel):
    """One VA benefits claim, normalized from Benefits Claims v1."""

    id: str | None = None
    status: str | None = None
    phase: int | None = None  # 1–5 step derived from status
    claim_type: str | None = None
    date_filed: str | None = None
    min_est_date: str | None = None
    max_est_date: str | None = None
    open: bool | None = None
    documents_needed: bool | None = None
    development_letter_sent: bool | None = None
    decision_letter_sent: bool | None = None
    requested_decision: bool | None = None
    events: list[dict] = Field(default_factory=list)


class VaClaimsOut(BaseModel):
    claims: list[VaClaimOut] = Field(default_factory=list)


class VaItfOut(BaseModel):
    """Intent to File (VA Form 0966) state."""

    active: bool = False
    id: str | None = None
    type: str | None = None
    status: str | None = None
    creation_date: str | None = None
    expiration_date: str | None = None


class VaItfFileIn(BaseModel):
    """POST /va/itf — SUBMITS an Intent to File to VA on the veteran's own
    consented token. confirm MUST be true: the UI shows exactly what will be
    filed and the veteran presses the button. Same act as filing it on VA.gov."""

    type: Literal["compensation"] = "compensation"
    confirm: bool = False


class LegalOut(BaseModel):
    """GET /api/legal — plain-language terms + privacy (markdown)."""

    terms: str
    privacy: str


# ── Appeals draft assist (Wave 7 — Supplemental Claim / HLR / Board) ─────────
AppealLane = Literal["supplemental_claim", "higher_level_review", "board_appeal"]


class AppealEvidenceRef(BaseModel):
    kind: str
    title: str


class AppealCandidate(BaseModel):
    """A denial (from a decoded letter) or a claimed condition the veteran could
    supplement/appeal. `new_evidence` = their have-status evidence that matches, the
    "new and relevant" material a Supplemental Claim needs."""

    source: Literal["decoded_letter", "condition"]
    name: str
    diagnostic_code: str | None = None
    decision: str | None = None
    missing_elements: list[str] = Field(default_factory=list)
    document_id: str | None = None
    condition_id: str | None = None
    decision_date: str | None = None
    appeal_window: dict | None = None
    new_evidence: list[AppealEvidenceRef] = Field(default_factory=list)


class AppealCandidatesOut(BaseModel):
    candidates: list[AppealCandidate]
    lanes: list[dict]
    vso_referral: str
    disclaimer: str


class AppealDraftContentionIn(BaseModel):
    name: str
    diagnostic_code: str | None = None
    missing_elements: list[str] = Field(default_factory=list)
    new_evidence_titles: list[str] = Field(default_factory=list)
    veteran_statement: str | None = None


class AppealDraftIn(BaseModel):
    lane: AppealLane = "supplemental_claim"
    decision_date: str | None = None
    contentions: list[AppealDraftContentionIn] = Field(..., min_length=1)


class AppealDraftContentionOut(BaseModel):
    name: str
    diagnostic_code: str | None = None
    missing_element_plain: list[str] = Field(default_factory=list)
    new_and_relevant_evidence: list[str] = Field(default_factory=list)
    veteran_statement: str | None = None
    what_this_addresses: str


class AppealDraftOut(BaseModel):
    lane_key: str
    lane_title: str
    lane_form: str
    prepared_on: str | None = None
    heading: str
    intro: str
    contentions: list[AppealDraftContentionOut]
    deadline: dict | None = None
    lane_guidance: list[dict]
    veteran_attestation: str
    signature_block: str
    vso_referral: str
    disclaimer: str
    source_note: str


# ── Game Plan (Wave 8 — strategy engine) ─────────────────────────────────────
GamePlanImpact = Literal["high", "medium", "low"]


class GamePlanSnapshot(BaseModel):
    current_combined: int | None = None
    conditions_total: int
    ready_count: int
    needs_evidence_count: int
    denied_count: int
    active_itf: dict | None = None


class GamePlanPathway(BaseModel):
    """One strategic option to CONSIDER. estimated_combined is §4.25 math on the
    veteran's OWN target ratings — educational, never a prediction of VA's decision
    (basis label always states this)."""

    key: str
    title: str
    summary: str
    steps: list[str] = Field(default_factory=list)
    included_conditions: list[str] = Field(default_factory=list)
    estimated_combined: int | None = None
    estimated_combined_basis: str
    tradeoff: str
    recommended: bool = False


class GamePlanAction(BaseModel):
    title: str
    why: str
    category: str
    condition_name: str | None = None
    impact: GamePlanImpact = "medium"
    link: str | None = None


class GamePlanBriefing(BaseModel):
    """A plain-language, personalized orientation of the veteran's situation.
    Educational only — organizes what they entered; never a diagnosis or a
    prediction. `generated_by` is "local" (the on-fleet LLM wrote it) or
    "summary" (the deterministic fallback) so the UI can be honest about it."""

    headline: str
    paragraphs: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    watch_outs: list[str] = Field(default_factory=list)
    generated_by: Literal["local", "summary"] = "summary"


class GamePlanConditionLine(BaseModel):
    """One claimed condition rendered for the Game Plan's at-a-glance list."""

    id: str | None = None
    name: str
    claim_type: str
    status: str
    va_status: str = "unknown"  # VA disposition — UI badges denied / service-connected
    band: str
    band_label: str
    ready: bool
    missing: list[str] = Field(default_factory=list)  # plain-English gaps
    current_rating: int | None = None
    target_rating: int | None = None
    link: str | None = None


class GamePlanMoney(BaseModel):
    """The 'what this means in dollars' anchor — VA's published monthly amount
    for the veteran's CURRENT combined rating (single-veteran baseline unless
    dependents are modeled). Educational; VA's award letter is authoritative."""

    current_combined: int | None = None
    current_monthly: float | None = None
    basis: str
    rate_year: int | None = None


class GamePlanStep(BaseModel):
    """One stop on the 'what to expect' claim-process roadmap."""

    key: str
    title: str
    body: str
    state: Literal["done", "now", "upcoming"] = "upcoming"


class GamePlanFocus(BaseModel):
    """The single most important next thing — the hero call-to-action."""

    title: str
    why: str
    link: str | None = None


class GamePlanCaution(BaseModel):
    """A rating-strategy trade-off to weigh BEFORE filing — "poking the bear."
    Covers pyramiding (§4.14 / §4.130), reduction risk (§3.344 / §3.951), CFS vs
    fibromyalgia distinct-manifestation trade-offs, and TDIU employment / side-gig
    risk. Educational and reg-grounded; never a bar on filing or a prediction."""

    key: str
    kind: Literal["pyramiding", "reduction", "filing_tradeoff", "tdiu_employment"]
    title: str
    body: str
    reg: str
    conditions: list[str] = Field(default_factory=list)
    severity: Literal["high", "medium", "low"] = "medium"


class GamePlanTdiu(BaseModel):
    """TDIU screen (§4.16) — 100% pay without a 100% rating when service-connected
    conditions prevent substantially gainful employment. Educational; whether the
    veteran actually qualifies is VA's determination, built on the work record."""

    eligible_schedular: bool
    why: str
    what_it_is: str
    evidence: list[str] = Field(default_factory=list)
    note: str
    reg: str
    form: str


class GamePlanOpportunity(BaseModel):
    """A 'you may be leaving compensation on the table' finding — a newly-establishable
    §3.310 SECONDARY theory, a RECLAIM (denied condition + new theory or new evidence
    path), or an Esteban-positive separate rating. Educational; each still needs its
    own nexus/evidence, and none asserts the link or predicts a rating."""

    key: str
    kind: Literal["secondary", "underrating", "reclaim"]
    title: str
    body: str
    reg: str
    primary: list[str] = Field(default_factory=list)
    secondary: str
    needs_nexus: bool = False
    severity: Literal["high", "medium", "low"] = "medium"
    # Reclaim / supplemental path (optional — present on kind=reclaim and denied
    # secondaries that surface as reclaim cards).
    pathway: str | None = None
    form: str | None = None
    attach_checklist: list[str] = Field(default_factory=list)


class DecisionStatusUpdateOut(BaseModel):
    """One proposed or applied va_status write from formal decision letters."""

    condition_id: str | None = None
    name: str
    from_status: str
    to_status: str
    decision_name: str = ""
    set_current_rating: int | None = None


class DecisionStatusApplyOut(BaseModel):
    """Preview or apply of decision-letter statuses onto claimed conditions.

    Educational organizing only — sets what the letters already say. dry_run
    previews without writing; apply=true persists unknown → SC/denied only.
    """

    dry_run: bool = True
    updated: int = 0
    updates: list[DecisionStatusUpdateOut] = Field(default_factory=list)
    note: str = (
        "Statuses come from formal VA decision / claim letters only — not C&P exams. "
        "Only conditions still marked unknown are updated; explicit statuses are kept."
    )


class CoachMoveOut(BaseModel):
    id: str = ""
    tier: str = "then"  # first | then | parked
    title: str
    why: str = ""
    link: str | None = None
    category: str | None = None
    condition_name: str | None = None
    impact: str = "medium"
    kind: str = "action"


class OutstandingItemOut(BaseModel):
    id: str
    kind: str
    severity: str = "medium"
    title: str
    why: str = ""
    link: str | None = None
    checklist: list[str] = Field(default_factory=list)
    status: str = "not_started"  # not_started | informational
    tier: str = "primary"  # primary | more


class SectionGuideOut(BaseModel):
    id: str
    title: str
    what: str = ""
    why: str = ""
    do: str = ""
    outstanding_ids: list[str] = Field(default_factory=list)
    status: str = "informational"  # action | clear | informational


class DuplicateClusterOut(BaseModel):
    key: str
    family: str = ""
    count: int = 0
    keep_name: str = ""
    keep_id: str | None = None
    keep_va_status: str = "unknown"
    park_names: list[str] = Field(default_factory=list)
    park_ids: list[str] = Field(default_factory=list)
    title: str = ""
    body: str = ""
    severity: str = "medium"
    link: str = "/conditions"


class InterviewQuestionOut(BaseModel):
    id: str
    topic: str = ""
    question: str
    why: str = ""
    maps_to: str = ""


class InterviewSeedOut(BaseModel):
    mode: str = "post_analysis"
    opening: str = ""
    questions: list[InterviewQuestionOut] = Field(default_factory=list)
    closing_hint: str = ""
    starter_user_message: str = ""


class CaseBriefOut(BaseModel):
    title: str = "Case brief"
    disclaimer: str = ""
    profile_summary: str = ""
    snapshot: dict = Field(default_factory=dict)
    service_connected: list[dict] = Field(default_factory=list)
    denied: list[dict] = Field(default_factory=list)
    do_this_first: CoachMoveOut | dict | None = None
    then: list[CoachMoveOut | dict] = Field(default_factory=list)
    outstanding_top: list[OutstandingItemOut | dict] = Field(default_factory=list)
    cautions: list[dict] = Field(default_factory=list)
    tdiu: dict | None = None
    duplicates: list[DuplicateClusterOut | dict] = Field(default_factory=list)


class GamePlanCoachOut(BaseModel):
    """Post-analysis coach: ordered moves, outstanding, section guides, interview."""

    do_this_first: CoachMoveOut | None = None
    do_this_first_reason: str | None = None
    then: list[CoachMoveOut] = Field(default_factory=list)
    parked: list[CoachMoveOut] = Field(default_factory=list)
    outstanding: list[OutstandingItemOut] = Field(default_factory=list)
    outstanding_primary: list[OutstandingItemOut] = Field(default_factory=list)
    outstanding_more: list[OutstandingItemOut] = Field(default_factory=list)
    outstanding_count: int = 0
    section_guides: list[SectionGuideOut] = Field(default_factory=list)
    duplicates: list[DuplicateClusterOut] = Field(default_factory=list)
    interview: InterviewSeedOut | None = None
    case_brief: CaseBriefOut | None = None
    post_analysis_cta: dict | None = None


class GamePlanOut(BaseModel):
    generated_at: str
    snapshot: GamePlanSnapshot
    pathways: list[GamePlanPathway]
    priority_actions: list[GamePlanAction]
    has_conditions: bool
    disclaimer: str
    vso_referral: str
    source_note: str
    # ── Wave 9: deeper, handholding briefing (all additive/optional so the
    # print view and any older client keep working) ──────────────────────────
    briefing: GamePlanBriefing | None = None
    condition_lines: list[GamePlanConditionLine] = Field(default_factory=list)
    money: GamePlanMoney | None = None
    process_roadmap: list[GamePlanStep] = Field(default_factory=list)
    focus: GamePlanFocus | None = None
    # ── Rating-strategy intelligence (pyramiding / reduction cautions + TDIU
    # screen). Additive/optional so the print view and any older client keep
    # working. ────────────────────────────────────────────────────────────────
    cautions: list[GamePlanCaution] = Field(default_factory=list)
    tdiu: GamePlanTdiu | None = None
    opportunities: list[GamePlanOpportunity] = Field(default_factory=list)
    # ── Coach layer (1.9.31+): do-this-first, outstanding, section guides ───
    coach: GamePlanCoachOut | None = None


class DeepDiveCandidateOut(BaseModel):
    """A deterministic candidate considered by the exhaustive rating sweep."""

    diagnostic_code: str
    title: str
    body_system: str | None = None
    origin: str
    seed_signal: str
    source_ref: str | None = None
    primary_dc: str | None = None


class DeepDiveFindingOut(BaseModel):
    """Reviewed Finding plus deterministic conflict annotations."""

    specialist: str
    kind: str
    key: str
    title: str
    body: str
    severity: Literal["high", "medium", "low"] = "medium"
    regs: list[str] = Field(default_factory=list)
    card_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)
    suggested_form: str | None = None
    confidence: float = 1.0
    # Phase 2b: layer + VA-register confidence + structured citations. A "floor"
    # finding is the deterministic seed (confidence 1.0, no register level); a
    # "theory" is an originated opinion above it (0<confidence<1, a level, cites).
    layer: Literal["floor", "theory"] = "floor"
    confidence_level: Literal[
        "more_likely_than_not",
        "at_least_as_likely",
        "less_likely_than_not",
        "insufficient_evidence",
    ] | None = None
    citations: list[dict] = Field(default_factory=list)
    reviewed: bool = False
    review_note: str | None = None
    seed: dict = Field(default_factory=dict)
    det_body: str = ""
    enriched: bool = False
    diagnostic_code: str | None = None
    origin: str | None = None
    rating_percent: int | None = None
    superseded_by: str | None = None
    excluded_by: str | None = None
    conflict_reason: str | None = None
    conflict_cfr: str | None = None
    active: bool = True


class DeepDiveNotificationOut(BaseModel):
    """Local-only signal that a proactive sweep found active keys not seen before."""

    has_new_findings: bool = False
    new_finding_keys: list[str] = Field(default_factory=list)
    trigger: str | None = None
    generated_at: str | None = None


class DeepDiveResultOut(BaseModel):
    """Cached Battle-Plan deep dive; combined math is educational, not predictive."""

    generated_at: str
    candidates: list[DeepDiveCandidateOut] = Field(default_factory=list)
    candidates_considered: int = 0
    findings: list[DeepDiveFindingOut] = Field(default_factory=list)
    projected_combined: int = 0
    current_combined: int | None = None
    delta: int = 0
    notes: list[str] = Field(default_factory=list)
    notification: DeepDiveNotificationOut | None = None


# ── TDIU workflow (§4.16 — Individual Unemployability) ────────────────────────
class TdiuForm(BaseModel):
    form: str
    title: str
    url: str
    who: str  # who fills it — "you" / "your employer" / "your provider"


class TdiuScreenOut(BaseModel):
    """The TDIU workspace: whether the veteran is at/near the §4.16 schedular door,
    what TDIU is, the evidence it turns on, and the forms. Educational — VA decides
    unemployability; this never says the veteran 'qualifies'."""

    at_or_near_threshold: bool
    eligible_schedular: bool
    why: str
    what_it_is: str
    how_it_works: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    forms: list[TdiuForm] = Field(default_factory=list)
    post_denial_note: str
    guidance_prompts: list[str] = Field(default_factory=list)
    disclaimer: str
    vso_note: str


class TdiuJob(BaseModel):
    employer: str = Field(default="", max_length=200)
    job_title: str = Field(default="", max_length=200)
    dates: str = Field(default="", max_length=120)
    hours_per_week: str = Field(default="", max_length=60)
    reason_ended: str = Field(default="", max_length=2000)  # verbatim


class TdiuWorksheetIn(BaseModel):
    """Work-history inputs for the 21-8940 worksheet. Narrative fields are the
    veteran's own words and are reproduced VERBATIM."""

    veteran_name: str = Field(default="", max_length=200)
    last_full_time_date: str = Field(default="", max_length=120)
    highest_earnings: str = Field(default="", max_length=160)
    education: str = Field(default="", max_length=600)
    training: str = Field(default="", max_length=600)
    jobs: list[TdiuJob] = Field(default_factory=list, max_length=20)
    how_conditions_limit_work: str = Field(default="", max_length=8000)  # verbatim
    doctor_restrictions: str = Field(default="", max_length=4000)        # verbatim


class TdiuWorksheetOut(BaseModel):
    form: str
    form_title: str
    worksheet_markdown: str
    guidance: list[str] = Field(default_factory=list)
    disclaimer: str


# ── Concurrent pay: CRDP (§1414) / CRSC (§1413a) ──────────────────────────────
class ConcurrentPayProgram(BaseModel):
    """One concurrent-receipt program's plain-language read. Educational — DFAS
    and the branch decide eligibility and amount; `likely_fits` is a read of the
    veteran's own facts, never a determination."""

    program: str            # "CRDP" / "CRSC"
    full_name: str
    statute: str            # citation, e.g. "10 U.S.C. §1414"
    who_its_for: str
    how_it_works: str
    requires_application: bool
    form: str | None = None  # CRSC only — DD Form 2860
    how_to_get_it: str
    taxable: bool
    tax_note: str
    likely_fits: bool
    status: str             # likely_eligible | below_rating_threshold | not_a_retiree | needs_combat_related | unknown
    headline: str


class ConcurrentPayEstimate(BaseModel):
    """A rough, clearly-bounded CRDP restoration estimate. Always an estimate,
    never a promise — DFAS decides the amount."""

    monthly_ceiling: float
    is_estimate: bool = True
    basis: str


class ConcurrentPayOut(BaseModel):
    """The concurrent-pay workspace: where the veteran stands on CRDP and CRSC,
    the election point when both fit, a rough restoration estimate, and what to do.
    Educational — this never says the veteran 'qualifies' or 'will receive'."""

    combined_rating: int
    receives_retired_pay: bool | None
    retired_pay_known: bool
    combat_related: bool
    crdp: ConcurrentPayProgram
    crsc: ConcurrentPayProgram
    must_elect: bool
    election_note: str
    estimate: ConcurrentPayEstimate | None = None
    what_to_do: list[str] = Field(default_factory=list)
    disclaimer: str
    vso_note: str


# ── Dependency / "respond to a VA action" (VA Form 21-686c) ───────────────────
DependencyAction = Literal["add", "respond_to_removal"]
DependentRelationship = Literal["spouse", "child", "stepchild", "parent"]


class DependencyForm(BaseModel):
    form: str
    title: str
    url: str
    who: str


class DependencyGuidanceOut(BaseModel):
    """What a dependency action is, the two response paths (add/re-add a dependent,
    or answer a proposed/completed removal), the forms, the due-process timeline,
    and the evidence. Educational — adding/removing a dependent changes your pay and
    is a filing action; Rating Raider prepares the paperwork, you (or a VSO) file."""

    what_it_is: str
    add_path: list[str]
    removal_path: list[str]
    timeline_note: str
    evidence: list[str]
    forms: list[DependencyForm]
    guidance_prompts: list[str]
    disclaimer: str
    vso_note: str


class DependentEntry(BaseModel):
    full_name: str = Field(default="", max_length=200)
    relationship: DependentRelationship = "spouse"
    event: str = Field(default="", max_length=120)       # marriage / birth / etc.
    event_date: str = Field(default="", max_length=120)
    event_place: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=2000)      # verbatim


class DependencyWorksheetIn(BaseModel):
    """Inputs for the 21-686c worksheet + cover statement. Narrative fields are the
    veteran's own words, reproduced VERBATIM. SSNs / VA file numbers are never
    collected here — those go on the signed form only."""

    veteran_name: str = Field(default="", max_length=200)
    action: DependencyAction = "add"
    dependents: list[DependentEntry] = Field(default_factory=list, max_length=12)
    explanation: str = Field(default="", max_length=8000)        # verbatim
    prior_removal_note: str = Field(default="", max_length=4000)  # verbatim


class DependencyWorksheetOut(BaseModel):
    form: str
    form_title: str
    worksheet_markdown: str
    guidance: list[str] = Field(default_factory=list)
    disclaimer: str


# ── Workspaces / tenancy (Wave 11) ───────────────────────────────────────────
class WorkspaceOut(BaseModel):
    id: str
    name: str
    kind: str          # personal | org
    plan_tier: str
    status: str
    role: str          # owner | admin | staff | member


class WorkspacesOut(BaseModel):
    workspaces: list[WorkspaceOut]
    current_workspace_id: str


# ── Organizations / teams (Wave 12) ──────────────────────────────────────────
OrgRole = Literal["owner", "admin", "staff", "member"]


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class OrgUpdateIn(BaseModel):
    name: str = Field(min_length=2, max_length=255)


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    kind: str
    plan_tier: str
    status: str
    role: str                 # the CALLER's role in this org
    member_count: int = 0
    seat_limit: int = 1       # -1 = unlimited


class OrgMemberOut(BaseModel):
    user_id: str
    email: EmailStr
    full_name: str = ""
    role: OrgRole
    created_at: datetime


class MemberRoleIn(BaseModel):
    role: OrgRole


class InviteCreateIn(BaseModel):
    email: EmailStr
    role: OrgRole = "member"


class InviteOut(BaseModel):
    id: str
    org_id: str
    email: EmailStr
    role: OrgRole
    status: str
    invited_by_email: str | None = None
    expires_at: datetime
    created_at: datetime


class InvitePreviewOut(BaseModel):
    """What the invitee sees on the accept page (no secrets, no full roster)."""
    org_name: str
    role: OrgRole
    email: EmailStr
    email_matches: bool       # does the logged-in user's email match the invite?
    status: str               # pending | expired | accepted | revoked
    invited_by_email: str | None = None


# ── Org caseload / cases (Wave 13) ───────────────────────────────────────────
CaseStatus = Literal["intake", "active", "filed", "closed"]
ConsentMethod = Literal["in_person", "written", "verbal", "portal"]


class CaseCreateIn(BaseModel):
    veteran_name: str = Field(min_length=1, max_length=255)
    veteran_email: EmailStr | None = None
    veteran_phone: str | None = Field(default=None, max_length=32)
    summary: str | None = Field(default=None, max_length=4000)


class CaseUpdateIn(BaseModel):
    veteran_name: str | None = Field(default=None, min_length=1, max_length=255)
    veteran_email: EmailStr | None = None
    veteran_phone: str | None = Field(default=None, max_length=32)
    status: CaseStatus | None = None
    summary: str | None = Field(default=None, max_length=4000)


class CaseAssigneeOut(BaseModel):
    user_id: str
    email: str = ""
    full_name: str = ""


class CaseOut(BaseModel):
    id: str
    veteran_name: str
    veteran_email: str | None = None
    veteran_phone: str | None = None
    status: CaseStatus
    consent_status: str            # none | granted | revoked
    summary: str | None = None
    assignees: list[CaseAssigneeOut] = []
    note_count: int = 0
    created_at: datetime
    updated_at: datetime


class AssignIn(BaseModel):
    user_id: str


class ConsentCaptureIn(BaseModel):
    method: ConsentMethod = "in_person"
    granted_by_name: str = Field(min_length=1, max_length=255)
    # The veteran's authorization in their OWN words (stored verbatim).
    statement: str | None = Field(default=None, max_length=4000)
    scope: str = Field(default="assist", max_length=32)
    # The caseworker must affirm the veteran was told this is app-assist, NOT VA
    # accredited representation (which needs VA Form 21-22). Guards the legal lane.
    acknowledged_not_poa: bool = False


class ConsentOut(BaseModel):
    id: str
    case_id: str
    method: str
    scope: str
    statement: str | None = None
    granted_by_name: str
    captured_by: str | None = None
    status: str                    # granted | revoked
    granted_at: datetime
    revoked_at: datetime | None = None


class CaseNoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


class CaseNoteOut(BaseModel):
    id: str
    case_id: str
    author_id: str | None = None
    author_email: str = ""
    body: str
    created_at: datetime


class AuditEntryOut(BaseModel):
    id: str
    action: str
    entity: str | None = None
    entity_id: str | None = None
    actor_user_id: str | None = None
    actor_email: str = ""
    meta: dict | None = None
    created_at: datetime


# ── Billing (Wave 14 — suite-aligned; Lago drives subscriptions) ─────────────
class PlanOut(BaseModel):
    tier: str
    name: str
    price_monthly: int | None            # None = "contact us" (enterprise)
    audience: str
    highlights: list[str]
    seat_limit: int                      # -1 = unlimited
    current: bool = False                # is this the active workspace's tier?


class PlansOut(BaseModel):
    plans: list[PlanOut]
    self_serve: bool                     # is in-app checkout live yet?
    portal_url: str | None = None        # suite billing portal ("Manage billing")


class BillingStatusOut(BaseModel):
    workspace_id: str
    kind: str                            # personal | org
    tier: str
    plan_name: str
    seat_limit: int
    seats_used: int
    features: list[str]
    self_serve: bool
    portal_url: str | None = None
    manageable: bool                     # may the caller manage billing (owner/admin)?


class TenantTierIn(BaseModel):
    """The suite billing/entitlement service pushes an org's tier here (Wave 14)."""
    workspace_id: str
    tier: Literal["free", "pro", "team", "enterprise"]
    # Optional idempotency/audit context from the caller (e.g. a Lago subscription id).
    reason: str | None = Field(default=None, max_length=255)


# ── Credits / grants / sponsorship ───────────────────────────────────────────
CreditProduct = Literal["full_claim", "topup", "sponsor"]
GrantApplicationStatus = Literal["pending", "approved", "denied"]
GrantEmploymentStatus = Literal["employed", "underemployed", "unemployed", "retired", "student", "other"]


class CheckoutSessionIn(BaseModel):
    product: CreditProduct
    beneficiary_email: EmailStr | None = None


class CheckoutSessionOut(BaseModel):
    session_id: str
    url: str
    product: CreditProduct
    amount_cents: int
    credits: int
    message: str


class CreditTransactionOut(_ORM):
    id: uuid.UUID
    delta: int
    balance_after: int
    operation: str
    reference_type: str | None = None
    reference_id: str | None = None
    note: str | None = None
    created_at: datetime


class CreditsOut(BaseModel):
    balance: int
    recent: list[CreditTransactionOut] = Field(default_factory=list)


class GrantApplicationIn(BaseModel):
    monthly_income_band: str | None = Field(default=None, max_length=64)
    household_size: int | None = Field(default=None, ge=1, le=12)
    employment_status: GrantEmploymentStatus | None = None
    hardship_summary: str = Field(min_length=20, max_length=2000)
    contact_email: EmailStr | None = None


class GrantApplicationOut(_ORM):
    id: uuid.UUID
    monthly_income_band: str | None = None
    household_size: int | None = None
    employment_status: GrantEmploymentStatus | None = None
    hardship_summary: str
    contact_email: EmailStr | None = None
    status: GrantApplicationStatus
    reviewer_user_id: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
    funded_sponsorship_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class GrantApplicationReviewIn(BaseModel):
    status: GrantApplicationStatus
    review_note: str | None = Field(default=None, max_length=2000)


class GrantPoolEntryOut(_ORM):
    id: uuid.UUID
    claims_delta: int
    kind: str
    sponsorship_id: uuid.UUID | None = None
    grant_application_id: uuid.UUID | None = None
    reserved_email: EmailStr | None = None
    reserved_user_id: uuid.UUID | None = None
    note: str | None = None
    created_at: datetime


class GrantPoolOut(BaseModel):
    available_claims: int
    earned_claims: int
    spent_claims: int
    recent: list[GrantPoolEntryOut] = Field(default_factory=list)


class SponsorshipOut(_ORM):
    id: uuid.UUID
    checkout_session_id: str
    payment_intent_id: str | None = None
    beneficiary_email: EmailStr | None = None
    beneficiary_user_id: uuid.UUID | None = None
    amount_cents: int
    status: str
    earmark_status: str
    pool_ledger_id: uuid.UUID | None = None
    consumed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AdminGrantsOut(BaseModel):
    pool: GrantPoolOut
    applications: list[GrantApplicationOut]
    sponsorships: list[SponsorshipOut] = Field(default_factory=list)


# ── Entitlements / tier (Wave 12) ────────────────────────────────────────────
class EntitlementsOut(BaseModel):
    workspace_id: str
    kind: str                 # personal | org
    tier: str                 # free | pro | team | enterprise
    role: str                 # caller's role in the active workspace
    features: list[str]       # enabled ORG feature keys
    seat_limit: int           # -1 = unlimited


# ── Military records corrections (Wave 10 — DRB / BCMR / PDBR) ────────────────
CorrectionGoal = Literal[
    "discharge_upgrade", "narrative_reason", "re_code", "records_error", "medical_rating"
]
LiberalTrigger = Literal["ptsd", "tbi", "mental_health", "mst"]


class CorrectionSituationIn(BaseModel):
    """What the veteran wants corrected + the facts that pick the right board.
    Everything optional so the router can guide a partially-filled situation."""

    goals: list[CorrectionGoal] = Field(default_factory=list)
    years_since_separation: int | None = None
    general_court_martial: bool = False
    drb_denied: bool = False
    related_to: list[LiberalTrigger] = Field(default_factory=list)
    medically_separated_2001_2009: bool = False
    dod_rating_20_or_less: bool = False
    discharge_char: str | None = None


class CorrectionLiberal(BaseModel):
    applies: bool
    note: str


class CorrectionAlsoConsider(BaseModel):
    board: str
    form: str
    when: str


class CorrectionRouteOut(BaseModel):
    routed: bool  # False when no goal was selected yet
    board: str | None = None
    board_full: str | None = None
    form: str | None = None
    form_title: str | None = None
    why: str
    deadline_note: str | None = None
    liberal_consideration: CorrectionLiberal
    character_of_discharge_note: str | None = None
    also_consider: list[CorrectionAlsoConsider] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source: str | None = None
    vso_referral: str
    legal_aid_referral: str
    disclaimer: str


class CorrectionRequestedItem(BaseModel):
    field: str
    current: str | None = None
    requested: str | None = None


class CorrectionDraftIn(BaseModel):
    situation: CorrectionSituationIn
    applicant_name: str | None = None
    corrections_requested: list[CorrectionRequestedItem] = Field(default_factory=list)
    veteran_statement: str | None = None


class CorrectionEvidenceItem(BaseModel):
    item: str
    why: str


class CorrectionPacketOut(BaseModel):
    route: CorrectionRouteOut
    prepared_on: str | None = None
    heading: str
    applicant_name: str | None = None
    corrections_requested: list[CorrectionRequestedItem]
    statement_of_error_or_injustice: str
    veteran_statement: str | None = None
    evidence_checklist: list[CorrectionEvidenceItem]
    instructions: list[str]
    attestation: str
    signature_block: str
    vso_referral: str
    legal_aid_referral: str
    disclaimer: str
    source_note: str


# ── Officer rank / promotion-correction analyzer ─────────────────────────────
RankSelection = Literal["1lt", "capt"]
RankStrength = Literal["strong", "moderate", "weak", "needs_dates"]


class RankAnalysisIn(BaseModel):
    """Officer service facts the analyzer reasons about. All optional so a
    partially-filled form still yields useful guidance."""

    commission_date: str | None = None
    date_of_rank_2lt: str | None = None
    promoted_to_1lt: bool = False
    date_of_rank_1lt: str | None = None
    promoted_to_capt: bool = False
    separation_date: str | None = None
    medically_retired: bool = False
    selected_for_promotion: RankSelection | None = None
    completed_captains_career_course: bool = False
    branch: str | None = None


class RankFinding(BaseModel):
    grade_from: str
    grade_to: str
    strength: RankStrength
    headline: str
    reasoning: str
    what_to_request: str


class RankAnalysisOut(BaseModel):
    findings: list[RankFinding]
    overall: str
    retired_grade_note: str
    board: str
    form: str
    form_title: str
    human_checklist: list[str]
    non_army_note: str | None = None
    vso_referral: str
    legal_aid_referral: str
    disclaimer: str


class RankGuidanceOut(BaseModel):
    what_it_is: str
    how_it_works: list[str]
    prompts: list[str]
    thresholds: list[str]
    disclaimer: str


# ── Account portability + erasure (Wave 9) ───────────────────────────────────
class AccountDeleteIn(BaseModel):
    """DELETE /account — the veteran must type their own email to confirm the
    irreversible deletion of their account and all data."""

    confirm_email: str


# ── Admin service settings (overrides) ──────────────────────────────────────
class ServiceOverridesIn(BaseModel):
    """Payload to update runtime overrides. Every field is optional; only
    supplied fields are written. ``None`` explicitly clears an override (falls
    back to env default), while an omitted field is left untouched."""

    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    reasoning_model: str | None = None
    briefing_model: str | None = None
    extraction_model: str | None = None
    classification_model: str | None = None
    embeddings_base_url: str | None = None
    embeddings_api_key: str | None = None
    embeddings_model: str | None = None
    reranker_base_url: str | None = None
    reranker_model: str | None = None
    ocr_base_url: str | None = None
    ocr_model: str | None = None
    ocr_engine: str | None = None
    center_deep_url_default: str | None = None
    center_deep_url_unicorncommander: str | None = None
    privacy_mode: bool | None = None


class ServiceSettingsOut(BaseModel):
    """Current effective settings (env + overrides) returned to the admin UI.
    Secrets are redacted (``None``) so they never cross the wire; the ``*_set``
    booleans tell the UI whether a key is configured without revealing it."""

    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    reasoning_model: str | None = None
    briefing_model: str | None = None
    extraction_model: str | None = None
    classification_model: str | None = None
    embeddings_base_url: str | None = None
    embeddings_api_key: str | None = None
    embeddings_model: str | None = None
    reranker_base_url: str | None = None
    reranker_model: str | None = None
    ocr_base_url: str | None = None
    ocr_model: str | None = None
    ocr_engine: str | None = None
    center_deep_url_default: str | None = None
    center_deep_url_unicorncommander: str | None = None
    privacy_mode: bool | None = None
    # Write-only secrets are redacted above; these say whether one is configured.
    llm_api_key_set: bool = False
    embeddings_api_key_set: bool = False


class WorkspacePrivacyIn(BaseModel):
    """Set the CURRENT workspace's privacy choice. ``True`` = force local-only
    (privacy-first); ``False`` = allow quality-first (frontier) routing; ``None`` =
    inherit the global/env default."""

    privacy_mode: bool | None = None


class WorkspacePrivacyOut(BaseModel):
    """The CURRENT workspace's privacy choice — the raw per-workspace column
    (``None`` = inherit) plus the ``effective`` value actually applied after
    resolving the global/env default."""

    workspace_id: str
    privacy_mode: bool | None = None
    effective: bool


class PiiCloudConsentIn(BaseModel):
    """Grant (``True``) or revoke (``False``) this workspace's consent to send the
    veteran's OWN record text to a frontier/cloud model when privacy mode is off."""

    consent: bool


class PiiCloudConsentOut(BaseModel):
    """The CURRENT workspace's PII→cloud consent state. ``consented`` gates the
    C-file quality mode's release of record text to a non-local model."""

    workspace_id: str
    consented: bool
    consent_at: datetime | None = None
    consent_by: str | None = None


class TestConnectionIn(BaseModel):
    """Candidate overrides to test before saving. The same schema as
    ServiceOverridesIn but every key is present at call time (the admin can
    test a subset)."""

    overrides: ServiceOverridesIn


class TestConnectionOut(BaseModel):
    ok: bool
    message: str = ""
    detail: str | None = None


# ── Meta ────────────────────────────────────────────────────────────────────
class MetaOut(BaseModel):
    name: str
    version: str
    disclaimer: str
    va_enabled: bool = False
    billing_self_serve: bool = False
    # Public terms/privacy: SPA page (prefer for VA portal) + JSON API source.
    # Relative paths so any host works; absolute when public_base is configured.
    legal_url: str = "/legal"
    legal_api_url: str = "/api/legal"
    # Additive eCFR-freshness surface: kb_stale is None until the first
    # successful eCFR check of this process, then True when Title 38 was
    # amended after kb_verified_as_of (frontend may surface a banner later).
    kb_stale: bool | None = None
    kb_verified_as_of: str | None = None
    kb_status: Literal["current", "stale", "unknown"] = "unknown"
    release_id: str | None = None
    rule_version: str | None = None
    rule_content_sha256: str | None = None


class ReleaseOut(BaseModel):
    schema_version: int
    product: str
    version: str
    release_id: str
    source_revision: str
    built_at: str
    schema_revision: str
    manifest_sha256: str
    manifest_valid: bool
    kb: dict
    rules: dict
    benefits: dict
    evaluations: dict
