"""Case-builder aggregation + candidate finalization (pure — no DB/LLM)."""

from __future__ import annotations

from app.analysis import case


class _Doc:
    def __init__(self, doc_id, mentions):
        self.id = doc_id
        self.extracted = {"conditions_mentioned": mentions}


def test_aggregate_dedupes_by_normalized_name():
    docs = [
        _Doc("d1", [{"name": "CFS"}, {"name": "Mono", "diagnostic_code": "6354"}]),
        _Doc("d2", [{"name": "cfs "}, {"name": "PTSD"}]),
    ]
    agg = case.aggregate_mentions(docs)
    # CFS collapses to the curated ME/CFS display name across both docs.
    cfs = next(r for r in agg if "fatigue" in r["name"].lower() or r["name"] == "CFS")
    assert cfs["count"] == 2
    assert cfs["document_ids"] == {"d1", "d2"}
    mono = next(r for r in agg if "mono" in r["name"].lower())
    assert mono["diagnostic_code"] == "6354"
    assert any(r["name"] == "PTSD" for r in agg)


def test_aggregate_auto_aliases_known_synonyms():
    """Chart/OCR spellings for the same condition collapse without an LLM."""
    docs = [
        _Doc("d1", [{"name": "CFS"}, {"name": "chronic fatigue"}, {"name": "ME/CFS"}]),
        _Doc("d2", [{"name": "post traumatic stress disorder"}, {"name": "PTSD"}]),
    ]
    agg = case.aggregate_mentions(docs)
    assert len(agg) == 2
    fatigue = next(r for r in agg if "fatigue" in r["name"].lower() or "cfs" in r["name"].lower())
    assert fatigue["count"] == 3
    assert set(fatigue["aliases"]) >= {"CFS", "chronic fatigue", "ME/CFS"}
    ptsd = next(r for r in agg if "ptsd" in r["name"].lower())
    assert ptsd["count"] == 2
    # Deterministic path surfaces the same merges offline.
    det = case.deterministic_candidates(agg)
    assert len(det) == 2
    assert any(c["mention_count"] == 3 for c in det)


def test_finalize_maps_aliases_and_keeps_unplaced():
    agg = case.aggregate_mentions([
        _Doc("d1", [{"name": "chronic fatigue"}, {"name": "ME/CFS"}, {"name": "tinnitus"}]),
    ])
    # LLM groups the two fatigue variants; leaves tinnitus unmentioned.
    llm = [{
        "name": "Chronic Fatigue Syndrome (ME/CFS)",
        "aliases": ["chronic fatigue", "ME/CFS"],
        "claim_type": "direct",
        "note": "Persistent disabling fatigue.",
    }]
    out = case._finalize(llm, agg)
    names = {c["name"] for c in out}
    # grouped candidate present, aliases merged, count summed
    grouped = next(c for c in out if c["name"].startswith("Chronic Fatigue"))
    assert grouped["mention_count"] == 2
    assert set(grouped["aliases"]) == {"chronic fatigue", "ME/CFS"}
    # the unplaced 'tinnitus' is not silently dropped
    assert any("tinnitus" in n.lower() for n in names)


def test_finalize_drops_invented_conditions():
    agg = case.aggregate_mentions([_Doc("d1", [{"name": "knee pain"}])])
    llm = [{"name": "Hypertension", "aliases": ["hypertension"]}]  # not in records
    out = case._finalize(llm, agg)
    # invented candidate has no matching alias → dropped; knee pain preserved
    assert all("hypertension" not in c["name"].lower() for c in out)
    assert any("knee" in c["name"].lower() for c in out)


def test_deterministic_fallback_titlecases():
    agg = case.aggregate_mentions([_Doc("d1", [{"name": "fibromyalgia"}])])
    out = case.deterministic_candidates(agg)
    assert out[0]["name"] == "Fibromyalgia"
    assert out[0]["claim_type"] == "direct"
