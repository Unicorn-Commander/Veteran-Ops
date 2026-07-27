"""The specialist firm (app/firm/): the Specialist framework, the four graduated
seeds, the theory-origination layer, the orchestrator (dedupe/rank), and the
adversarial reviewer.

Legal-lane asserted throughout. The FLOOR invariant still holds: a deterministic
FLOOR finding surfaces ONLY when its seed fires (the LLM never originates one),
enrichment always falls back to the seed note, and a lane-violating floor finding
reverts or is removed. Phase 2b adds a deliberate, config-GATED exception ABOVE the
floor — the theory layer — where the model MAY originate a cited, confidence-tagged
opinion that must pass the reviewer's well-foundedness gates (Check A + Check B).
The "never originates" rule now scopes to the floor, not the theory layer.
"""

from __future__ import annotations

import json
import re
import uuid

import pytest

from app.config import settings
from app.llm.gateway import gateway as _gateway
from app.firm.base import Finding, confidence_for_level
from app.firm.context import VeteranDossier
from app.firm.orchestrator import _rank_key, run_firm
from app.firm.reviewer import review
from app.firm.specialists import (
    CpExamSpecialist,
    NexusEvidenceSpecialist,
    PresumptivesSpecialist,
    PyramidingSpecialist,
    SecondariesSpecialist,
    SmcSpecialist,
    TdiuSpecialist,
    TheorySpecialist,
)
from app.strategy.rating_rules import (
    find_pyramiding_cautions,
    find_secondary_opportunities,
    find_underrating_opportunities,
)

_PROMISE = re.compile(
    r"\b(you will (?:get|receive|be granted|qualify)|guarantee|guaranteed|"
    r"entitled to \d|100% chance|is service-connected|qualif(?:y|ies) for)\b",
    re.IGNORECASE,
)


def _cond(**kw):
    base = dict(id=str(uuid.uuid4()), name="X", claim_type="direct", status="considering",
                va_status="unknown", current_rating=None, target_rating=None,
                diagnostic_code=None, band="early", missing=[], has_have_evidence=False)
    base.update(kw)
    return base


def _dossier(conditions, *, current_combined=None, profile=None):
    return VeteranDossier(uid=str(uuid.uuid4()), conditions=conditions,
                          current_combined=current_combined, profile=profile,
                          generated_at="2026-07-09T00:00:00+00:00")


def _fake_complete(text):
    async def _c(messages, **kw):  # noqa: ANN001
        return text
    return _c


# ── Finding value object ─────────────────────────────────────────────────────

def test_finding_to_render_overlays_body_on_seed():
    seed = {"key": "secondary:x", "kind": "secondary", "title": "T", "body": "SEED",
            "reg": "38 CFR §3.310", "primary": ["CFS"], "secondary": "Anxiety",
            "needs_nexus": True, "severity": "high"}
    f = Finding(specialist="secondaries", kind="secondary", key="secondary:x", title="T",
                body="WARMER", severity="high", seed=seed, det_body="SEED")
    r = f.to_render()
    assert r["body"] == "WARMER"           # enriched body wins
    assert r["reg"] == "38 CFR §3.310"     # every other seed field preserved
    assert r["needs_nexus"] is True and r["severity"] == "high"


def test_finding_revert_restores_seed_note():
    f = Finding(specialist="s", kind="secondary", key="k", title="T",
                body="WARMER but wrong", det_body="SAFE SEED", enriched=True)
    f.revert_to_deterministic("bad")
    assert f.body == "SAFE SEED" and f.enriched is False and f.review_note == "bad"


def test_finding_roundtrip_dict():
    f = Finding(specialist="s", kind="underrating", key="k", title="T", body="B",
                det_body="B", regs=["r"], needs=["nexus"])
    assert Finding.from_dict(f.to_dict()).to_dict() == f.to_dict()


# ── Graduated seeds match the deterministic finders exactly ───────────────────

def test_secondaries_specialist_seed_matches_finder():
    cfs = _cond(name="ME/CFS", va_status="service_connected", current_rating=60,
                diagnostic_code="6354", band="complete")
    anxiety = _cond(name="Anxiety disorder", va_status="denied")
    d = _dossier([cfs, anxiety], current_combined=60)
    assert SecondariesSpecialist().seed(d) == find_secondary_opportunities(d.conditions)
    assert SecondariesSpecialist().seed(d), "expected a secondary seed to fire"


