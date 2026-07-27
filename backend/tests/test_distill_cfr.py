"""Unit tests for the deterministic eCFR → KB card distiller.

Exercises the parser against small, hand-built eCFR-shaped XML fixtures and
proves the four contract properties:

1. A DC-per-row rating table yields well-formed ``rating_criteria`` cards and
   the tiers parse correctly for a known diagnostic code.
2. A shared "General Rating Formula" (mental-style DC list + formula table, and
   spine-style formula-before-DC-range with a scope note) attaches the right
   verbatim tiers to the right diagnostic codes — and never to out-of-scope DCs.
3. A malformed / cross-reference-only table degrades to a verbatim ``process``
   card and NEVER fabricates a tier; the max-rating ceiling guard degrades an
   over-ceiling card too.
4. Every emitted item validates against the real ``KBRefreshBatch`` Pydantic
   schema, passes the receiver's legal-lane source rules, and passes the router
   host allowlist for criteria items.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.kb import distill_cfr as d
from app.kb.refresh import (
    is_high_trust_criteria_url,
    normalize_rating_item,
    validate_refresh_batch_sources,
)
from app.kb.store import validate_kb_max_ratings
from app.routers.kb_admin import _validate_criteria_sources
from app.schemas import KBRefreshBatch, KBRefreshRatingCriteriaItem

EFF = date(2026, 6, 15)


# ── Fixtures (minimal eCFR-shaped XML) ───────────────────────────────────────
PART4_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DIV5 N="4" TYPE="PART">
  <DIV8 N="4.14" TYPE="SECTION">
    <HEAD>&#xA7; 4.14 Avoidance of pyramiding.</HEAD>
    <P>The evaluation of the same disability under various diagnoses is to be avoided.</P>
  </DIV8>
  <DIV8 N="4.114" TYPE="SECTION">
    <HEAD>&#xA7; 4.114 Schedule of ratings&#x2014;digestive system.</HEAD>
    <DIV><TABLE>
      <THEAD><TR><TH> </TH><TH>Rating</TH></TR></THEAD>
      <TBODY>
        <TR><TD class="left border-right-single">7301 Peritoneum, adhesions of:</TD><TD class="right"/></TR>
        <TR><TD class="left border-right-single primary-indent-hanging-2">Severe; definite partial obstruction shown by X-ray</TD><TD class="right">50</TD></TR>
        <TR><TD class="left border-right-single primary-indent-hanging-2">Moderately severe; partial obstruction manifested by delayed motility</TD><TD class="right">30</TD></TR>
        <TR><TD class="left border-right-single primary-indent-hanging-2">Mild</TD><TD class="right">10</TD></TR>
        <TR><TD class="left border-right-single">7346 Hiatal hernia:</TD><TD class="right"/></TR>
        <TR><TD class="left border-right-single primary-indent-hanging-2">Rate as esophagus, stricture of (DC 7203).</TD><TD class="right"/></TR>
      </TBODY>
    </TABLE></DIV>
  </DIV8>
  <DIV8 N="4.130" TYPE="SECTION">
    <HEAD>&#xA7; 4.130 Schedule of ratings&#x2014;Mental disorders.</HEAD>
    <P>The schedule for rating for mental disorders is set forth as follows:</P>
    <EXTRACT>
      <FP-2>9411 Posttraumatic stress disorder</FP-2>
      <FP-2>9434 Major depressive disorder</FP-2>
      <FP-2>9440 Chronic adjustment disorder</FP-2>
    </EXTRACT>
    <DIV><TABLE>
      <CAPTION><P>General Rating Formula for Mental Disorders</P></CAPTION>
      <THEAD><TR><TH> </TH><TH>Rating</TH></TR></THEAD>
      <TBODY>
        <TR><TD class="left border-right-single">Total occupational and social impairment</TD><TD class="right">100</TD></TR>
        <TR><TD class="left border-right-single">Occupational and social impairment, with deficiencies in most areas</TD><TD class="right">70</TD></TR>
        <TR><TD class="left border-right-single">Reduced reliability and productivity</TD><TD class="right">50</TD></TR>
        <TR><TD class="left border-right-single">Occasional decrease in work efficiency</TD><TD class="right">30</TD></TR>
        <TR><TD class="left border-right-single">Mild or transient symptoms</TD><TD class="right">10</TD></TR>
        <TR><TD class="left border-right-single">A mental condition has been formally diagnosed, but symptoms are not severe enough</TD><TD class="right">0</TD></TR>
      </TBODY>
    </TABLE></DIV>
  </DIV8>
  <DIV8 N="4.71b" TYPE="SECTION">
    <HEAD>&#xA7; 4.71b Schedule of ratings&#x2014;the spine.</HEAD>
    <DIV><TABLE>
      <TBODY>
        <TR><TD class="left">General Rating Formula for Diseases and Injuries of the Spine</TD><TD class="right"/></TR>
        <TR><TD class="left">(For diagnostic codes 5235 to 5237 unless 5243 is evaluated otherwise)</TD><TD class="right"/></TR>
        <TR><TD class="left primary-indent-hanging-1">Unfavorable ankylosis of the entire spine</TD><TD class="right">100</TD></TR>
        <TR><TD class="left primary-indent-hanging-1">Forward flexion of the thoracolumbar spine 30 degrees or less</TD><TD class="right">40</TD></TR>
        <TR><TD class="left primary-indent-hanging-1">Forward flexion greater than 30 degrees but not greater than 60 degrees</TD><TD class="right">20</TD></TR>
        <TR><TD class="left primary-indent-hanging-1">Forward flexion greater than 60 degrees but not greater than 85 degrees</TD><TD class="right">10</TD></TR>
        <TR><TD class="left">5235 Vertebral fracture or dislocation</TD><TD class="right"/></TR>
        <TR><TD class="left">5236 Sacroiliac injury and weakness</TD><TD class="right"/></TR>
        <TR><TD class="left">5237 Lumbosacral or cervical strain</TD><TD class="right"/></TR>
        <TR><TD class="left">5244 Traumatic paralysis, complete:</TD><TD class="right"/></TR>
        <TR><TD class="left primary-indent-hanging-1">Quadriplegia: Rate under diagnostic code 5110.</TD><TD class="right"/></TR>
      </TBODY>
    </TABLE></DIV>
  </DIV8>
</DIV5>
"""

