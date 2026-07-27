"""Whole-document extract-verify: the verifier reads the ENTIRE record in
overlapping segments (like the classifier), so a condition whose supporting
sentence sits past the old head-only 24K cap is still quoted and reconciled —
it no longer comes back silently `unverified`. Model seam is monkeypatched; the
pure validator runs for real. No fleet, no DB.
"""

from __future__ import annotations

import json

import pytest

from app.intake.segment import DEFAULT_SEGMENT_CHARS, map_segments
from app.intake.verify import _best_span, _norm, validate_verification, verify_extraction

PTSD_SENT = "The veteran's PTSD is evaluated at 50 percent disabling under diagnostic code 9411."
TINNITUS_SENT = "Addendum: Tinnitus was granted at 10 percent evaluation."

# The honest "model": for each condition it was asked about, it quotes the span
# ONLY when that condition's supporting sentence is in the window it can see; and
# it surfaces any known condition present in the window but absent from the ask.
_SPANS = {"PTSD": PTSD_SENT, "Tinnitus": TINNITUS_SENT}


def _fake_gateway(monkeypatch, counter: dict | None = None):
    from app.llm.gateway import gateway as _gw

    async def fake_complete(messages, **kwargs):
        if counter is not None:
            counter["calls"] = counter.get("calls", 0) + 1
        payload = json.loads(messages[-1]["content"])
        source = payload["source_text"]
        asked = payload["extracted_conditions"]
        asked_names = {c["name"] for c in asked}
        conditions = [
            {"name": c["name"], "span": _SPANS[c["name"]] if _SPANS.get(c["name"], "") in source else ""}
            for c in asked
        ]
        missing = [
            {"name": name, "span": span}
            for name, span in _SPANS.items()
            if span in source and name not in asked_names
        ]
        return json.dumps({"conditions": conditions, "missing": missing})

    monkeypatch.setattr(_gw, "complete", fake_complete)
    return counter


def _extracted(conds):
    return {"conditions_mentioned": conds}


# ── _best_span (pure merge) ──────────────────────────────────────────────────

def test_best_span_prefers_a_grounded_quote_over_a_hallucinated_one():
    source_norm = _norm("VA Rating Decision. " + PTSD_SENT)
    chosen = _best_span(["the left leg was amputated below the knee", PTSD_SENT], source_norm)
    assert chosen == PTSD_SENT  # the real substring wins even though it came second


def test_best_span_empty_when_every_candidate_is_empty():
    assert _best_span(["", "   "], _norm("anything")) == ""


# ── verify_extraction (whole-document) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_short_document_makes_a_single_pass(monkeypatch):
    counter = _fake_gateway(monkeypatch, {"calls": 0})
    source = PTSD_SENT + " " + TINNITUS_SENT
    assert len(map_segments(source)) == 1  # guard: this really is one segment
    extracted = _extracted(
        [
            {"name": "PTSD", "rating_percent": 50, "diagnostic_code": "9411", "decision": None},
            {"name": "Tinnitus", "rating_percent": 10, "diagnostic_code": None, "decision": "granted"},
        ]
    )
    raw = await verify_extraction(source, extracted, model="local")
    assert counter["calls"] == 1
    spans = {c["name"]: c["span"] for c in raw["conditions"]}
    assert spans["PTSD"] == PTSD_SENT and spans["Tinnitus"] == TINNITUS_SENT


@pytest.mark.asyncio
async def test_a_condition_proved_beyond_the_head_cap_is_recovered(monkeypatch):
    # THE regression this closes: Tinnitus' proof sits far past 24K. The old
    # head-only pass never saw it → Tinnitus came back unverified. Whole-doc reads
    # the deep segment, quotes it, and the validator CONFIRMS it.
    filler = " Routine progress note continued. " * 1000  # ~34K of padding
    source = "VA Rating Decision. " + PTSD_SENT + filler + TINNITUS_SENT
    assert source.index(TINNITUS_SENT) > DEFAULT_SEGMENT_CHARS  # guard: genuinely past the cap
    assert len(map_segments(source)) >= 2

    counter = _fake_gateway(monkeypatch, {"calls": 0})
    extracted = _extracted(
        [
            {"name": "PTSD", "rating_percent": 50, "diagnostic_code": "9411", "decision": None},
            {"name": "Tinnitus", "rating_percent": 10, "diagnostic_code": None, "decision": "granted"},
        ]
    )
    raw = await verify_extraction(source, extracted, model="local")
    assert counter["calls"] >= 2  # it actually read past the first window
    spans = {c["name"]: c["span"] for c in raw["conditions"]}
    assert spans["Tinnitus"] == TINNITUS_SENT  # the deep span was recovered and unioned

    verdict = validate_verification(source, extracted, raw)
    by_name = {c["name"]: c["status"] for c in verdict["conditions"]}
    assert by_name["PTSD"] == "confirmed"
    assert by_name["Tinnitus"] == "confirmed"  # would be "unverified" under the old cap
    assert verdict["status"] == "clear"


@pytest.mark.asyncio
async def test_missing_recall_across_segments_is_deduped(monkeypatch):
    # Tinnitus is NOT extracted; its sentence is deep in the record. Whole-doc
    # recall surfaces it exactly once even if more than one segment sees it.
    filler = " Continued progress note. " * 1200
    source = "VA Rating Decision. " + PTSD_SENT + filler + TINNITUS_SENT + (" tail." * 400)
    assert len(map_segments(source)) >= 2
    _fake_gateway(monkeypatch)
    extracted = _extracted(
        [{"name": "PTSD", "rating_percent": 50, "diagnostic_code": "9411", "decision": None}]
    )
    raw = await verify_extraction(source, extracted, model="local")
    verdict = validate_verification(source, extracted, raw)
    assert [m["name"] for m in verdict["missing_conditions"]] == ["Tinnitus"]  # once, not twice


@pytest.mark.asyncio
async def test_every_segment_failing_returns_none(monkeypatch):
    from app.llm.gateway import gateway as _gw

    async def boom(messages, **kwargs):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(_gw, "complete", boom)
    filler = " note. " * 5000
    source = PTSD_SENT + filler + TINNITUS_SENT
    assert len(map_segments(source)) >= 2
    extracted = _extracted(
        [{"name": "PTSD", "rating_percent": 50, "diagnostic_code": "9411", "decision": None}]
    )
    assert await verify_extraction(source, extracted, model="local") is None


@pytest.mark.asyncio
async def test_no_conditions_skips_the_gateway(monkeypatch):
    counter = _fake_gateway(monkeypatch, {"calls": 0})
    assert await verify_extraction("some long text " * 4000, _extracted([]), model="local") is None
    assert counter["calls"] == 0
