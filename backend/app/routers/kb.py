"""Knowledge-base browsing: card list/search, card detail, DBQ lookup.

Global reference material (no PII, not RLS-fenced) — still authed like the rest
of the API. Search uses vector retrieval when a query is given and embeddings
are up; otherwise ILIKE keyword fallback.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user_id, get_db
from ..kb import freshness
from ..kb.store import (
    cached_contention_map,
    cached_max_ratings,
    classify_contention,
    dbq_catalog_source,
    load_dbq_catalog,
    retrieve_cards,
)
from ..models import KBCard
from ..schemas import KBCardOut

router = APIRouter(prefix="/kb", tags=["kb"])


@router.get("/cards", response_model=list[KBCardOut])
async def list_cards(
    type: str | None = Query(default=None, alias="type"),
    body_system: str | None = None,
    q: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    _uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if q:
        rows = await retrieve_cards(db, q, k=limit, card_type=type, body_system=body_system)
        return rows
    stmt = select(KBCard).order_by(KBCard.card_type, KBCard.title).limit(limit)
    if type:
        stmt = stmt.where(KBCard.card_type == type)
    if body_system:
        stmt = stmt.where(KBCard.body_system == body_system)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/cards/{card_id}", response_model=KBCardOut)
async def get_card(
    card_id: uuid.UUID,
    _uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.get(KBCard, card_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Card not found")
    return obj


@router.get("/max-rating/{dc}")
async def max_rating_lookup(
    dc: str,
    _uid: str = Depends(current_user_id),
) -> dict:
    """Schedular ceiling for a diagnostic code (vendored VA max-ratings dataset,
    CC0; educational — verify current criteria at eCFR). 404 for unknown codes."""
    row = cached_max_ratings().get(dc.strip())
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Unknown diagnostic code in the max-ratings dataset"
        )
    return {
        **row,
        "source": "VA disability-max-ratings dataset (CC0) — verify at eCFR / VA.gov",
    }


@router.get("/classify-contention")
async def classify_contention_lookup(
    text: str = Query(min_length=1, max_length=255),
    _uid: str = Depends(current_user_id),
) -> dict:
    """VA official contention-classification taxonomy match for a condition name
    (deterministic — vendored CC0 dataset, no LLM). matched=false when no hit."""
    hit = classify_contention(text=text, cmap=cached_contention_map())
    return {
        "text": text,
        "matched": hit is not None,
        "classification_code": (hit or {}).get("classification_code"),
        "classification_name": (hit or {}).get("classification_name"),
        "match": (hit or {}).get("match"),
        "source": "VA contention-classification dataset (CC0)",
    }


@router.get("/freshness")
async def kb_freshness(_uid: str = Depends(current_user_id)) -> dict:
    """Is the KB older than the last 38 CFR amendment? Live eCFR check with a
    cached fallback; never 5xxs on eCFR being unreachable."""
    verified_as_of = await freshness.effective_kb_verified_as_of()
    try:
        return await freshness.check_freshness(verified_as_of)
    except Exception:  # noqa: BLE001 — degrade to the last known result
        cached = freshness.cached_freshness()
        if cached is not None:
            return {**cached, "cached": True}
        return {
            "title38_latest_amended_on": None,
            "kb_verified_as_of": verified_as_of.isoformat(),
            "stale": False,
            "error": "ecfr_unreachable",
        }


@router.get("/dbq")
async def dbq_lookup(
    condition: str = Query(min_length=1),
    _uid: str = Depends(current_user_id),
) -> dict:
    """Best-match DBQ form for a condition name (authored catalog, deterministic)."""
    from ..analysis.gaps import map_dbq

    catalog = load_dbq_catalog()
    dbq = map_dbq(condition, None, catalog)
    return {
        "condition": condition,
        "dbq": dbq,
        "source": dbq_catalog_source(),
    }
