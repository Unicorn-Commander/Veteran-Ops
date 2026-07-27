"""SQLAlchemy ORM models — the LOCKED data model from docs/BUILD-SPEC.md.

`users` is intentionally NOT RLS-fenced (login must look users up by email before
a user context exists); it is guarded by the auth router. `kb_cards` is NOT fenced
either — global reference material (rating criteria, rules, presumptive lists)
with no user_id and no PII. Every other table carries a `user_id` and is fenced
by the `user_isolation` RLS policy (see db.py).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .config import settings
from .db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )


def _user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


def _workspace_fk() -> Mapped[uuid.UUID | None]:
    """workspace/tenant scope (Wave 11). Nullable at the ORM layer so the additive
    migration can add the column and backfill it before any NOT NULL is enforced; new
    rows get it stamped automatically by the `set_workspace_id` BEFORE-INSERT trigger
    from the `app.current_workspace` GUC (see db.py)."""
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Organization(Base):
    """A workspace / tenant (Wave 11). `kind='personal'` is the auto-created
    single-member workspace every veteran gets; `kind='org'` is a multi-member tenant
    (a VSO, clinic, law firm, or county veterans office). plan_tier is the suite's
    string tier_code (default 'free'); status parks/removes a tenant."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    plan_tier: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # NULL = inherit the global/env privacy_mode; True = force local-only (privacy-
    # first) for this workspace; False = allow quality-first (frontier) routing.
    # Resolved live per request by overrides.workspace_privacy_mode().
    privacy_mode: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # PII→cloud consent (Phase 3). NULL consent_at = NOT consented (the default).
    # A non-NULL timestamp records that this workspace explicitly consented to the
    # veteran's OWN record text being processed by a frontier/cloud model when
    # privacy_mode is off. The C-file quality mode checks this before releasing PII to
    # a non-local model (overrides.resolve_pii_model); without it, PII stays local even
    # with privacy off. consent_by is the granting user (plain UUID, no FK — it must
    # survive that user's erasure, like audit_log.actor_user_id). Every grant/revoke
    # AND every actual release is audit-logged.
    pii_cloud_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pii_cloud_consent_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = _created()


class OrganizationMember(Base):
    """A user's membership in a workspace, with their role there. Roles:
    owner | admin | staff | member. Unique per (org, user) — see db.py init DDL."""

    __tablename__ = "organization_members"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[uuid.UUID] = _user_fk()
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Wave 12: proven-email gate. Native sign-ups start False and verify via an emailed
    # link; SSO/Brigade identities are provisioned True (their IdP already verified the
    # email). Existing pre-Wave-12 users are backfilled True (see db.py) so nobody is
    # locked out. NEVER gates a veteran's own self-help — only sensitive org actions.
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Suite avatar spine: the veteran's Unicorn Commander profile photo, captured from
    # the Keycloak `picture` claim (uchub `profile` scope) on SSO login and synced on
    # every subsequent SSO login so a changed/removed OC photo propagates. Nullable —
    # native email/password accounts have none and fall back to rendered initials.
    avatar_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = _created()

    @property
    def platform_admin(self) -> bool:
        """Whether this identity may manage instance-wide service configuration."""
        return settings.platform_admin_email_allowed(self.email)


