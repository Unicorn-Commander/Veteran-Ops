"""FastAPI dependencies: auth + the per-request RLS-scoped DB session.

The RLS contract: `current_user_id` resolves the caller from the bearer token,
then `get_db` opens ONE transaction with the `app.current_user_id` GUC pinned
(via set_config is_local) so the `user_isolation` policies fence every query.
Handlers must not commit() mid-request — SET LOCAL is per-transaction; use
flush() to obtain ids and let the teardown commit once at the end.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import SessionLocal
from .models import User
from .security import decode_brigade_token, decode_token

_bearer = HTTPBearer(auto_error=False)
_UNAUTH = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def current_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Resolve the caller's user id from a native Valor token or a trusted-suite
    (Brigade) token. This id is the RLS key for the whole request."""
    if creds is None or not creds.credentials:
        raise _UNAUTH
    token = creds.credentials
    # 1) Native Valor token (sub = user_id).
    payload: dict | None
    try:
        payload = decode_token(token)
    except Exception:  # noqa: BLE001 — fall through to the trusted-suite path
        payload = None
    if payload is not None:
        sub = payload.get("sub")
        if not sub:
            raise _UNAUTH
        return str(sub)
    # 2) Trusted-suite (Brigade) per-user token: aud-scoped, separate secret, email -> user.
    try:
        payload = decode_brigade_token(token)
    except Exception as exc:  # noqa: BLE001
        raise _UNAUTH from exc
    email = str(payload.get("email") or payload.get("sub") or "").strip().lower()
    if "@" not in email:
        raise _UNAUTH
    return await _resolve_brigade_user(email)


async def _resolve_brigade_user(email: str) -> str:
    """Map a Brigade-authenticated email to a Valor user id (auto-provisioning a
    no-local-login account on first use when enabled). The users table is NOT
    RLS-fenced, so this runs in a plain session before the RLS context is set."""
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            if not settings.brigade_auto_provision:
                raise _UNAUTH
            user = User(
                email=email, full_name="",
                password_hash="!brigade-no-login", email_verified=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return str(user.id)


def _personal_ws_id(uid: str) -> str:
    """Deterministic id for a user's personal workspace — same value here and in the
    db.py backfill, so self-provisioning never needs to read the new row back (which
    FORCE RLS would filter out before a membership exists)."""
    return str(uuid.UUID(hashlib.md5(f"personal:{uid}".encode()).hexdigest()))


async def _resolve_workspace(uid: str, requested: str | None) -> str:
    """The active workspace for this request: the requested one IF the caller is a
    member of it (else it's ignored — no cross-tenant access), otherwise their personal
    workspace. Auto-provisions a personal workspace for a user that has none."""
    async with SessionLocal() as s:
        # user context lets the member_self / org_visible RLS see the caller's rows
        await s.execute(text("SELECT set_config('app.current_user_id', :u, true)"), {"u": uid})
        rows = (await s.execute(text(
            "SELECT o.id::text AS id, o.kind, COALESCE(o.status,'active') AS status "
            "FROM organizations o JOIN organization_members m ON m.org_id = o.id "
            "WHERE m.user_id = CAST(:u AS uuid)"
        ), {"u": uid})).mappings().all()
        active = [r for r in rows if r["status"] == "active"]
        if active:
            ids = {r["id"] for r in active}
            if requested and requested in ids:
                await s.commit()
                return requested
            personal = next((r["id"] for r in active if r["kind"] == "personal"), None)
            await s.commit()
            return personal or sorted(ids)[0]

        # No membership yet (a new or pre-tenancy user) → provision a personal
        # workspace with a DETERMINISTIC id (no RLS-filtered read-back needed).
        # A PLAIN insert (ON CONFLICT fails the RLS arbiter check under FORCE RLS
        # when the new org isn't yet visible); a savepoint swallows the rare
        # unique-violation race so a concurrent first request doesn't 500.
        ws_id = _personal_ws_id(uid)
        try:
            async with s.begin_nested():
                await s.execute(text(
                    "INSERT INTO organizations (id, name, slug, kind, plan_tier, status) "
                    "SELECT CAST(:o AS uuid), "
                    "  COALESCE(NULLIF(u.full_name,''), split_part(u.email,'@',1)) || ' (personal)', "
                    "  'personal-' || u.id::text, 'personal', 'free', 'active' "
                    "FROM users u WHERE u.id = CAST(:u AS uuid)"
                ), {"o": ws_id, "u": uid})
        except IntegrityError:
            pass  # already provisioned by a racing request — fine
        await s.execute(text(
            "INSERT INTO organization_members (id, org_id, user_id, role) "
            "SELECT gen_random_uuid(), CAST(:o AS uuid), CAST(:u AS uuid), 'owner' "
            "WHERE NOT EXISTS (SELECT 1 FROM organization_members m "
            "                  WHERE m.org_id = CAST(:o AS uuid) AND m.user_id = CAST(:u AS uuid))"
        ), {"o": ws_id, "u": uid})
        await s.commit()
        return ws_id


async def current_workspace_id(
    request: Request, uid: str = Depends(current_user_id)
) -> str:
    """The tenant scope for this request. Honors an `X-Workspace-Id` header only when
    the caller is a member of it; otherwise falls back to their personal workspace."""
    requested = request.headers.get("X-Workspace-Id")
    return await _resolve_workspace(uid, requested)


async def get_db(
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
) -> AsyncIterator[AsyncSession]:
    """One transaction per request with BOTH RLS GUCs pinned: the active workspace
    (fences veteran data) and the caller (fences membership/org lookups)."""
    async with SessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_user_id', :uid, true)"),
            {"uid": uid},
        )
        await session.execute(
            text("SELECT set_config('app.current_workspace', :wid, true)"),
            {"wid": workspace_id},
        )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def current_user(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> User:
    user = await db.get(User, uuid.UUID(uid))
    if user is None:
        raise _UNAUTH
    return user


async def require_platform_admin(user: User = Depends(current_user)) -> User:
    """Require an instance operator, independent of active-workspace ownership."""
    if not settings.platform_admin_email_allowed(user.email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires instance operator access.",
        )
    return user
