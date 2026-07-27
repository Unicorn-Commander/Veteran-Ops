"""Database engine, session factories, and Row-Level-Security wiring.

Multi-tenant (Wave 11): veteran-data tables are fenced with Postgres RLS keyed on
the GUC `app.current_workspace` (the tenant / organization id), the suite-canonical
tenancy model. Each authenticated request runs inside ONE transaction that sets both
`app.current_workspace` and `app.current_user_id` via `set_config(..., is_local =>
true)`; RLS then restricts every row to the active workspace. The app connects as the
non-superuser `valor_app` role and we FORCE row level security, so even the table
owner is subject to the policies.

A BEFORE-INSERT trigger stamps `workspace_id` from the GUC, so application insert
code never has to set it (and a context-less insert fails the WITH CHECK — fail
closed). Individual veterans each get an auto-created `kind='personal'` workspace;
organizations (VSOs / clinics / firms) are multi-member workspaces.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from .config import settings

log = logging.getLogger("veteran_ops")


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Tables that hold per-veteran data and are isolated per WORKSPACE (tenant).
# `users`, `organizations`, `organization_members`, and `kb_cards` are handled
# separately (see below) — they can't be workspace-fenced (login/tenant resolution
# must read them before a workspace context exists) or are global reference material.
FENCED_TABLES = [
    "veteran_profiles",
    "claimed_conditions",
    "evidence_items",
    "rating_scenarios",
    "checklist_items",
    "documents",
    "document_chunks",
    "document_facts",
    "evidence_citation",
    "game_plan_briefing_cache",
    "game_plan_firm_cache",
    "cfile_picture_cache",
    "analysis_runs",
    "va_connections",
    "symptom_log_entries",
    "itf_records",
    "audit_log",
    "credit_balance",
    "credit_transaction",
]

# Wave 13 org-caseload tables: also workspace-fenced (same RLS + auto-stamp trigger),
# but they have NO `user_id` column — they belong to the ORG workspace, not a veteran
# user — so they get the tenancy plumbing WITHOUT the user_id-based backfill the fenced
# tables use. They're new (empty on first migration), so nothing to backfill anyway.
CASE_TABLES = [
    "cases",
    "case_assignments",
    "case_consents",
    "case_notes",
]

# Every table that carries workspace_id + the isolation policy + the stamp trigger.
WORKSPACE_TABLES = FENCED_TABLES + CASE_TABLES

_WORKSPACE_GUC = "current_setting('app.current_workspace', true)"
_USER_GUC = "current_setting('app.current_user_id', true)"


async def init_db(target_engine: AsyncEngine | None = None) -> None:
    """Create tables and (idempotently) apply the multi-tenant RLS + backfill.

    The whole thing runs in ONE transaction (engine.begin) — atomic: a failure rolls
    back and the app refuses to start rather than leaving a half-migrated schema. Safe
    to run on every boot: the backfill inserts/updates are guarded to touch 0 rows once
    applied. Non-destructive: it only adds tables/columns and backfills — never drops
    data.

    `target_engine` defaults to the module engine (the normal boot path); the
    Postgres integration tests pass their own engine so the real RLS DDL runs against
    a throwaway database. It MUST be a valor_app-equivalent (NOBYPASSRLS) role for the
    FORCE-RLS policies to actually bind.
    """
    from . import models  # noqa: F401 — register models on Base.metadata

    eng = target_engine or engine
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # ── Pre-existing additive migrations (unchanged) ─────────────────────
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_veteran_profiles_user "
            "ON veteran_profiles (user_id)"
        ))
        await conn.execute(text(
            "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor_user_id UUID"
        ))
        # Wave 13: preserve the org accountability trail across a staffer's account
        # erasure. Denormalize WHO did it, and re-point the user_id FK from CASCADE
        # (the shared _user_fk default) to SET NULL so DELETE /account keeps the audit
        # rows (with actor_label) instead of cascading them away.
        await conn.execute(text(
            "ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS actor_label VARCHAR(255)"
        ))
        await conn.execute(text("ALTER TABLE audit_log ALTER COLUMN user_id DROP NOT NULL"))
        await conn.execute(text(
            "ALTER TABLE audit_log DROP CONSTRAINT IF EXISTS audit_log_user_id_fkey"
        ))
        await conn.execute(text(
            "ALTER TABLE audit_log ADD CONSTRAINT audit_log_user_id_fkey "
            "FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_va_connections_user_api "
            "ON va_connections (user_id, provider, api)"
        ))
        # A condition's real VA disposition (unknown | service_connected | denied |
        # pending). server_default 'unknown' keeps every existing row valid; NEW
        # databases get the column from create_all with the same default, so the
        # DEFAULT is kept (unlike email_verified, the app-side default IS 'unknown').
        await conn.execute(text(
            "ALTER TABLE claimed_conditions ADD COLUMN IF NOT EXISTS "
            "va_status VARCHAR(24) NOT NULL DEFAULT 'unknown'"
        ))
        await conn.execute(text(
            "ALTER TABLE veteran_profiles ADD COLUMN IF NOT EXISTS "
            "receives_military_retired_pay BOOLEAN"
        ))
        await conn.execute(text(
            "ALTER TABLE veteran_profiles ADD COLUMN IF NOT EXISTS "
            "combat_related_disability BOOLEAN"
        ))
        await conn.execute(text(
            "ALTER TABLE veteran_profiles ADD COLUMN IF NOT EXISTS "
            "medically_retired BOOLEAN"
        ))
        await conn.execute(text(
            "ALTER TABLE veteran_profiles ADD COLUMN IF NOT EXISTS "
            "medically_separated BOOLEAN"
        ))
        await conn.execute(text(
            "ALTER TABLE veteran_profiles ADD COLUMN IF NOT EXISTS identity JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE veteran_profiles ADD COLUMN IF NOT EXISTS dependents JSONB"
        ))
        await conn.execute(text(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS page_offsets JSONB"
        ))
        # Phase 3 intake: extract-verify / OCR cross-read review flag. NULL for every
        # existing row (nothing flagged retroactively); new databases get the same
        # nullable column from create_all.
        await conn.execute(text(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS review_status VARCHAR(16)"
        ))
        # Content-level near-duplicate detection (intake/dedup.py): fingerprint over
        # normalized text + a 64-bit SimHash (hex) + a pointer to the document this one
        # duplicates. NULL for existing rows (they simply aren't cross-checked until
        # reprocessed); new databases get these from create_all.
        await conn.execute(text(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS text_fingerprint VARCHAR(64)"
        ))
        await conn.execute(text(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS simhash VARCHAR(16)"
        ))
        await conn.execute(text(
            "ALTER TABLE documents ADD COLUMN IF NOT EXISTS duplicate_of UUID"
        ))
        await conn.execute(text(
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS privacy_mode BOOLEAN"
        ))
        # Phase 3: per-workspace PII→cloud consent (NULL = not consented). Additive +
        # nullable so existing workspaces default to NO consent (PII stays local even
        # with privacy off); new databases get the same columns from create_all.
        await conn.execute(text(
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS pii_cloud_consent_at "
            "TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE organizations ADD COLUMN IF NOT EXISTS pii_cloud_consent_by UUID"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_org_members "
            "ON organization_members (org_id, user_id)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_game_plan_briefing_cache_scope_hash "
            "ON game_plan_briefing_cache (user_id, workspace_id, facts_hash)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_game_plan_firm_cache_scope_hash "
            "ON game_plan_firm_cache (user_id, workspace_id, facts_hash)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_cfile_picture_cache_scope_hash "
            "ON cfile_picture_cache (user_id, workspace_id, facts_hash)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_credit_balance_user "
            "ON credit_balance (user_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_credit_transaction_user_created "
            "ON credit_transaction (user_id, created_at DESC)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_grant_application_status_created "
            "ON grant_application (status, created_at DESC)"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_sponsorship_checkout_session "
            "ON sponsorship (checkout_session_id)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_sponsorship_beneficiary_email "
            "ON sponsorship (beneficiary_email)"
        ))
        # KB refresh spine: additive source/date metadata for refreshed cards and
        # lookup indexes for the global audit/status tables. The tables themselves are
        # model-created by create_all; they are global reference/audit data, not
        # workspace-scoped veteran records.
        await conn.execute(text(
            "ALTER TABLE kb_cards ADD COLUMN IF NOT EXISTS source_name VARCHAR(255)"
        ))
        await conn.execute(text(
            "ALTER TABLE kb_cards ADD COLUMN IF NOT EXISTS source_url VARCHAR(1024)"
        ))
        await conn.execute(text(
            "ALTER TABLE kb_cards ADD COLUMN IF NOT EXISTS effective_date DATE"
        ))
        await conn.execute(text(
            "ALTER TABLE kb_cards ADD COLUMN IF NOT EXISTS verified_as_of DATE"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_kb_revisions_kind_created "
            "ON kb_revisions (kind, created_at DESC)"
        ))
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_kb_refresh_signals_open "
            "ON kb_refresh_signals (status, topic, created_at DESC)"
        ))

        # ── Flag: runtime overrides table for admin service settings ─────────
        await conn.execute(text(
            "CREATE TABLE IF NOT EXISTS app_service_settings ("
            "  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),"
            "  settings JSONB NOT NULL DEFAULT '{}'::jsonb,"
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
            "  updated_by UUID REFERENCES users(id) ON DELETE SET NULL"
            ")"
        ))

        # ── Wave 12: email verification + org invitations ────────────────────
        # Add email_verified defaulting TRUE so EXISTING users (who predate the
        # column) stay unblocked; then drop the default so NEW rows use the app's
        # client-side default (native sign-ups False, SSO/Brigade True).
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
            "email_verified BOOLEAN NOT NULL DEFAULT true"
        ))
        await conn.execute(text("ALTER TABLE users ALTER COLUMN email_verified DROP DEFAULT"))
        # Suite avatar spine (additive): the veteran's Unicorn Commander profile photo
        # (Keycloak `picture` claim), captured/synced on SSO login. Nullable — existing
        # and native users have none and fall back to initials. create_all makes the
        # same column on brand-new databases.
        await conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(1024)"
        ))

        # Durable comprehensive-analysis jobs. `analysis_jobs` / `analysis_workers`
        # are created above by create_all and intentionally remain outside RLS because
        # they contain operational metadata only; `analysis_runs` remains FORCE-RLS.
        await conn.execute(text(
            "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(64)"
        ))
        await conn.execute(text(
            "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS attempt_count INTEGER "
            "NOT NULL DEFAULT 0"
        ))
        await conn.execute(text(
            "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS max_attempts INTEGER "
            "NOT NULL DEFAULT 3"
        ))
        await conn.execute(text(
            "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS cancel_requested_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "ALTER TABLE analysis_jobs ADD COLUMN IF NOT EXISTS run_synced_at TIMESTAMPTZ"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_runs_idempotency "
            "ON analysis_runs (idempotency_key) WHERE idempotency_key IS NOT NULL"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_jobs_active_workspace "
            "ON analysis_jobs (user_id, workspace_id) "
            "WHERE status IN ('queued','leased','running','retryable')"
        ))
        # organization_invites is created by create_all (it's a model); add a lookup
        # index for the admin "pending invites for this org" listing.
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_org_invites_org_status "
            "ON organization_invites (org_id, status)"
        ))

        # ── Wave 11/13 tenancy: add workspace_id to every workspace-scoped table ──
        for table in WORKSPACE_TABLES:
            await conn.execute(text(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS workspace_id UUID"
            ))

        # Lift RLS on those tables so the backfill (run as the table owner) sees every
        # row; drop any prior policy (old per-user or a re-run's workspace one).
        for table in WORKSPACE_TABLES:
            await conn.execute(text(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"DROP POLICY IF EXISTS user_isolation ON {table}"))
            await conn.execute(text(f"DROP POLICY IF EXISTS workspace_isolation ON {table}"))

        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_case_assignment "
            "ON case_assignments (case_id, user_id)"
        ))

        # Lift RLS on the tenant tables too, so the backfill's membership check and
        # org inserts aren't masked by a prior boot's policies (they're re-forced at
        # the end). Without this, a re-boot sees 0 memberships and re-inserts orgs.
        await conn.execute(text("ALTER TABLE organizations DISABLE ROW LEVEL SECURITY"))
        await conn.execute(text("DROP POLICY IF EXISTS org_visible ON organizations"))
        await conn.execute(text("ALTER TABLE organization_members DISABLE ROW LEVEL SECURITY"))
        await conn.execute(text("DROP POLICY IF EXISTS member_self ON organization_members"))

        # ── Backfill: a personal workspace + owner membership per user that has
        #    none, then stamp workspace_id on every orphaned row from its owner's
        #    personal workspace. Deterministic slug 'personal-<uid>' links them. ──
        # Personal-workspace id is DETERMINISTic (md5('personal:'||uid)) so it matches
        # the runtime self-provision path in deps.py exactly (idempotent either way).
        await conn.execute(text(
            "INSERT INTO organizations (id, name, slug, kind, plan_tier, status) "
            "SELECT (md5('personal:' || u.id::text))::uuid, "
            "       COALESCE(NULLIF(u.full_name,''), split_part(u.email,'@',1)) || ' (personal)', "
            "       'personal-' || u.id::text, 'personal', 'free', 'active' "
            "FROM users u "
            "WHERE NOT EXISTS (SELECT 1 FROM organization_members m WHERE m.user_id = u.id) "
            "ON CONFLICT (id) DO NOTHING"
        ))
        await conn.execute(text(
            "INSERT INTO organization_members (id, org_id, user_id, role) "
            "SELECT gen_random_uuid(), o.id, u.id, 'owner' "
            "FROM users u JOIN organizations o ON o.slug = 'personal-' || u.id::text "
            "WHERE NOT EXISTS (SELECT 1 FROM organization_members m "
            "                  WHERE m.user_id = u.id AND m.org_id = o.id)"
        ))
        for table in FENCED_TABLES:
            await conn.execute(text(
                f"UPDATE {table} t SET workspace_id = ("
                "  SELECT o.id FROM organizations o "
                "  JOIN organization_members m ON m.org_id = o.id "
                "  WHERE m.user_id = t.user_id AND o.kind = 'personal' LIMIT 1"
                ") WHERE t.workspace_id IS NULL"
            ))
        await conn.execute(text(
            "INSERT INTO credit_balance (user_id, workspace_id, balance) "
            "SELECT u.id, o.id, 0 "
            "FROM users u "
            "JOIN organizations o ON o.slug = 'personal-' || u.id::text "
            "ON CONFLICT (user_id) DO NOTHING"
        ))

        # Upgrade safety for deployments that still have an ephemeral BackgroundTask
        # run from the pre-worker implementation. Keep only the newest orphan active
        # run per workspace retryable; older duplicates become explicit failures. A
        # legacy terminal `complete` row is deliberately untouched and remains readable.
        await conn.execute(text(
            "WITH orphan AS ("
            "  SELECT r.id, "
            "         row_number() OVER ("
            "           PARTITION BY r.user_id, r.workspace_id "
            "           ORDER BY r.created_at DESC, r.id DESC"
            "         ) AS position, "
            "         EXISTS ("
            "           SELECT 1 FROM analysis_jobs active "
            "           WHERE active.user_id = r.user_id "
            "             AND active.workspace_id = r.workspace_id "
            "             AND active.status IN ('queued','leased','running','retryable')"
            "         ) AS already_active "
            "  FROM analysis_runs r "
            "  WHERE r.status IN ('queued','running','retryable') "
            "    AND NOT EXISTS (SELECT 1 FROM analysis_jobs j WHERE j.run_id = r.id)"
            ") "
            "UPDATE analysis_runs r SET "
            "  idempotency_key = COALESCE(r.idempotency_key, 'legacy:' || r.id::text), "
            "  status = CASE WHEN orphan.position = 1 AND NOT orphan.already_active "
            "                THEN 'retryable' ELSE 'failed' END, "
            "  error = CASE WHEN orphan.position = 1 AND NOT orphan.already_active "
            "               THEN 'Recovered after the durable worker upgrade; the analysis will restart.' "
            "               ELSE 'Superseded during the durable worker upgrade.' END, "
            "  next_attempt_at = CASE WHEN orphan.position = 1 AND NOT orphan.already_active "
            "                         THEN now() ELSE NULL END, "
            "  lease_expires_at = NULL, "
            "  finished_at = CASE WHEN orphan.position = 1 AND NOT orphan.already_active "
            "                     THEN NULL ELSE COALESCE(r.finished_at, now()) END "
            "FROM orphan WHERE r.id = orphan.id"
        ))
        await conn.execute(text(
            "INSERT INTO analysis_jobs ("
            "  id, run_id, user_id, workspace_id, idempotency_key, status, attempts, "
            "  max_attempts, available_at, last_error, run_synced_at"
            ") "
            "SELECT gen_random_uuid(), r.id, r.user_id, r.workspace_id, "
            "       r.idempotency_key, 'retryable', r.attempt_count, r.max_attempts, "
            "       COALESCE(r.next_attempt_at, now()), "
            "       'Legacy analysis recovered for durable retry.', now() "
            "FROM analysis_runs r "
            "WHERE r.status = 'retryable' "
            "  AND r.idempotency_key LIKE 'legacy:%' "
            "  AND r.workspace_id IS NOT NULL "
            "  AND NOT EXISTS (SELECT 1 FROM analysis_jobs j WHERE j.run_id = r.id) "
            "ON CONFLICT DO NOTHING"
        ))

        # ── Auto-stamp trigger: fill workspace_id from the GUC on insert ─────
        await conn.execute(text(
            "CREATE OR REPLACE FUNCTION set_workspace_id() RETURNS trigger AS $$ "
            "BEGIN "
            "  IF NEW.workspace_id IS NULL THEN "
            f"    NEW.workspace_id := NULLIF({_WORKSPACE_GUC}, '')::uuid; "
            "  END IF; "
            "  RETURN NEW; "
            "END; $$ LANGUAGE plpgsql"
        ))

        # ── Re-enable + FORCE RLS on every workspace-scoped table, keyed on the
        #    WORKSPACE (fenced + case tables share the identical policy/trigger) ──
        for table in WORKSPACE_TABLES:
            await conn.execute(text(
                f"DROP TRIGGER IF EXISTS trg_set_workspace ON {table}"
            ))
            await conn.execute(text(
                f"CREATE TRIGGER trg_set_workspace BEFORE INSERT ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION set_workspace_id()"
            ))
            await conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
            await conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
            await conn.execute(text(
                f"CREATE POLICY workspace_isolation ON {table} "
                f"USING (workspace_id = NULLIF({_WORKSPACE_GUC}, '')::uuid) "
                f"WITH CHECK (workspace_id = NULLIF({_WORKSPACE_GUC}, '')::uuid)"
            ))

        # ── RLS on the tenant tables themselves ─────────────────────────────
        # organization_members: per-command policies keyed on the ACTIVE workspace,
        # so an admin scoped to their team can manage its roster while cross-tenant
        # isolation still holds — and, crucially, without any recursive self-lookup
        # (which FORCE RLS + NOBYPASSRLS makes painful). The split, by command:
        #   SELECT/DELETE : rows of your ACTIVE workspace (see the roster / remove a
        #                   member) OR your OWN membership anywhere (tenant resolution,
        #                   accept-invite readback, "leave org").
        #   INSERT        : into your active workspace (admin adds a member) OR a row
        #                   for YOURSELF (create-org owner row, accept an invite).
        #   UPDATE        : only within your active workspace (role changes).
        # ROLE authorization (who may actually do these) is enforced in the router via
        # rbac.require_role — RLS here only bounds WHICH tenant's rows are reachable.
        _ws = f"NULLIF({_WORKSPACE_GUC}, '')::uuid"
        _uid = f"NULLIF({_USER_GUC}, '')::uuid"
        await conn.execute(text("ALTER TABLE organization_members ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text("ALTER TABLE organization_members FORCE ROW LEVEL SECURITY"))
        for pol in ("member_self", "member_select", "member_insert",
                    "member_update", "member_delete"):
            await conn.execute(text(f"DROP POLICY IF EXISTS {pol} ON organization_members"))
        await conn.execute(text(
            "CREATE POLICY member_select ON organization_members FOR SELECT "
            f"USING (org_id = {_ws} OR user_id = {_uid})"
        ))
        await conn.execute(text(
            "CREATE POLICY member_insert ON organization_members FOR INSERT "
            f"WITH CHECK (org_id = {_ws} OR user_id = {_uid})"
        ))
        await conn.execute(text(
            "CREATE POLICY member_update ON organization_members FOR UPDATE "
            f"USING (org_id = {_ws}) WITH CHECK (org_id = {_ws})"
        ))
        await conn.execute(text(
            "CREATE POLICY member_delete ON organization_members FOR DELETE "
            f"USING (org_id = {_ws} OR user_id = {_uid})"
        ))
        # organizations: PER-COMMAND policies. A single FOR ALL policy applies its
        # USING expression as the INSERT check too (Postgres behavior), which would
        # block self-provisioning a brand-new org (the caller isn't a member yet). So
        # split: read/modify/delete require membership (or the active workspace);
        # INSERT is open (an empty org grants nothing until a membership exists).
        _org_member = (
            f"(id = NULLIF({_WORKSPACE_GUC}, '')::uuid "
            "  OR EXISTS (SELECT 1 FROM organization_members m "
            "             WHERE m.org_id = organizations.id "
            f"               AND m.user_id = NULLIF({_USER_GUC}, '')::uuid))"
        )
        await conn.execute(text("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY"))
        await conn.execute(text("ALTER TABLE organizations FORCE ROW LEVEL SECURITY"))
        for pol in ("org_visible", "org_select", "org_insert", "org_update", "org_delete"):
            await conn.execute(text(f"DROP POLICY IF EXISTS {pol} ON organizations"))
        await conn.execute(text(
            f"CREATE POLICY org_select ON organizations FOR SELECT USING ({_org_member})"
        ))
        await conn.execute(text(
            "CREATE POLICY org_insert ON organizations FOR INSERT WITH CHECK (true)"
        ))
        await conn.execute(text(
            f"CREATE POLICY org_update ON organizations FOR UPDATE USING ({_org_member}) "
            f"WITH CHECK ({_org_member})"
        ))
        await conn.execute(text(
            f"CREATE POLICY org_delete ON organizations FOR DELETE USING ({_org_member})"
        ))

    # ── Safety checks (own connection; log-only, never crash startup) ───────
    try:
        async with eng.connect() as conn:
            row = (await conn.execute(text(
                "SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user"
            ))).first()
            if row and row[0]:
                log.warning("SECURITY: DB role has BYPASSRLS — RLS is NOT enforced. "
                            "Provision valor_app as NOBYPASSRLS.")
            for table in FENCED_TABLES:
                n = (await conn.execute(text(
                    f"SELECT count(*) FROM {table} WHERE workspace_id IS NULL"
                ))).scalar()
                if n:
                    log.warning("tenancy backfill: %s rows still NULL workspace_id in %s", n, table)
    except Exception:  # noqa: BLE001 — diagnostics only
        log.warning("tenancy post-init checks skipped", exc_info=True)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Plain session (no RLS context) — used by auth/registration + tenant
    resolution helpers that must read users/memberships before a workspace exists."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def personal_workspace_id(user_id: str) -> str:
    """Deterministic id of a user's personal workspace (matches the db.py backfill and
    deps.py self-provision). Lets background work resolve a workspace with no query."""
    return str(uuid.UUID(hashlib.md5(f"personal:{user_id}".encode()).hexdigest()))


async def session_for_user(
    user_id: str, workspace_id: str | None = None
) -> AsyncIterator[AsyncSession]:
    """RLS-scoped session for background work (e.g. the intake pipeline). Sets
    app.current_user_id and app.current_workspace for the whole txn. When the caller
    doesn't specify a workspace, defaults to the user's PERSONAL workspace (correct for
    a veteran's own background work, e.g. a VA connection); the intake pipeline passes
    the real workspace the document was uploaded to.

    Handlers must NOT commit mid-request (SET LOCAL is per-transaction); use flush()
    to obtain ids. The teardown commits once at the end.
    """
    async with SessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_user_id', :uid, true)"),
            {"uid": str(user_id)},
        )
        await session.execute(
            text("SELECT set_config('app.current_workspace', :wid, true)"),
            {"wid": workspace_id or personal_workspace_id(str(user_id))},
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