def test_pyramiding_specialist_seed_is_cautions_plus_underrating():
    # PTSD + depression → a §4.130 mental-health pyramiding caution; the knee →
    # an Esteban under-rating opportunity. (CFS/fibromyalgia is deliberately NO
    # LONGER a pyramiding pair — it is now an under-rating opportunity — so the
    # pyramiding case here uses the mental-health group.)
    ptsd = _cond(name="PTSD", va_status="service_connected", current_rating=50,
                 diagnostic_code="9411", band="complete")
    depression = _cond(name="Major depressive disorder", va_status="denied", band="early")
    knee = _cond(name="Right knee instability", va_status="service_connected",
                 current_rating=10, diagnostic_code="5257", band="complete")
    d = _dossier([ptsd, depression, knee], current_combined=50)
    expected = find_pyramiding_cautions(d.conditions) + find_underrating_opportunities(d.conditions)
    assert PyramidingSpecialist().seed(d) == expected
    kinds = {s["kind"] for s in PyramidingSpecialist().seed(d)}
    assert kinds == {"pyramiding", "underrating"}


def test_tdiu_specialist_wraps_screen_when_it_fires():
    cfs = _cond(name="CFS", va_status="service_connected", current_rating=60, band="complete")
    seeds = TdiuSpecialist().seed(_dossier([cfs], current_combined=60))
    assert len(seeds) == 1
    s = seeds[0]
    assert s["kind"] == "tdiu" and s["key"] == "tdiu" and s["severity"] == "high"
    assert s["eligible_schedular"] is True and "21-8940" in s["form"]


def test_tdiu_specialist_empty_below_threshold():
    c = _cond(name="Tinnitus", va_status="service_connected", current_rating=10)
    assert TdiuSpecialist().seed(_dossier([c], current_combined=10)) == []


def test_smc_specialist_seeds_smc_s_when_100_plus_60_remainder():
    """100% + independent 60% → educational SMC-S housebound screen (not entitlement)."""
    primary = _cond(name="PTSD", va_status="service_connected", current_rating=100,
                    diagnostic_code="9411", band="complete")
    other = _cond(name="Bilateral knee", va_status="service_connected", current_rating=60,
                  band="complete")
    seeds = SmcSpecialist().seed(_dossier([primary, other], current_combined=100))
    assert seeds
    keys = {s["key"] for s in seeds}
    assert "smc_education:smc_s" in keys
    smc_s = next(s for s in seeds if s["key"] == "smc_education:smc_s")
    assert smc_s["kind"] == "smc_education"
    assert smc_s["severity"] == "high"
    body_l = smc_s["body"].lower()
    assert "3.350" in smc_s["reg"] or "§3.350" in smc_s["body"]
    assert "vso" in body_l
    # Educational lane — never entitlement.
    assert "you qualify for smc" not in body_l
    assert "entitled to smc" not in body_l
    # TDIU is owned by TdiuSpecialist — never re-surface here.
    assert all(s.get("smc_flag_key") != "tdiu" for s in seeds)


def test_smc_specialist_empty_without_ratings():
    c = _cond(name="Tinnitus", va_status="considering", current_rating=None)
    assert SmcSpecialist().seed(_dossier([c])) == []


def test_smc_specialist_no_smc_s_below_remainder_threshold():
    """100% alone (no independent 60% remainder) must not seed smc_s."""
    only = _cond(name="PTSD", va_status="service_connected", current_rating=100)
    seeds = SmcSpecialist().seed(_dossier([only], current_combined=100))
    assert not any(s.get("smc_flag_key") == "smc_s" for s in seeds)


def test_presumptives_specialist_no_profile_no_seed():
    assert PresumptivesSpecialist().seed(_dossier([_cond(name="X")])) == []


def test_cp_exam_specialist_seeds_per_condition():
    knee = _cond(name="Right knee strain", band="building",
                 missing=["Current diagnosis"], body_system="musculoskeletal")
    d = _dossier([knee])
    seeds = CpExamSpecialist().seed(d)
    assert len(seeds) == 1
    s = seeds[0]
    assert s["kind"] == "cp_exam_prep"
    assert s["condition_name"] == "Right knee strain"
    assert s["open_route"] == "/cp-companion"
    assert "still_needed" in s
    # Educational lane — never a guaranteed rating percentage.
    assert "you will get" not in s["body"].lower()
    assert "%" not in s["title"] or "X%" not in s["body"]


