"""Registration (closed-instance bootstrap semantics) and login."""

from __future__ import annotations

import logging
import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import current_user
from ..email import send_password_reset_email, send_verification_email
from ..models import User
from ..schemas import (
    AuthConfigOut,
    EmailIn,
    LoginIn,
    PasswordResetIn,
    RegisterIn,
    SimpleMessage,
    TokenIn,
    TokenOut,
    UserOut,
)
from ..security import (
    create_access_token,
    hash_password,
    make_purpose_token,
    password_fingerprint,
    verify_password,
    verify_purpose_token,
)

log = logging.getLogger("veteran_ops.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


def _require_password_login() -> None:
    if not settings.password_login_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Password sign-in is not enabled on this instance.",
        )


async def _send_verify_link(user: User) -> None:
    token = make_purpose_token(
        "verify-email", str(user.id), settings.verify_token_minutes, email=user.email
    )
    base = settings.public_base
    link = f"{base}/verify-email#token={token}" if base else f"(set PUBLIC_BASE) token={token}"
    await send_verification_email(user.email, link)


@router.get("/config", response_model=AuthConfigOut)
async def auth_config(db: AsyncSession = Depends(get_session)) -> AuthConfigOut:
    """Public auth capabilities so the login screen knows what to offer."""
    if not settings.password_login_enabled:
        registration_mode = "closed"
    elif settings.allow_registration:
        registration_mode = "open"
    else:
        user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
        registration_mode = "bootstrap" if user_count == 0 else "closed"
    return AuthConfigOut(
        sso_enabled=settings.keycloak_enabled,
        password_login_enabled=settings.password_login_enabled,
        registration_open=registration_mode != "closed",
        registration_mode=registration_mode,
        email_enabled=settings.email_enabled,
        password_reset_enabled=bool(
            settings.password_login_enabled and settings.email_enabled and settings.public_base
        ),
    )


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn, db: AsyncSession = Depends(get_session)) -> TokenOut:
    _require_password_login()
    # Closed-instance gate: when registration is off, only the very first account may
    # be created (operator bootstrap); after that the endpoint is closed.
    if not settings.allow_registration:
        user_count = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
        if user_count > 0:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Registration is closed on this instance.",
            )
    existing = (
        await db.execute(select(User).where(User.email == payload.email.lower()))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with that email already exists")
    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        email_verified=False,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    # Send the verification link (best-effort — never blocks sign-up). The user is
    # logged in immediately; a banner nudges them to verify.
    await _send_verify_link(user)
    token = create_access_token(str(user.id), user.email)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginIn, db: AsyncSession = Depends(get_session)) -> TokenOut:
    _require_password_login()
    user = (
        await db.execute(select(User).where(User.email == payload.email.lower()))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    token = create_access_token(str(user.id), user.email)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)


# ── Email verification (Wave 12) ─────────────────────────────────────────────

@router.post("/verify-email/request", response_model=SimpleMessage)
async def request_verification(user: User = Depends(current_user)) -> SimpleMessage:
    """Resend the current user's verification link (no-op if already verified)."""
    if user.email_verified:
        return SimpleMessage(ok=True, message="Your email is already verified.")
    await _send_verify_link(user)
    return SimpleMessage(ok=True, message="Verification email sent.")


@router.post("/verify-email/confirm", response_model=SimpleMessage)
async def confirm_verification(
    payload: TokenIn, db: AsyncSession = Depends(get_session)
) -> SimpleMessage:
    """Confirm an email from the emailed link. Self-authenticating (the signed token IS
    the proof), so it works from a fresh browser with no session."""
    try:
        claims = verify_purpose_token(payload.token, "verify-email")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    user = await db.get(User, uuid.UUID(str(claims["sub"])))
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    if not user.email_verified:
        user.email_verified = True
        await db.flush()
    return SimpleMessage(ok=True, message="Email verified. Thank you.")


# ── Password reset (Wave 12) ─────────────────────────────────────────────────

@router.post("/password/forgot", response_model=SimpleMessage)
async def forgot_password(
    payload: EmailIn, db: AsyncSession = Depends(get_session)
) -> SimpleMessage:
    """Begin a password reset. Always returns the same message — never reveals whether
    an account exists (no user enumeration)."""
    _require_password_login()
    if not settings.email_enabled or not settings.public_base:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Password reset email is not configured on this instance.",
        )
    generic = SimpleMessage(
        ok=True, message="If an account exists for that email, a reset link is on its way."
    )
    email = payload.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        return generic
    # SSO-/Brigade-only accounts (sentinel hash) sign in through their IdP — never mint
    # a local password for them via a reset link (that would sidestep the SSO
    # entitlement gate). Return the same neutral message; send nothing.
    if (user.password_hash or "").startswith("!"):
        return generic
    token = make_purpose_token(
        "pw-reset", str(user.id), settings.reset_token_minutes,
        fp=password_fingerprint(user.password_hash),
    )
    base = settings.public_base
    link = f"{base}/reset-password#token={token}" if base else f"(set PUBLIC_BASE) token={token}"
    await send_password_reset_email(user.email, link)
    return generic


@router.post("/password/reset", response_model=SimpleMessage)
async def reset_password(
    payload: PasswordResetIn, db: AsyncSession = Depends(get_session)
) -> SimpleMessage:
    """Complete a password reset. The token's fingerprint must still match the account's
    current password hash, so a link is single-use (a completed reset invalidates any
    others). A successful reset also proves email control → marks the email verified."""
    _require_password_login()
    try:
        claims = verify_purpose_token(payload.token, "pw-reset")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    user = await db.get(User, uuid.UUID(str(claims["sub"])))
    if user is None or claims.get("fp") != password_fingerprint(user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired.")
    # Defense in depth against a forged token: never convert an IdP-only account into a
    # local-login one (forgot_password won't issue such a token, so this shouldn't be
    # reachable, but a leaked jwt_secret must not open this door either).
    if (user.password_hash or "").startswith("!"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This account signs in with Unicorn Commander — password reset isn't available.",
        )
    user.password_hash = hash_password(payload.password)
    user.email_verified = True
    await db.flush()
    return SimpleMessage(ok=True, message="Your password has been reset. You can sign in now.")
