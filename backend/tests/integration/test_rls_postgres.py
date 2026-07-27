"""REAL-Postgres integration tier — the RLS / tenancy layer the SQLite unit suite
CANNOT exercise (SQLite has no ROW LEVEL SECURITY, no SET LOCAL GUCs, no triggers).

The fast SQLite suite proves logic + the explicit user_id IDOR filter; THIS suite runs
the app's actual `init_db()` against a live Postgres 16 (the prod pgvector image),
connecting as a NOBYPASSRLS role exactly like prod, and proves the defense-in-depth
RLS layer is genuinely enforced — including on the new `analysis_runs` table.

Runs ONLY when a superuser DSN is provided (so the default `pytest` run skips it):
    VALOR_PG_SUPERUSER_DSN=postgresql+asyncpg://postgres:PW@localhost:PORT/valor
The one-command way is `scripts/test-pg.sh`, which spins the prod image and sets it.
"""

from __future__ import annotations

import os
import asyncio
import uuid

import pytest

_SUPER = os.getenv("VALOR_PG_SUPERUSER_DSN")
pytestmark = pytest.mark.skipif(
    not _SUPER,
    reason="set VALOR_PG_SUPERUSER_DSN (or run scripts/test-pg.sh) for the real-Postgres tier",
)

pytest.importorskip("asyncpg")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.analysis.jobs import claim_next_job  # noqa: E402

# Distinct ids so a re-run against a persistent DB is idempotent.
UA = uuid.UUID("00000000-0000-0000-0000-00000000a001")
UB = uuid.UUID("00000000-0000-0000-0000-00000000b002")
WA = uuid.UUID("00000000-0000-0000-0000-0000000c0a01")
WB = uuid.UUID("00000000-0000-0000-0000-0000000c0b02")

_APP_ROLE = "valor_app_it"
_APP_PW = "valor_app_it_pw"


def _app_dsn(super_dsn: str) -> str:
    """Same host/port/db as the superuser DSN but as the NOBYPASSRLS app role."""
    tail = super_dsn.split("@", 1)[1]  # host:port/db
    return f"postgresql+asyncpg://{_APP_ROLE}:{_APP_PW}@{tail}"


@pytest.fixture()
async def pg():
    """Provision the app role, build the schema+RLS via the app's real init_db(), and
    seed two tenants (as superuser, which bypasses RLS — this is DB setup, not the app
    path). Yields the app-role engine.

    Function-scoped on purpose: pytest-asyncio gives each test its own event loop, and
    an asyncpg engine must live on the same loop as the test that uses it (a
    module-scoped engine raises 'attached to a different loop'). init_db + the seeds are
    idempotent, so re-provisioning per test is cheap and safe."""
    from app.db import init_db

    su = create_async_engine(_SUPER, isolation_level="AUTOCOMMIT")
    async with su.connect() as c:
        await c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await c.execute(text(
            f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='{_APP_ROLE}') "
            f"THEN CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_PW}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS; END IF; END $$"
        ))
        await c.execute(text(f"GRANT ALL ON SCHEMA public TO {_APP_ROLE}"))
        await c.execute(text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {_APP_ROLE}"
        ))
        await c.execute(text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {_APP_ROLE}"
        ))

    app_engine = create_async_engine(_app_dsn(_SUPER))
    await init_db(app_engine)  # the app's REAL migration, as the app role

    # Seed prerequisite tenant rows (users/orgs/members) as superuser.
    su2 = create_async_engine(_SUPER)
    async with su2.begin() as c:
        for wsid, uid, email in ((WA, UA, "it-a@e.test"), (WB, UB, "it-b@e.test")):
            await c.execute(text(
                "INSERT INTO organizations (id,name,slug,kind,plan_tier,status) "
                "VALUES (:id,:n,:s,'personal','free','active') ON CONFLICT DO NOTHING"
            ), {"id": wsid, "n": email, "s": f"personal-{uid}"})
            await c.execute(text(
                "INSERT INTO users (id,email,password_hash,full_name,email_verified) "
                "VALUES (:id,:e,'x',:e,true) ON CONFLICT DO NOTHING"
            ), {"id": uid, "e": email})
            await c.execute(text(
                "INSERT INTO organization_members (id,org_id,user_id,role) "
                "VALUES (gen_random_uuid(),:w,:u,'owner') ON CONFLICT DO NOTHING"
            ), {"w": wsid, "u": uid})
    await su.dispose()
    await su2.dispose()
    yield app_engine
    await app_engine.dispose()


