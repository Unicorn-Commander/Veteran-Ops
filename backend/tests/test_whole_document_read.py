"""Whole-document read (Phase 1a): the classifier must read EVERY segment of a
large record and union the conditions, so a condition buried deep in a C-file is
no longer dropped by the old head-only ~16K-char cap. Pure + monkeypatched — no
fleet."""

from __future__ import annotations

import pytest

from app.intake import classify, ocr
from app.intake.segment import DEFAULT_SEGMENT_CHARS, map_segments


# ── segmenter (pure) ─────────────────────────────────────────────────────────


def test_short_text_is_one_segment():
    segs = map_segments("a short record")
    assert len(segs) == 1
    assert segs[0].text == "a short record"
    assert segs[0].start == 0 and segs[0].end == len("a short record")


def test_blank_text_is_no_segments():
    assert map_segments("") == []
    assert map_segments("   \n  ") == []


def test_large_text_splits_and_covers_everything_with_overlap():
    text = ("x" * 500 + "\n\n") * 200  # ~100k chars, paragraph breaks
    segs = map_segments(text)
    assert len(segs) > 1
    assert segs[0].start == 0
    assert segs[-1].end == len(text)
    for a, b in zip(segs, segs[1:]):
        assert b.start <= a.end           # never a gap
        assert b.start < a.end            # genuine overlap


def test_no_separators_hard_cuts_within_window_and_terminates():
    text = "y" * (DEFAULT_SEGMENT_CHARS * 3)  # no breaks → hard cuts
    segs = map_segments(text)
    assert all(len(s.text) <= DEFAULT_SEGMENT_CHARS for s in segs)
    assert segs[-1].end == len(text)      # full coverage, no infinite loop


# ── classify_text is now a whole-document union ──────────────────────────────


@pytest.mark.asyncio
async def test_classify_text_unions_conditions_across_segments(monkeypatch):
    long_text = ("A" * 30000) + ("B" * 30000)  # → 3 segments (window 24k)
    seq = [
        {"doc_type": "rating_decision", "is_va_decision": True, "summary": "s",
         "conditions_mentioned": [{"name": "PTSD", "diagnostic_code": "9411"}]},
        {"conditions_mentioned": [{"name": "Tinnitus", "diagnostic_code": "6260"}]},
        {"conditions_mentioned": [{"name": "ptsd", "diagnostic_code": "9411"}]},  # dup
    ]
    it = iter(seq)

    async def fake_segment(text):
        try:
            return next(it)
        except StopIteration:
            return {"conditions_mentioned": []}

    monkeypatch.setattr(classify, "_classify_segment", fake_segment)
    out = await classify.classify_text(long_text)
    names = {c["name"].casefold() for c in out["conditions_mentioned"]}
    assert names == {"ptsd", "tinnitus"}                 # deduped union
    assert out["doc_type"] == "rating_decision"          # head fields preserved
    assert out["is_va_decision"] is True
    assert out["read_coverage"]["segments_total"] >= 2


@pytest.mark.asyncio
async def test_classify_text_returns_none_when_head_fails(monkeypatch):
    async def head_down(text):
        return None

    monkeypatch.setattr(classify, "_classify_segment", head_down)
    assert await classify.classify_text("A" * 30000) is None  # retryable


@pytest.mark.asyncio
async def test_classify_text_tolerates_deep_segment_failure(monkeypatch):
    long_text = ("A" * 30000) + ("B" * 30000)
    seq = [{"conditions_mentioned": [{"name": "PTSD", "diagnostic_code": "9411"}]}, None]
    it = iter(seq)

    async def flaky(text):
        try:
            return next(it)
        except StopIteration:
            return {"conditions_mentioned": []}

    monkeypatch.setattr(classify, "_classify_segment", flaky)
    out = await classify.classify_text(long_text)
    assert out is not None                                    # head succeeded
    assert out["read_coverage"]["segments_failed"] >= 1


@pytest.mark.asyncio
async def test_single_segment_doc_records_full_coverage(monkeypatch):
    async def one(text):
        return {"doc_type": "treatment_record", "conditions_mentioned": []}

    monkeypatch.setattr(classify, "_classify_segment", one)
    out = await classify.classify_text("a short record")
    assert out["read_coverage"] == {"segments_total": 1, "segments_read": 1, "segments_failed": 0}


# ── OCR full-read page selection ─────────────────────────────────────────────


def test_full_read_reads_every_page():
    idx, truncated = ocr._pdf_page_indices(1000, full_read=True)
    assert idx == list(range(1000))
    assert truncated is False


def test_default_read_caps_head_and_tail():
    idx, truncated = ocr._pdf_page_indices(1000, full_read=False)
    assert truncated is True
    assert len(idx) == ocr._PDF_HEAD_PAGES + ocr._PDF_TAIL_PAGES
