"""Role-based access control for organization (team) workspaces — Wave 12.

The tenancy split, by design:
- **RLS (db.py)** guarantees TENANT ISOLATION — a request scoped to workspace X can
  only ever touch rows in X. This is the hard, security-critical guarantee and it's
  enforced by Postgres, below the app.
- **This module** enforces INTRA-tenant AUTHORIZATION — within workspace X, who may do
  what (owner > admin > staff > member). It runs in the app, on top of the isolation
  RLS already provides.

`current_role` resolves the caller's role in their ACTIVE workspace (the one get_db
pinned). A personal workspace's sole member is always its owner. `require_role(min)`
is a dependency factory that 403s when the caller ranks below `min` in the active
workspace.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .deps import current_user_id, current_workspace_id, get_db

# Higher rank = more authority. Unknown/absent role → -1 (no access).
ROLE_RANK: dict[str, int] = {"member": 0, "staff": 1, "admin": 2, "owner": 3}


def rank(role: str | None) -> int:
    return ROLE_RANK.get(role or "", -1)


async def current_role(
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> str:
    """The caller's role in the ACTIVE workspace. Resolution already proved membership
    (deps._resolve_workspace only honors a workspace the caller belongs to), so a
    missing row is anomalous → treated as 'member' (least privilege)."""
    row = (
        await db.execute(
            text(
                "SELECT role FROM organization_members "
                "WHERE org_id = CAST(:w AS uuid) AND user_id = CAST(:u AS uuid) LIMIT 1"
            ),
            {"w": workspace_id, "u": uid},
        )
    ).first()
    return (row[0] if row else None) or "member"


def is_manager(role: str | None) -> bool:
    """admin/owner — sees the whole org caseload, manages assignments. staff/member do
    not (staff see only their assigned cases; a plain member has no caseload)."""
    return rank(role) >= ROLE_RANK["admin"]


def require_role(minimum: str):
    """Dependency factory: allow only callers whose active-workspace role ranks at or
    above `minimum`. Use on org-management endpoints (e.g. require_role('admin'))."""
    need = ROLE_RANK[minimum]

    async def _dep(role: str = Depends(current_role)) -> str:
        if rank(role) < need:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the '{minimum}' role or higher in this workspace.",
            )
        return role

    return _dep