async def _tenant_conn(app_engine, wsid, uid):
    """A dedicated connection scoped to one tenant via the RLS GUCs. Prod sets them
    per-transaction (SET LOCAL) for connection-pool safety; here each connection is
    used by a single tenant and we commit mid-test, so we set them at SESSION level
    (is_local=false) — otherwise the commit would clear them and RLS would then hide
    the tenant's own just-committed rows. `current_setting` reads either identically,
    so the policy under test is exactly the production policy."""
    c = await app_engine.connect()
    await c.execute(text("SELECT set_config('app.current_user_id',:u,false)"), {"u": str(uid)})
    await c.execute(text("SELECT set_config('app.current_workspace',:w,false)"), {"w": str(wsid)})
    return c


async def test_analysis_runs_table_has_forced_rls(pg):
    async with pg.connect() as c:
        row = (await c.execute(text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='analysis_runs'"
        ))).first()
        assert row == (True, True)
        pol = (await c.execute(text(
            "SELECT polname FROM pg_policy p JOIN pg_class cl ON cl.oid=p.polrelid "
            "WHERE cl.relname='analysis_runs'"
        ))).scalars().all()
        assert "workspace_isolation" in pol


async def test_analysis_job_dispatch_is_metadata_only_and_not_rls_fenced(pg):
    async with pg.connect() as c:
        row = (await c.execute(text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname='analysis_jobs'"
        ))).first()
        assert row == (False, False)
        columns = set((await c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='analysis_jobs'"
        ))).scalars().all())
        assert {"run_id", "user_id", "workspace_id", "status", "lease_token"} <= columns
        assert "run_synced_at" in columns
        assert not {"prompt", "document_text", "findings", "summary", "result"} & columns


async def test_rls_isolates_analysis_runs_without_any_explicit_filter(pg):
    # Each tenant inserts a run (workspace_id OMITTED → the stamp trigger fills it),
    # then a BARE SELECT (no user_id/workspace_id predicate) must return only its own.
    ca = await _tenant_conn(pg, WA, UA)
    cb = await _tenant_conn(pg, WB, UB)
    try:
        for c, uid in ((ca, UA), (cb, UB)):
            await c.execute(text(
                "INSERT INTO analysis_runs (id,user_id,status,steps) "
                "VALUES (gen_random_uuid(),:u,'queued','[]'::jsonb)"
            ), {"u": str(uid)})
            await c.commit()
        a_rows = (await ca.execute(text("SELECT user_id, workspace_id FROM analysis_runs"))).all()
        b_rows = (await cb.execute(text("SELECT user_id, workspace_id FROM analysis_runs"))).all()
        assert {str(r[0]) for r in a_rows} == {str(UA)}, a_rows
        assert {str(r[0]) for r in b_rows} == {str(UB)}, b_rows
        # (3) the BEFORE-INSERT trigger stamped workspace_id from the GUC.
        assert str(a_rows[0][1]) == str(WA)
    finally:
        await ca.close()
        await cb.close()


async def test_bare_delete_is_rls_fenced_to_the_active_tenant(pg):
    # The reset endpoint deletes with an explicit user_id filter AND under RLS. Prove the
    # RLS half alone: tenant A's unqualified DELETE can never reach tenant B's rows.
    ca = await _tenant_conn(pg, WA, UA)
    cb = await _tenant_conn(pg, WB, UB)
    try:
        for c, uid in ((ca, UA), (cb, UB)):
            await c.execute(text(
                "INSERT INTO analysis_runs (id,user_id,status,steps) "
                "VALUES (gen_random_uuid(),:u,'queued','[]'::jsonb)"
            ), {"u": str(uid)})
            await c.commit()
        await ca.execute(text("DELETE FROM analysis_runs"))  # no WHERE — RLS is the fence
        await ca.commit()
        assert (await ca.execute(text("SELECT count(*) FROM analysis_runs"))).scalar() == 0
        # B is untouched — A's DELETE could not see B's rows.
        assert (await cb.execute(text("SELECT count(*) FROM analysis_runs"))).scalar() >= 1
    finally:
        await ca.close()
        await cb.close()


