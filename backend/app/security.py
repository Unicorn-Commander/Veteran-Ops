"""Password hashing and JWT helpers (native sessions, Brigade trust, uchub SSO)."""

from __future__ import annotations

import hashlib
import secrets
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import httpx
import jwt
from jwt import PyJWKClient

from .config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, email: str) -> str:
    """Mint a native session token. `sub` is the user id — the RLS key."""
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Validate a NATIVE session token. Rejects tokens carrying a purpose/state marker
    even though they're signed with the same secret+alg: an email-verify / password-
    reset token (`p` claim) or an OIDC CSRF-state token (`k` claim) must NEVER be
    replayable as a session bearer (it would confer a full account session from a link
    scoped to one narrow action). This is the missing negative counterpart to the
    positive `p`/`k` checks in verify_purpose_token / verify_sso_state."""
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp"]},
        leeway=30,
    )
    if payload.get("p") is not None or payload.get("k") is not None:
        raise jwt.InvalidTokenError("not a session token")
    return payload


# ── Purpose-scoped signed tokens (email verification, password reset) — Wave 12 ─────
# Stateless links: a short-lived HS256 token carrying a `p` (purpose) claim so a token
# minted for one flow can never be replayed in another (or as a session JWT). The
# purpose check mirrors verify_sso_state's k-claim guard.

def make_purpose_token(purpose: str, sub: str, minutes: int, **extra: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict = {
        "p": purpose,
        "sub": str(sub),
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
        **extra,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_purpose_token(token: str, purpose: str) -> dict:
    """Verify signature + expiry AND that the token was minted for exactly `purpose`.
    Raises jwt.InvalidTokenError on any mismatch."""
    claims = jwt.decode(
        token, settings.jwt_secret, algorithms=["HS256"],
        options={"require": ["exp", "sub"]}, leeway=30,
    )
    if claims.get("p") != purpose:
        raise jwt.InvalidTokenError("wrong token purpose")
    return claims


def password_fingerprint(password_hash: str) -> str:
    """Short digest of the current password hash, embedded in a reset token so that
    completing a reset (which changes the hash) invalidates any other outstanding reset
    links for the account."""
    return hashlib.sha256((password_hash or "").encode()).hexdigest()[:16]


# ── Organization invitations — Wave 12 ──────────────────────────────────────────────
# A high-entropy raw token travels only in the emailed link; the DB stores its SHA-256.

def generate_invite_token() -> str:
    return secrets.token_urlsafe(32)


def hash_invite_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def decode_brigade_token(token: str) -> dict:
    """Validate a per-user token minted by a trusted suite caller (Brigade): HS256 with
    the SHARED brigade secret, audience-scoped. A separate trust domain from native
    tokens — this secret can only mint aud=valor-ops tokens, resolved by email."""
    if not settings.brigade_jwt_secret:
        raise jwt.InvalidTokenError("brigade auth not configured")
    return jwt.decode(
        token,
        settings.brigade_jwt_secret,
        algorithms=["HS256"],
        audience=settings.brigade_audience,
        options={"require": ["exp", "aud"]},
        leeway=30,
    )


# ── Keycloak / uchub SSO (OIDC Authorization Code) ──────────────────────────────────
# A confidential client (client_secret) does the code↔token exchange server-side; the
# id_token is verified against the realm JWKS. The entitlement gate lives in the router.

_jwks_client: PyJWKClient | None = None
# auth.unicorncommander.ai sits behind Cloudflare, which 403s the default Python-urllib
# User-Agent that PyJWKClient uses. Send a browser UA so the JWKS fetch isn't bot-blocked
# (the httpx token-exchange call already passes for the same reason).
_JWKS_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            f"{settings.oidc_issuer}/protocol/openid-connect/certs",
            headers={"User-Agent": _JWKS_UA},
        )
    return _jwks_client


def make_sso_state(base: str | None = None) -> str:
    """Stateless CSRF state: a short-lived signed token verified on callback. The
    chosen redirect `base` is carried inside so the callback rebuilds the SAME
    redirect_uri (OAuth requires authorize and token-exchange to match) and lands the
    veteran back on the host they signed in from."""
    now = datetime.now(timezone.utc)
    payload = {"k": "sso-state", "nonce": uuid.uuid4().hex, "iat": now, "exp": now + timedelta(minutes=10)}
    if base:
        payload["b"] = base.rstrip("/")
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def verify_sso_state(state: str) -> str | None:
    """Signature+expiry AND purpose: without the k-claim check, any unexpired
    token signed with jwt_secret (e.g. a native session JWT) would pass as
    OIDC state, collapsing the CSRF-state trust domain into the session one.
    Returns the carried redirect base (or None), so the callback can only ever use a
    base WE signed at login — never one an attacker supplies."""
    claims = jwt.decode(
        state, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp"]}, leeway=10
    )
    if claims.get("k") != "sso-state":
        raise jwt.InvalidTokenError("not an sso-state token")
    base = claims.get("b")
    return base if isinstance(base, str) and base else None


def sso_authorize_url(state: str, redirect_uri: str | None = None) -> str:
    params = {
        "client_id": settings.keycloak_client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri or settings.sso_callback_url,
        "state": state,
    }
    return f"{settings.oidc_issuer}/protocol/openid-connect/auth?" + urllib.parse.urlencode(params)


async def sso_exchange_code(code: str, redirect_uri: str | None = None) -> dict:
    """Trade the authorization code for the token set at the Keycloak token endpoint.
    `redirect_uri` MUST match the one used at authorize (per OAuth)."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"{settings.oidc_issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri or settings.sso_callback_url,
                "client_id": settings.keycloak_client_id,
                "client_secret": settings.keycloak_client_secret,
            },
        )
        resp.raise_for_status()
        return resp.json()


def validate_id_token(id_token: str) -> dict:
    """Verify signature (realm JWKS, RS256) + audience + issuer + expiry. SYNC (does a
    cached JWKS fetch) — call via run_in_threadpool from async code."""
    signing_key = _jwks().get_signing_key_from_jwt(id_token)
    return jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256"],
        audience=settings.keycloak_client_id,
        issuer=settings.oidc_issuer,
        options={"require": ["exp", "iat"]},
        leeway=30,
    )


def decode_unverified(token: str) -> dict:
    """Read claims WITHOUT signature check — only safe for the access_token we just
    received directly from Keycloak's token endpoint over TLS (already trusted), used
    to harvest realm/client roles for the entitlement check."""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except Exception:  # noqa: BLE001
        return {}


def extract_entitlements(*claim_sets: dict) -> set[str]:
    """Collect entitlement strings from the configured claim (array or csv) plus realm
    and client roles, across every provided claim set (id_token + access_token)."""
    out: set[str] = set()
    claim = settings.sso_entitlement_claim
    cid = settings.keycloak_client_id
    for claims in claim_sets:
        if not isinstance(claims, dict):
            continue
        v = claims.get(claim)
        if isinstance(v, str):
            out.update(p.strip() for p in v.split(",") if p.strip())
        elif isinstance(v, (list, tuple)):
            out.update(str(p) for p in v)
        ra = claims.get("realm_access") or {}
        out.update(str(r) for r in (ra.get("roles") or []))
        res = (claims.get("resource_access") or {}).get(cid) or {}
        out.update(str(r) for r in (res.get("roles") or []))
    return out
