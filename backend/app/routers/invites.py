"""Accepting organization invitations — Wave 12.

The invitee reaches these already signed in (a native or SSO Valor session), but is NOT
yet a member of the inviting org — so the org's rows are invisible under RLS. We resolve
the invite by its secret token (organization_invites is intentionally unfenced), and use
that token as the capability to read the one org it names: we pin the active-workspace
GUC to the invite's org for the rest of the request, which makes exactly that org row
visible and lets the invitee insert their OWN membership (member_insert's self clause).

Binding: the accepting account's email MUST match the invited email — an invite link
forwarded to the wrong person can't be redeemed by them.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..deps import current_user, get_db
from ..features import SEAT_LIMIT, has_feature
from ..models import User
from ..schemas import InvitePreviewOut, OrgOut
from ..security import hash_invite_token

router = APIRouter(prefix="/invites", tags=["orgs"])


async def _load_invite(db: AsyncSession, token: str) -> dict:
    row = (await db.execute(
        text(
            "SELECT i.id::text AS id, i.org_id::text AS org_id, i.email, i.role, "
            "       i.status, i.expires_at, u.email AS invited_by_email "
            "FROM organization_invites i LEFT JOIN users u ON u.id = i.invited_by "
            "WHERE i.token_hash = :h LIMIT 1"
        ),
        {"h": hash_invite_token(token)},
    )).mappings().first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invitation link is not valid.")
    return dict(row)


def _effective_status(inv: dict) -> str:
    if inv["status"] == "pending" and inv["expires_at"] <= datetime.now(timezone.utc):
        return "expired"
    return inv["status"]


async def _pin_org(db: AsyncSession, org_id: str) -> dict | None:
    """Use the invite as a capability: pin the workspace GUC to the invite's org so its
    row is visible for this request, and return it (name/tier/status)."""
    await db.execute(
        text("SELECT set_config('app.current_workspace', :w, true)"), {"w": org_id}
    )
    row = (await db.execute(
        text(
            "SELECT id::text AS id, name, slug, kind, plan_tier, status "
            "FROM organizations WHERE id = CAST(:w AS uuid) LIMIT 1"
        ),
        {"w": org_id},
    )).mappings().first()
    return dict(row) if row else None


@router.get("", response_model=InvitePreviewOut)
async def preview_invite(
    token: str = Query(min_length=8, max_length=4096),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> InvitePreviewOut:
    inv = await _load_invite(db, token)
    org = await _pin_org(db, inv["org_id"])
    return InvitePreviewOut(
        org_name=org["name"] if org else "(unknown team)",
        role=inv["role"],
        email=inv["email"],
        email_matches=(user.email or "").strip().lower() == inv["email"].strip().lower(),
        status=_effective_status(inv),
        invited_by_email=inv["invited_by_email"],
    )


@router.post("/accept", response_model=OrgOut)
async def accept_invite(
    token: str = Query(min_length=8, max_length=4096),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> OrgOut:
    inv = await _load_invite(db, token)
    eff = _effective_status(inv)
    if eff == "expired":
        raise HTTPException(status.HTTP_410_GONE, "This invitation has expired.")
    if eff == "revoked":
        raise HTTPException(status.HTTP_410_GONE, "This invitation was revoked.")
    if eff == "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "This invitation was already used.")
    if (user.email or "").strip().lower() != inv["email"].strip().lower():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"This invitation is for {inv['email']}. Sign in with that email to accept.",
        )

    org = await _pin_org(db, inv["org_id"])
    if not org or org["status"] != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That team is no longer available.")

    uid = str(user.id)
    # Idempotent: if already a member, just consume the invite.
    existing = (await db.execute(
        text(
            "SELECT role FROM organization_members "
            "WHERE org_id = CAST(:o AS uuid) AND user_id = CAST(:u AS uuid)"
        ),
        {"o": inv["org_id"], "u": uid},
    )).mappings().first()
    if existing:
        role = existing["role"]
    else:
        # Re-validate against the org's CURRENT plan at accept time: if the team was
        # downgraded after the invite went out, the seat is no longer available (a
        # stale invite can't grow a team beyond what its plan now allows).
        if not has_feature(org["plan_tier"], "org_invites"):
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                "This team's plan no longer includes teammates. Ask an admin to upgrade.",
            )
        limit = SEAT_LIMIT.get(org["plan_tier"], 1)
        members_now = int((await db.execute(
            text("SELECT count(*) FROM organization_members WHERE org_id = CAST(:o AS uuid)"),
            {"o": inv["org_id"]},
        )).scalar() or 0)
        if limit != -1 and members_now >= limit:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED,
                "This team is full for its current plan. Ask an admin to upgrade.",
            )
        role = inv["role"]
        await db.execute(
            text(
                "INSERT INTO organization_members (id, org_id, user_id, role) "
                "VALUES (gen_random_uuid(), CAST(:o AS uuid), CAST(:u AS uuid), :r)"
            ),
            {"o": inv["org_id"], "u": uid, "r": role},
        )
    await db.execute(
        text(
            "UPDATE organization_invites SET status = 'accepted', accepted_at = now() "
            "WHERE id = CAST(:i AS uuid)"
        ),
        {"i": inv["id"]},
    )
    member_count = int((await db.execute(
        text("SELECT count(*) FROM organization_members WHERE org_id = CAST(:o AS uuid)"),
        {"o": inv["org_id"]},
    )).scalar() or 0)
    return OrgOut(
        id=org["id"], name=org["name"], slug=org["slug"], kind=org["kind"],
        plan_tier=org["plan_tier"], status=org["status"], role=role,
        member_count=member_count, seat_limit=SEAT_LIMIT.get(org["plan_tier"], 1),
    )
