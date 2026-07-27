"""GET /entitlements — Wave 12.

The single source the frontend reads to gate team/enterprise UI for the ACTIVE
workspace: its tier, the caller's role, the enabled feature keys, and the seat limit.
Individual veteran tools are never in `features` because they're never gated — this
endpoint is purely about org/enterprise capabilities.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_workspace_id, get_db
from ..features import SEAT_LIMIT, active_tier, features_for
from ..rbac import current_role
from ..schemas import EntitlementsOut

router = APIRouter(prefix="/entitlements", tags=["entitlements"])


@router.get("", response_model=EntitlementsOut)
async def get_entitlements(
    workspace_id: str = Depends(current_workspace_id),
    tier: str = Depends(active_tier),
    role: str = Depends(current_role),
    db: AsyncSession = Depends(get_db),
) -> EntitlementsOut:
    kind = (await db.execute(
        text("SELECT kind FROM organizations WHERE id = CAST(:w AS uuid) LIMIT 1"),
        {"w": workspace_id},
    )).scalar() or "personal"
    return EntitlementsOut(
        workspace_id=workspace_id,
        kind=kind,
        tier=tier,
        role=role,
        features=features_for(tier),
        seat_limit=SEAT_LIMIT.get(tier, 1),
    )
