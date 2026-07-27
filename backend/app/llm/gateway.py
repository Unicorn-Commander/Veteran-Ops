"""OpenAI-compatible LLM + embeddings gateway (UC LiteLLM).

Works unchanged against LiteLLM, llama.cpp server, vLLM, Ollama, or OpenRouter —
point the *_BASE_URL settings at your inference fleet. Rating Raider targets the
tailnet LiteLLM gateway routing to LOCAL models so a veteran's PII never leaves
the fleet by default.

Two cross-cutting concerns handled here so callers don't have to:
  * <think> suppression — local reasoning models emit a (sometimes empty)
    <think>…</think> block. We ask them not to
    (chat_template_kwargs.enable_thinking=false) AND strip any that slips
    through, so a user never sees raw chain-of-thought.
  * PII model guard — a requested model id that is not on the deny-by-default
    allowlist (allowed_models) is dropped and the default LOCAL model
    is used instead, so PII can't be steered to a cloud model by a caller.

The gateway reads from the overrides module so that admin-level DB overrides
(LLM base URL, model, API key, privacy mode, etc.) are picked up at call time
without a restart. Clients are lazily re-created when their config changes.
"""

from __future__ import annotations

import logging
import re

import httpx
from openai import AsyncOpenAI

from ..config import settings
from .. import overrides

log = logging.getLogger("veteran_ops.gateway")

# Tolerant of whitespace/attributes inside the tag (<think>, < think >, <think foo>).
_THINK_BLOCK = re.compile(r"<\s*think\b[^>]*>.*?<\s*/\s*think\s*>", re.DOTALL | re.IGNORECASE)
_BARE_TAG = re.compile(r"<\s*/?\s*think\b[^>]*>", re.IGNORECASE)


def strip_think(text: str) -> str:
    """Remove well-formed <think>…</think> blocks and any stray tags."""
    text = _THINK_BLOCK.sub("", text)
    text = _BARE_TAG.sub("", text)
    return text.strip()


def _extra_body() -> dict:
    if settings.llm_disable_thinking:
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}