def test_cp_exam_specialist_empty_without_conditions():
    assert CpExamSpecialist().seed(_dossier([])) == []


def test_nexus_evidence_specialist_seeds_when_nexus_missing():
    c = _cond(
        name="Lumbar strain",
        claim_type="direct",
        band="early",
        missing=["Medical nexus opinion", "Current diagnosis"],
    )
    seeds = NexusEvidenceSpecialist().seed(_dossier([c]))
    assert len(seeds) == 1
    s = seeds[0]
    assert s["kind"] == "nexus_gap"
    assert s["open_route"] == "/nexus"
    assert s["needs_nexus"] is True
    assert s["severity"] == "high"
    assert "nexus" in s["body"].lower()


def test_nexus_evidence_specialist_skips_when_no_nexus_gap():
    c = _cond(name="Tinnitus", claim_type="direct", band="complete", missing=[])
    assert NexusEvidenceSpecialist().seed(_dossier([c])) == []


def test_nexus_evidence_specialist_skips_presumptive_claim_type():
    c = _cond(
        name="Hypertension",
        claim_type="presumptive",
        missing=["Medical nexus opinion"],
    )
    assert NexusEvidenceSpecialist().seed(_dossier([c])) == []


# ── Graduation rule: no seed → no finding; the LLM never originates ───────────

@pytest.mark.asyncio
async def test_no_seed_no_finding():
    # No granted primary → secondaries cannot fire, even though the LLM exists.
    d = _dossier([_cond(name="Anxiety disorder", va_status="denied")])
    assert await SecondariesSpecialist().find(None, d) == []


# ── explain(): enrichment + always-safe fallback ─────────────────────────────

@pytest.mark.asyncio
async def test_secondary_enrichment_flows_when_clean(monkeypatch):
    monkeypatch.setattr(_gateway, "complete",
                        _fake_complete('{"body": "A warmer, safe rewrite grounded in §3.310."}'))
    cfs = _cond(name="ME/CFS", va_status="service_connected", current_rating=60,
                diagnostic_code="6354", band="complete")
    anxiety = _cond(name="Anxiety disorder", va_status="denied")
    findings = await SecondariesSpecialist().find(None, _dossier([cfs, anxiety], current_combined=60))
    assert len(findings) == 1
    f = findings[0]
    assert f.enriched is True
    assert f.body == "A warmer, safe rewrite grounded in §3.310."
    assert f.confidence == 1.0  # seed fired; the LLM never changes this
    assert not _PROMISE.search(f.body)


@pytest.mark.asyncio
async def test_secondary_enrichment_falls_back_on_lane_violation(monkeypatch):
    monkeypatch.setattr(_gateway, "complete",
                        _fake_complete('{"body": "You will qualify for 70% and it is service-connected."}'))
    cfs = _cond(name="ME/CFS", va_status="service_connected", current_rating=60,
                diagnostic_code="6354", band="complete")
    anxiety = _cond(name="Anxiety disorder", va_status="denied")
    findings = await SecondariesSpecialist().find(None, _dossier([cfs, anxiety], current_combined=60))
    f = findings[0]
    assert f.enriched is False                 # rejected by the local lane gate
    assert f.body == f.det_body                # fell back to the deterministic seed note
    assert not _PROMISE.search(f.body)


