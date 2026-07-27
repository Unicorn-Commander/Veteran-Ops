"""WAVE13 — ORM/schema-level tests for the org caseload data model.

The cases router uses raw Postgres SQL (CAST(:x AS uuid), gen_random_uuid(), ::text)
that does NOT run on SQLite, so the endpoints are covered by a Postgres E2E, not here.
This suite proves the UNIT-testable layer: the SQLAlchemy model defaults, the
case→(assignment|consent|note) ON DELETE CASCADE the Postgres schema relies on, the
consent revoke shape, and that the Pydantic request/response schemas validate — all on
the same SQLite + @compiles harness the Wave-9/12 suites use.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

pytest.importorskip("aiosqlite")
pydantic = pytest.importorskip("pydantic")

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import event, func, select  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import models, schemas  # noqa: E402
from app.db import Base  # noqa: E402
from app.rbac import is_manager  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover
    Vector = None


@compiles(PGUUID, "sqlite")
def _u(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _j(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


if Vector is not None:
    @compiles(Vector, "sqlite")
    def _v(type_, compiler, **kw):  # noqa: ANN001, ANN003
        return "TEXT"


_TABLES = [
    models.Organization.__table__,
    models.OrganizationMember.__table__,
    models.User.__table__,
    models.Case.__table__,
    models.CaseAssignment.__table__,
    models.CaseConsent.__table__,
    models.CaseNote.__table__,
]
for _t in _TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())


@pytest.fixture()
def engine(tmp_path):
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path/'caseload.db'}", poolclass=NullPool
    )

    # SQLite ignores ON DELETE CASCADE unless FK enforcement is on — turn it on so this
    # test actually exercises the cascade the Postgres schema relies on.
    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    yield eng
    import asyncio
    asyncio.run(eng.dispose())


async def _sessionmaker(engine):
    """Create the Wave-13 tables (idempotent) and return an async sessionmaker bound to
    the test's event loop."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _seed_org(session):
    org = models.Organization(name="County Vets Office", slug="county-" + uuid.uuid4().hex[:8],
                              kind="org")
    session.add(org)
    await session.commit()
    return org


async def test_case_defaults_status_and_consent(engine):
    maker = await _sessionmaker(engine)
    async with maker() as s:
        org = await _seed_org(s)
        case = models.Case(workspace_id=org.id, veteran_name="Dana Vet")
        s.add(case)
        await s.commit()
        await s.refresh(case)
        assert case.status == "intake"
        assert case.consent_status == "none"
        assert case.veteran_name == "Dana Vet"


async def test_children_created_and_counted(engine):
    maker = await _sessionmaker(engine)
    async with maker() as s:
        org = await _seed_org(s)
        case = models.Case(workspace_id=org.id, veteran_name="Pat Vet")
        s.add(case)
        await s.commit()

        u1, u2 = uuid.uuid4(), uuid.uuid4()
        s.add_all([
            models.CaseAssignment(workspace_id=org.id, case_id=case.id, user_id=u1),
            models.CaseAssignment(workspace_id=org.id, case_id=case.id, user_id=u2),
            models.CaseConsent(workspace_id=org.id, case_id=case.id, granted_by_name="Pat Vet"),
            models.CaseNote(workspace_id=org.id, case_id=case.id, body="Intake call"),
            models.CaseNote(workspace_id=org.id, case_id=case.id, body="Filed ITF"),
        ])
        await s.commit()

        n_assign = (await s.execute(
            select(func.count()).select_from(models.CaseAssignment)
            .where(models.CaseAssignment.case_id == case.id)
        )).scalar_one()
        n_consent = (await s.execute(
            select(func.count()).select_from(models.CaseConsent)
            .where(models.CaseConsent.case_id == case.id)
        )).scalar_one()
        n_notes = (await s.execute(
            select(func.count()).select_from(models.CaseNote)
            .where(models.CaseNote.case_id == case.id)
        )).scalar_one()
        assert (n_assign, n_consent, n_notes) == (2, 1, 2)

        # Consent default status is 'granted'.
        consent = (await s.execute(
            select(models.CaseConsent).where(models.CaseConsent.case_id == case.id)
        )).scalar_one()
        assert consent.status == "granted"
        assert consent.scope == "assist"
        assert consent.method == "in_person"


