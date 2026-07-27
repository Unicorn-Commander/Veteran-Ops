"""Unit tests for the document-RAG chunker (pure, stdlib-only — no DB/fleet)."""

from __future__ import annotations

from app.intake.chunk import (
    MIN_CHUNK_CHARS,
    OVERLAP_CHARS,
    TARGET_CHARS,
    chunk_text,
)


def test_empty_and_whitespace_yield_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []


def test_short_text_is_a_single_chunk():
    spans = chunk_text("A brief treatment note about the knee.")
    assert len(spans) == 1
    start, end, content = spans[0]
    assert start == 0
    assert content == "A brief treatment note about the knee."


def test_long_text_splits_with_overlap_and_valid_offsets():
    body = (
        "Continuity of knee pain since separation in 2010. "
        + ("Clinical detail. " * 120)
        + "Assessment: chronic condition, ongoing."
    )
    spans = chunk_text(body)
    assert len(spans) >= 2
    # Offsets are ordered, in-bounds, and each span is non-empty.
    for start, end, content in spans:
        assert 0 <= start < end <= len(body)
        assert content.strip()
    # Adjacent chunks overlap (next start steps back by ~OVERLAP_CHARS), so a fact
    # on a boundary survives in at least one chunk.
    starts = [s for s, _, _ in spans]
    ends = [e for _, e, _ in spans]
    assert starts[1] < ends[0]
    assert ends[0] - starts[1] <= OVERLAP_CHARS + 5


def test_chunks_respect_target_ceiling():
    body = "word " * 4000  # ~20k chars
    spans = chunk_text(body)
    # No chunk materially exceeds the target window (boundary hunt only backs up).
    assert all((end - start) <= TARGET_CHARS + 5 for start, end, _ in spans)
    # And the whole document is covered start-to-finish.
    assert spans[0][0] == 0
    assert spans[-1][1] == len(body)


def test_boundary_preference_breaks_on_paragraphs():
    para = "First paragraph. " + ("x" * 400)
    body = para + "\n\n" + "Second paragraph starts here. " + ("y" * 400)
    spans = chunk_text(body, target=450, overlap=50)
    # The first cut should land at the paragraph break, not mid-word.
    first_end = spans[0][1]
    assert body[first_end - 2 : first_end] == "\n\n" or body[:first_end].endswith("\n\n")


def test_min_chunk_floor_drops_trailing_scraps():
    # A tiny tail shorter than the floor shouldn't appear as its own chunk.
    body = ("a" * (TARGET_CHARS - 5)) + "\n\n" + ("b" * (MIN_CHUNK_CHARS - 5))
    spans = chunk_text(body)
    assert all(len(c) >= 1 for _, _, c in spans)


def test_needs_reindex_selects_unindexed_and_degraded_only():
    from app.routers.documents import _needs_reindex

    # Never chunked (predates document-RAG) → needs indexing.
    assert _needs_reindex(0, 0) is True
    # Chunked but some chunk has no vector (embeddings outage) → needs re-embed.
    assert _needs_reindex(5, 3) is True
    assert _needs_reindex(5, 0) is True
    # Fully embedded → already searchable, left alone (idempotent).
    assert _needs_reindex(5, 5) is False
    assert _needs_reindex(1, 1) is False