@pytest.mark.asyncio
async def test_deterministic_specialist_never_calls_model(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("deterministic specialist must not call the model")
    monkeypatch.setattr(_gateway, "complete", _boom)
    knee = _cond(name="Right knee instability", va_status="service_connected",
                 current_rating=10, diagnostic_code="5257", band="complete")
    findings = await PyramidingSpecialist().find(None, _dossier([knee], current_combined=10))
    assert findings and all(f.enriched is False for f in findings)


# ── The adversarial reviewer ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reviewer_removes_lane_violating_finding():
    # Guaranteed-outcome phrasing in BOTH the enriched and the deterministic body =
    # no safe fallback → the reviewer drops it entirely. ("entitled to" /
    # "service-connected" are now legitimate analysis and would be KEPT.)
    bad = "You will be granted 70% and will receive back pay."
    f = Finding(specialist="x", kind="secondary", key="k", title="T",
                body=bad, det_body=bad, enriched=False)  # no safe version at all
    assert await review([f], None) == []


@pytest.mark.asyncio
async def test_reviewer_keeps_clean_deterministic_finding():
    f = Finding(specialist="x", kind="underrating", key="k", title="T",
                body="A calm, reg-grounded educational note (§4.14).", det_body="same",
                enriched=False)
    kept = await review([f], None)
    assert len(kept) == 1 and kept[0].reviewed is True


@pytest.mark.asyncio
async def test_reviewer_reverts_ungrounded_enrichment_to_seed():
    # Enriched body invents a percentage the seed note never had → revert, keep.
    f = Finding(specialist="x", kind="secondary", key="k", title="T",
                body="This may relate under §3.310 at the 90% level.",
                det_body="This may relate under §3.310.", enriched=True)
    kept = await review([f], None)
    assert len(kept) == 1
    assert kept[0].body == "This may relate under §3.310."  # reverted to seed
    assert kept[0].enriched is False and kept[0].reviewed is True


@pytest.mark.asyncio
async def test_reviewer_reverts_when_llm_unavailable():
    # Clean, grounded enrichment but no reviewer LLM (db=None) → conservative revert.
    f = Finding(specialist="x", kind="secondary", key="k", title="T",
                body="A warmer restatement of the same §3.310 theory.",
                det_body="The §3.310 theory.", enriched=True)
    kept = await review([f], None)
    assert len(kept) == 1 and kept[0].body == "The §3.310 theory."


@pytest.mark.asyncio
async def test_reviewer_approves_grounded_enrichment_with_positive_verdict(monkeypatch):
    async def _cards(db, query, **kw):  # noqa: ANN001
        return []
    monkeypatch.setattr("app.kb.store.retrieve_cards", _cards)
    monkeypatch.setattr(_gateway, "complete",
                        _fake_complete('{"supported": true, "lane_ok": true, "note": "faithful"}'))
    f = Finding(specialist="x", kind="secondary", key="k", title="T",
                body="A warmer restatement of the same §3.310 theory.",
                det_body="The §3.310 theory.", enriched=True)
    kept = await review([f], object())  # non-None db so the LLM path runs
    assert len(kept) == 1
    assert kept[0].enriched is True and kept[0].body.startswith("A warmer")


# ── Orchestrator: dedupe + rank ──────────────────────────────────────────────

def test_rank_key_orders_high_severity_then_confidence():
    hi = Finding(specialist="s", kind="secondary", key="a", title="", body="", severity="high")
    med = Finding(specialist="s", kind="underrating", key="b", title="", body="", severity="medium")
    assert _rank_key(hi) < _rank_key(med)


@pytest.mark.asyncio
async def test_run_firm_dedupes_and_ranks_deterministic_findings():
    # A granted knee (→ underrating, medium) + a single SC disability at 60%
    # (→ TDIU, high). No secondary/pyramiding seed fires, so no model is needed.
    knee = _cond(name="Right knee instability", va_status="service_connected",
                 current_rating=10, diagnostic_code="5257", band="complete")
    cfs = _cond(name="CFS", va_status="service_connected", current_rating=60, band="complete")
    findings = await run_firm(_dossier([knee, cfs], current_combined=60), None)
    keys = [f.key for f in findings]
    assert len(keys) == len(set(keys)), "findings must be deduped by key"
    assert all(f.reviewed for f in findings), "orchestrator drops unreviewed findings"
    kinds = [f.kind for f in findings]
    assert "tdiu" in kinds and "underrating" in kinds
    # high-severity TDIU ranks before the medium under-rating finding.
    assert kinds.index("tdiu") < kinds.index("underrating")


@pytest.mark.asyncio
async def test_run_firm_only_filter_restricts_roster():
    knee = _cond(name="Right knee instability", va_status="service_connected",
                 current_rating=10, diagnostic_code="5257", band="complete")
    cfs = _cond(name="CFS", va_status="service_connected", current_rating=60, band="complete")
    findings = await run_firm(_dossier([knee, cfs], current_combined=60), None, only=["tdiu"])
    assert findings and all(f.specialist == "tdiu" for f in findings)


# ── Phase 2b: the theory layer ABOVE the floor ───────────────────────────────
# The FLOOR is deterministic and never changes; the theory layer is a config-gated
# origination pass where the model MAY propose a cited, confidence-tagged opinion —
# but the reviewer is the VETERAN-SAFETY control and FAILS CLOSED: a theory survives
# ONLY if its citations RE-RESOLVE against the veteran's record, its prose facts are
# grounded, and the FULL record-aware panel unanimously verifies it.

_UID = "11111111-1111-1111-1111-111111111111"


class _Card:
    """A minimal KB-card double (id/title/content/source), enough to ground a theory."""
    def __init__(self, id, *, title="§3.310 secondary service connection",
                 content="Secondary service connection under 38 CFR 3.310: a condition "
                         "caused or aggravated by a service-connected disability.",
                 source="38 CFR §3.310", diagnostic_code=None, card_type="rule"):
        self.id = id; self.title = title; self.content = content
        self.source = source; self.diagnostic_code = diagnostic_code; self.card_type = card_type


class _Chunk:
    """A minimal veteran-record chunk double (id/content)."""
    def __init__(self, id, content="Progress note: chronic low-back pain with new "
                                    "depressive symptoms and poor sleep."):
        self.id = id; self.content = content


def _patch_theory_resolution(monkeypatch, *, cards=None, chunks=None):
    """Wire the reviewer's independent citation RE-RESOLUTION to fakes that return only
    the rows whose ids were actually requested — so a stale/fabricated id resolves to
    nothing (the fail-closed path), exactly like the real DB helpers."""
    _cards = [_Card(id="card-1")] if cards is None else cards
    _chunks = [_Chunk(id="chunk-1")] if chunks is None else chunks

    async def _cby(db, ids):  # noqa: ANN001
        want = {str(i) for i in ids}
        return [c for c in _cards if str(c.id) in want]

    async def _chby(db, uid, ids):  # noqa: ANN001
        want = {str(i) for i in ids}
        return [c for c in _chunks if str(c.id) in want]

    monkeypatch.setattr("app.kb.store.cards_by_ids", _cby)
    monkeypatch.setattr("app.rag.chunks_by_ids", _chby)


def _fake_complete_stateful(replies):
    """A gateway.complete double that returns replies[i] on the i-th call, then the
    last reply forever — lets a test simulate a PARTIAL panel (some lenses unparseable)."""
    calls = {"n": 0}

    async def _c(messages, **kw):  # noqa: ANN001
        i = calls["n"]
        calls["n"] += 1
        return replies[i] if i < len(replies) else replies[-1]
    return _c


def _theory_finding(**kw):
    """A layer='theory' Finding with well-founded defaults (resolvable cites + a uid on
    the seed so re-resolution can run). Override per test. The default body carries no
    year and no multi-word proper noun, so prose-grounding passes trivially."""
    base = dict(
        specialist="theory", kind="secondary", key="theory:x", title="Depression secondary to back",
        body="the record shows chronic back pain with depressive symptoms; this is at least "
             "as likely as not related to service under 38 CFR 3.310.",
        severity="high", layer="theory", confidence_level="at_least_as_likely", confidence=0.50,
        regs=["38 CFR §3.310"], card_ids=["card-1"], evidence_refs=["chunk-1"],
        citations=[{"card_id": "card-1", "chunk_id": "chunk-1", "reg": "38 CFR §3.310"}],
        det_body="", seed={"uid": _UID, "key": "theory:x"},
    )
    base.update(kw)
    return Finding(**base)


_PANEL_OK = '{"supported": true, "lane_ok": true, "note": "well-founded"}'


# ── Origination ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_theorize_noop_when_flag_off(monkeypatch):
    # Default (flag off): TheorySpecialist originates nothing and never calls the model.
    monkeypatch.setattr(settings, "theory_origination_enabled", False)
    def _boom(*a, **k):
        raise AssertionError("theory pass must not run when the flag is off")
    monkeypatch.setattr(_gateway, "complete", _boom)
    d = _dossier([_cond(name="Chronic low-back pain", va_status="service_connected")])
    assert await TheorySpecialist().find(object(), d) == []


@pytest.mark.asyncio
async def test_theory_origination_builds_cited_tagged_framed_finding(monkeypatch):
    monkeypatch.setattr(settings, "theory_origination_enabled", True)
    card, chunk = _Card(id="card-1"), _Chunk(id="chunk-1")

    async def _grounding(self, db, dossier):
        return {"cards": [card], "chunks": [chunk]}
    monkeypatch.setattr(TheorySpecialist, "retrieve_for_theory", _grounding)
    reply = json.dumps({"theories": [{
        "kind": "secondary",
        "title": "Depression secondary to chronic back pain",
        "body": "The record shows chronic back pain and depressive symptoms; under 38 CFR "
                "3.310 a chronic pain condition is a recognized cause of secondary depression, "
                "so this is at least as likely as not related to service.",
        "confidence_level": "at_least_as_likely",
        "citations": [{"card_id": "card-1", "chunk_id": "chunk-1"}],
    }]})
    monkeypatch.setattr(_gateway, "complete", _fake_complete(reply))

    d = _dossier([_cond(name="Chronic low-back pain", va_status="service_connected")])
    findings = await TheorySpecialist().find(object(), d)  # non-None db → theory pass runs
    assert len(findings) == 1
    t = findings[0]
    assert t.layer == "theory"
    assert 0 < t.confidence < 1                       # never the deterministic floor's 1.0
    assert t.confidence_level == "at_least_as_likely"
    assert t.citations and t.citations[0]["card_id"] == "card-1"
    assert t.card_ids == ["card-1"] and t.evidence_refs == ["chunk-1"]
    assert t.seed.get("uid") == d.uid                # uid rides on the seed for re-resolution
    assert t.body.startswith("[Assessment (at least as likely as not)")  # server-side framing (MEDIUM)
    assert not _PROMISE.search(t.body)


@pytest.mark.asyncio
async def test_theory_origination_drops_fabricated_citation(monkeypatch):
    # A theory citing an id NOT in the grounding is unfounded — origination drops it.
    monkeypatch.setattr(settings, "theory_origination_enabled", True)
    card, chunk = _Card(id="card-1"), _Chunk(id="chunk-1")

    async def _grounding(self, db, dossier):
        return {"cards": [card], "chunks": [chunk]}
    monkeypatch.setattr(TheorySpecialist, "retrieve_for_theory", _grounding)
    reply = json.dumps({"theories": [{
        "kind": "secondary", "title": "Invented",
        "body": "This is at least as likely as not related to service under 38 CFR 3.310.",
        "confidence_level": "at_least_as_likely",
        "citations": [{"card_id": "card-DOES-NOT-EXIST", "chunk_id": "chunk-NOPE"}],
    }]})
    monkeypatch.setattr(_gateway, "complete", _fake_complete(reply))
    d = _dossier([_cond(name="Chronic low-back pain", va_status="service_connected")])
    assert await TheorySpecialist().find(object(), d) == []


@pytest.mark.asyncio
async def test_theory_origination_drops_guaranteed_outcome(monkeypatch):
    monkeypatch.setattr(settings, "theory_origination_enabled", True)
    card, chunk = _Card(id="card-1"), _Chunk(id="chunk-1")

    async def _grounding(self, db, dossier):
        return {"cards": [card], "chunks": [chunk]}
    monkeypatch.setattr(TheorySpecialist, "retrieve_for_theory", _grounding)
    reply = json.dumps({"theories": [{
        "kind": "secondary", "title": "Overpromise",
        "body": "You will be granted this claim — it is guaranteed.",
        "confidence_level": "more_likely_than_not",
        "citations": [{"card_id": "card-1", "chunk_id": "chunk-1"}],
    }]})
    monkeypatch.setattr(_gateway, "complete", _fake_complete(reply))
    d = _dossier([_cond(name="Chronic low-back pain", va_status="service_connected")])
    assert await TheorySpecialist().find(object(), d) == []


# ── Reviewer: deterministic gates (Check A / Check B) ────────────────────────

@pytest.mark.asyncio
async def test_reviewer_removes_uncited_theory():
    # Check A: an originated theory with no citations has no safe floor → removed
    # (fails before any DB re-resolution).
    f = _theory_finding(regs=[], card_ids=[], evidence_refs=[], citations=[])
    assert await review([f], object()) == []


@pytest.mark.asyncio
async def test_check_a_rejects_theory_missing_law_or_record_cite():
    # Missing the RECORD cite (law only) → removed.
    law_only = _theory_finding(evidence_refs=[], citations=[{"card_id": "card-1", "reg": "38 CFR §3.310"}])
    assert await review([law_only], object()) == []
    # Missing the LAW cite (record only) → removed.
    rec_only = _theory_finding(regs=[], card_ids=[], citations=[{"chunk_id": "chunk-1"}])
    assert await review([rec_only], object()) == []


@pytest.mark.asyncio
async def test_check_b_rejects_untagged_theory():
    # Well-cited but no confidence tag → removed.
    assert await review([_theory_finding(confidence_level=None)], object()) == []


# ── Reviewer: fail-closed re-resolution + prose grounding + panel ────────────

@pytest.mark.asyncio
async def test_reviewer_unavailable_drops_theory_db_none(monkeypatch):
    # CRITICAL-2: no DB means citations cannot re-resolve → FAIL CLOSED (drop), never keep.
    # An APPROVING gateway is wired so the db=None gate is the ONLY thing that can drop it.
    _patch_theory_resolution(monkeypatch)
    monkeypatch.setattr(_gateway, "complete", _fake_complete(_PANEL_OK))
    assert await review([_theory_finding()], None) == []


@pytest.mark.asyncio
async def test_reviewer_unavailable_drops_theory_when_gateway_down(monkeypatch):
    # CRITICAL-2 in prod: cites re-resolve and prose grounds, but the panel LLM is down
    # (every lens raises) → panel None → FAIL CLOSED (drop).
    _patch_theory_resolution(monkeypatch)
    def _boom(*a, **k):
        raise RuntimeError("gateway down")
    monkeypatch.setattr(_gateway, "complete", _boom)
    assert await review([_theory_finding()], object()) == []


@pytest.mark.asyncio
async def test_partial_panel_drops_theory(monkeypatch):
    # HIGH-1: only one lens returns a parseable verdict; the panel is incomplete →
    # FAIL CLOSED (never approve on fewer than the full three-lens panel).
    _patch_theory_resolution(monkeypatch)
    monkeypatch.setattr(_gateway, "complete",
                        _fake_complete_stateful([_PANEL_OK, "not json", "not json"]))
    assert await review([_theory_finding()], object()) == []


@pytest.mark.asyncio
async def test_stale_citation_id_fails_reresolution(monkeypatch):
    # HIGH-2: the cited chunk id no longer resolves to a veteran record (stale/wrong) →
    # re-resolution fails → dropped, even though the panel would have approved.
    _patch_theory_resolution(monkeypatch, chunks=[_Chunk(id="chunk-OTHER")])
    monkeypatch.setattr(_gateway, "complete", _fake_complete(_PANEL_OK))
    assert await review([_theory_finding()], object()) == []


@pytest.mark.asyncio
async def test_fabricated_prose_fact_theory_dropped(monkeypatch):
    # CRITICAL-1: a fabricated prose service-event (real cites, NO %/DC number) whose
    # asserted fact is absent from the cited record → dropped by prose grounding, even
    # with an APPROVING panel. The year 1985 is not in the veteran's record excerpt.
    _patch_theory_resolution(monkeypatch)  # record excerpt mentions back pain, not Camp Lejeune/1985
    monkeypatch.setattr(_gateway, "complete", _fake_complete(_PANEL_OK))
    fabricated = _theory_finding(
        body="the veteran's service records document Camp Lejeune stationing in 1985 and "
             "burn-pit exposure, so this is at least as likely as not related to service.",
    )
    assert await review([fabricated], object()) == []


@pytest.mark.asyncio
async def test_well_founded_theory_survives_full_panel(monkeypatch):
    # The happy path: cites re-resolve, prose grounds, the FULL panel unanimously approves.
    _patch_theory_resolution(monkeypatch)
    monkeypatch.setattr(_gateway, "complete", _fake_complete(_PANEL_OK))
    kept = await review([_theory_finding()], object())
    assert len(kept) == 1
    t = kept[0]
    assert t.layer == "theory" and t.reviewed is True
    assert 0 < t.confidence < 1 and t.citations


@pytest.mark.asyncio
async def test_reviewer_downgrades_overconfident_theory(monkeypatch):
    _patch_theory_resolution(monkeypatch)
    # The full panel supports the theory but judges it over-stated (a lower register level).
    monkeypatch.setattr(_gateway, "complete", _fake_complete(
        '{"supported": true, "lane_ok": true, "confidence_level": "less_likely_than_not", '
        '"note": "evidence is thinner than claimed"}'))
    f = _theory_finding(confidence_level="more_likely_than_not",
                        confidence=confidence_for_level("more_likely_than_not"))
    kept = await review([f], object())
    assert len(kept) == 1
    t = kept[0]
    assert t.confidence_level == "less_likely_than_not"   # downgraded, not removed
    assert t.confidence == pytest.approx(confidence_for_level("less_likely_than_not"))
    assert "downgraded" in (t.review_note or "")


@pytest.mark.asyncio
async def test_reviewer_does_not_raise_confidence_of_theory(monkeypatch):
    _patch_theory_resolution(monkeypatch)
    # Panel offers a HIGHER level than claimed — the reviewer must never raise it.
    monkeypatch.setattr(_gateway, "complete", _fake_complete(
        '{"supported": true, "lane_ok": true, "confidence_level": "more_likely_than_not", "note": "ok"}'))
    f = _theory_finding(confidence_level="at_least_as_likely",
                        confidence=confidence_for_level("at_least_as_likely"))
    kept = await review([f], object())
    assert len(kept) == 1
    assert kept[0].confidence_level == "at_least_as_likely"  # unchanged (never raised)


@pytest.mark.asyncio
async def test_reviewer_removes_theory_the_panel_rejects(monkeypatch):
    _patch_theory_resolution(monkeypatch)
    # Full panel, but the evidence lens dissents (unanimity required) → removed.
    monkeypatch.setattr(_gateway, "complete", _fake_complete(
        '{"supported": false, "lane_ok": true, "note": "leans on a record fact not shown"}'))
    assert await review([_theory_finding()], object()) == []


@pytest.mark.asyncio
async def test_reviewer_removes_guaranteed_outcome_theory():
    # A theory body that guarantees an outcome trips the lane gate → removed (before any DB).
    f = _theory_finding(body="you will be granted 70% and will receive back pay.")
    assert await review([f], object()) == []


# ── HIGH-3: enriched-floor SC assertion (the fix must be what distinguishes) ──

@pytest.mark.asyncio
async def test_enriched_floor_uncited_sc_assertion_reverts_to_seed(monkeypatch):
    # HIGH-3, mutation-honest: with a NON-None db and an APPROVING reviewer, an enriched
    # FLOOR body that asserts SC but carries NO citations must still revert to its safe
    # deterministic seed — proving Check A (not merely LLM-unavailability) does the work.
    async def _cards(db, query, **kw):  # noqa: ANN001
        return []
    monkeypatch.setattr("app.kb.store.retrieve_cards", _cards)
    monkeypatch.setattr(_gateway, "complete", _fake_complete(_PANEL_OK))  # reviewer APPROVES
    safe = "Depression may be establishable as secondary to your back (§3.310)."
    f = Finding(specialist="secondaries", kind="secondary", key="k", title="T",
                body="Your depression is service-connected as secondary to your back.",
                det_body=safe, enriched=True, layer="floor", severity="medium",
                regs=[], card_ids=[], evidence_refs=[], citations=[])
    kept = await review([f], object())
    assert len(kept) == 1
    assert kept[0].enriched is False and kept[0].body == safe   # Check A → reverted


@pytest.mark.asyncio
async def test_enriched_floor_hedged_body_kept_when_reviewer_approves(monkeypatch):
    # Mutation-honest counterpart: a hedged enriched FLOOR reword does NOT assert SC, so
    # Check A does not apply; with a NON-None db + APPROVING reviewer it stays enriched.
    async def _cards(db, query, **kw):  # noqa: ANN001
        return []
    monkeypatch.setattr("app.kb.store.retrieve_cards", _cards)
    monkeypatch.setattr(_gateway, "complete", _fake_complete(_PANEL_OK))
    body = "A warmer restatement of the same §3.310 theory to explore with a VSO."
    f = Finding(specialist="x", kind="secondary", key="k", title="T",
                body=body, det_body="The §3.310 theory.", enriched=True, layer="floor",
                severity="medium")
    kept = await review([f], object())
    assert len(kept) == 1
    assert kept[0].enriched is True and kept[0].body == body
