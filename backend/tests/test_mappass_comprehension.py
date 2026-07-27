"""Whole-C-file map-reduce (Phase 3 intake): the MAP pass validates + stamps
provenance per segment (mirroring classify.validate_extraction), records honest
read coverage, and the REDUCE folds facts into a CFilePicture with the 3 SC
elements per condition, coverage gaps, and an honest read-completeness record.
PURE — the model seam is monkeypatched; no fleet, no DB.
"""

from __future__ import annotations

import pytest

from app.analysis.comprehension import build_case_picture
from app.intake import mappass
from app.intake.mappass import run_map_pass, validate_map_facts


# ── MAP: pure per-segment validation + provenance ────────────────────────────
def test_validate_map_facts_cleans_and_stamps_provenance():
    raw = {
        "claim_relevant": True,
        "salience": 0.8,
        # 55 is off-grid → the reused classifier cleaner drops it to None.
        "conditions": [{"name": "PTSD", "rating_percent": 55, "diagnostic_code": "9411", "decision": "granted"}],
        "exams": [
            {"type": "C&P exam", "date": "2019-03-14", "provider": "Dr. X"},
            {"provider": "no type — dropped"},
        ],
        # The model said meets_standard=False, but the deterministic phrase wins.
        "nexus_statements": [{"text": "It is at least as likely as not related to service", "meets_standard": False}],
        "decisions": [{"condition": "PTSD", "decision": "granted", "date": "2019-03-14"}],
        "dates": ["2019-03-14", "not-a-date"],
        "contradictions": ["states both 50 and 70 percent"],
        "invented_field": "discarded",
    }
    out = validate_map_facts(raw, segment_index=2, char_start=100, char_end=200, page_offsets=[0, 50, 150])
    assert out["segment"] == 2 and out["char_start"] == 100 and out["char_end"] == 200
    assert out["page"] == 1  # offset 100 lands on page index 1 (50 <= 100 < 150)
    assert out["claim_relevant"] is True and out["salience"] == 0.8
    assert out["conditions"][0]["rating_percent"] is None      # 55 dropped by the reused cleaner
    assert out["conditions"][0]["diagnostic_code"] == "9411"
    assert len(out["exams"]) == 1                              # the type-less exam dropped
    assert out["nexus_statements"][0]["meets_standard"] is True  # phrase overrides the model boolean
    assert out["dates"] == ["2019-03-14"]                      # the junk date dropped
    assert "invented_field" not in out


@pytest.mark.asyncio
async def test_run_map_pass_records_coverage_and_tolerates_failure(monkeypatch):
    text = ("A" * 30000) + ("B" * 30000)  # → 3 segments (24k window)
    seq = [
        {"conditions": [{"name": "PTSD", "diagnostic_code": "9411"}]},
        None,  # a segment the model couldn't read (transient) — tolerated
        {"conditions": [{"name": "Tinnitus", "diagnostic_code": "6260"}]},
    ]
    it = iter(seq)

    async def fake(text, *, model=""):
        try:
            return next(it)
        except StopIteration:
            return {"conditions": []}

    monkeypatch.setattr(mappass, "_map_segment", fake)
    out = await run_map_pass(text)
    assert out["read_coverage"]["segments_total"] >= 3
    assert out["read_coverage"]["segments_failed"] >= 1
    names = {c["name"] for seg in out["segments"] for c in seg["conditions"]}
    assert names == {"PTSD", "Tinnitus"}


# ── REDUCE: CFilePicture ──────────────────────────────────────────────────────
def _seg(**kw):
    base = {
        "segment": 0, "char_start": 0, "char_end": 10, "page": 0,
        "claim_relevant": True, "salience": 0.5,
        "conditions": [], "exams": [], "nexus_statements": [],
        "decisions": [], "dates": [], "contradictions": [],
    }
    base.update(kw)
    return base


def test_build_case_picture_rosters_conditions_with_sc_elements_and_gaps():
    segments = [
        _seg(
            segment=0, page=0,
            conditions=[{"name": "PTSD", "rating_percent": 50, "diagnostic_code": "9411", "decision": "granted"}],
            exams=[{"type": "C&P exam", "date": "2019-03-14", "provider": "Dr. X"}],
            nexus_statements=[{"text": "PTSD is at least as likely as not due to service", "meets_standard": True}],
            decisions=[{"condition": "PTSD", "decision": "granted", "date": "2019-03-14"}],
            dates=["2019-03-14"],
        ),
        _seg(
            segment=1, page=1, salience=0.4,
            conditions=[{"name": "Sleep apnea", "rating_percent": None, "diagnostic_code": "6847", "decision": None}],
            contradictions=["conflicting onset dates for the apnea"],
        ),
    ]
    pic = build_case_picture(
        segments, read_coverage={"segments_total": 2, "segments_read": 2, "segments_failed": 0}
    )
    assert {c["name"] for c in pic["condition_roster"]} == {"PTSD", "Sleep apnea"}

    ptsd = next(c for c in pic["condition_roster"] if c["name"] == "PTSD")
    # PTSD: named (diagnosis) + granted (in-service accepted) + nexus on file → nothing missing.
    assert ptsd["missing_elements"] == []
    assert ptsd["sc_elements"]["nexus"]["meets_standard"] is True

    apnea = next(c for c in pic["condition_roster"] if c["name"] == "Sleep apnea")
    assert set(apnea["missing_elements"]) == {"in_service_event", "nexus"}
    assert any(g["condition"] == "Sleep apnea" for g in pic["coverage_gaps"])

    assert pic["timeline"][0]["date"] == "2019-03-14"
    assert any("conflicting onset" in c["note"] for c in pic["contradictions"])
    assert pic["read_completeness"]["complete"] is True


def test_timeline_excludes_spouse_dob_and_dedupes_record_dates():
    spouse_dob = "1964-06-11"
    segments = [
        _seg(
            segment=0,
            salience=0.8,
            exams=[{"type": "C&P exam", "date": "2019-03-14", "provider": "Dr. X"}],
            dates=[spouse_dob, "2019-03-14", "2019-03-14"],
        ),
        _seg(
            segment=1,
            salience=0.1,  # noise segment — generic dates ignored
            dates=["1970-01-01"],
        ),
    ]
    pic = build_case_picture(
        segments,
        read_coverage={"segments_total": 2, "segments_read": 2, "segments_failed": 0},
        exclude_timeline_dates={spouse_dob},
    )
    dates = [e["date"] for e in pic["timeline"]]
    assert spouse_dob not in dates
    assert "1970-01-01" not in dates
    assert dates.count("2019-03-14") == 1  # exam, not duplicated as record date


def test_build_case_picture_is_honest_about_partial_reads():
    segments = [_seg(conditions=[], claim_relevant=False, salience=0.0)]
    pic = build_case_picture(
        segments,
        read_coverage={"segments_total": 5, "segments_read": 3, "segments_failed": 2},
        page_stats={"pages_total": 40, "pages_read": 36, "pages_unreadable": 4},
        truncated=True,
    )
    rc = pic["read_completeness"]
    assert rc["complete"] is False
    assert rc["segments_failed"] == 2 and rc["pages_unreadable"] == 4 and rc["truncated"] is True
    assert "unreadable" in rc["note"]
    # A file-level coverage gap makes the partial read impossible to miss.
    assert any(g.get("missing_elements") == ["full_read"] for g in pic["coverage_gaps"])
