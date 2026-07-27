"""Pure text segmentation for whole-document reading.

The classifier reads one bounded window at a time; a large record (a C-file
running to thousands of pages) is split into coarse, overlapping segments so
EVERY page is read, not just the head. Boundaries prefer paragraph/line breaks so
a condition, exam, or nexus statement is not split mid-sentence, and a small
overlap keeps context that straddles a break from being lost.

Pure + stdlib-only — no LLM, no I/O — so it is unit-testable without the fleet
and reused by both the classification union and (later) the fuller map pass.
"""

from __future__ import annotations

from dataclasses import dataclass

# Coarse read window (~10 pages at ~2,400 chars/page): big enough to hold a full
# C&P exam or nexus opinion intact, small enough to bound a single model call.
DEFAULT_SEGMENT_CHARS = 24_000
DEFAULT_OVERLAP_CHARS = 1_000


@dataclass(frozen=True)
class Segment:
    index: int
    start: int  # char offset into the source text (inclusive)
    end: int    # char offset (exclusive)
    text: str


def _boundary(text: str, target: int, floor: int) -> int:
    """A clean break at or before `target` (never at/below `floor`): prefer a
    paragraph break, then a line break, then a space; else a hard cut at target."""
    if target >= len(text):
        return len(text)
    for sep in ("\n\n", "\n", " "):
        idx = text.rfind(sep, floor, target)
        if idx > floor:
            return idx + len(sep)
    return target


def map_segments(
    text: str,
    *,
    segment_chars: int = DEFAULT_SEGMENT_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> list[Segment]:
    """Split `text` into overlapping segments on clean boundaries.

    A short text returns a single whole-text segment. Deterministic; the segments
    cover the entire text (with overlap), so nothing between the head and the tail
    is dropped. `start + 1` floors guarantee forward progress (never an infinite
    loop) regardless of overlap/segment sizing.
    """
    text = text or ""
    if not text.strip():
        return []
    if len(text) <= segment_chars:
        return [Segment(0, 0, len(text), text)]

    overlap = max(0, min(overlap_chars, segment_chars - 1))
    segs: list[Segment] = []
    start = 0
    idx = 0
    n = len(text)
    while start < n:
        target = min(start + segment_chars, n)
        end = _boundary(text, target, start + 1)
        segs.append(Segment(idx, start, end, text[start:end]))
        if end >= n:
            break
        start = max(end - overlap, start + 1)
        idx += 1
    return segs
