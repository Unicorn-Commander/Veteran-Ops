#!/usr/bin/env python3
"""Validate the VA Lighthouse connector against the LIVE sandbox.

Non-interactive, network-only. Fetches each API's published
`.well-known/openid-configuration` from VA's sandbox and asserts that the URLs,
scopes, and client-auth method our connector (app/va/lighthouse.py) constructs
actually match what VA serves. This is the "tested against sandbox" gate for the
parts we can prove without an interactive OAuth login — it catches endpoint,
scope, or auth-method drift before we ever request production access.

What it CANNOT prove (needs an interactive auth-code login as a VA sandbox test
user, i.e. a staging deploy with a registered redirect URI): the live token
exchange and the real /disability_rating + /service_history data pull. Those are
the remaining E2E steps; the response PARSING for them is covered by the
normalize.py unit tests.

Run:  VA_BASE_URL=https://sandbox-api.va.gov .venv/bin/python scripts/validate_va_sandbox.py
Exit 0 = all checks pass.
"""

from __future__ import annotations

import os
import sys
import urllib.request
import json

# Ensure we validate against the sandbox regardless of the ambient config.
os.environ.setdefault("VA_BASE_URL", "https://sandbox-api.va.gov")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.va import lighthouse  # noqa: E402


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as r:  # noqa: S310 — fixed VA host
        return json.loads(r.read().decode())


def _check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'✓' if ok else '✗'} {name}" + (f" — {detail}" if detail else ""))
    return ok


def validate_api(key: str) -> bool:
    api = lighthouse.get_api(key)
    meta_url = lighthouse.oauth_url(api, ".well-known/openid-configuration")
    print(f"\n[{key}] {api.label}\n  metadata: {meta_url}")
    try:
        meta = _get_json(meta_url)
    except Exception as e:  # noqa: BLE001
        return _check("fetch metadata", False, str(e))

    ok = True
    ok &= _check(
        "authorization endpoint",
        meta.get("authorization_endpoint") == lighthouse.oauth_url(api, "authorization"),
        meta.get("authorization_endpoint", ""),
    )
    ok &= _check(
        "token endpoint",
        meta.get("token_endpoint") == lighthouse.oauth_url(api, "token"),
        meta.get("token_endpoint", ""),
    )
    ok &= _check(
        "revocation endpoint",
        meta.get("revocation_endpoint") == lighthouse.oauth_url(api, "revoke"),
        meta.get("revocation_endpoint", ""),
    )

    supported = set(meta.get("scopes_supported") or [])
    requested = set(api.scopes.split())
    missing = requested - supported
    ok &= _check(
        "requested scopes supported",
        not missing,
        f"requested={sorted(requested)}" + (f" MISSING={sorted(missing)}" if missing else ""),
    )

    auth_methods = set(meta.get("token_endpoint_auth_methods_supported") or [])
    # lighthouse.py posts the token request with HTTP Basic auth = client_secret_basic.
    ok &= _check(
        "client_secret_basic auth supported",
        "client_secret_basic" in auth_methods,
        f"server={sorted(auth_methods)}",
    )
    return ok


def main() -> int:
    print("Validating VA Lighthouse connector against LIVE sandbox "
          f"({lighthouse._base()}) …")
    # verification = what Rating Raider (claim/ratings) uses; claims = future.
    results = {key: validate_api(key) for key in ("verification", "claims")}
    print("\n" + "=" * 48)
    all_ok = all(results.values())
    for key, ok in results.items():
        print(f"  {key:14s} {'PASS' if ok else 'FAIL'}")
    print(f"\n{'ALL CHECKS PASS' if all_ok else 'SOME CHECKS FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