async def test_init_db_promotes_legacy_active_run_and_preserves_complete_history(pg):
    """The additive upgrade must not strand old BackgroundTask-era rows."""
    from app.db import init_db

    # Isolate this migration case from durable jobs promoted by earlier tests in
    # the script's shared throwaway database.
    async with pg.begin() as cleanup:
        await cleanup.execute(text("DELETE FROM analysis_jobs"))
    for wsid, uid in ((WA, UA), (WB, UB)):
        tenant = await _tenant_conn(pg, wsid, uid)
        try:
            await tenant.execute(text(
                "UPDATE analysis_runs SET status='failed', finished_at=now() "
                "WHERE status IN ('queued','leased','running','retryable')"
            ))
            await tenant.commit()
        finally:
            await tenant.close()

    active_id = uuid.uuid4()
    complete_id = uuid.uuid4()
    ca = await _tenant_conn(pg, WA, UA)
    try:
        await ca.execute(text(
            "INSERT INTO analysis_runs (id,user_id,status,steps) VALUES "
            "(:active,:u,'running','[]'::jsonb),"
            "(:complete,:u,'complete','[]'::jsonb)"
        ), {"active": active_id, "complete": complete_id, "u": UA})
        await ca.commit()
    finally:
        await ca.close()

    await init_db(pg)

    ca = await _tenant_conn(pg, WA, UA)
    try:
        rows = dict((await ca.execute(text(
            "SELECT id, status FROM analysis_runs WHERE id IN (:active,:complete)"
        ), {"active": active_id, "complete": complete_id})).all())
        assert rows[active_id] == "retryable"
        assert rows[complete_id] == "complete"
    finally:
        await ca.close()
    async with pg.connect() as c:
        jobs = (await c.execute(text(
            "SELECT run_id, status FROM analysis_jobs "
            "WHERE run_id IN (:active,:complete)"
        ), {"active": active_id, "complete": complete_id})).all()
        assert jobs == [(active_id, "retryable")]


async def test_postgres_skip_locked_allows_only_one_worker_to_claim_a_job(pg):
    # Earlier RLS tests intentionally leave raw queued legacy runs behind; init_db's
    # compatibility migration can promote those into jobs on the next fixture boot.
    # Isolate this locking assertion to the single job created below.
    async with pg.begin() as cleanup:
        await cleanup.execute(text("DELETE FROM analysis_jobs"))
    ca = await _tenant_conn(pg, WA, UA)
    run_id = uuid.uuid4()
    job_id = uuid.uuid4()
    try:
        await ca.execute(text(
            "INSERT INTO analysis_runs (id,user_id,status,steps,idempotency_key) "
            "VALUES (:id,:u,'queued','[]'::jsonb,:key)"
        ), {"id": run_id, "u": UA, "key": uuid.uuid4().hex})
        await ca.execute(text(
            "INSERT INTO analysis_jobs "
            "(id,run_id,user_id,workspace_id,idempotency_key,status,attempts,max_attempts) "
            "VALUES (:id,:r,:u,:w,:key,'queued',0,3)"
        ), {"id": job_id, "r": run_id, "u": UA, "w": WA, "key": uuid.uuid4().hex})
        await ca.commit()
    finally:
        await ca.close()

    Session = async_sessionmaker(pg, expire_on_commit=False)

    async def claim(worker_id):
        async with Session() as db:
            lease = await claim_next_job(db, worker_id)
            await asyncio.sleep(0.05)
            await db.commit()
            return lease

    leases = await asyncio.gather(claim("pg-worker-a"), claim("pg-worker-b"))
    claimed = [lease for lease in leases if lease is not None]
    assert len(claimed) == 1
    assert claimed[0].run_id == str(run_id)
