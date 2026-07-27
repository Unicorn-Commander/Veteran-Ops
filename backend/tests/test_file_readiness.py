"""Tests for the file-readiness delta aggregation (analysis/file_readiness.py)."""

from app.analysis.file_readiness import HANDOFF, assemble_file_readiness


def _cond(cid, name, **kw):
    base = {
        "id": cid, "name": name, "claim_type": "direct", "secondary_to": None,
        "in_service_event": None, "nexus_notes": None, "diagnostic_code": None,
        "current_rating": None,
    }
    base.update(kw)
    return base


def test_bare_direct_condition_is_not_ready_and_lists_needs():
    r = assemble_file_readiness([_cond("1", "Knee strain")], {}, None, None)
    assert r["has_conditions"] and r["total_conditions"] == 1
    assert r["all_ready"] is False and r["ready_conditions"] == 0
    assert r["file_ready_score"] == 0
    labels = {n["label"] for n in r["still_needed"]}
    assert "Current diagnosis" in labels and "Medical nexus opinion" in labels
    # Every need carries a fix route + the condition it's for.
    for n in r["still_needed"]:
        assert n["route"].startswith("/") and n["conditions"] == ["Knee strain"]
    # Slim blockers mirror still_needed labels/routes/hows (no conditions list).
    assert len(r["blockers"]) == len(r["still_needed"])
    for b in r["blockers"]:
        assert set(b) == {"label", "route", "how"}
        assert b["route"].startswith("/")


def test_fully_supported_condition_is_ready():
    ev = {"1": [
        {"kind": "diagnosis", "status": "have"},
        {"kind": "service_record", "status": "have"},
        {"kind": "nexus_letter", "status": "have"},
        {"kind": "continuity", "status": "have"},
    ]}
    r = assemble_file_readiness(
        [_cond("1", "Tinnitus", in_service_event="acoustic trauma", nexus_notes="linked")],
        ev, None, None,
    )
    assert r["all_ready"] is True and r["ready_conditions"] == 1
    assert r["still_needed"] == []
    assert r["blockers"] == []
    assert r["file_ready_score"] == 100
    assert r["per_condition"][0]["ready"] is True


def test_shared_need_is_grouped_across_conditions():
    # Two direct conditions, neither with a nexus → one "Medical nexus opinion" entry
    # naming both.
    conds = [_cond("1", "Back", in_service_event="fall"), _cond("2", "Neck", in_service_event="fall")]
    ev = {
        "1": [{"kind": "diagnosis", "status": "have"}, {"kind": "continuity", "status": "have"}],
        "2": [{"kind": "diagnosis", "status": "have"}, {"kind": "continuity", "status": "have"}],
    }
    r = assemble_file_readiness(conds, ev, None, None)
    nexus = [n for n in r["still_needed"] if n["label"] == "Medical nexus opinion"]
    assert len(nexus) == 1
    assert set(nexus[0]["conditions"]) == {"Back", "Neck"}
    # Grouped need blocking 2 claims sorts ahead of single-claim needs.
    assert r["still_needed"][0]["label"] == "Medical nexus opinion"
    assert r["file_ready_score"] == 0


def test_score_is_ready_over_total_percent():
    # One fully supported, one bare → 50.
    ready_ev = {"1": [
        {"kind": "diagnosis", "status": "have"},
        {"kind": "service_record", "status": "have"},
        {"kind": "nexus_letter", "status": "have"},
        {"kind": "continuity", "status": "have"},
    ]}
    conds = [
        _cond("1", "Tinnitus", in_service_event="noise", nexus_notes="linked"),
        _cond("2", "Knee"),
    ]
    r = assemble_file_readiness(conds, ready_ev, None, None)
    assert r["ready_conditions"] == 1 and r["total_conditions"] == 2
    assert r["file_ready_score"] == 50
    assert r["all_ready"] is False
    assert any(b["label"] for b in r["blockers"])


def test_handoff_links_are_static_pro_se_constants():
    r = assemble_file_readiness([], {}, None, None)
    assert r["handoff"] == HANDOFF
    assert r["handoff"]["form526_route"] == "/application"
    assert r["handoff"]["va_gov_claim_url"].startswith("https://www.va.gov/")
    assert r["handoff"]["vso_url"].startswith("https://www.va.gov/")
    assert r["handoff"]["itf_url"].startswith("https://www.va.gov/")
    assert "never e-file" in r["handoff"]["packet_note"].lower()


def test_no_conditions_is_empty_but_valid():
    r = assemble_file_readiness([], {}, None, None)
    assert r["has_conditions"] is False and r["all_ready"] is False
    assert r["still_needed"] == [] and r["per_condition"] == []
    assert r["file_ready_score"] == 0
    assert r["blockers"] == []
