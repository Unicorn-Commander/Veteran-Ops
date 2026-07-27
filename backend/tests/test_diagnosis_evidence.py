"""Diagnosis-evidence auto-identification — the bridge from "records name this
condition" to a satisfied 'Current diagnosis' readiness element.

Covers:
  * `_best_diagnosis_doc` prioritization (pure).
  * build-case adds ONE 'have' diagnosis item from a clinical source record, and
    that item closes the gaps.py "Current diagnosis" gap.
  * a condition whose only source is a lay_statement gets NO diagnosis item
    (legal lane — this app organizes evidence, it is not a doctor).
  * the backfill endpoint fills conditions built before this logic, idempotently.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date
from types import SimpleNamespace

import pytest

from app.analysis.gaps import analyze_gaps
from app.routers.analysis import _best_diagnosis_doc

# ── _best_diagnosis_doc prioritization (pure — no DB/LLM) ─────────────────────


def _doc(doc_type, doc_date=None, filename="rec.pdf"):
    return SimpleNamespace(
        doc_type=doc_type, doc_date=doc_date, filename=filename, title=None,
        file_ref=f"/x/{filename}", summary=None, id=uuid.uuid4(),
    )


def test_best_diagnosis_doc_prefers_rating_decision_over_treatment():
    treat = _doc("treatment_record", date(2020, 1, 1))
    rating = _doc("rating_decision", date(2015, 1, 1))
    assert _best_diagnosis_doc([treat, rating]) is rating


def test_best_diagnosis_doc_picks_most_recent_within_priority():
    older = _doc("treatment_record", date(2018, 6, 1))
    newer = _doc("treatment_record", date(2023, 6, 1))
    assert _best_diagnosis_doc([older, newer]) is newer
    # ordering of the input list must not matter
    assert _best_diagnosis_doc([newer, older]) is newer


def test_best_diagnosis_doc_dated_sorts_before_undated():
    undated = _doc("dbq", None)
    dated = _doc("dbq", date(2019, 1, 1))
    assert _best_diagnosis_doc([undated, dated]) is dated


def test_best_diagnosis_doc_returns_none_for_non_clinical():
    lay = _doc("lay_statement", date(2020, 1, 1))
    bare = _doc("service_record", date(2020, 1, 1))
    other = _doc("other", None)
    assert _best_diagnosis_doc([lay, bare, other]) is None
    assert _best_diagnosis_doc([]) is None


# ── Endpoint tests on a SQLite harness (mirrors test_strategy.py) ─────────────

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import deps, models  # noqa: E402
from app.db import Base  # noqa: E402
from app.routers import analysis as analysis_mod  # noqa: E402

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
    models.User.__table__, models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__, models.EvidenceItem.__table__,
    models.Document.__table__, models.AuditLog.__table__,
]
for _t in _TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())

UA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
WS = uuid.UUID("00000000-0000-0000-0000-0000000000c3")
D_TREAT = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
D_LAY = uuid.UUID("00000000-0000-0000-0000-0000000000d2")


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path/'s.db'}", poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(UA), "workspace_id": str(WS)}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add(models.User(id=UA, email="a@e.test", password_hash="x", full_name="Alex V"))
            # A clinical treatment record naming "Lumbar strain".
            s.add(models.Document(
                id=D_TREAT, user_id=UA, filename="treatment.pdf", sha256="a" * 64,
                status="ready", doc_type="treatment_record", doc_date=date(2022, 3, 1),
                title="VA Clinic Note", summary="Assessment: chronic lumbar strain.",
                file_ref="/uploads/treatment.pdf",
                extracted={"conditions_mentioned": [{"name": "Lumbar strain"}]},
            ))
            # A lay statement (buddy letter) naming "Tinnitus" — NOT clinical.
            s.add(models.Document(
                id=D_LAY, user_id=UA, filename="buddy.pdf", sha256="b" * 64,
                status="ready", doc_type="lay_statement", doc_date=date(2021, 1, 1),
                title="Buddy Statement", summary="States ringing in ears since service.",
                file_ref="/uploads/buddy.pdf",
                extracted={"conditions_mentioned": [{"name": "Tinnitus"}]},
            ))
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(analysis_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.current_workspace_id] = lambda: current["workspace_id"]
    app.dependency_overrides[deps.get_db] = _test_db
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current, Session=Session)


async def _evidence_for(Session, condition_name):
    async with Session() as s:
        cond = (await s.execute(
            select(models.ClaimedCondition).where(models.ClaimedCondition.name == condition_name)
        )).scalar_one()
        items = list((await s.execute(
            select(models.EvidenceItem).where(models.EvidenceItem.condition_id == cond.id)
        )).scalars().all())
        return cond, items


def test_build_case_adds_diagnosis_from_clinical_record_and_closes_gap(env):
    r = env.client.post("/api/analysis/build-case", json={
        "candidates": [{
            "name": "Lumbar strain",
            "claim_type": "direct",
            "document_ids": [str(D_TREAT)],
        }],
        "link_evidence": True,
    })
    assert r.status_code == 200, r.text
    import asyncio
    cond, items = asyncio.run(
        _evidence_for(env.Session, "Lumbar strain")
    )
    dx = [e for e in items if e.kind == "diagnosis"]
    assert len(dx) == 1
    assert dx[0].status == "have"
    assert "confirm" in (dx[0].notes or "").lower()  # honest framing
    assert dx[0].source == "Uploaded record"

    # Feeding that evidence to the gap engine → no "Current diagnosis" gap.
    ev = [{"kind": e.kind, "status": e.status} for e in items]
    gaps = analyze_gaps({"name": "Lumbar strain", "claim_type": "direct"}, ev, None)
    assert "diagnosis" not in [g["kind"] for g in gaps]


def test_build_case_lay_statement_gets_no_diagnosis(env):
    r = env.client.post("/api/analysis/build-case", json={
        "candidates": [{
            "name": "Tinnitus",
            "claim_type": "direct",
            "document_ids": [str(D_LAY)],
        }],
        "link_evidence": True,
    })
    assert r.status_code == 200, r.text
    import asyncio
    cond, items = asyncio.run(
        _evidence_for(env.Session, "Tinnitus")
    )
    assert [e for e in items if e.kind == "diagnosis"] == []
    # readiness still reports the missing diagnosis (honest — no clinical record).
    ev = [{"kind": e.kind, "status": e.status} for e in items]
    gaps = analyze_gaps({"name": "Tinnitus", "claim_type": "direct"}, ev, None)
    assert "diagnosis" in [g["kind"] for g in gaps]


def test_backfill_adds_diagnosis_for_preexisting_condition_and_is_idempotent(env):
    import asyncio

    # Simulate a condition created BEFORE this logic: no diagnosis evidence.
    async def _seed():
        async with env.Session() as s:
            s.add(models.ClaimedCondition(
                user_id=UA, name="Lumbar strain", claim_type="direct", status="considering",
            ))
            await s.commit()

    asyncio.run(_seed())

    r = env.client.post("/api/analysis/backfill-diagnosis-evidence")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conditions_updated"] == 1
    assert body["evidence_added"] == 1

    _, items = asyncio.run(
        _evidence_for(env.Session, "Lumbar strain")
    )
    dx = [e for e in items if e.kind == "diagnosis"]
    assert len(dx) == 1 and dx[0].status == "have"

    # Re-run: already has a diagnosis item → skipped, nothing added.
    body2 = env.client.post("/api/analysis/backfill-diagnosis-evidence").json()
    assert body2["evidence_added"] == 0
    assert body2["skipped_existing"] == 1


def test_build_case_start_comprehensive_default_false(env):
    """Default body leaves comprehensive unstarted; response carries the flag fields."""
    r = env.client.post("/api/analysis/build-case", json={
        "candidates": [{
            "name": "Knee strain",
            "claim_type": "direct",
            "document_ids": [str(D_TREAT)],
        }],
        "link_evidence": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["comprehensive_started"] is False
    assert body.get("comprehensive_run_id") in (None, "")


def test_build_case_start_comprehensive_soft_fails_without_readable_text(env):
    """Opt-in must not fail the build when prerequisites (readable text) are incomplete."""
    r = env.client.post("/api/analysis/build-case", json={
        "candidates": [{
            "name": "Shoulder strain",
            "claim_type": "direct",
            "document_ids": [str(D_TREAT)],
        }],
        "link_evidence": True,
        "start_comprehensive": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["created"]) == 1
    # Docs in this fixture have no text_content → prereq soft-skip.
    assert body["comprehensive_started"] is False
    assert body.get("comprehensive_run_id") in (None, "")
