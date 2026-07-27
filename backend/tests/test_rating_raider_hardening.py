"""Adversarial contracts for the Rating Raider backend wave.

These tests deliberately use empty and synthetic dossiers: the agent must remain
safe and useful even when intake data is incomplete or a gateway is unavailable.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import Settings
from app.evidence import autolink
from app.evidence.proactive import (
    draft_for_opportunity,
    evidence_opportunities,
    evidence_review,
    existing_evidence,
)
from app.evidence.research import center_deep_base, nexus_research
from app.deadlines import appeal_deadline, dependent_deadline, itf_deadline
from app.firm.context import VeteranDossier
from app.raider import agent, tools
from app.raider.agent import _LANE_FALLBACK, _clean_answer, _lane_ok, _make_lane_safe
from app.strategy.concurrent_pay import screen_concurrent_pay


def _dossier(conditions=None, documents=None):
    return VeteranDossier(
        uid="00000000-0000-0000-0000-000000000001",
        conditions=conditions or [],
        documents=documents or [],
        profile={},
        current_combined=0,
    )


def test_every_tool_is_json_safe_with_an_empty_context_and_unknown_is_an_error():
    ctx = SimpleNamespace(db=None, uid="not-a-real-user", dossier=None, host=None)
    async def check():
        for spec in tools.TOOLS:
            result = await tools.run_tool(spec.name, None, ctx)
            assert isinstance(result, dict), spec.name
            json.dumps(result)
        unknown = await tools.run_tool("unknown", {}, ctx)
        assert "error" in unknown
    import asyncio
    asyncio.run(check())


def test_tool_pii_matrix_and_navigation_allowlist():
    pii = {
        "get_my_situation", "run_deep_dive", "find_secondary_conditions", "screen_tdiu",
        "check_readiness", "list_deadlines", "check_concurrent_pay", "review_my_evidence",
        # Phase 3 advocate tools that read the veteran's OWN record → PII-marked.
        "search_my_records", "get_case_picture",
        # C&P exam prep reads claimed conditions + readiness from the dossier.
        "prepare_cp_exam",
    }
    public = {
        "search_va_rulebook", "preview_form", "list_workflows", "find_supporting_research",
        "take_me_to", "open_form",
    }
    assert {t.name for t in tools.TOOLS if t.touches_pii} == pii
    assert {t.name for t in tools.TOOLS if not t.touches_pii} == public

    async def check():
        ctx = SimpleNamespace(db=None, uid="x", dossier=_dossier())
        good = await tools.run_tool("take_me_to", {"destination": "documents"}, ctx)
        assert good["ui_action"] == {"type": "navigate", "route": "/documents"}
        for destination in ("/admin", "documents?next=/admin", "../admin", "unknown"):
            bad = await tools.run_tool("take_me_to", {"destination": destination}, ctx)
            assert "error" in bad and "ui_action" not in bad
    import asyncio
    asyncio.run(check())


def test_tool_specs_have_one_json_serializable_entry_per_tool():
    specs = tools.openai_tool_specs()
    assert len(specs) == len(tools.TOOLS)
    assert {s["function"]["name"] for s in specs} == {t.name for t in tools.TOOLS}
    json.dumps(specs)


@pytest.mark.parametrize("text", [
    "<tool_call>{\"name\": \"get_my_situation\"}</tool_call>answer",
    "before <function=search_va_rulebook><parameter=query>x</parameter></function> after",
    "before <parameter=query>leaked syntax",
])
def test_clean_answer_removes_literal_tool_protocol(text):
    cleaned = _clean_answer(text)
    assert "tool_call" not in cleaned.lower()
    assert "function=" not in cleaned.lower()
    assert "parameter=" not in cleaned.lower()


@pytest.mark.parametrize("text", [
    "You will receive the rating.",
    "You will be granted service connection.",
    "This is a guarantee of back pay.",
    "You'll get 70% for sure.",
    "You are certain to be approved.",
])
def test_lane_guard_blocks_guaranteed_outcomes(text):
    assert not _lane_ok(text)


@pytest.mark.parametrize("text", [
    "You qualify for this benefit under the criteria.",
    "This condition is service-connected on your record.",
    "It is at least as likely as not related to service.",
    "Your evidence supports a 70% rating.",
    "You should be rated at 70% under §4.130.",
])
def test_lane_guard_allows_cited_opinions(text):
    # 2026 posture: full-advocate opinions are legitimate output, not lane violations.
    assert _lane_ok(text)


def test_lane_revision_keeps_clean_rewrite_and_falls_back_if_needed(monkeypatch):
    async def clean(*args, **kwargs):
        return "The criteria require review; your record shows the evidence to discuss with a VSO."
    monkeypatch.setattr(agent.gateway, "complete", clean)
    import asyncio
    revised = asyncio.run(_make_lane_safe("You will be granted 70%.", model="local"))
    assert revised.startswith("The criteria require")
    assert revised != _LANE_FALLBACK

    async def still_bad(*args, **kwargs):
        return "You will receive the benefit."
    monkeypatch.setattr(agent.gateway, "complete", still_bad)
    fallback = asyncio.run(_make_lane_safe("You will be granted 70%.", model="local"))
    assert fallback == _LANE_FALLBACK


def _tool_call(name, args="{}"):
    return SimpleNamespace(id="call-1", function=SimpleNamespace(name=name, arguments=args))


@pytest.mark.asyncio
async def test_agent_emits_tool_ui_tokens_and_done(monkeypatch):
    calls = [SimpleNamespace(content="", tool_calls=[_tool_call("take_me_to", '{"destination":"documents"}')]),
             SimpleNamespace(content="", tool_calls=[])]
    async def complete_with_tools(*args, **kwargs):
        return calls.pop(0)
    async def complete(*args, **kwargs):
        return "The criteria require review; your record shows the next step."
    async def run_tool(name, args, ctx):
        return {"ui_action": {"type": "navigate", "route": "/documents"}}
    monkeypatch.setattr(agent.gateway, "complete_with_tools", complete_with_tools)
    monkeypatch.setattr(agent.gateway, "complete", complete)
    monkeypatch.setattr(agent, "run_tool", run_tool)
    events = [e async for e in agent.run_agent(SimpleNamespace(), [])]
    assert events[0:2] == [
        {"type": "tool", "name": "take_me_to", "status": "start"},
        {"type": "tool", "name": "take_me_to", "status": "done"},
    ]
    assert {"type": "ui", "action": {"type": "navigate", "route": "/documents"}} in events
    assert any(e["type"] == "token" for e in events)
    assert events[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_agent_is_bounded_and_gateway_failure_is_graceful(monkeypatch):
    count = 0
    async def forever(*args, **kwargs):
        nonlocal count
        count += 1
        return SimpleNamespace(content="", tool_calls=[_tool_call("list_workflows")])
    async def run_tool(name, args, ctx):
        return {}
    monkeypatch.setattr(agent.gateway, "complete_with_tools", forever)
    monkeypatch.setattr(agent, "run_tool", run_tool)
    events = [e async for e in agent.run_agent(SimpleNamespace(), [])]
    assert count == agent.MAX_TOOL_ROUNDS
    assert events[-1]["type"] == "done"
    assert any(e["type"] == "token" for e in events)

    async def down(*args, **kwargs):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(agent.gateway, "complete_with_tools", down)
    failed = [e async for e in agent.run_agent(SimpleNamespace(), [])]
    assert failed[-1] == {"type": "done"}
    assert failed[-2]["type"] == "token"


def test_proactive_evidence_matches_mentions_and_requires_real_gaps():
    condition = {"name": "PTSD", "diagnostic_code": "9411", "in_service_event": "deployment stressor", "missing": ["nexus"]}
    doc = SimpleNamespace(id="doc-1", doc_type="nexus_letter", title="Provider letter", filename=None,
                          extracted={"conditions_mentioned": [{"name": "PTSD"}]})
    dossier = _dossier([condition], [doc])
    have = existing_evidence(dossier)
    assert have[0]["condition"] == "PTSD" and have[0]["evidence_type"] == "nexus"
    assert evidence_opportunities(dossier)[0]["opportunity"] == "nexus"
    mature = _dossier([{**condition, "missing": [], "va_status": "service_connected"}])
    assert evidence_opportunities(mature) == []
    direct = _dossier([{**condition, "missing": [], "diagnostic_code": None, "va_status": "unknown"}])
    assert evidence_opportunities(direct) == []
    direct.conditions[0].update({"missing": ["nexus"], "diagnostic_code": None, "band": "developing"})
    assert evidence_opportunities(direct)[0]["opportunity"] == "nexus"


def test_proactive_drafts_are_nonempty_and_leave_provider_opinion_blank():
    dossier = _dossier([{"name": "PTSD", "diagnostic_code": "9411", "in_service_event": "deployment stressor", "missing": ["nexus"]}])
    opp = evidence_opportunities(dossier)[0]
    draft = draft_for_opportunity(dossier, opp)
    assert draft and draft["markdown"].strip()
    assert "[provider to complete]" in draft["markdown"].lower()
    assert "[caused by / related to / aggravated by]" in draft["markdown"].lower()
    assert "________________________________________________________________" in draft["markdown"]
    assert evidence_review(_dossier())["worth_adding"] == []


def test_research_is_host_routed_and_deidentified(monkeypatch):
    monkeypatch.setattr("app.evidence.research.settings.center_deep_url_unicorncommander", "https://prod.example")
    monkeypatch.setattr("app.evidence.research.settings.center_deep_url_default", "https://default.example")
    assert center_deep_base("rating.unicorncommander.ai:443") == "https://prod.example"
    assert center_deep_base("localhost:3000") == "https://default.example"
    result = nexus_research(condition="sleep apnea", primary="PTSD", host="rating.unicorncommander.ai")
    parsed = urlparse(result["center_deep_url"])
    query = parse_qs(parsed.query)["q"][0]
    assert parsed.scheme == "https" and parsed.netloc == "prod.example"
    assert "sleep apnea" in query and "PTSD" in query
    assert all(value not in query for value in ("Veteran", "00000000", "ssn", "@"))


def test_model_for_truth_table():
    s = Settings(llm_model="local", reasoning_model="", privacy_mode=True)
    assert s.model_for(tier="reasoning") == "local"
    assert s.model_for(tier="default") == "local"
    s = Settings(llm_model="local", reasoning_model="cloud", privacy_mode=False)
    assert s.model_for(tier="reasoning", touches_pii=True) == "cloud"
    assert s.model_for(tier="default", touches_pii=True) == "local"


def test_deadline_boundaries_today_and_one_year_are_consistent():
    today = __import__("datetime").date(2026, 7, 10)
    # Exactly today is still surfaced as soon; one day beyond the one-year
    # boundary is not silently treated as a different date rule.
    assert itf_deadline([{"filed_date": "2025-07-10", "type": "compensation"}], today).days_left == 0
    assert appeal_deadline([{"decision_date": "2025-07-10"}], today).days_left == 0
    assert dependent_deadline([{"relationship": "spouse", "marriage_date": "2025-07-10"}], today).days_left == 0
    assert itf_deadline([{"filed_date": "2026-07-10", "type": "compensation"}], today).days_left == 365
    assert appeal_deadline([{"decision_date": "2026-07-10"}], today).days_left == 365
    assert itf_deadline([{"filed_date": "2026-07-11", "type": "compensation"}], today).days_left == 366


@pytest.mark.parametrize("rating", [40, 50, 60, 70])
def test_concurrent_pay_rating_boundaries_keep_programs_separate(rating):
    result = screen_concurrent_pay(rating, receives_retired_pay=True, combat_related=True)
    assert result["crdp"]["likely_fits"] is (rating >= 50)
    assert result["crsc"]["likely_fits"] is (rating >= 10)
    assert result["must_elect"] is (rating >= 50)
    assert "promise" not in str(result).lower()


@pytest.mark.asyncio
async def test_auto_link_is_idempotent_and_leaves_ambiguous_rows(monkeypatch):
    pytest.importorskip("aiosqlite")
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.schema import ColumnDefault
    from app import models
    from app.db import Base
    @compiles(PGUUID, "sqlite")
    def _uuid(type_, compiler, **kwargs):
        return "CHAR(36)"
    @compiles(JSONB, "sqlite")
    def _json(type_, compiler, **kwargs):
        return "JSON"
    tables = [models.User.__table__, models.ClaimedCondition.__table__, models.Document.__table__, models.EvidenceItem.__table__]
    for table in tables:
        for column in table.columns:
            if column.server_default is not None and "gen_random_uuid" in str(getattr(column.server_default, "arg", "")):
                column.server_default = None
                column.default = ColumnDefault(lambda: uuid.uuid4())
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    Session = async_sessionmaker(engine, expire_on_commit=False)
    uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    condition = models.ClaimedCondition(id=uuid.uuid4(), user_id=uid, name="PTSD", status="considering")
    other = models.ClaimedCondition(id=uuid.uuid4(), user_id=uid, name="Anxiety", status="considering")
    doc = models.Document(id=uuid.uuid4(), user_id=uid, filename="nexus.pdf", sha256="a" * 64, size_bytes=1,
                          doc_type="nexus_letter", title="Nexus", file_ref="nexus.pdf",
                          extracted={"conditions_mentioned": [{"name": "PTSD"}]})
    ambiguous = models.Document(id=uuid.uuid4(), user_id=uid, filename="dbq.pdf", sha256="b" * 64, size_bytes=1,
                                doc_type="dbq", title="DBQ", extracted={"conditions_mentioned": [{"name": "PTSD"}, {"name": "Anxiety"}]})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=tables)
    async with Session() as db:
        db.add_all([models.User(id=uid, email="a@example.com", password_hash="x"), condition, other, doc, ambiguous])
        await db.commit()
        dossier = _dossier([{"name": "PTSD"}, {"name": "Anxiety"}], [doc, ambiguous])
        monkeypatch.setattr(autolink, "build_dossier", lambda *args: _async_value(dossier))
        first = await autolink.auto_link_evidence(db, str(uid))
        second = await autolink.auto_link_evidence(db, str(uid))
        assert len(first["linked"]) == 1
        assert second["linked"] == [] and second["already_linked"] == 1
        assert second["ambiguous"]
        rows = (await db.execute(select(models.EvidenceItem))).scalars().all()
        assert len(rows) == 1 and rows[0].kind == "nexus_letter"
    await engine.dispose()


async def _async_value(value):
    return value
