"""Coach layer — do-this-first, outstanding, duplicates, interview seed."""

from __future__ import annotations

from app.strategy.coach import (
    build_interview_seed,
    build_moves,
    enrich_plan_with_coach,
    find_duplicate_clusters,
)
from app.strategy.plan import build_game_plan


def _c(i, name, **kw):
    base = {
        "id": f"00000000-0000-0000-0000-{i:012d}",
        "name": name,
        "claim_type": "direct",
        "va_status": "unknown",
        "status": "considering",
        "band": "early",
        "missing": ["nexus"],
        "score": 20,
        "has_have_evidence": False,
    }
    base.update(kw)
    return base


def test_duplicate_clusters_cfs_family():
    conds = [
        _c(1, "Chronic Fatigue Syndrome (ME/CFS)", va_status="service_connected", current_rating=60),
        _c(2, "chronic fatigue syndrome"),
        _c(3, "Myalgic Encephalomyelitis/Chronic Fatigue Syndrome"),
        _c(4, "Unrelated tinnitus"),
    ]
    dups = find_duplicate_clusters(conds)
    cfs = [d for d in dups if d["family"] == "cfs"]
    assert cfs and cfs[0]["count"] == 3
    assert "Chronic Fatigue Syndrome" in cfs[0]["keep_name"]


def test_enrich_plan_has_coach_first_and_outstanding():
    cfs = _c(
        1, "ME/CFS", va_status="service_connected", current_rating=60,
        claim_type="increase", status="decided", band="complete", missing=[], score=100,
    )
    anx = _c(2, "Anxiety", va_status="denied", missing=["nexus"])
    plan = build_game_plan(
        conditions=[cfs, anx],
        denials=[{"name": "Anxiety", "missing_elements": ["nexus"]}],
        suggestions=[],
        active_itf=None,
        current_combined=60,
        generated_at="t",
    )
    enrich_plan_with_coach(plan, conditions=[cfs, anx], denials=[{"name": "Anxiety"}])
    coach = plan["coach"]
    assert coach["do_this_first"] is not None
    assert coach["outstanding_count"] >= 1
    assert any(o["kind"] == "reclaim" for o in coach["outstanding"])
    assert coach["section_guides"]
    assert coach["interview"]["questions"]
    assert coach["case_brief"]["do_this_first"]


def test_interview_asks_tdiu_when_screened():
    cfs = _c(
        1, "ME/CFS", va_status="service_connected", current_rating=60,
        claim_type="increase", band="complete", missing=[], status="decided",
    )
    plan = build_game_plan(
        conditions=[cfs], denials=[], suggestions=[], active_itf=None,
        current_combined=60, generated_at="t",
    )
    seed = build_interview_seed(plan=plan, conditions=[cfs], outstanding=[])
    topics = [q["topic"] for q in seed["questions"]]
    assert any("TDIU" in t or "work" in t.lower() for t in topics)
    assert seed["starter_user_message"]


def test_build_moves_prefers_reclaim_or_tdiu():
    plan = {
        "priority_actions": [
            {"title": "File ITF", "why": "x", "category": "protect_backpay", "impact": "high", "link": "/itf"},
            {"title": "Reclaim Anxiety", "why": "y", "category": "reclaim", "impact": "high", "link": "/nexus"},
            {"title": "Get diagnosis", "why": "z", "category": "close_gap", "impact": "high", "link": "/c"},
        ]
    }
    m = build_moves(plan)
    assert m["do_this_first"]["title"] in ("File ITF", "Reclaim Anxiety")
