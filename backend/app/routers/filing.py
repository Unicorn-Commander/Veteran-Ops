"""Filing lanes guide — static KB `process` cards (ITF, 526EZ/FDC, AMA review
lanes, effective dates, CUE, C&P exam, accredited help), ordered for the guide
page. Falls back to the authored JSON when the DB corpus hasn't seeded yet."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user_id, get_db
from ..kb.store import cards_by_type, load_cards

router = APIRouter(prefix="/filing", tags=["filing"])


def _order(data: dict | None) -> int:
    try:
        return int((data or {}).get("order", 999))
    except (TypeError, ValueError):
        return 999


@router.get("/lanes")
async def filing_lanes(
    _uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await cards_by_type(db, "process")
    if rows:
        lanes = [
            {
                "id": str(r.id),
                "title": r.title,
                "content": r.content,
                "source": r.source,
                "order": _order(r.data),
            }
            for r in rows
        ]
    else:  # corpus not seeded yet — serve from the authored files
        lanes = [
            {
                "id": None,
                "title": c.get("title", ""),
                "content": c.get("content", ""),
                "source": c.get("source", ""),
                "order": _order(c.get("data")),
            }
            for c in load_cards()
            if c.get("card_type") == "process"
        ]
    lanes.sort(key=lambda x: x["order"])
    return {"lanes": lanes}
