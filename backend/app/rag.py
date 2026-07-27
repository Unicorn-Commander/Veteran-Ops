"""Retrieval over a veteran's OWN uploaded documents (document RAG).

The symmetric half of kb/store.py: where the KB grounds answers in VA *law*
(rating criteria, CFR, DBQ catalog), this grounds them in the veteran's *real
evidence* — the text of the documents they uploaded. Same stack (pgvector cosine
over bge-m3 embeddings, dim = settings.embedding_dim), same graceful degradation
to ILIKE keyword search when embeddings are unavailable.

LEGAL LANE: everything here reads the veteran's OWN uploaded text verbatim and
returns excerpts. It organizes and surfaces evidence; it never authors a medical
opinion. The LLM gateway is imported lazily so this module stays importable in
pure-function environments (tests, tooling) without the `openai` package.

RLS: `document_chunks` is workspace + user_id fenced. Callers already run inside
an RLS-scoped session; the explicit `user_id` filter here is defense-in-depth and
keeps cross-user behavior testable without a live Postgres.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .intake.chunk import chunk_text
from .models import DocumentChunk

log = logging.getLogger("veteran_ops.rag")

# Bound per-document fan-out: a pathological (or truncation-escaped) file can't
# spend unbounded embeddings. Upstream extraction already caps stored text, so
# this is a backstop, not the primary limit.
MAX_CHUNKS_PER_DOC = 400
# Embed in batches so one document never sends a single huge embeddings request.
_EMBED_BATCH = 64

_GENERIC_TERMS = {
    "the", "and", "with", "for", "was", "are", "this", "that", "has", "have",
    "from", "your", "you", "condition", "chronic", "acute",
}


async def build_chunk_rows(text: str) -> list[dict]:
    """Chunk `text` and embed each piece → row dicts ready for DocumentChunk.

    Returns [{chunk_index, char_start, char_end, content, embedding}, ...].
    Embedding is None per-chunk when the gateway is unconfigured or errors — the
    chunk is still stored (retrievable via the ILIKE fallback) and a later
    reprocess can fill the vector. Never raises on embedding-infra failure.
    """
    spans = chunk_text(text)
    if not spans:
        return []
    if len(spans) > MAX_CHUNKS_PER_DOC:
        log.warning(
            "document produced %d chunks; embedding the first %d only",
            len(spans), MAX_CHUNKS_PER_DOC,
        )
        spans = spans[:MAX_CHUNKS_PER_DOC]

    contents = [c for _, _, c in spans]
    vectors: list[list[float] | None] = [None] * len(contents)
    try:
        from .llm.gateway import gateway  # lazy — keep importable without openai

        for i in range(0, len(contents), _EMBED_BATCH):
            batch = contents[i : i + _EMBED_BATCH]
            embedded = await gateway.embed(batch)
            for j, vec in enumerate(embedded or []):
                vectors[i + j] = vec
    except Exception:  # noqa: BLE001 — degrade: store chunks without vectors
        log.warning("embedding unavailable; storing chunks without vectors", exc_info=True)

    return [
        {
            "chunk_index": idx,
            "char_start": start,
            "char_end": end,
            "content": content,
            "embedding": vectors[idx],
        }
        for idx, (start, end, content) in enumerate(spans)
    ]


def _keyword_filter(query: str):
    """OR of ILIKE terms over chunk content — the no-embeddings fallback."""
    terms = [w.strip() for w in query.split() if len(w.strip()) >= 3]
    if not terms:
        terms = [query.strip()] if query.strip() else []
    clauses = [DocumentChunk.content.ilike(f"%{t}%") for t in terms]
    return or_(*clauses) if clauses else None


async def search_document_chunks(
    db: AsyncSession,
    user_id: str,
    query: str,
    *,
    k: int = 6,
    document_id: str | None = None,
) -> tuple[list[DocumentChunk], bool]:
    """Top-k chunks of the veteran's OWN documents for a query, plus a flag for
    whether ranking was SEMANTIC (embeddings) or the keyword fallback.

    pgvector cosine over embedded chunks when available; ILIKE keyword otherwise.
    Never raises on retrieval-infrastructure failure — grounding is best-effort.
    """
    if not query.strip():
        return [], False
    uid = uuid.UUID(str(user_id))

    # Vector path — needs an embeddings endpoint AND embedded chunks.
    qv: list[float] | None = None
    try:
        from .llm.gateway import gateway  # lazy

        vecs = await gateway.embed([query])
        qv = vecs[0] if vecs else None
    except Exception:  # noqa: BLE001 — degrade to keyword search
        qv = None

    if qv is not None:
        from .config import settings

        recall_k = max(k, settings.rerank_candidate_k) if settings.reranker_enabled else k
        stmt = select(DocumentChunk).where(
            DocumentChunk.user_id == uid,
            DocumentChunk.embedding.is_not(None),
        )
        if document_id:
            stmt = stmt.where(DocumentChunk.document_id == uuid.UUID(str(document_id)))
        stmt = stmt.order_by(DocumentChunk.embedding.cosine_distance(qv)).limit(recall_k)
        try:
            rows = list((await db.execute(stmt)).scalars().all())
        except Exception:  # noqa: BLE001
            log.warning("vector retrieval failed; falling back to keyword", exc_info=True)
            rows = []
        if rows:
            if settings.reranker_enabled and len(rows) > k:
                from .llm.gateway import gateway

                rows = await gateway.rerank_rows(
                    query, rows, lambda c: (c.content or "")[:2000], k=k
                )
            return rows[:k], True

    return await keyword_chunks(db, user_id, query, k=k, document_id=document_id), False


async def retrieve_document_chunks(
    db: AsyncSession,
    user_id: str,
    query: str,
    *,
    k: int = 6,
    document_id: str | None = None,
) -> list[DocumentChunk]:
    """Top-k chunks for grounding a draft (rows only — see search_document_chunks
    when the caller also needs the semantic-vs-keyword flag)."""
    rows, _ = await search_document_chunks(
        db, user_id, query, k=k, document_id=document_id
    )
    return rows


async def chunks_by_ids(
    db: AsyncSession, user_id: str, ids: list[str]
) -> list[DocumentChunk]:
    """Fetch a veteran's OWN document chunks by exact id, SCOPED to that veteran —
    the reviewer's independent RE-RESOLUTION of a theory's record citations (never
    trust the finding's own evidence_refs list). The explicit user_id filter is
    defense-in-depth on top of RLS: a cited chunk id that isn't the veteran's own
    (or doesn't exist) simply doesn't come back, so the caller fails closed. Malformed
    ids are dropped."""
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        return []
    cuuids: list[uuid.UUID] = []
    for i in ids or []:
        try:
            cuuids.append(uuid.UUID(str(i)))
        except (ValueError, TypeError, AttributeError):
            continue
    if not cuuids:
        return []
    stmt = select(DocumentChunk).where(
        DocumentChunk.user_id == uid, DocumentChunk.id.in_(cuuids)
    )
    return list((await db.execute(stmt)).scalars().all())


async def keyword_chunks(
    db: AsyncSession,
    user_id: str,
    query: str,
    *,
    k: int = 6,
    document_id: str | None = None,
) -> list[DocumentChunk]:
    """ILIKE keyword search over the veteran's chunks — the no-embeddings path.

    Fetches a wider net, then ranks in Python by how many non-generic query terms
    actually hit, so a bare OR + LIMIT doesn't surface whatever indexed first.
    """
    uid = uuid.UUID(str(user_id))
    stmt = select(DocumentChunk).where(DocumentChunk.user_id == uid)
    if document_id:
        stmt = stmt.where(DocumentChunk.document_id == uuid.UUID(str(document_id)))
    flt = _keyword_filter(query)
    if flt is not None:
        stmt = stmt.where(flt)
    try:
        rows = (await db.execute(stmt.limit(max(k * 8, 32)))).scalars().all()
    except Exception:  # noqa: BLE001
        return []

    terms = {
        w.strip().lower()
        for w in query.split()
        if len(w.strip()) >= 3 and w.strip().lower() not in _GENERIC_TERMS
    } or {query.strip().lower()}

    def score(chunk: DocumentChunk) -> int:
        body = (chunk.content or "").lower()
        return sum(1 for t in terms if t in body)

    ranked = sorted(rows, key=score, reverse=True)
    ranked = [r for r in ranked if score(r) > 0]
    return ranked[:k]