PART3_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DIV5 N="3" TYPE="PART">
  <DIV8 N="3.303" TYPE="SECTION">
    <HEAD>&#xA7; 3.303 Principles relating to service connection.</HEAD>
    <P>Service connection connotes many factors but basically it means that the facts establish a particular injury or disease was incurred in service.</P>
  </DIV8>
  <DIV8 N="3.307" TYPE="SECTION">
    <HEAD>&#xA7; 3.307 Presumptive service connection for chronic diseases.</HEAD>
    <P>A chronic disease may be presumed to have been incurred in service if it became manifest to a compensable degree within the applicable period.</P>
  </DIV8>
  <DIV8 N="3.999" TYPE="SECTION">
    <HEAD>&#xA7; 3.999 Not a curated section.</HEAD>
    <P>This administrative section is not in the curated allow-list.</P>
  </DIV8>
</DIV5>
"""


@pytest.fixture()
def part4_path(tmp_path):
    p = tmp_path / "part4.xml"
    p.write_text(PART4_XML, encoding="utf-8")
    return p


@pytest.fixture()
def part3_path(tmp_path):
    p = tmp_path / "part3.xml"
    p.write_text(PART3_XML, encoding="utf-8")
    return p


@pytest.fixture()
def part4_items(part4_path, monkeypatch):
    # No vendor ceilings by default so the parser output is tested on its own.
    monkeypatch.setattr(d, "_max_ratings_ceilings", lambda: {})
    return d.distill_part4(part4_path, EFF)


def _by_dc(items):
    return {it["diagnostic_code"]: it for it in items if it.get("diagnostic_code")}


# ── 1. DC-per-row table ──────────────────────────────────────────────────────
def test_dc_per_row_tiers_parse(part4_items):
    card = _by_dc(part4_items)["7301"]
    assert card["content_kind"] == "criteria"
    assert card["affects_advice"] is True
    assert card["body_system"] == "digestive"
    assert card["diagnostic_code"] == "7301"
    tiers = card["data"]["tiers"]
    assert [t["percent"] for t in tiers] == [50, 30, 10]
    # verbatim criterion text, not paraphrased
    assert tiers[0]["criteria"] == "Severe; definite partial obstruction shown by X-ray"
    assert card["source"] == "38 CFR §4.114, DC 7301"
    assert card["source_url"].startswith("https://www.ecfr.gov/current/title-38")


def test_cross_reference_only_dc_degrades_to_process(part4_items):
    # 7346 is "Rate as esophagus, stricture of (DC 7203)" — no tiers of its own.
    assert "7346" not in _by_dc(part4_items)
    refs = [
        it
        for it in part4_items
        if it["content_kind"] == "explainer" and "7346" in it["title"]
    ]
    assert refs, "cross-reference DC must become a verbatim process card"
    assert refs[0]["affects_advice"] is False
    assert "tiers" not in (refs[0]["data"] or {})  # never fabricate a tier


# ── 2. Shared formulas ───────────────────────────────────────────────────────
def test_mental_general_formula_fans_out_per_dc(part4_items):
    by = _by_dc(part4_items)
    for dc in ("9411", "9434", "9440"):
        assert dc in by, f"mental DC {dc} should get the general formula"
        assert [t["percent"] for t in by[dc]["data"]["tiers"]] == [100, 70, 50, 30, 10, 0]
        assert by[dc]["body_system"] == "mental"
    # verbatim shared criterion
    assert (
        by["9411"]["data"]["tiers"][0]["criteria"]
        == "Total occupational and social impairment"
    )


def test_spine_formula_scope_range(part4_items):
    by = _by_dc(part4_items)
    # in-scope 5235–5237 get the spine formula
    for dc in ("5235", "5236", "5237"):
        assert [t["percent"] for t in by[dc]["data"]["tiers"]] == [100, 40, 20, 10]
    # 5244 is out of the "(For diagnostic codes 5235 to 5237)" scope AND a
    # cross-reference — it must NOT inherit the formula's tiers.
    assert "5244" not in by


# ── 3. Degrade paths (never fabricate) ───────────────────────────────────────
def test_section_without_table_is_a_process_rule_card(part4_items):
    rule = [it for it in part4_items if "4.14 Avoidance of pyramiding" in it["title"]]
    assert len(rule) == 1
    assert rule[0]["content_kind"] == "explainer"
    assert rule[0]["data"]["distill"]["kind"] == "rule"
    assert "pyramiding" in rule[0]["content"].lower()


def test_no_rating_card_has_an_empty_or_fabricated_tier_list(part4_items):
    for it in part4_items:
        if it["content_kind"] == "criteria":
            tiers = it["data"]["tiers"]
            assert tiers, "a criteria card must carry at least one parsed tier"
            for t in tiers:
                assert isinstance(t["percent"], int)
                assert t["criteria"].strip()


def test_over_ceiling_card_degrades_to_process(part4_path, monkeypatch):
    # Force a ceiling below 7301's parsed 50% top tier → must degrade to prose.
    monkeypatch.setattr(d, "_max_ratings_ceilings", lambda: {"7301": 30})
    items = d.distill_part4(part4_path, EFF)
    assert "7301" not in _by_dc(items)
    degraded = [
        it for it in items if it["content_kind"] == "explainer" and "7301" in it["title"]
    ]
    assert degraded, "over-ceiling DC must degrade to a process card"
    dz = degraded[0]["data"]["distill"]
    assert dz["kind"] == "rating_ref"
    assert "exceeds" in dz["degraded"]
    assert "tiers" not in (degraded[0]["data"] or {})


# ── Part 3 ───────────────────────────────────────────────────────────────────
def test_part3_process_and_presumptive_classification(part3_path):
    items = d.distill_part3(part3_path, EFF)
    kinds = {it["title"].split()[1]: it["data"]["distill"]["kind"] for it in items}
    assert kinds.get("3.303") == "process"
    assert kinds.get("3.307") == "presumptive"
    # a non-allow-listed admin section is not emitted
    assert all("3.999" not in it["title"] for it in items)
    for it in items:
        assert it["content_kind"] == "explainer"
        assert it["affects_advice"] is False


def test_part3_all_sections_mode(part3_path):
    items = d.distill_part3(part3_path, EFF, all_sections=True)
    titles = " ".join(it["title"] for it in items)
    assert "3.999" in titles  # allow-list bypassed


# ── 4. Every emitted item validates end-to-end ───────────────────────────────
def test_every_item_validates_against_schema_and_allowlist(part4_path, part3_path, monkeypatch):
    monkeypatch.setattr(d, "_max_ratings_ceilings", lambda: {})
    items = d.distill_part4(part4_path, EFF) + d.distill_part3(part3_path, EFF)
    batches = d.build_batches(items, batch_prefix="test-38cfr", chunk_size=10)
    assert batches
    seen_criteria = seen_process = 0
    for raw in batches:
        model = KBRefreshBatch.model_validate(raw)  # real Pydantic shape
        validate_refresh_batch_sources(model)       # receiver legal-lane rules
        _validate_criteria_sources(model)            # router host allowlist
        for item in model.items:
            assert isinstance(item, KBRefreshRatingCriteriaItem)
            normalized = normalize_rating_item(item, model)  # must not raise
            if item.content_kind == "criteria":
                seen_criteria += 1
                assert normalized["card_type"] == "rating_criteria"
                assert is_high_trust_criteria_url(item.source_url)
            else:
                seen_process += 1
                assert normalized["card_type"] == "process"
    assert seen_criteria and seen_process


def test_criteria_items_pass_max_rating_ceiling(part4_path, part3_path, monkeypatch):
    monkeypatch.setattr(d, "_max_ratings_ceilings", lambda: {})
    items = d.distill_part4(part4_path, EFF) + d.distill_part3(part3_path, EFF)
    batches = d.build_batches(items, batch_prefix="test-38cfr", chunk_size=10)
    proposed = []
    for raw in batches:
        model = KBRefreshBatch.model_validate(raw)
        for item in model.items:
            proposed.append(normalize_rating_item(item, model))
    rating_cards = [c for c in proposed if c["card_type"] == "rating_criteria"]
    # Uses the REAL vendored VA max-ratings dataset — fixture DCs must not exceed it.
    assert validate_kb_max_ratings(cards=rating_cards) == []


def test_criteria_host_allowlist_rejects_non_authoritative(part4_path, monkeypatch):
    monkeypatch.setattr(d, "_max_ratings_ceilings", lambda: {})
    items = d.distill_part4(part4_path, EFF)
    criteria = next(it for it in items if it["content_kind"] == "criteria")
    bad = dict(criteria, source_url="https://example.com/not-ecfr")
    batch = d.build_batches([bad], batch_prefix="bad")[0]
    model = KBRefreshBatch.model_validate(batch)
    with pytest.raises(Exception):
        _validate_criteria_sources(model)


def test_summary_counts(part4_path, monkeypatch):
    monkeypatch.setattr(d, "_max_ratings_ceilings", lambda: {})
    items = d.distill_part4(part4_path, EFF)
    summary = d.summarize(items)
    assert summary["_total"] == len(items)
    assert summary["rating_criteria"] == summary["_rating_criteria_cards"]
    assert summary["_rating_criteria_cards"] >= 5  # 7301 + 9411/9434/9440 + spine DCs
