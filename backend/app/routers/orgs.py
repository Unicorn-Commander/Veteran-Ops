"""Organizations / teams — Wave 12.

Management endpoints act on the caller's ACTIVE workspace ("current"): the frontend
switches to a team (X-Workspace-Id) and then manages it. This keeps them coherent with
the RLS model (organization_members write policies are keyed on the active workspace),
so tenant isolation is enforced by Postgres and can't be bypassed by passing another
org's id in the URL.

Authorization layers, from the outside in:
- RLS (db.py): the request can only ever touch rows in the active workspace.
- require_role (rbac.py): the caller must rank high enough (admin to manage, member to
  view).
- tier/seat gates (features.py): inviting teammates is a paid capability, seat-limited.

Creating a team is free (anyone with a verified email); the tier gates growth — a free
team seats only its owner, so adding teammates is the upgrade surface.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..deps import current_user, current_user_id, current_workspace_id, get_db
from ..email import send_org_invite_email
from ..features import SEAT_LIMIT, active_tier, has_feature, require_feature
from ..models import User
from ..rbac import ROLE_RANK, current_role, rank, require_role
from ..schemas import (
    AuditEntryOut,
    InviteCreateIn,
    InviteOut,
    MemberRoleIn,
    OrgCreateIn,
    OrgMemberOut,
    OrgOut,
    OrgUpdateIn,
)
from ..security import generate_invite_token, hash_invite_token

router = APIRouter(prefix="/orgs", tags=["orgs"])


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "team"
    return f"{base}-{secrets.token_hex(3)}"


async def _seat_count(db: AsyncSession, org_id: str) -> int:
    """Members + still-open invites (an outstanding invite reserves a seat)."""
    n = (await db.execute(
        text("SELECT count(*) FROM organization_members WHERE org_id = CAST(:o AS uuid)"),
        {"o": org_id},
    )).scalar() or 0
    p = (await db.execute(
        text(
            "SELECT count(*) FROM organization_invites "
            "WHERE org_id = CAST(:o AS uuid) AND status = 'pending' "
            "AND expires_at > now()"
        ),
        {"o": org_id},
    )).scalar() or 0
    return int(n) + int(p)


async def _active_org(db: AsyncSession, workspace_id: str) -> dict:
    row = (await db.execute(
        text(
            "SELECT id::text AS id, name, slug, kind, plan_tier, status "
            "FROM organizations WHERE id = CAST(:w AS uuid) LIMIT 1"
        ),
        {"w": workspace_id},
    )).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.")
    return dict(row)


def _require_team_workspace(org: dict) -> None:
    if org["kind"] == "personal":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This is your personal workspace. Create or switch to a team to manage members.",
        )


# ── Create / list / read ────────────────────────────────────────────────────

@router.post("", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_org(
    payload: OrgCreateIn,
    user: User = Depends(current_user),
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> OrgOut:
    """Create a team workspace; the caller becomes its owner. Free to create — the tier
    gates growth. Requires a verified email (teams can send email; block spam upfront)."""
    if settings.require_verified_email_for_orgs and not user.email_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Verify your email address before creating a team.",
        )
    org_id = str(uuid.uuid4())
    name = payload.name.strip()
    slug = _slugify(name)
    await db.execute(
        text(
            "INSERT INTO organizations (id, name, slug, kind, plan_tier, status) "
            "VALUES (CAST(:id AS uuid), :name, :slug, 'org', 'free', 'active')"
        ),
        {"id": org_id, "name": name, "slug": slug},
    )
    await db.execute(
        text(
            "INSERT INTO organization_members (id, org_id, user_id, role) "
            "VALUES (gen_random_uuid(), CAST(:o AS uuid), CAST(:u AS uuid), 'owner')"
        ),
        {"o": org_id, "u": uid},
    )
    return OrgOut(
        id=org_id, name=name, slug=slug, kind="org",
        plan_tier="free", status="active", role="owner", member_count=1,
        seat_limit=SEAT_LIMIT["free"],
    )


@router.get("", response_model=list[OrgOut])
async def list_orgs(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> list[OrgOut]:
    """Every workspace the caller belongs to (personal + teams), with their role and a
    live member count."""
    rows = (await db.execute(
        text(
            "SELECT o.id::text AS id, o.name, o.slug, o.kind, o.plan_tier, o.status, "
            "       m.role, "
            "       (SELECT count(*) FROM organization_members mm WHERE mm.org_id = o.id) AS member_count "
            "FROM organizations o JOIN organization_members m ON m.org_id = o.id "
            "WHERE m.user_id = CAST(:u AS uuid) "
            "ORDER BY (o.kind = 'personal') DESC, o.name"
        ),
        {"u": uid},
    )).mappings().all()
    return [
        OrgOut(
            id=r["id"], name=r["name"], slug=r["slug"], kind=r["kind"],
            plan_tier=r["plan_tier"], status=r["status"], role=r["role"],
            member_count=int(r["member_count"]),
            seat_limit=SEAT_LIMIT.get(r["plan_tier"], 1),
        )
        for r in rows
    ]


@router.get("/current", response_model=OrgOut)
async def get_current_org(
    workspace_id: str = Depends(current_workspace_id),
    role: str = Depends(current_role),
    db: AsyncSession = Depends(get_db),
) -> OrgOut:
    org = await _active_org(db, workspace_id)
    return OrgOut(
        **{k: org[k] for k in ("id", "name", "slug", "kind", "plan_tier", "status")},
        role=role, member_count=await _seat_count_members(db, workspace_id),
        seat_limit=SEAT_LIMIT.get(org["plan_tier"], 1),
    )


async def _seat_count_members(db: AsyncSession, org_id: str) -> int:
    return int((await db.execute(
        text("SELECT count(*) FROM organization_members WHERE org_id = CAST(:o AS uuid)"),
        {"o": org_id},
    )).scalar() or 0)


@router.patch("/current", response_model=OrgOut)
async def rename_current_org(
    payload: OrgUpdateIn,
    workspace_id: str = Depends(current_workspace_id),
    role: str = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> OrgOut:
    org = await _active_org(db, workspace_id)
    _require_team_workspace(org)
    await db.execute(
        text("UPDATE organizations SET name = :n WHERE id = CAST(:w AS uuid)"),
        {"n": payload.name.strip(), "w": workspace_id},
    )
    org["name"] = payload.name.strip()
    return OrgOut(
        **{k: org[k] for k in ("id", "name", "slug", "kind", "plan_tier", "status")},
        role=role, member_count=await _seat_count_members(db, workspace_id),
        seat_limit=SEAT_LIMIT.get(org["plan_tier"], 1),
    )


# ── Members ─────────────────────────────────────────────────────────────────

@router.get("/current/members", response_model=list[OrgMemberOut])
async def list_members(
    workspace_id: str = Depends(current_workspace_id),
    _role: str = Depends(require_role("member")),
    db: AsyncSession = Depends(get_db),
) -> list[OrgMemberOut]:
    """The active workspace's roster (any member may view their own team)."""
    rows = (await db.execute(
        text(
            "SELECT m.user_id::text AS user_id, u.email, u.full_name, m.role, m.created_at "
            "FROM organization_members m JOIN users u ON u.id = m.user_id "
            "WHERE m.org_id = CAST(:w AS uuid) "
            "ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 "
            "         WHEN 'staff' THEN 2 ELSE 3 END, u.email"
        ),
        {"w": workspace_id},
    )).mappings().all()
    return [OrgMemberOut(**r) for r in rows]


