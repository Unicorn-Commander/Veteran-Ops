"""Deadline Guardian tests — the veteran's 1-year clocks (veteran-workflows
research §cross-cutting #2). Pure tests exercise app/deadlines.py directly with a
fixed `today` (so they stay hermetic across calendar time): ITF expiry, the
decision-review window, the dependency-retroactivity window, the urgency buckets,
and the soonest-first ordering. Endpoint tests mount the real /deadlines router on
the same SQLite harness the other router tests use (PG types shimmed,
gen_random_uuid()→uuid4, cross-user isolation via the router's user_id filters).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.deadlines import (
    RETRO_OVERDUE_GRACE_DAYS,
    SOON_THRESHOLD_DAYS,
    appeal_deadline,
    compute_deadlines,
    dependent_deadline,
    itf_deadline,
    urgency_for,
)
from app.deadlines_notify import format_deadline_email
from app.decoder.deadline import add_one_year

TODAY = date(2026, 7, 10)


# ═══════════════════════════════════════════════════════════════════════════
# 0. format_deadline_email — pure digest body (deadline notify)
# ═══════════════════════════════════════════════════════════════════════════
def test_format_deadline_email_urgent_overdue_subject_and_body():
    deadlines = [
        {
            "kind": "itf",
            "title": "Complete your compensation claim before your Intent to File expires",
            "due_date": "2026-06-01",
            "days_left": -10,
            "urgency": "overdue",
            "what_to_do": "File the claim before the date.",
            "related_route": "/itf",
        },
        {
            "kind": "appeal",
            "title": "Decision-review deadline on your VA decision",
            "due_date": "2026-08-01",
            "days_left": 22,
            "urgency": "soon",
            "what_to_do": "File a review within one year.",
            "related_route": "/appeals",
        },
        {
            "kind": "dependent",
            "title": "Far out clock",
            "due_date": "2027-01-01",
            "days_left": 200,
            "urgency": "ok",
            "what_to_do": "Nothing urgent.",
            "related_route": "/dependency",
        },
    ]
    subject, body = format_deadline_email(
        deadlines, public_base="https://valor.magicunicorn.dev"
    )
    assert "overdue" in subject.lower()
    assert "1 overdue" in subject
    # ok urgency is filtered out of the urgent set; only soon/overdue remain.
    assert "Intent to File" in body
    assert "Decision-review" in body
    assert "Far out clock" not in body
    assert "10 day(s) overdue" in body
    assert "22 day(s) left" in body
    assert "https://valor.magicunicorn.dev/itf" in body
    assert "What to do:" in body


def test_format_deadline_email_empty_and_relative_routes():
    subject, body = format_deadline_email([])
    assert "deadline" in subject.lower()
    assert "No urgent" in body or body.startswith("(")

    subject2, body2 = format_deadline_email(
        [
            {
                "title": "Soon clock",
                "due_date": None,
                "days_left": None,
                "urgency": "soon",
                "what_to_do": "Check dates.",
                "related_route": "/deadlines",
            }
        ]
    )
    assert "upcoming deadline" in subject2
    assert "date not detected" in body2
    assert "unknown days left" in body2
    assert "In app: /deadlines" in body2


def test_format_deadline_email_accepts_deadline_dataclasses():
    d = itf_deadline(
        [{"type": "compensation", "filed_date": date(2026, 5, 1)}],
        TODAY,
    )
    assert d is not None
    # Force urgency for the formatter path.
    forced = {
        **{
            "kind": d.kind,
            "title": d.title,
            "due_date": d.due_date,
            "days_left": 5,
            "urgency": "soon",
            "what_to_do": d.what_to_do,
            "related_route": d.related_route,
        }
    }
    subject, body = format_deadline_email([forced])
    assert "upcoming" in subject
    assert d.title in body


# ═══════════════════════════════════════════════════════════════════════════
# 1. urgency buckets — pure
# ═══════════════════════════════════════════════════════════════════════════
def test_urgency_buckets():
    assert urgency_for(-1) == "overdue"
    assert urgency_for(0) == "soon"
    assert urgency_for(SOON_THRESHOLD_DAYS) == "soon"
    assert urgency_for(SOON_THRESHOLD_DAYS + 1) == "ok"
    assert urgency_for(400) == "ok"
    # Unknown date still nudges rather than reading as safe.
    assert urgency_for(None) == "soon"


# ═══════════════════════════════════════════════════════════════════════════
# 2. ITF expiry — pure (filed_date + 1yr, soonest un-expired)
# ═══════════════════════════════════════════════════════════════════════════
def test_itf_deadline_soonest_unexpired_and_math():
    recs = [
        {"type": "compensation", "filed_date": date(2026, 6, 10)},  # deadline 2027-06-10
        {"type": "pension", "filed_date": date(2026, 1, 10)},       # deadline 2027-01-10 (soonest)
        {"type": "survivors", "filed_date": date(2024, 1, 1)},      # long expired → skipped
    ]
    d = itf_deadline(recs, TODAY)
    assert d is not None
    assert d.kind == "itf"
    assert d.due_date == add_one_year(date(2026, 1, 10)).isoformat()  # "2027-01-10"
    assert d.days_left == (date(2027, 1, 10) - TODAY).days
    assert d.urgency == urgency_for(d.days_left)
    assert d.related_route == "/itf"
    assert "pension" in d.title


def test_itf_deadline_none_when_empty_or_all_expired():
    assert itf_deadline([], TODAY) is None
    assert itf_deadline([{"type": "compensation", "filed_date": date(2020, 1, 1)}], TODAY) is None


def test_itf_deadline_accepts_iso_string_dates():
    d = itf_deadline([{"type": "compensation", "filed_date": "2026-06-10"}], TODAY)
    assert d is not None and d.due_date == "2027-06-10"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Decision-review window — pure (decision_date + 1yr, soonest still-open)
# ═══════════════════════════════════════════════════════════════════════════
def test_appeal_deadline_soonest_open_recomputed():
    decodes = [
        {"decision_date": "2026-01-05"},   # deadline 2027-01-05 (soonest open)
        {"decision_date": "2026-05-01"},   # deadline 2027-05-01 (open)
        {"decision_date": "2024-01-01"},   # expired → skipped
        {"decision_date": None},           # no date → skipped
        {"decision_date": "not-a-date"},   # unparseable → skipped
        "not-a-dict",                       # junk → skipped
    ]
    d = appeal_deadline(decodes, TODAY)
    assert d is not None
    assert d.kind == "appeal"
    assert d.due_date == "2027-01-05"
    # Recomputed against TODAY, not any stale stored days_remaining.
    assert d.days_left == (date(2027, 1, 5) - TODAY).days
    assert d.related_route == "/appeals"


def test_appeal_deadline_none_when_no_open_windows():
    assert appeal_deadline([], TODAY) is None
    assert appeal_deadline([{"decision_date": "2020-01-01"}], TODAY) is None


# ═══════════════════════════════════════════════════════════════════════════
# 4. Dependency retroactivity — pure (marriage/birth + 1yr, 38 CFR 3.401)
# ═══════════════════════════════════════════════════════════════════════════
def test_dependent_deadline_spouse_uses_marriage_date():
    deps = [{"relationship": "spouse", "full_name": "Jane Q. Veteran", "marriage_date": "2026-05-01"}]
    d = dependent_deadline(deps, TODAY)
    assert d is not None
    assert d.kind == "dependent"
    assert d.due_date == "2027-05-01"
    assert "Jane Q. Veteran" in d.title
    assert d.related_route == "/dependency"


def test_dependent_deadline_child_uses_dob_and_generic_name():
    deps = [{"relationship": "child", "date_of_birth": "2026-06-01"}]
    d = dependent_deadline(deps, TODAY)
    assert d is not None and d.due_date == "2027-06-01"
    assert "your child" in d.title  # no full_name → generic


def test_dependent_deadline_just_missed_is_overdue_within_grace():
    # Marriage 2026-06-20 → deadline 2026-06-20+1yr? no — deadline = 2026-06-20.
    # Use last year so the window has just closed: 2025-06-20 → deadline 2026-06-20,
    # ~20 days past TODAY (within the 60-day grace) → surfaced as overdue.
    deps = [{"relationship": "spouse", "marriage_date": "2025-06-20"}]
    d = dependent_deadline(deps, TODAY)
    assert d is not None
    assert d.urgency == "overdue"
    assert d.days_left is not None and d.days_left < 0
    assert -RETRO_OVERDUE_GRACE_DAYS <= d.days_left < 0


def test_dependent_deadline_ancient_and_parent_and_missing_skipped():
    assert dependent_deadline([{"relationship": "spouse", "marriage_date": "2000-01-01"}], TODAY) is None
    assert dependent_deadline([{"relationship": "parent", "date_of_birth": "2026-01-01"}], TODAY) is None
    assert dependent_deadline([{"relationship": "spouse"}], TODAY) is None  # no marriage_date
    assert dependent_deadline([], TODAY) is None


def test_dependent_deadline_soonest_of_several():
    deps = [
        {"relationship": "spouse", "marriage_date": "2026-06-01"},  # deadline 2027-06-01
        {"relationship": "child", "date_of_birth": "2025-09-01"},   # deadline 2026-09-01 (soonest)
    ]
    d = dependent_deadline(deps, TODAY)
    assert d is not None and d.due_date == "2026-09-01"


# ═══════════════════════════════════════════════════════════════════════════
# 5. compute_deadlines — ordering + graceful degradation
# ═══════════════════════════════════════════════════════════════════════════
def test_compute_deadlines_sorted_soonest_first():
    itf = [{"type": "compensation", "filed_date": "2026-06-10"}]      # deadline 2027-06-10 (~335)
    decodes = [{"decision_date": "2026-05-10"}]                        # deadline 2027-05-10 (~304)
    deps = [{"relationship": "spouse", "marriage_date": "2025-09-01"}] # deadline 2026-09-01 (~53)
    out = compute_deadlines(itf_records=itf, decodes=decodes, dependents=deps, today=TODAY)
    assert [d.kind for d in out] == ["dependent", "appeal", "itf"]
    assert out == sorted(out, key=lambda d: d.days_left)


def test_compute_deadlines_degrades_to_empty():
    assert compute_deadlines(itf_records=None, decodes=None, dependents=None, today=TODAY) == []
    # Present-but-empty / undated sources contribute nothing rather than error.
    assert compute_deadlines(
        itf_records=[], decodes=[{"decision_date": None}], dependents=[{}], today=TODAY
    ) == []


# ═══════════════════════════════════════════════════════════════════════════
# 6. Endpoint — real /deadlines router on the SQLite harness (RLS-scoped)
# ═══════════════════════════════════════════════════════════════════════════
fastapi = pytest.importorskip("fastapi")
pytest.importorskip("aiosqlite")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from sqlalchemy.schema import ColumnDefault  # noqa: E402

from app import deps, models  # noqa: E402
from app.db import Base  # noqa: E402
from app.routers import deadlines as deadlines_mod  # noqa: E402

try:
    from pgvector.sqlalchemy import Vector  # noqa: E402
except Exception:  # pragma: no cover
    Vector = None


@compiles(PGUUID, "sqlite")
def _pg_uuid_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "CHAR(36)"


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
    return "JSON"


if Vector is not None:
    @compiles(Vector, "sqlite")
    def _vector_sqlite(type_, compiler, **kw):  # noqa: ANN001, ANN003
        return "TEXT"


_TABLES = [
    models.User.__table__,
    models.VeteranProfile.__table__,
    models.ClaimedCondition.__table__,
    models.ItfRecord.__table__,
    models.Document.__table__,
    models.AuditLog.__table__,
]

for _t in _TABLES:
    for _c in _t.columns:
        if _c.server_default is not None and "gen_random_uuid" in str(
            getattr(_c.server_default, "arg", "")
        ):
            _c.server_default = None
            _c.default = ColumnDefault(lambda: uuid.uuid4())


USER_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
USER_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")


@pytest.fixture()
def env(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'dl.db'}", poolclass=NullPool
    )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    current = {"uid": str(USER_A)}

    today = date.today()
    itf_filed = today - timedelta(days=30)     # deadline ~ +335 → ok
    decision_date = today - timedelta(days=60)  # deadline ~ +305 → ok
    marriage = today - timedelta(days=300)      # deadline ~ +65  → soon (soonest)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=_TABLES)
        async with Session() as s:
            s.add_all([
                models.User(id=USER_A, email="a@x.com", password_hash="x", full_name="A"),
                models.User(id=USER_B, email="b@x.com", password_hash="x", full_name="B"),
                models.ItfRecord(user_id=USER_A, type="compensation", filed_date=itf_filed),
                models.Document(
                    user_id=USER_A,
                    filename="decision.pdf",
                    sha256="a" * 64,
                    size_bytes=1,
                    status="ready",
                    extracted={"decode": {"decision_date": decision_date.isoformat(), "has_denials": True}},
                ),
                models.VeteranProfile(
                    user_id=USER_A,
                    dependents=[{
                        "relationship": "spouse",
                        "full_name": "Jane Q. Veteran",
                        "marriage_date": marriage.isoformat(),
                    }],
                ),
            ])
            await s.commit()
        yield
        await engine.dispose()

    app = FastAPI(lifespan=lifespan)
    app.include_router(deadlines_mod.router, prefix="/api")

    async def _test_db():
        async with Session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[deps.current_user_id] = lambda: current["uid"]
    app.dependency_overrides[deps.get_db] = _test_db

    with TestClient(app) as client:
        yield SimpleNamespace(client=client, current=current)


def test_deadlines_all_three_sources_sorted_and_semantic(env):
    body = env.client.get("/api/deadlines").json()
    kinds = [d["kind"] for d in body["deadlines"]]
    # Soonest-first: dependent (~65d) < appeal (~305d) < itf (~335d).
    assert kinds == ["dependent", "appeal", "itf"]
    dep, appeal, itf = body["deadlines"]
    assert dep["urgency"] == "soon" and dep["related_route"] == "/dependency"
    assert appeal["urgency"] == "ok" and appeal["related_route"] == "/appeals"
    assert itf["urgency"] == "ok" and itf["related_route"] == "/itf"
    # Live countdowns, strictly ordered; every card is actionable.
    assert dep["days_left"] < appeal["days_left"] < itf["days_left"]
    assert all(d["days_left"] > 0 for d in body["deadlines"])
    assert all(d["title"] and d["what_to_do"] and d["due_date"] for d in body["deadlines"])
    assert "Jane Q. Veteran" in dep["title"]
    assert body["disclaimer"]


def test_deadlines_isolated_per_user(env):
    env.current["uid"] = str(USER_B)  # B has no ITF, docs, or dependents
    body = env.client.get("/api/deadlines").json()
    assert body["deadlines"] == []
    assert body["disclaimer"]
