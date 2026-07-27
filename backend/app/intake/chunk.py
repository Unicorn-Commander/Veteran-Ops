"""Deterministic, boundary-aware text chunker for document RAG.

Pure (stdlib only) so it's unit-testable without a DB or an inference fleet. The
intake pipeline chunks a veteran's parsed document text into overlapping windows,
each of which is embedded and stored as a DocumentChunk for retrieval over the
veteran's OWN records.

Design goals:
  • Windows land on natural boundaries (paragraph → line → sentence → word) so an
    excerpt reads as a coherent passage, not a mid-word slice.
  • Overlap carries context across a boundary so a fact split across the cut is
    still retrievable from at least one chunk.
  • Deterministic: same text in → same chunks out (no clocks, no randomness).
"""

from __future__ import annotations

# Target characters per chunk. bge-m3 handles ~8k tokens; ~1000 chars (~250
# tokens) keeps each embedding tight and a retrieved excerpt readable in the UI.
TARGET_CHARS = 1000
# Carried context between adjacent chunks.
OVERLAP_CHARS = 150
# How far back from the hard cut we'll hunt for a nicer boundary.
BOUNDARY_LOOKBACK = 240
# Chunks shorter than this (after strip) are dropped — usually trailing scraps.
MIN_CHUNK_CHARS = 24

# Boundary markers in descending preference; each is scored by where it ends.
_BOUNDARIES = ("\n\n", "\n", ". ", "? ", "! ", "; ", " ")


def _best_boundary(text: str, lo: int, hi: int) -> int | None:
    """The end index of the latest preferred boundary within text[lo:hi], or None.

    Tries each marker class in order and returns the first that yields a cut — a
    paragraph break beats a bare space even if the space is closer to `hi`.
    """
    if hi <= lo:
        return None
    window = text[lo:hi]
    for marker in _BOUNDARIES:
        idx = window.rfind(marker)
        if idx != -1:
            # Cut AFTER the marker so the delimiter stays with the earlier chunk.
            return lo + idx + len(marker)
    return None


def chunk_text(
    text: str,
    *,
    target: int = TARGET_CHARS,
    overlap: int = OVERLAP_CHARS,
) -> list[tuple[int, int, str]]:
    """Split `text` into overlapping windows.

    Returns [(char_start, char_end, chunk_text), ...] with offsets into the
    ORIGINAL string (chunk_text is stripped for storage but offsets bound the raw
    span). Empty/whitespace-only input → []. Always makes forward progress.
    """
    if not text or not text.strip():
        return []

    n = len(text)
    if n <= target:
        stripped = text.strip()
        return [(0, n, stripped)] if len(stripped) >= 1 else []

    out: list[tuple[int, int, str]] = []
    start = 0
    while start < n:
        hard_end = min(start + target, n)
        if hard_end < n:
            # Prefer a natural boundary in the last BOUNDARY_LOOKBACK chars.
            cut = _best_boundary(text, max(start + 1, hard_end - BOUNDARY_LOOKBACK), hard_end)
            end = cut if cut is not None else hard_end
        else:
            end = n

        piece = text[start:end].strip()
        if len(piece) >= MIN_CHUNK_CHARS or (not out and piece):
            out.append((start, end, piece))

        if end >= n:
            break
        # Step forward with overlap, but always past the previous start so a
        # boundary that lands early can't stall the loop.
        nxt = end - overlap
        start = nxt if nxt > start else end
    return out
