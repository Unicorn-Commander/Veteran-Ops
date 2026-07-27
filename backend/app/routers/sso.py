"""unicorncommander.ai (uchub) Keycloak SSO — OIDC Authorization Code flow.

Mirrors the suite pattern (glitter-mane/email-ops): GET /auth/keycloak redirects to
Keycloak; GET /auth/keycloak/callback exchanges the code, validates the id_token,
ENFORCES the entitlement gate, resolves/provisions the Valor user, mints a NATIVE
Valor session token, and redirects to the SPA's /auth/sso-callback?token=… (the
frontend stores it).

Entitlement gate (self-service is OFF): a uchub identity may sign in only if its
token carries the `valor-ops` entitlement (a product key in the configured claim,
or a realm/client role) OR its email is on the bootstrap allowlist. Anyone else is
denied — being authenticated by Keycloak is necessary but NOT sufficient.
"""

from __future__ import annotations

import logging
import urllib.parse

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..models import User
from ..security import (
    create_access_token,
    decode_unverified,
    extract_entitlements,
    make_sso_state,
    sso_authorize_url,
    sso_exchange_code,
    validate_id_token,
    verify_sso_state,
)

log = logging.getLogger("veteran_ops.sso")
router = APIRouter(prefix="/auth/keycloak", tags=["auth"])


def _landing(base: str | None = None, **params: str) -> RedirectResponse:
    landing = settings.sso_frontend_landing_for(base) if base else settings.sso_frontend_landing
    url = landing + "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.get("")
async def keycloak_login(request: Request) -> RedirectResponse:
    """Redirect to the Keycloak (uchub) login page. The redirect base is derived from
    the host the veteran arrived on (allowlisted) so they land back on that same
    domain; the base is carried in the signed state through the OAuth round-trip."""
    if not settings.keycloak_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO is not configured")
    base = settings.sso_base_for_host(request.headers.get("host"))
    state = make_sso_state(base)
    return RedirectResponse(
        sso_authorize_url(state, settings.sso_callback_url_for(base)),
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/callback")
async def keycloak_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """OIDC callback: validate, gate on entitlement, mint a Valor session."""
    if not settings.keycloak_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "SSO is not configured")
    if error:
        return _landing(error="sso_failed")
    if not code or not state:
        return _landing(error="missing_code")
    try:
        base = verify_sso_state(state)  # the host we signed at login (or None)
    except Exception:  # noqa: BLE001
        return _landing(error="bad_state")

    # Code → tokens → verified identity. redirect_uri MUST match the login one.
    try:
        tokens = await sso_exchange_code(code, settings.sso_callback_url_for(base) if base else None)
        id_token = tokens.get("id_token")
        if not id_token:
            raise ValueError("no id_token in token response")
        id_claims = await run_in_threadpool(validate_id_token, id_token)
    except Exception as exc:  # noqa: BLE001
        log.warning("SSO token exchange/validation failed: %s", exc)
        return _landing(base, error="sso_failed")

    email = str(id_claims.get("email") or "").strip().lower()
    if "@" not in email:
        return _landing(base, error="no_email")
    # Default-deny: an ABSENT email_verified claim is treated as unverified —
    # accounts are keyed and merged by email, so only a proven email may log in.
    if id_claims.get("email_verified") is not True:
        return _landing(base, error="email_unverified")

    # Entitlement gate — authenticated is NOT enough.
    access_claims = decode_unverified(tokens.get("access_token") or "")
    entitlements = extract_entitlements(id_claims, access_claims)
    entitled = settings.sso_required_entitlement in entitlements
    if not (entitled or settings.sso_email_allowed(email)):
        log.info("SSO denied (no entitlement) for %s; had=%s", email, sorted(entitlements))
        return _landing(base, error="not_entitled")

    name = str(id_claims.get("name") or id_claims.get("given_name") or "").strip()
    avatar_url = _clean_picture(id_claims.get("picture"))
    uid = await _resolve_sso_user(email, name, avatar_url)
    if uid is None:
        return _landing(base, error="no_account")
    # Deliver the session token in the URL FRAGMENT, not the query string:
    # fragments never reach the server, so the token stays out of nginx/Traefik
    # access logs and Referer headers (the SPA also scrubs it from history).
    token = urllib.parse.urlencode({"token": create_access_token(uid, email)})
    return RedirectResponse(
        (settings.sso_frontend_landing_for(base) if base else settings.sso_frontend_landing) + "#" + token,
        status_code=status.HTTP_302_FOUND
    )


def _clean_picture(value: object) -> str | None:
    """The Keycloak `picture` claim (uchub `profile` scope) → a safe avatar URL, or
    None. Only http(s) URLs within the column bound are accepted — a hostile IdP must
    not be able to slip a `javascript:`/`data:` value into a src the UI renders."""
    url = str(value or "").strip()
    if url.startswith(("https://", "http://")) and len(url) <= 1024:
        return url
    return None


async def _resolve_sso_user(
    email: str, full_name: str, avatar_url: str | None
) -> str | None:
    """Map an entitled SSO identity to a Valor user id, auto-provisioning a
    no-local-password account on first login when sso_auto_provision is on. The
    users table is not RLS-fenced, so this runs in a plain session before RLS
    is set. The avatar is kept in sync with the veteran's Unicorn Commander profile
    photo on every login (a changed or removed OC photo propagates here)."""
    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()
        if user is None:
            if not settings.sso_auto_provision:
                return None
            user = User(
                email=email, full_name=full_name or "",
                avatar_url=avatar_url,
                password_hash="!sso-no-login", email_verified=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        elif user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            await session.commit()
        return str(user.id)
