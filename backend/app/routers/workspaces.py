"""Workspaces — the caller's tenancy surface (Wave 11).

Lists the workspaces the user belongs to (their personal one plus any organizations)
and reports which is active for this request. The active workspace is chosen by the
`X-Workspace-Id` header (validated against membership) or defaults to personal — see
deps.current_workspace_id. Org creation / invites / role management land in a later
wave; this is the read surface the switcher needs.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user_id, current_workspace_id, get_db
from ..schemas import WorkspaceOut, WorkspacesOut

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=WorkspacesOut)
async def list_workspaces(
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(
        text(
            "SELECT o.id::text AS id, o.name, o.kind, o.plan_tier, "
            "       COALESCE(o.status,'active') AS status, m.role "
            "FROM organizations o JOIN organization_members m ON m.org_id = o.id "
            "WHERE m.user_id = CAST(:u AS uuid) "
            "ORDER BY (o.kind = 'personal') DESC, o.name"
        ),
        {"u": uid},
    )).mappings().all()
    return WorkspacesOut(
        workspaces=[WorkspaceOut(**r) for r in rows],
        current_workspace_id=wsid,
    )