class LLMGateway:
    """Thin async client over the OpenAI-compatible gateway: chat + embeddings.

    Clients are created lazily and re-created when the effective (env + DB
    override) config changes, so admin-level service overrides are picked up
    without a server restart.
    """

    def __init__(self) -> None:
        self._chat = None
        self._chat_cfg: dict | None = None
        self._embed = None
        self._embed_cfg: dict | None = None
        self._rerank = None
        self._rerank_cfg: dict | None = None

    # ── lazy client helpers ────────────────────────────────────────────────

    def _ensure_chat(self) -> AsyncOpenAI:
        cfg = {
            "base_url": overrides.effective("llm_base_url") or settings.llm_base_url,
            "api_key": overrides.effective("llm_api_key") or settings.llm_api_key or "sk-local",
        }
        if self._chat is None or self._chat_cfg != cfg:
            self._chat = AsyncOpenAI(
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
                timeout=180.0,
                max_retries=1,
            )
            self._chat_cfg = cfg
        return self._chat

    def _ensure_embed(self) -> AsyncOpenAI | None:
        enabled = settings.embeddings_enabled
        if not enabled:
            self._embed = None
            self._embed_cfg = None
            return None
        cfg = {
            "base_url": overrides.effective("embeddings_base_url") or settings.embeddings_base_url,
            "api_key": overrides.effective("embeddings_api_key") or settings.embeddings_api_key or "sk-local",
        }
        if self._embed is None or self._embed_cfg != cfg:
            self._embed = AsyncOpenAI(
                base_url=cfg["base_url"],
                api_key=cfg["api_key"],
                timeout=60.0,
                max_retries=1,
            )
            self._embed_cfg = cfg
        return self._embed

    def _ensure_rerank(self) -> httpx.AsyncClient | None:
        enabled = settings.reranker_enabled
        if not enabled:
            self._rerank = None
            self._rerank_cfg = None
            return None
        cfg = {
            "base_url": overrides.effective("reranker_base_url") or settings.reranker_base_url,
        }
        if self._rerank is None or self._rerank_cfg != cfg:
            self._rerank = httpx.AsyncClient(
                base_url=cfg["base_url"].rstrip("/"),
                headers={"Authorization": f"Bearer {settings.reranker_api_key or 'sk-local'}"},
                timeout=30.0,
            )
            self._rerank_cfg = cfg
        return self._rerank

    # ── model resolution ───────────────────────────────────────────────────

    def _resolve_model(
        self, model: str | None, *,
        privacy_mode: bool | None = None, touches_pii: bool = False,
    ) -> str:
        """Steer-guard + PII backstop. A caller may only reach an id in the
        allowlist; anything else (a cloud id the gateway also exposes) falls back to
        the local model. Under privacy mode a PII-touching call is forced local even
        if the id is allowlisted — defence in depth behind the primary guard
        (``effective_model_for`` at the call site). The allowlist now carries the
        reasoning/tier ids, so we no longer special-case the reasoning id past the
        mode check (which previously let a caller passing it reach cloud under
        privacy mode)."""
        allowed = overrides.effective_allowed_models()
        llm = overrides.effective("llm_model") or settings.llm_model
        if not (model and model in allowed):
            return llm
        if privacy_mode is None:
            pm = overrides.effective("privacy_mode")
            if pm is None:
                pm = settings.privacy_mode
        else:
            pm = privacy_mode
        if touches_pii and pm and model != llm:
            return llm
        return model

    # ── LLM methods ────────────────────────────────────────────────────────

    async def complete(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        privacy_mode: bool | None = None,
        touches_pii: bool = False,
    ) -> str:
        """Non-streaming chat completion. Returns think-stripped text."""
        client = self._ensure_chat()
        resp = await client.chat.completions.create(
            model=self._resolve_model(model, privacy_mode=privacy_mode, touches_pii=touches_pii),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra_body=_extra_body(),
        )
        return strip_think(resp.choices[0].message.content or "")

    async def complete_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        privacy_mode: bool | None = None,
        touches_pii: bool = False,
    ):
        """One tool-calling turn. Returns the raw assistant message (which may carry
        tool_calls OR final content). The caller runs the agent loop: execute any
        tool_calls, append their results, and call again until content is returned."""
        client = self._ensure_chat()
        resp = await client.chat.completions.create(
            model=self._resolve_model(model, privacy_mode=privacy_mode, touches_pii=touches_pii),
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra_body=_extra_body(),
        )
        return resp.choices[0].message

    async def stream(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1200,
        privacy_mode: bool | None = None,
        touches_pii: bool = False,
    ):
        """Async generator of think-stripped text deltas."""
        client = self._ensure_chat()
        stream_resp = await client.chat.completions.create(
            model=self._resolve_model(model, privacy_mode=privacy_mode, touches_pii=touches_pii),
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            extra_body=_extra_body(),
        )
        in_think = False
        async for chunk in stream_resp:
            delta = (chunk.choices[0].delta.content or "") if chunk.choices else ""
            if not delta:
                continue
            if "<think" in delta.lower():
                in_think = True
            if in_think:
                if "</think" in delta.lower():
                    in_think = False
                continue
            yield delta

    # ── Embeddings ─────────────────────────────────────────────────────────

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via bge-m3 (dim = settings.embedding_dim). Returns [] when
        embeddings are not configured — KB retrieval degrades to ILIKE search."""
        client = self._ensure_embed()
        if not client or not texts:
            return []
        model = overrides.effective("embeddings_model") or settings.embeddings_model
        resp = await client.embeddings.create(model=model, input=texts)
        return [d.embedding for d in resp.data]

    # ── Reranker ───────────────────────────────────────────────────────────

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[tuple[int, float]]:
        """Cross-encoder rerank via bge-reranker-v2-m3 (Infinity /rerank).

        Returns [(original_index, relevance_score), ...] sorted best-first. Returns
        [] when the reranker is not configured, the input is empty, or anything
        fails — the caller MUST treat [] as "keep the existing (vector) order"."""
        client = self._ensure_rerank()
        if not client or not query.strip() or not documents:
            return []
        model = overrides.effective("reranker_model") or settings.reranker_model
        payload: dict = {
            "model": model,
            "query": query,
            "documents": documents,
        }
        if top_n:
            payload["top_n"] = top_n
        try:
            resp = await client.post("/rerank", json=payload)
            resp.raise_for_status()
            results = resp.json().get("results") or []
            pairs = [
                (
                    int(r["index"]),
                    float(r.get("relevance_score", r.get("score", 0.0))),
                )
                for r in results
                if isinstance(r, dict) and "index" in r
            ]
            pairs.sort(key=lambda p: p[1], reverse=True)
            return pairs
        except Exception:  # noqa: BLE001 — degrade to caller's vector order
            log.warning("rerank failed; keeping vector order", exc_info=True)
            return []

    async def rerank_rows(
        self, query: str, rows: list, text_of, *, k: int
    ) -> list:
        """Reorder ORM rows by cross-encoder relevance, return the top-k.

        `text_of(row) -> str` renders each row into the text the reranker scores.
        On any reranker miss (unconfigured/outage), returns rows[:k] with the
        caller's original (vector-similarity) order intact."""
        if not rows:
            return []
        docs = [text_of(r) for r in rows]
        ranked = await self.rerank(query, docs, top_n=k)
        if not ranked:
            return rows[:k]
        return [rows[i] for i, _ in ranked if 0 <= i < len(rows)][:k]

    # ── Health pings ───────────────────────────────────────────────────────

    async def ping_llm(self) -> bool:
        try:
            client = self._ensure_chat()
            model = overrides.effective("llm_model") or settings.llm_model
            await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                stream=False,
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    async def ping_embeddings(self) -> bool:
        client = self._ensure_embed()
        if not client:
            return False
        try:
            model = overrides.effective("embeddings_model") or settings.embeddings_model
            await client.embeddings.create(model=model, input=["ping"])
            return True
        except Exception:  # noqa: BLE001
            return False


gateway = LLMGateway()
