"""Intake classify segment sampling — large Blue Buttons must not enqueue dozens of LLM calls."""

from __future__ import annotations

from types import SimpleNamespace

from app.intake.classify import select_classify_segments
from app.intake.segment import map_segments


def _segs(n: int):
    return [SimpleNamespace(text=f"seg-{i}", index=i) for i in range(n)]


def test_select_under_cap_returns_all():
    segs = _segs(5)
    chosen, sampled = select_classify_segments(segs, 9)
    assert not sampled
    assert len(chosen) == 5
    assert chosen[0].text == "seg-0"
    assert chosen[-1].text == "seg-4"


def test_select_over_cap_samples_head_tail_and_middle():
    segs = _segs(27)  # ~600k Blue Button at 24k windows
    chosen, sampled = select_classify_segments(segs, 9)
    assert sampled
    assert len(chosen) <= 9
    assert chosen[0].text == "seg-0"
    assert chosen[-1].text == "seg-26"
    # Distinct indices only
    texts = [c.text for c in chosen]
    assert len(texts) == len(set(texts))


def test_map_segments_then_sample_bounds_llm_calls():
    # ~600k of text → many segments → sampled to ≤9
    blob = ("Condition hypertension rated 30 percent. " * 200 + "\n") * 80
    all_segs = map_segments(blob)
    assert len(all_segs) > 9
    chosen, sampled = select_classify_segments(all_segs, 9)
    assert sampled
    assert 2 <= len(chosen) <= 9
    assert chosen[0] is all_segs[0] or chosen[0].text == all_segs[0].text


def test_limit_one_is_head_only():
    segs = _segs(10)
    chosen, sampled = select_classify_segments(segs, 1)
    assert sampled
    assert len(chosen) == 1
    assert chosen[0].text == "seg-0"
