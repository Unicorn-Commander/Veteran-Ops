#!/usr/bin/env python3
"""Manual VA Lighthouse SANDBOX smoke test — NOT collected by pytest.

Walks the real OAuth Authorization Code + PKCE flow against
https://sandbox-api.va.gov with the sandbox test users, then exercises the
data endpoints through the app's own client + normalizers, so what you see is
exactly what /va/sync and /va/claims will return.

Prereqs (one-time):
  1. Sign up at https://developer.va.gov/onboarding — request sandbox access
     for "Veteran Service History and Eligibility" and "Benefits Claims"
     (Authorization Code Grant). You'll get a client id (and optionally a
     secret) per signup.
  2. Register a redirect URI. Any URI works for this script (you paste the
     redirected URL back), but it must EXACTLY match what's registered —
     e.g. https://valor.magicunicorn.dev/api/va/callback .
  3. Sandbox test-user credentials (ID.me/Login.gov test accounts) are listed
     on the developer portal after signup.

Usage (from backend/, reads .env or environment):
  VA_CLIENT_ID=... [VA_CLIENT_SECRET=...] [VA_REDIRECT_BASE=https://...] \
      python tests/manual_va_sandbox.py verification
  python tests/manual_va_sandbox.py claims
  python tests/manual_va_sandbox.py claims --itf   # ALSO files a test Intent
                                                   # to File (sandbox only!)

Flow: prints the authorize URL → you open it in a browser, sign in as a
sandbox test user, consent → the browser lands on your redirect URI (it will
likely 404 — fine) → paste that full URL here → the script exchanges the code
(PKCE) and calls the APIs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.config import settings  # noqa: E402
from app.va import lighthouse, normalize  # noqa: E402


def _check_config() -> None:
    problems = []
    if not settings.va_client_id:
        problems.append("VA_CLIENT_ID is not set")
    if not settings.va_public_base:
        problems.append("VA_REDIRECT_BASE (or SSO_REDIRECT_BASE) is not set")
    if "sandbox" not in settings.va_base_url:
        problems.append(
            f"VA_BASE_URL={settings.va_base_url!r} is not the sandbox — refusing "
            "to smoke-test against production"
        )
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(2)


def _code_from_pasted_url(pasted: str) -> str:
    query = urllib.parse.urlparse(pasted.strip()).query
    params = dict(urllib.parse.parse_qsl(query))
    if params.get("error"):
        print(f"VA returned an error: {params['error']} "
              f"({params.get('error_description', '')})")
        sys.exit(1)
    code = params.get("code")
    if not code:
        print("No ?code= found in that URL — paste the FULL redirected URL.")
        sys.exit(1)
    return code


def _show(label: str, data) -> None:
    print(f"\n── {label} " + "─" * max(0, 60 - len(label)))
    print(json.dumps(data, indent=2, default=str))


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("api", choices=sorted(lighthouse.APIS),
                    help="which API family to walk")
    ap.add_argument("--itf", action="store_true",
                    help="claims only: ALSO file a test Intent to File (0966)")
    args = ap.parse_args()

    _check_config()
    api = lighthouse.get_api(args.api)

    verifier, challenge = lighthouse.make_pkce()
    url = lighthouse.build_authorize_url(
        api, state="manual-smoke-test", code_challenge=challenge
    )
    print(f"\nAPI:          {api.label}")
    print(f"Base:         {settings.va_base_url}")
    print(f"Client:       {settings.va_client_id[:8]}… "
          f"({'confidential' if settings.va_client_secret else 'public PKCE'})")
    print(f"Redirect URI: {settings.va_redirect_uri}")
    print("\n1) Open this URL in a browser and sign in as a SANDBOX test user:\n")
    print(url)
    print("\n2) After consent you'll land on the redirect URI (a 404 there is fine).")
    pasted = input("3) Paste the FULL redirected URL here:\n> ")
    code = _code_from_pasted_url(pasted)

    print("\nExchanging code (PKCE)…")
    tokens = await lighthouse.exchange_code(api, code=code, code_verifier=verifier)
    print(f"  ✓ access token received "
          f"(expires_in={tokens.get('expires_in')}s, "
          f"refresh={'yes' if tokens.get('refresh_token') else 'no'})")
    print(f"  ✓ granted scopes: {tokens.get('scope')}")
    at = tokens["access_token"]

    if args.api == "verification":
        raw = await lighthouse.api_request(api, "GET", "service_history", access_token=at)
        _show("service_history (normalized)", normalize.normalize_service_history(raw))
        raw = await lighthouse.api_request(api, "GET", "disability_rating", access_token=at)
        _show("disability_rating (normalized)", normalize.normalize_disability_rating(raw))
        try:
            raw = await lighthouse.api_request(
                api, "GET", "permanent_and_total_disability", access_token=at)
            _show("permanent_and_total (normalized)", normalize.normalize_pt(raw))
        except lighthouse.VaError as exc:
            print(f"\npermanent_and_total: {exc}")
        try:
            raw = await lighthouse.api_request(api, "GET", "status", access_token=at)
            _show("veteran status", normalize.normalize_veteran_status(raw))
        except lighthouse.VaError as exc:
            print(f"\nstatus: {exc}")
    else:
        raw = await lighthouse.api_request(api, "GET", "claims", access_token=at)
        _show("claims (normalized)", normalize.normalize_claims(raw))
        try:
            raw = await lighthouse.api_request(api, "GET", "forms/0966/active",
                                               access_token=at)
            _show("active Intent to File (normalized)", normalize.normalize_itf(raw))
        except lighthouse.VaNotFound:
            print("\nNo active Intent to File on record.")
        if args.itf:
            confirm = input(
                "\nFile a TEST Intent to File (compensation) in the sandbox? [y/N] ")
            if confirm.strip().lower() == "y":
                raw = await lighthouse.api_request(
                    api, "POST", "forms/0966", access_token=at,
                    json_body={"data": {"attributes": {"type": "compensation"}}})
                _show("filed Intent to File", normalize.normalize_itf(raw))

    # Best-effort cleanup: revoke what we minted for this smoke test.
    if tokens.get("refresh_token"):
        ok = await lighthouse.revoke_token(
            api, token=tokens["refresh_token"], token_type_hint="refresh_token")
        print(f"\nRevoked smoke-test tokens: {'yes' if ok else 'no (revoke endpoint declined)'}")
    print("\nDone — the backend flow (/va/connect → /va/callback → /va/sync) "
          "uses exactly these calls.")


if __name__ == "__main__":
    asyncio.run(main())
