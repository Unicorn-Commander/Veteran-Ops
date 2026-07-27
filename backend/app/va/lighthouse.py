"""VA Lighthouse OAuth (Authorization Code Grant + PKCE S256) + API HTTP calls.

Mirrors the proven Glitter Mane SMART-on-FHIR connector (medical/fhir_connect.py):
PKCE helpers, explicit endpoints, friendly errors, and NO token values in logs.

Lighthouse OAuth is PER-API FAMILY — each has its own authorization server:

    {base}/oauth2/{oauth_slug}/v1/authorization
    {base}/oauth2/{oauth_slug}/v1/token
    {base}/oauth2/{oauth_slug}/v1/revoke

(verified 2026-07 against the live sandbox .well-known/openid-configuration for
both `veteran-verification` and `claims`; S256 is the only supported challenge
method). Data lives under a separate versioned base per API (see APIS below).

Client auth: with va_client_secret set we are a confidential client → HTTP Basic
at the token/revoke endpoints IN ADDITION to PKCE; with it empty we are a public
PKCE-only client (client_id in the form body).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import urllib.parse
from typing import Any, NamedTuple

import httpx

from ..config import settings

log = logging.getLogger("veteran_ops.va")

_HTTP_TIMEOUT = 30.0
_UA = "RatingRaider/0.1 (+https://valor.magicunicorn.dev)"


class VaError(Exception):
    """Talking to VA failed — surfaced to the veteran as a friendly message,
    never a stack trace, and never containing a token."""


class VaAuthError(VaError):
    """The connection's tokens no longer work (revoked/expired beyond refresh)
    — the veteran needs to reconnect at VA.gov."""


class VaNotFound(VaError):
    """A 404 from a data endpoint (e.g. no active Intent to File)."""


class VaApi(NamedTuple):
    key: str          # our short name ("verification" | "claims")
    label: str        # human name for UI copy
    oauth_slug: str   # path segment of the per-API authorization server
    data_base: str    # versioned data base path
    scopes: str       # requested at consent; VA may grant a subset


# The API families we integrate. `offline_access` → refresh token, so a
# connection survives past the (short) access-token lifetime.
APIS: dict[str, VaApi] = {
    "verification": VaApi(
        key="verification",
        label="Veteran Service History and Eligibility",
        oauth_slug="veteran-verification",
        data_base="/services/veteran_verification/v2",
        scopes=(
            "openid profile offline_access "
            "service_history.read disability_rating.read "
            "permanent_and_total_disability.read veteran_status.read"
        ),
    ),
    "claims": VaApi(
        key="claims",
        label="Benefits Claims",
        oauth_slug="claims",
        data_base="/services/claims/v1",
        scopes="openid profile offline_access claim.read claim.write",
    ),
    # Patient Health (FHIR R4) is a designed-for follow-up: add an entry here
    # (oauth_slug="health", data_base="/services/fhir/v0/r4", patient/*.read
    # scopes) and the token store + refresh machinery already handle it.
}


def get_api(key: str) -> VaApi:
    api = APIS.get(key)
    if api is None:
        raise VaError(f"Unknown VA API {key!r}")
    return api


def _base() -> str:
    base = (settings.va_base_url or "").rstrip("/")
    # Operator config, not user input — but insist on https anywhere real.
    parts = urllib.parse.urlparse(base)
    if parts.scheme != "https" and parts.hostname not in ("localhost", "127.0.0.1", "testserver"):
        raise VaError("VA_BASE_URL must be an https URL.")
    return base


def oauth_url(api: VaApi, kind: str) -> str:
    """kind: authorization | token | revoke"""
    return f"{_base()}/oauth2/{api.oauth_slug}/v1/{kind}"


def data_url(api: VaApi, path: str) -> str:
    return f"{_base()}{api.data_base}/{path.lstrip('/')}"


# ── PKCE (S256) ──────────────────────────────────────────────────────────────

def make_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge)."""
    verifier = secrets.token_urlsafe(64)[:120]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


# ── Authorize URL ────────────────────────────────────────────────────────────