async def _owner_count(db: AsyncSession, org_id: str) -> int:
    return int((await db.execute(
        text(
            "SELECT count(*) FROM organization_members "
            "WHERE org_id = CAST(:o AS uuid) AND role = 'owner'"
        ),
        {"o": org_id},
    )).scalar() or 0)


@router.patch("/current/members/{target_id}", response_model=OrgMemberOut)
async def set_member_role(
    target_id: str,
    payload: MemberRoleIn,
    workspace_id: str = Depends(current_workspace_id),
    caller_role: str = Depends(require_role("admin")),
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> OrgMemberOut:
    """Change a member's role. Guardrails: you can't grant a role above your own, only
    an owner may create/remove owners, and the last owner can't be demoted."""
    org = await _active_org(db, workspace_id)
    _require_team_workspace(org)
    target = (await db.execute(
        text(
            "SELECT m.role, u.email, u.full_name, m.created_at "
            "FROM organization_members m JOIN users u ON u.id = m.user_id "
            "WHERE m.org_id = CAST(:w AS uuid) AND m.user_id = CAST(:t AS uuid)"
        ),
        {"w": workspace_id, "t": target_id},
    )).mappings().first()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person isn't a member of this team.")

    new_role = payload.role
    # Can't assign a role higher than your own.
    if rank(new_role) > rank(caller_role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't grant a role above your own.")
    # Only an owner may confer or revoke ownership (change to/from owner).
    if (new_role == "owner" or target["role"] == "owner") and caller_role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an owner can change owner roles.")
    # Never leave a team with zero owners.
    if target["role"] == "owner" and new_role != "owner" and await _owner_count(db, workspace_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A team must keep at least one owner.")

    await db.execute(
        text(
            "UPDATE organization_members SET role = :r "
            "WHERE org_id = CAST(:w AS uuid) AND user_id = CAST(:t AS uuid)"
        ),
        {"r": new_role, "w": workspace_id, "t": target_id},
    )
    return OrgMemberOut(
        user_id=target_id, email=target["email"], full_name=target["full_name"],
        role=new_role, created_at=target["created_at"],
    )


@router.delete("/current/members/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    target_id: str,
    workspace_id: str = Depends(current_workspace_id),
    caller_role: str = Depends(current_role),
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member, or leave the team yourself. Admins may remove anyone below their
    rank; anyone may remove themselves (leave). The last owner can't be removed."""
    org = await _active_org(db, workspace_id)
    _require_team_workspace(org)
    target = (await db.execute(
        text(
            "SELECT role FROM organization_members "
            "WHERE org_id = CAST(:w AS uuid) AND user_id = CAST(:t AS uuid)"
        ),
        {"w": workspace_id, "t": target_id},
    )).mappings().first()
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That person isn't a member of this team.")

    is_self = target_id == uid
    if not is_self:
        if rank(caller_role) < ROLE_RANK["admin"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an admin can remove members.")
        if rank(target["role"]) >= rank(caller_role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "You can't remove someone at or above your role."
            )
    if target["role"] == "owner" and await _owner_count(db, workspace_id) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A team must keep at least one owner.")

    await db.execute(
        text(
            "DELETE FROM organization_members "
            "WHERE org_id = CAST(:w AS uuid) AND user_id = CAST(:t AS uuid)"
        ),
        {"w": workspace_id, "t": target_id},
    )
    return None


# ── Invitations ─────────────────────────────────────────────────────────────

@router.post("/current/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteCreateIn,
    workspace_id: str = Depends(current_workspace_id),
    caller_role: str = Depends(require_role("admin")),
    user: User = Depends(current_user),
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> InviteOut:
    """Invite an email to the active team. Gated on the `org_invites` tier feature and
    the plan's seat limit. You can't invite to a role above your own."""
    org = await _active_org(db, workspace_id)
    _require_team_workspace(org)
    if settings.require_verified_email_for_orgs and not user.email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Verify your email before inviting.")
    if not has_feature(org["plan_tier"], "org_invites"):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "Inviting teammates is a paid feature. Upgrade this team's plan to add seats.",
        )
    if rank(payload.role) > rank(caller_role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't invite to a role above your own.")

    limit = SEAT_LIMIT.get(org["plan_tier"], 1)
    if limit != -1 and await _seat_count(db, workspace_id) >= limit:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"This plan is limited to {limit} seats (members + pending invites). "
            "Upgrade for more.",
        )

    email = payload.email.strip().lower()
    # Already a member?
    already = (await db.execute(
        text(
            "SELECT 1 FROM organization_members m JOIN users u ON u.id = m.user_id "
            "WHERE m.org_id = CAST(:w AS uuid) AND lower(u.email) = :e"
        ),
        {"w": workspace_id, "e": email},
    )).first()
    if already:
        raise HTTPException(status.HTTP_409_CONFLICT, "That person is already on this team.")

    # Supersede any prior pending invite for the same email+org (one live link each).
    await db.execute(
        text(
            "UPDATE organization_invites SET status = 'revoked' "
            "WHERE org_id = CAST(:w AS uuid) AND lower(email) = :e AND status = 'pending'"
        ),
        {"w": workspace_id, "e": email},
    )
    raw = generate_invite_token()
    invite_id = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(days=settings.invite_expire_days)
    await db.execute(
        text(
            "INSERT INTO organization_invites "
            "(id, org_id, email, role, token_hash, invited_by, status, expires_at) "
            "VALUES (CAST(:id AS uuid), CAST(:o AS uuid), :e, :r, :h, CAST(:by AS uuid), "
            "        'pending', :exp)"
        ),
        {"id": invite_id, "o": workspace_id, "e": email, "r": payload.role,
         "h": hash_invite_token(raw), "by": uid, "exp": expires},
    )
    link = f"{settings.public_base}/invite#token={raw}" if settings.public_base else f"(set PUBLIC_BASE) token={raw}"
    await send_org_invite_email(email, org["name"], user.full_name or user.email, link)
    return InviteOut(
        id=invite_id, org_id=workspace_id, email=email, role=payload.role,
        status="pending", invited_by_email=user.email, expires_at=expires,
        created_at=datetime.now(timezone.utc),
    )


@router.get("/current/invites", response_model=list[InviteOut])
async def list_invites(
    workspace_id: str = Depends(current_workspace_id),
    _role: str = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[InviteOut]:
    rows = (await db.execute(
        text(
            "SELECT i.id::text AS id, i.org_id::text AS org_id, i.email, i.role, i.status, "
            "       i.expires_at, i.created_at, u.email AS invited_by_email "
            "FROM organization_invites i LEFT JOIN users u ON u.id = i.invited_by "
            "WHERE i.org_id = CAST(:w AS uuid) AND i.status = 'pending' "
            "ORDER BY i.created_at DESC"
        ),
        {"w": workspace_id},
    )).mappings().all()
    return [InviteOut(**r) for r in rows]


@router.delete("/current/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: str,
    workspace_id: str = Depends(current_workspace_id),
    _role: str = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        text(
            "UPDATE organization_invites SET status = 'revoked' "
            "WHERE id = CAST(:i AS uuid) AND org_id = CAST(:w AS uuid) AND status = 'pending'"
        ),
        {"i": invite_id, "w": workspace_id},
    )
    if res.rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pending invite with that id.")
    return None


# ── Audit trail (Wave 13) ───────────────────────────────────────────────────

@router.get("/current/audit", response_model=list[AuditEntryOut])
async def org_audit(
    limit: int = 100,
    workspace_id: str = Depends(current_workspace_id),
    _role: str = Depends(require_role("admin")),
    _feat: str = Depends(require_feature("staff_caseload")),
    db: AsyncSession = Depends(get_db),
) -> list[AuditEntryOut]:
    """Recent activity in this org workspace (admin+, team tier). audit_log is
    workspace-fenced, so this only ever shows THIS org's actions; case actions record
    the acting staff, so the trail names who did what. The staff_caseload feature gate
    also keeps a personal/free workspace out (it has no caseload to audit). The actor is
    read from the denormalized `actor_label` first, so a departed (erased) staffer is
    still attributable."""
    limit = max(1, min(limit, 500))
    rows = (await db.execute(
        text(
            "SELECT a.id::text AS id, a.action, a.entity, a.entity_id, "
            "       a.user_id::text AS actor_user_id, "
            "       COALESCE(a.actor_label, u.email, '') AS actor_email, "
            "       a.meta, a.created_at "
            "FROM audit_log a LEFT JOIN users u ON u.id = a.user_id "
            "ORDER BY a.created_at DESC LIMIT :lim"
        ),
        {"lim": limit},
    )).mappings().all()
    return [AuditEntryOut(**r) for r in rows]