class OrganizationInvite(Base):
    """A pending invitation for an email to join an organization (Wave 12).

    NOT RLS-fenced (like `users` / `va_connect_states`): the accept flow resolves an
    invite by its secret token BEFORE the invitee is a member of the org, so a
    workspace-scoped policy would hide it. Access is enforced in the router — admin
    endpoints filter by org_id + verify the caller's role; accept resolves by
    `token_hash` and requires the caller's email to match `email`.

    Only the SHA-256 of the token is stored; the raw token lives solely in the emailed
    link. status: pending | accepted | revoked.
    """

    __tablename__ = "organization_invites"

    id: Mapped[uuid.UUID] = _uuid_pk()
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Case(Base):
    """A veteran an ORGANIZATION is helping — the unit of an org's caseload (Wave 13).

    A case lives in the ORG workspace (RLS-fenced by workspace_id) and is NOT keyed to a
    Valor user: the veteran often has no account (the classic VSO/clinic intake, where a
    caseworker sits with them). So identity here is descriptive (name/contact), not an
    FK. If the veteran DOES have their own personal account, a future consent-linkage
    (Model B) can bridge the two records; v1 keeps the org's case file self-contained.

    status: intake | active | filed | closed
    consent_status: none | granted | revoked  (see CaseConsent for the artifact)

    ⚖️ Legal lane: a case is the org's file for ASSISTING/organizing a veteran's claim.
    It is NOT VA power of attorney — formally representing a veteran before VA requires
    the org to be VA-accredited and appointed via VA Form 21-22 / 21-22a. The consent
    captured here is an app-level authorization to assist, and the UI says so.
    """

    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    veteran_name: Mapped[str] = mapped_column(String(255), nullable=False)
    veteran_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    veteran_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="intake")
    consent_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The staff member (org user) who created the case. Plain UUID (not an FK to users,
    # which is a different tenancy domain) — resolved for display via a join when needed.
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class CaseAssignment(Base):
    """Which staff member is assigned to a case (Wave 13). Drives the caseload scope:
    a `staff`-role user sees only cases assigned to them; admin/owner see the whole org
    caseload. Unique per (case, user) — see db.py init DDL."""

    __tablename__ = "case_assignments"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = _created()


class CaseConsent(Base):
    """The veteran's authorization for the org to assist on a case (Wave 13).

    First-class, audited artifact. method: in_person | written | verbal | portal.
    `statement` stores the veteran's authorization VERBATIM (their words, like every
    other veteran-authored text in the app). captured_by = the staff user who recorded
    it. Revocation is a status flip + timestamp (append-only history is the audit log).

    ⚖️ This is an app-level assist authorization, NOT VA Form 21-22 accreditation. The
    UI makes that distinction explicit and refers orgs/veterans to the real VA form for
    formal representation.
    """

    __tablename__ = "case_consents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="in_person")
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="assist")
    statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    granted_by_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    captured_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="granted")
    granted_at: Mapped[datetime] = _created()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CaseNote(Base):
    """A timeline note on a case (Wave 13) — the caseworker's own record of contact /
    action. author_id = the staff user who wrote it. RLS-fenced by the org workspace."""

    __tablename__ = "case_notes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = _created()