def build_authorize_url(api: VaApi, *, state: str, code_challenge: str) -> str:
    params = {
        "client_id": settings.va_client_id,
        "response_type": "code",
        "redirect_uri": settings.va_redirect_uri,
        "scope": api.scopes,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return oauth_url(api, "authorization") + "?" + urllib.parse.urlencode(params)


# ── Token endpoint (exchange / refresh) ──────────────────────────────────────

def _client_auth() -> tuple[str, str] | None:
    """Confidential-symmetric fallback: HTTP Basic when a secret is configured;
    None → public PKCE client (client_id goes in the form body)."""
    if settings.va_client_secret:
        return (settings.va_client_id, settings.va_client_secret)
    return None


async def _token_request(api: VaApi, data: dict[str, str]) -> dict[str, Any]:
    auth = _client_auth()
    if auth is None:
        data = {**data, "client_id": settings.va_client_id}
    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT, headers={"User-Agent": _UA, "Accept": "application/json"}
    ) as client:
        try:
            resp = await client.post(oauth_url(api, "token"), data=data, auth=auth)
        except httpx.HTTPError as exc:
            raise VaError("Couldn't reach VA right now — try again in a moment.") from exc
    if resp.status_code in (400, 401):
        # invalid_grant / revoked refresh token → the veteran must reconnect.
        # Log the grant type + status only — NEVER the payload (it has tokens).
        log.info("VA token request declined (api=%s, grant=%s, status=%s)",
                 api.key, data.get("grant_type"), resp.status_code)
        raise VaAuthError("VA declined the credentials — please reconnect at VA.gov.")
    if resp.status_code != 200:
        log.warning("VA token endpoint error (api=%s, status=%s)", api.key, resp.status_code)
        raise VaError(f"VA's sign-in service returned an error ({resp.status_code}).")
    try:
        tok = resp.json()
    except ValueError as exc:
        raise VaError("VA returned an unreadable token response.") from exc
    if not tok.get("access_token"):
        raise VaError("VA did not return an access token.")
    return tok


async def exchange_code(api: VaApi, *, code: str, code_verifier: str) -> dict[str, Any]:
    return await _token_request(
        api,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.va_redirect_uri,
            "code_verifier": code_verifier,
        },
    )


async def refresh_tokens(api: VaApi, *, refresh_token: str) -> dict[str, Any]:
    return await _token_request(
        api, {"grant_type": "refresh_token", "refresh_token": refresh_token}
    )


async def revoke_token(api: VaApi, *, token: str, token_type_hint: str) -> bool:
    """Best-effort revocation at the per-API revoke endpoint. Returns success;
    never raises — disconnect must always be able to delete the local row."""
    data = {"token": token, "token_type_hint": token_type_hint}
    auth = _client_auth()
    if auth is None:
        data["client_id"] = settings.va_client_id
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, headers={"User-Agent": _UA}
        ) as client:
            resp = await client.post(oauth_url(api, "revoke"), data=data, auth=auth)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001 — best-effort by contract
        log.info("VA token revocation unreachable (api=%s)", api.key)
        return False


# ── Authenticated data calls ─────────────────────────────────────────────────

async def api_request(
    api: VaApi,
    method: str,
    path: str,
    *,
    access_token: str,
    json_body: dict | None = None,
) -> dict[str, Any]:
    """One authenticated call to a Lighthouse data endpoint. Raises VaAuthError
    on 401/403 (caller refreshes or marks needs_reconnect), VaError otherwise.
    The Authorization header is never logged."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "User-Agent": _UA,
    }
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, headers=headers) as client:
        try:
            resp = await client.request(method, data_url(api, path), json=json_body)
        except httpx.HTTPError as exc:
            raise VaError("Couldn't reach VA right now — try again in a moment.") from exc
    if resp.status_code in (401, 403):
        log.info("VA API auth failure (api=%s, path=%s, status=%s)", api.key, path, resp.status_code)
        raise VaAuthError("Your VA connection is no longer valid — please reconnect.")
    if resp.status_code == 404:
        # e.g. no active Intent to File — callers that expect this handle it.
        raise VaNotFound(f"VA has no record for this request ({path}).")
    if resp.status_code >= 400:
        log.warning("VA API error (api=%s, path=%s, status=%s)", api.key, path, resp.status_code)
        raise VaError(f"VA returned an error ({resp.status_code}). Try again later.")
    try:
        return resp.json()
    except ValueError as exc:
        raise VaError("VA returned unreadable data.") from exc
