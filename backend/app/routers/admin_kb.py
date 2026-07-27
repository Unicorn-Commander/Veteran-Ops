"""Admin-only KB maintenance endpoint — refresh hand-authored file cards.

POST /admin/kb/refresh-authored triggers an upsert-only refresh of the
hand-authored KB cards from backend/app/kb/data/*.json, matching by
(card_type, title).  Curated-corpus cards (added by the /kb/refresh receiver)
whose (card_type, title) is absent from the files are NEVER touched.
See backend/app/kb/seed.py:refresh_authored_cards for the contract.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import get_db
from ..kb.seed import refresh_authored_cards
from ..rbac import require_role

log = logging.getLogger("veteran_ops.admin_kb")

router = APIRouter(
    prefix="/admin/kb",
    tags=["admin", "kb"],
    dependencies=[Depends(require_role("admin"))],
)


@router.post("/refresh-authored")
async def refresh_authored(
    db: AsyncSession = Depends(get_db),
    _admin_role: str = Depends(require_role("admin")),
) -> dict:
    """Upsert hand-authored KB file cards into the database.

    Matches by (card_type, title).  Updates changed fields and nulls the
    embedding (re-embedded on next boot via _backfill_embeddings).  Inserts
    new file cards.  Never deletes and never touches curated-corpus cards.
    Safe to call repeatedly — a second call with no file changes is a no-op.
    """
    result = await refresh_authored_cards(db)
    log.info("Admin /admin/kb/refresh-authored: %s", result)
    return {"ok": True, **result}