class VeteranProfile(Base):
    """One row per veteran (unique index on user_id lives in db.py init DDL).

    service_periods: [{branch, component, start_date, end_date, discharge_character}]
    exposures: {burn_pits, agent_orange, gulf_war, radiation, camp_lejeune,
                other: str, locations: [str]}
    """

    __tablename__ = "veteran_profiles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    service_periods: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    combat_service: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Explicit concurrent-pay facts. Nullable keeps existing profiles unchanged;
    # the enumerator never infers military-retiree status from years served.
    receives_military_retired_pay: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    combat_related_disability: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Chapter 61 / medical retirement vs length-of-service. Nullable = not answered.
    medically_retired: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Separated for medical reasons without being retired (e.g. PEB sep vs retirement).
    medically_separated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    exposures: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    current_combined_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Identity + household for pre-filling the veteran's own official VA forms.
    # NO SSN by design (see schemas.VeteranIdentity). Both JSONB, nullable.
    identity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    dependents: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class ClaimedCondition(Base):
    """A condition the veteran is claiming (or considering claiming).

    claim_type: direct | secondary | presumptive | increase
    status: considering | gathering_evidence | ready_to_file | filed | decided
    secondary_to: the primary claimed condition when claim_type == secondary.
    """

    __tablename__ = "claimed_conditions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    body_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    diagnostic_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    claim_type: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    secondary_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claimed_conditions.id", ondelete="SET NULL"),
        nullable=True,
    )
    current_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="considering")
    # The condition's real VA disposition (distinct from the veteran's own workflow
    # `status`): unknown | service_connected | denied | pending. A `denied` value is
    # first-class input to the Game Plan's "Respond to your denials" path, alongside
    # denials decoded from decision letters. server_default keeps existing rows valid
    # once the column is ALTERed in (see db.py additive migration).
    va_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="unknown", server_default="unknown"
    )
    onset_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    in_service_event: Mapped[str | None] = mapped_column(Text, nullable=True)
    nexus_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    dbq_form: Mapped[str | None] = mapped_column(String(160), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class EvidenceItem(Base):
    """A piece of evidence attached to a claimed condition.

    kind: diagnosis | service_record | nexus_letter | dbq | lay_statement |
          continuity | treatment_record | other
    status: have | need | requested | not_applicable
    """

    __tablename__ = "evidence_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    condition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claimed_conditions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="need")
    source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class EvidenceCitation(Base):
    """A veteran-pinned citation for one evidence item.

    One row per evidence item (primary key = evidence_id). It stores the exact
    quote the veteran wants the packet to surface, plus the offsets needed to
    jump back into the source document.
    """

    __tablename__ = "evidence_citation"

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("evidence_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class RatingScenario(Base):
    """A saved §4.25/§4.26 what-if.

    entries: [{label, percent int, side: "left"|"right"|null, group: str|null}]
    (side non-null marks a bilateral-candidate extremity entry).
    result: the rating engine's CombinedResult snapshot — the server recomputes
    on save; client math is never trusted.
    """

    __tablename__ = "rating_scenarios"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entries: Mapped[list] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created()


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    condition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claimed_conditions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = _created()


class AuditLog(Base):
    """Append-only trail. `actor_user_id` is the shared-access seam (NULL = the
    veteran acted on their own record).

    ⚠️ user_id here is ON DELETE SET NULL (NOT the CASCADE the veteran-owned tables use):
    an org's case-action audit rows must SURVIVE a staff member exercising their own
    right-to-erasure (Wave 9 DELETE /account) — otherwise a departing worker could
    silently wipe the org's accountability record of what they did on veterans' cases.
    `actor_label` denormalizes the actor's identity (email) at write time so "who did
    this" is preserved even after the user row (and its PII) is erased. See db.py, which
    re-points the FK to SET NULL on migration (the shared _user_fk default is CASCADE)."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created()


class CreditBalance(Base):
    """Per-user credit wallet. One row per veteran; balance is the live spendable
    credit amount and is updated together with the append-only transaction ledger."""

    __tablename__ = "credit_balance"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = _updated()


class CreditTransaction(Base):
    """Append-only per-user credit ledger. Positive deltas add credits; negative
    deltas spend them. Every row is tagged with an operation + reference."""

    __tablename__ = "credit_transaction"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created()


class GrantApplication(Base):
    """Need-based grant request from a veteran. Keep the intake light: enough to
    assess hardship, nothing sensitive like SSNs or bank data."""

    __tablename__ = "grant_application"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    monthly_income_band: Mapped[str | None] = mapped_column(String(64), nullable=True)
    household_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    employment_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    hardship_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    funded_sponsorship_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Sponsorship(Base):
    """Stripe-backed sponsor payment. May be earmarked to a named veteran by email,
    or left general for the next approved grant applicant."""

    __tablename__ = "sponsorship"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    checkout_session_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    payment_intent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    beneficiary_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    beneficiary_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="completed")
    earmark_status: Mapped[str] = mapped_column(String(24), nullable=False, default="general")
    pool_ledger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class GrantPool(Base):
    """Global grant pool ledger. Positive rows add sponsor-funded claims, negative
    rows spend one claim to award a grant."""

    __tablename__ = "grant_pool"

    id: Mapped[uuid.UUID] = _uuid_pk()
    claims_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sponsorship_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    grant_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reserved_email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    reserved_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()


class Document(Base):
    """An uploaded veteran document (rating decision, STR, DBQ, treatment record,
    decision letter, lay statement, …) flowing through the intake pipeline:
    upload → OCR/parse → classify+extract (local LLM) → veteran-confirmed linking.

    status:   uploaded | processing | ready | failed | duplicate
              ("duplicate" = auto-skipped as near-identical content of another ready
               document; never consumed by analysis, which filters status=="ready")
    doc_type: rating_decision | decision_letter | str | dbq | treatment_record |
              lay_statement | service_record | other (NULL until classified)
    sha256:   per-user dedupe key (same bytes uploaded twice → skip flag). Content-level
              near-dupes (different bytes, same words) use text_fingerprint/simhash.
    extracted: validated LLM output — {doc_type, doc_date, title, summary,
              conditions_mentioned: [{name, rating_percent?, diagnostic_code?,
              decision?}], is_va_decision, suggested_links: [{condition_id, name,
              match}], rating_summary: [...]}. Suggestions are deterministic fuzzy
              matches; NOTHING is auto-linked — the veteran confirms via the link
              endpoint.
    error:    human-readable failure message the UI can show (status == failed).
    file_ref: disk path under {UPLOAD_DIR}/{user_id}/ (container: /app/uploads).
    """

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploaded")
    doc_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    doc_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_offsets: Mapped[list[int] | None] = mapped_column(JSONB, nullable=True)
    condition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claimed_conditions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    file_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Near-duplicate detection over the EXTRACTED TEXT (intake/dedup.py). The
    # upload-time sha256 is over raw bytes; these are over content, so a re-scanned or
    # re-downloaded record that says the same thing is caught even when its bytes
    # differ. `text_fingerprint` = sha256 of normalized text (exact-content key);
    # `simhash` = 16-hex 64-bit SimHash (fuzzy near-dup). When this document is judged
    # a duplicate, `duplicate_of` points at the ready document it duplicates — and if
    # it was AUTO-SKIPPED, status is "duplicate" so no analysis ever consumes it; a
    # borderline match stays status="ready" with duplicate_of set as a soft flag.
    text_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    simhash: Mapped[str | None] = mapped_column(String(16), nullable=True)
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Extract-verify / OCR cross-read fidelity flag (Phase 3 intake):
    #   NULL/'clear' — nothing needs a human;
    #   'flagged'    — a disputed/unsupported extraction or a two-engine OCR
    #                  conflict is awaiting the veteran's reconcile (the disputed
    #                  value is NEVER silently persisted as fact — extracted['review']
    #                  carries the per-field candidates);
    #   'resolved'   — the veteran reconciled it.
    review_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    @property
    def relevance(self) -> str | None:
        """The classifier's claim-relevance label ('relevant'|'unclear'|'off_topic'),
        carried inside `extracted` (no dedicated column). None until classified."""
        return (self.extracted or {}).get("relevance")

    @property
    def relevance_flagged(self) -> bool:
        """Whether this document is SOFTLY flagged as possibly not related to the
        claim (so the veteran can review/delete). Deterministic guard in
        intake.classify.relevance_flag — evidence doc_types can never be flagged."""
        from .intake.classify import relevance_flag  # lazy: avoid import cycle

        return relevance_flag(self.extracted, self.doc_type)["flagged"]

    @property
    def relevance_reason(self) -> str | None:
        """The short why-it-looks-off-topic phrase, only when actually flagged."""
        from .intake.classify import relevance_flag

        return relevance_flag(self.extracted, self.doc_type)["reason"]


class DocumentFact(Base):
    """A veteran's OWN document, MAPPED into structured per-segment facts with
    provenance (intake/mappass.py) — the durable input the comprehension REDUCE
    (analysis/comprehension.py) folds into a whole-C-file case picture.

    RLS-FENCED exactly like `document_chunks` (workspace_id + user_id): a veteran's
    facts never cross a tenant boundary. One row per read segment; `facts` holds the
    validated bundle (conditions / exams / nexus / decisions / dates / contradictions
    — the model proposed, the pure validators disposed). Deleting the parent document
    (CASCADE) or the user removes them.

    LEGAL LANE: these are validated readings of the veteran's OWN text with a source
    pointer — organized evidence, never an AI-authored medical opinion.
    """

    __tablename__ = "document_facts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_relevant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    facts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()


class DocumentChunk(Base):
    """A retrievable slice of a veteran's OWN uploaded document, embedded for
    semantic search over their records (pgvector cosine, bge-m3, dim =
    settings.embedding_dim — the same stack that grounds the KB).

    RLS-FENCED exactly like `documents` (workspace_id + user_id): a veteran's
    chunks never cross a tenant boundary. Written by the intake pipeline once a
    document reaches `ready` with extractable text; deleting the parent document
    (ON DELETE CASCADE) or the user (via `_user_fk` CASCADE) removes them.

    LEGAL LANE: a chunk holds the veteran's own uploaded text VERBATIM. Retrieval
    surfaces excerpts to GROUND drafts in the veteran's real evidence — it never
    stores or adds an interpretation. No AI-authored content lives here.
    """

    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Char offsets into the parent document's text_content — lets the UI locate an
    # excerpt in the source without re-storing the whole document per chunk.
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )
    created_at: Mapped[datetime] = _created()


class GamePlanBriefingCache(Base):
    """Cached local-LLM Game Plan briefing keyed by the exact deterministic facts
    that were handed to the briefing writer.

    RLS-fenced like documents: the payload is derived from a veteran's own claim
    facts and never crosses user/workspace boundaries. It stores only the JSON
    briefing returned to the UI, not prompts or raw document text.
    """

    __tablename__ = "game_plan_briefing_cache"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    facts_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()


class GamePlanFirmCache(Base):
    """Cached specialist-firm findings keyed by the exact deterministic facts that
    drove them — the firm's equivalent of GamePlanBriefingCache.

    RLS-fenced like documents: findings are derived from a veteran's own claim
    facts and never cross user/workspace boundaries. The namespaced payload stores
    the fast firm's serialized ``findings``, the exhaustive ``deep_dive`` result,
    and a local-only ``notification`` flag (no prompts and no raw document text).
    Both analyses run on a facts-hash miss or explicit/proactive refresh, never as
    an unbounded per-render model call.
    """

    __tablename__ = "game_plan_firm_cache"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    facts_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()


class CFilePictureCache(Base):
    """Cached whole-C-file comprehension picture (analysis/comprehension.py), keyed
    by the exact ready-document revisions that drove it — the intake equivalent of
    GamePlanFirmCache.

    RLS-fenced like documents: the picture is a deterministic REDUCE of a veteran's
    own mapped facts and never crosses user/workspace boundaries. Rebuilt on a
    facts-hash miss (a document changed) or an explicit refresh, never per render.
    """

    __tablename__ = "cfile_picture_cache"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    facts_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _created()


class VaConnection(Base):
    """A veteran-consented VA Lighthouse (developer.va.gov) API connection.

    The veteran signs in at VA.gov (Login.gov / ID.me) and consents; we hold the
    resulting OAuth tokens ON THEIR BEHALF. Tokens are per-veteran credentials:
    this table is RLS-FENCED and token values must NEVER be logged or audited.

    Lighthouse OAuth is per-API (each API family has its own authorization
    server), so one row exists per (user, provider, api):
      provider: 'lighthouse'
      api:      'verification' (Service History & Eligibility) | 'claims'
                (Benefits Claims v1) | future: 'health' (Patient Health FHIR R4)
    scope_set: the space-joined scopes actually GRANTED at consent.
    meta:      needs_reconnect flag + the last normalized sync snapshot
               (meta['sync']) that /va/apply validates against.
    """

    __tablename__ = "va_connections"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="lighthouse")
    api: Mapped[str] = mapped_column(String(32), nullable=False, default="verification")
    scope_set: Mapped[str | None] = mapped_column(String(512), nullable=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connected_at: Mapped[datetime] = _created()
    last_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class VaConnectState(Base):
    """One-time OAuth-PKCE handshake row (mirrors Glitter Mane's
    FhirConnectState). The VA callback is a top-level browser navigation with no
    app session, so the initiating user + PKCE code_verifier are recovered from a
    signed `state` JWT pointing at this row. Single-use: consumed (deleted)
    on callback; abandoned rows are pruned on the next /va/connect.

    Deliberately NOT RLS-fenced — it is resolved by the signed state before any
    user context exists, holds no tokens, and lives for minutes.
    """

    __tablename__ = "va_connect_states"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    api: Mapped[str] = mapped_column(String(32), nullable=False, default="verification")
    code_verifier: Mapped[str] = mapped_column(String(160), nullable=False)
    scopes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = _created()


class SymptomLogEntry(Base):
    """A dated symptom-log entry — the veteran's own lay evidence, mirroring the
    §4 rating-criteria fields for a condition (exportable as dated lay evidence).
    The natural Glitter Mane bridge: entries pulled from GM are tagged
    source='glitter'. RLS-FENCED.

    criteria_tags: [str] — the §4 criteria phrases this entry supports (chips the
                   veteran picks in the UI), so the export reads against the
                   rating schedule.
    source: 'manual' | 'glitter'
    """

    __tablename__ = "symptom_log_entries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    condition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claimed_conditions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    symptoms: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0–10
    functional_impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    criteria_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ItfRecord(Base):
    """An Intent to File the veteran has on record (manually entered or surfaced
    from the VA connector). An ITF preserves the effective date for ONE YEAR;
    the countdown is computed (filed_date + 1yr) — no stored deadline to drift.
    RLS-FENCED.

    type: 'compensation' | 'pension' | 'survivors'
    source: 'manual' | 'va'
    """

    __tablename__ = "itf_records"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="compensation")
    filed_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = _created()


class KBCard(Base):
    """A concise, attributed knowledge card (rating criteria tiers, combine rules,
    presumptive lists, DBQ mappings, process guides) used to GROUND every AI answer
    in a citable source. Global shared knowledge — no user_id, NOT RLS-fenced,
    holds no PII. Seeded idempotently from backend/app/kb/data/*.json.

    card_type: rating_criteria | rule | presumptive | dbq | process
    source: the cite string, e.g. "38 CFR §4.130, DC 9411".
    data: structured payload (rating tiers, presumptive condition lists, …).
    """

    __tablename__ = "kb_cards"

    id: Mapped[uuid.UUID] = _uuid_pk()
    card_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    body_system: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    diagnostic_code: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    verified_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(settings.embedding_dim), nullable=True
    )


class KBBenefit(Base):
    """A curated benefits-directory override/upsert supplied out of band by a trusted
    curator. Global shared knowledge, no PII and not workspace-fenced. The file-backed
    benefits.json remains the baseline; rows here override or add entries."""

    __tablename__ = "kb_benefits"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    min_rating: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    requires_pt: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    states: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False, default="varies")
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    verified_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class KBRevision(Base):
    """Append-only global audit trail for trusted KB refresh batches."""

    __tablename__ = "kb_revisions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    batch_id: Mapped[str] = mapped_column(String(160), unique=True, index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[dict] = mapped_column(JSONB, nullable=False)
    verified_as_of: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    diff: Mapped[dict] = mapped_column(JSONB, nullable=False)
    applied_by: Mapped[str] = mapped_column(String(255), nullable=False, default="kb-refresh-service")
    created_at: Mapped[datetime] = _created()


class KBRefreshSignal(Base):
    """Operational signal that the global KB needs curator review after a freshness
    check detects a monitored source changed after our verified-as-of date."""

    __tablename__ = "kb_refresh_signals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    topic: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    kb_verified_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    detected_source_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = _created()
    last_seen_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AnalysisRun(Base):
    """RLS-fenced user-facing result for a durable comprehensive-analysis job.

    The API only creates this row plus a metadata-only AnalysisJob dispatch row. A
    database-leased worker executes the pipeline and stamps live progress here. The
    result therefore survives API/worker restarts without putting veteran content in
    the global dispatch queue.

    Doubles as the per-file BENCHMARK log: `steps[*].seconds` + `total_seconds` record
    exactly what a full run costs, and rows are kept across a records-reset so runs can
    be compared. RLS-fenced like every user-derived row; carries NO prompts and NO raw
    document text — only step timings and the final ComprehensiveOut counts (`ran` +
    `summary`).

    steps: [{key, label, status: pending|running|complete|failed, seconds: float|None,
             detail: str|None}] — ordered, seeded pending at creation.
    status: queued | leased | running | retryable | completed | failed | cancelled.
    """

    __tablename__ = "analysis_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID | None] = _workspace_fk()
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    steps: Mapped[list] = mapped_column(JSONB, nullable=False)
    ran: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()


class AnalysisJob(Base):
    """Metadata-only durable dispatch row for an RLS-fenced AnalysisRun.

    This table is intentionally not workspace-RLS fenced: workers must atomically
    discover the next tenant without a privileged/BYPASSRLS database role. It stores
    UUIDs and operational state only, never prompts, record text, findings, or PII.
    Every API lookup still filters user_id + workspace_id + run_id explicitly; all
    substantive work re-enters a normal RLS-scoped session.
    """

    __tablename__ = "analysis_jobs"
    __table_args__ = (
        Index("uq_analysis_jobs_idempotency", "idempotency_key", unique=True),
        Index("ix_analysis_jobs_claim", "status", "available_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = _user_fk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_token: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A global queue transition can commit just before the worker repairs the
    # FORCE-RLS run row. NULL marks that repair as outstanding so the next worker
    # pass converges after a crash instead of leaving the UI permanently stale.
    run_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AnalysisWorker(Base):
    """PII-free heartbeat used by readiness and queue operations."""

    __tablename__ = "analysis_workers"

    worker_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = _created()
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