async def test_delete_case_cascades_to_children(engine):
    maker = await _sessionmaker(engine)
    async with maker() as s:
        org = await _seed_org(s)
        case = models.Case(workspace_id=org.id, veteran_name="Sam Vet")
        s.add(case)
        await s.commit()
        cid = case.id
        s.add_all([
            models.CaseAssignment(workspace_id=org.id, case_id=cid, user_id=uuid.uuid4()),
            models.CaseConsent(workspace_id=org.id, case_id=cid, granted_by_name="Sam Vet"),
            models.CaseNote(workspace_id=org.id, case_id=cid, body="note"),
        ])
        await s.commit()

        await s.delete(case)
        await s.commit()

        for model in (models.CaseAssignment, models.CaseConsent, models.CaseNote):
            remaining = (await s.execute(
                select(func.count()).select_from(model).where(model.case_id == cid)
            )).scalar_one()
            assert remaining == 0, f"{model.__name__} not cascaded"


async def test_consent_revoke_shape_persists(engine):
    maker = await _sessionmaker(engine)
    async with maker() as s:
        org = await _seed_org(s)
        case = models.Case(workspace_id=org.id, veteran_name="Lee Vet")
        s.add(case)
        await s.commit()
        consent = models.CaseConsent(
            workspace_id=org.id, case_id=case.id, granted_by_name="Lee Vet", status="granted"
        )
        s.add(consent)
        await s.commit()

        when = datetime.now(timezone.utc)
        consent.status = "revoked"
        consent.revoked_at = when
        await s.commit()

        reloaded = (await s.execute(
            select(models.CaseConsent).where(models.CaseConsent.id == consent.id)
        )).scalar_one()
        assert reloaded.status == "revoked"
        assert reloaded.revoked_at is not None


# ── Pure schema round-trips (no DB) ──────────────────────────────────────────
def test_consent_capture_in_defaults():
    c = schemas.ConsentCaptureIn(
        method="in_person", granted_by_name="Jane Vet", acknowledged_not_poa=True
    )
    assert c.scope == "assist"
    assert c.method == "in_person"
    assert c.acknowledged_not_poa is True


def test_case_create_in_validation():
    ok = schemas.CaseCreateIn(veteran_name="A")
    assert ok.veteran_name == "A"
    # veteran_email is EmailStr | None; email-validator rejects .test, use example.com.
    ok2 = schemas.CaseCreateIn(veteran_name="B", veteran_email="b@example.com")
    assert ok2.veteran_email == "b@example.com"
    with pytest.raises(ValidationError):
        schemas.CaseCreateIn(veteran_name="")


def test_response_schemas_validate():
    now = datetime.now(timezone.utc)
    cid = str(uuid.uuid4())
    case = schemas.CaseOut(
        id=cid, veteran_name="A", status="intake", consent_status="none",
        created_at=now, updated_at=now,
    )
    assert case.assignees == [] and case.note_count == 0

    note = schemas.CaseNoteOut(id=str(uuid.uuid4()), case_id=cid, body="hi", created_at=now)
    assert note.author_email == ""

    audit = schemas.AuditEntryOut(id=str(uuid.uuid4()), action="case.created", created_at=now)
    assert audit.actor_email == ""


def test_caseload_scope_guard():
    """Documents the intended visibility policy at the logic level: managers
    (admin/owner) see the whole org caseload; staff/member do not (staff visibility is
    assignment-based)."""
    assert is_manager("owner") and is_manager("admin")
    assert not is_manager("staff") and not is_manager("member")
