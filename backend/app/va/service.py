"""va_connections store: lookup, upsert-on-connect, refresh-when-expired,
needs_reconnect bookkeeping, and the one authenticated-call helper the router
uses.

Token lifecycle:
  • connect callback → upsert_connection() stores the token set (RLS-fenced).
  • before every data call, ensure_fresh() refreshes when the access token is
    within _REFRESH_SKEW of expiry (refresh_token grant) and persists the new
    set (VA rotates refresh tokens — always store what came back).
  • a 401/403 from a data endpoint gets ONE forced-refresh retry; if that also
    fails the connection is marked needs_reconnect (meta flag) and the caller
    gets VaAuthError → /va/status shows needs_reconnect until the veteran
    reconnects at VA.gov.

Token values are never logged and never placed in audit meta.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import session_for_user
from ..models import VaConnection
from . import lighthouse
from .lighthouse import VaApi, VaAuthError
from .token_crypto import TokenEncryptionError, decrypt_token, encrypt_token

# Refresh this long before nominal expiry so a token can't die mid-request.
_REFRESH_SKEW = timedelta(seconds=60)

# The router + callback (which has no request session) share this; tests
# monkeypatch it to their own session factory, same as intake/process.py.
user_session = asynccontextmanager(session_for_user)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite (tests) hands back naive datetimes; treat naive as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def expires_at_from(tokens: dict) -> datetime | None:
    expires_in = tokens.get("expires_in")
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return _utcnow() + timedelta(seconds=int(expires_in))
    return None


async def get_connection(
    db: AsyncSession, uid: str, api_key: str
) -> VaConnection | None:
    """RLS is the primary fence; the explicit user filter is defense-in-depth
    (and keeps behavior testable on SQLite)."""
    return (
        await db.execute(
            select(VaConnection).where(
                VaConnection.user_id == uuid.UUID(str(uid)),
                VaConnection.provider == "lighthouse",
                VaConnection.api == api_key,
            )
        )
    ).scalar_one_or_none()


async def list_connections(db: AsyncSession, uid: str) -> list[VaConnection]:
    return list(
        (
            await db.execute(
                select(VaConnection).where(
                    VaConnection.user_id == uuid.UUID(str(uid)),
                    VaConnection.provider == "lighthouse",
                ).order_by(VaConnection.api)
            )
        )
        .scalars()
        .all()
    )


async def upsert_connection(
    db: AsyncSession, uid: str, api: VaApi, tokens: dict
) -> VaConnection:
    """Store (or replace — reconnect) the veteran's consented token set."""
    conn = await get_connection(db, uid, api.key)
    if conn is None:
        conn = VaConnection(user_id=uuid.UUID(str(uid)), provider="lighthouse", api=api.key)
        db.add(conn)
    _apply_tokens(conn, tokens)
    conn.meta = {**(conn.meta or {}), "needs_reconnect": False}
    await db.flush()
    await db.refresh(conn)
    return conn


def _apply_tokens(conn: VaConnection, tokens: dict) -> None:
    conn.access_token = encrypt_token(tokens["access_token"])
    # VA rotates refresh tokens; keep the previous one only if none came back.
    refresh = tokens.get("refresh_token")
    if refresh:
        conn.refresh_token = encrypt_token(refresh)
    conn.token_expires_at = expires_at_from(tokens)
    granted = tokens.get("scope")
    if isinstance(granted, str) and granted.strip():
        conn.scope_set = granted.strip()[:512]


def needs_reconnect(conn: VaConnection | None) -> bool:
    return bool(conn is not None and (conn.meta or {}).get("needs_reconnect"))


def _mark_stale(conn: VaConnection) -> None:
    conn.meta = {**(conn.meta or {}), "needs_reconnect": True}


def _is_expired(conn: VaConnection) -> bool:
    exp = _aware(conn.token_expires_at)
    return exp is not None and exp <= _utcnow() + _REFRESH_SKEW


async def ensure_fresh(db: AsyncSession, conn: VaConnection, *, force: bool = False) -> str:
    """Return a usable access token, refreshing (and persisting) when expired.
    Raises VaAuthError — after marking needs_reconnect — when refresh isn't
    possible or is declined."""
    api = lighthouse.get_api(conn.api)
    try:
        access_token = decrypt_token(conn.access_token)
        refresh_token = decrypt_token(conn.refresh_token)
    except TokenEncryptionError as exc:
        _mark_stale(conn)
        await db.flush()
        raise VaAuthError("Your VA connection must be reconnected securely.") from exc
    if not force and not _is_expired(conn):
        if not access_token:
            raise VaAuthError("Your VA connection must be reconnected securely.")
        return access_token
    if not refresh_token:
        _mark_stale(conn)
        await db.flush()
        raise VaAuthError("Your VA connection expired — please reconnect at VA.gov.")
    try:
        tokens = await lighthouse.refresh_tokens(api, refresh_token=refresh_token)
    except VaAuthError:
        _mark_stale(conn)
        await db.flush()
        raise
    _apply_tokens(conn, tokens)
    conn.meta = {**(conn.meta or {}), "needs_reconnect": False}
    await db.flush()
    token = decrypt_token(conn.access_token)
    if not token:  # pragma: no cover - token response contract requires this field
        raise VaAuthError("VA did not return a usable access token.")
    return token


async def va_call(
    db: AsyncSession,
    conn: VaConnection,
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
) -> dict:
    """One data call on a stored connection, with expiry-refresh up front and a
    single forced-refresh retry on 401/403. Marks the row needs_reconnect when
    VA definitively rejects the credentials."""
    api = lighthouse.get_api(conn.api)
    token = await ensure_fresh(db, conn)
    try:
        return await lighthouse.api_request(
            api, method, path, access_token=token, json_body=json_body
        )
    except VaAuthError:
        pass  # token may have been revoked server-side — try one hard refresh
    try:
        token = await ensure_fresh(db, conn, force=True)
        return await lighthouse.api_request(
            api, method, path, access_token=token, json_body=json_body
        )
    except VaAuthError:
        _mark_stale(conn)
        await db.flush()
        raise
