"""Two-stage retrieval (cross-encoder rerank) — degradation + reordering.

The contract that matters: a reranker MISS (unconfigured or outage) must never
degrade grounding below single-stage vector recall — the caller keeps the vector
order. A reranker HIT reorders by relevance.
"""

from __future__ import annotations

import types

import pytest

from app.llm.gateway import LLMGateway, gateway


class _Row:
    def __init__(self, tag: str):
        self.tag = tag

    def __repr__(self) -> str:  # nice failure messages
        return f"Row({self.tag})"


@pytest.mark.asyncio
async def test_rerank_returns_empty_when_unconfigured(monkeypatch):
    """No reranker client → [] (caller keeps vector order), never raises.

    The gateway now obtains its client lazily via `_ensure_rerank()` (so a runtime
    base-URL override is picked up without a restart); patch that seam so the test
    is deterministic regardless of the ambient reranker config."""
    gw = LLMGateway.__new__(LLMGateway)
    monkeypatch.setattr(gw, "_ensure_rerank", lambda: None)
    assert await gw.rerank("knee", ["a", "b"]) == []


@pytest.mark.asyncio
async def test_rerank_rows_keeps_vector_order_on_miss():
    """rerank() -> [] must yield rows[:k] unchanged."""
    rows = [_Row("a"), _Row("b"), _Row("c")]

    async def _empty(query, docs, *, top_n=None):
        return []

    gw = LLMGateway.__new__(LLMGateway)
    gw.rerank = _empty  # type: ignore[assignment]
    out = await gw.rerank_rows("q", rows, lambda r: r.tag, k=2)
    assert [r.tag for r in out] == ["a", "b"]


@pytest.mark.asyncio
async def test_rerank_rows_reorders_by_score():
    """A reranker hit reorders rows and applies top-k."""
    rows = [_Row("a"), _Row("b"), _Row("c")]

    async def _scores(query, docs, *, top_n=None):
        # promote index 2, then 0 — index 1 drops out under top-k
        return [(2, 0.9), (0, 0.5), (1, 0.1)]

    gw = LLMGateway.__new__(LLMGateway)
    gw.rerank = _scores  # type: ignore[assignment]
    out = await gw.rerank_rows("q", rows, lambda r: r.tag, k=2)
    assert [r.tag for r in out] == ["c", "a"]


@pytest.mark.asyncio
async def test_rerank_rows_empty_input():
    gw = LLMGateway.__new__(LLMGateway)
    assert await gw.rerank_rows("q", [], lambda r: r, k=4) == []


@pytest.mark.asyncio
async def test_rerank_parses_infinity_shape(monkeypatch):
    """Parse Infinity's {'results':[{'index','relevance_score'}]} shape + sort."""

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": [
                {"index": 0, "relevance_score": 0.2},
                {"index": 1, "relevance_score": 0.8},
            ]}

    class _Client:
        async def post(self, path, json):
            assert path == "/rerank"
            assert json["query"] == "knee instability"
            return _Resp()

    gw = LLMGateway.__new__(LLMGateway)
    client = _Client()
    monkeypatch.setattr(gw, "_ensure_rerank", lambda: client)
    pairs = await gw.rerank("knee instability", ["low", "high"])
    assert pairs == [(1, 0.8), (0, 0.2)]  # sorted best-first


@pytest.mark.asyncio
async def test_rerank_swallows_transport_error(monkeypatch):
    class _Boom:
        async def post(self, path, json):
            raise RuntimeError("reranker down")

    gw = LLMGateway.__new__(LLMGateway)
    boom = _Boom()
    monkeypatch.setattr(gw, "_ensure_rerank", lambda: boom)
    assert await gw.rerank("q", ["a"]) == []
