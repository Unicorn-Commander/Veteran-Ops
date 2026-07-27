"""KB corpus + loader tests — pure file-level checks, no Postgres.

Validates the authored data files load, every card carries a source cite (the
grounding contract: every AI answer cites its card), the secondary map has the
expected shape, and the DBQ mapper picks sensible forms.
"""

from __future__ import annotations

from app.analysis.gaps import map_dbq
from app.kb.store import (
    dbq_catalog_source,
    load_cards,
    load_dbq_catalog,
    load_secondary_map,
)

VALID_CARD_TYPES = {"rating_criteria", "rule", "presumptive", "dbq", "process"}


def test_load_cards_nonempty_and_shaped():
    cards = load_cards()
    assert len(cards) >= 30  # rating criteria + rules + presumptives + dbq + process
    for c in cards:
        assert c["card_type"] in VALID_CARD_TYPES, c.get("title")
        assert c.get("title")
        assert c.get("content")
        # The grounding contract: every card must be citable.
        assert c.get("source"), f"card missing source cite: {c.get('title')}"


def test_secondary_map_not_in_cards():
    """secondary_map.json is NOT a kb_card and must not be seeded as one."""
    titles = " ".join(c.get("title", "") for c in load_cards())
    assert "primary_keywords" not in titles
    for c in load_cards():
        assert "primary_keywords" not in (c.get("data") or {})


def test_load_secondary_map_shape():
    smap = load_secondary_map()
    assert len(smap) >= 5
    for entry in smap:
        assert entry["primary_keywords"], entry
        assert entry["secondaries"], entry
        for sec in entry["secondaries"]:
            assert sec["condition"]
            assert sec["rationale"]
            assert sec["dbq"]


def test_rating_criteria_tiers_are_wellformed():
    for c in load_cards():
        if c["card_type"] != "rating_criteria":
            continue
        tiers = (c.get("data") or {}).get("tiers") or []
        assert tiers, f"rating_criteria card without tiers: {c['title']}"
        for t in tiers:
            assert 0 <= int(t["percent"]) <= 100
            assert t["criteria"]


def test_presumptive_cards_have_program_data():
    programs = set()
    for c in load_cards():
        if c["card_type"] != "presumptive":
            continue
        data = c.get("data") or {}
        assert data.get("program")
        assert data.get("conditions")
        assert "qualifying_service" in data
        programs.add(data["program"])
    assert {"pact_burn_pits", "agent_orange", "gulf_war", "gulf_war_infectious",
            "mustard_gas", "camp_lejeune", "radiation", "chronic_one_year",
            "pow", "als"} <= programs


def test_dbq_catalog_loads():
    catalog = load_dbq_catalog()
    assert len(catalog) >= 20
    for entry in catalog:
        assert entry["condition"]
        assert entry["dbq"]
    assert "VA" in dbq_catalog_source()


def test_map_dbq_by_name():
    catalog = load_dbq_catalog()
    assert "Sleep Apnea" in map_dbq("Obstructive sleep apnea", None, catalog)
    assert "Hearing Loss and Tinnitus" in map_dbq("tinnitus", None, catalog)
    assert "Hypertension" in map_dbq("Hypertension", None, catalog)
    assert "Headaches" in map_dbq("Migraine headaches", "neurological", catalog)


def test_map_dbq_falls_back_to_body_system():
    catalog = load_dbq_catalog()
    dbq = map_dbq("Zqxwv unknown condition", "mental", catalog)
    assert dbq is not None and "DBQ" in dbq


def test_map_dbq_unknown_returns_none():
    catalog = load_dbq_catalog()
    assert map_dbq("Zqxwv unknown condition", None, catalog) is None
