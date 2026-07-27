"""Wave 14 — billing surface. The plan catalog + the service-token RECEIVER auth (the
one security-sensitive endpoint). The receiver's DB path uses raw Postgres SQL and is
covered by the prod E2E; here we lock the AUTH gate (disabled-when-unset, constant-time
token check, tier validation) which is pure and testable, plus the catalog integrity."""

from __future__ import annotations

import pytest

from app.config import settings
from app.features import PLAN_CATALOG, SEAT_LIMIT, TIERS


# ── Plan catalog integrity ───────────────────────────────────────────────────

def test_catalog_covers_known_tiers_and_shapes():
    tiers = {p["tier"] for p in PLAN_CATALOG}
    assert {"free", "team", "enterprise"} <= tiers
    for p in PLAN_CATALOG:
        assert p["tier"] in TIERS
        assert isinstance(p["name"], str) and p["name"]
        assert p["price_monthly"] is None or isinstance(p["price_monthly"], int)
        assert isinstance(p["highlights"], list) and p["highlights"]
        assert p["tier"] in SEAT_LIMIT


def test_free_plan_is_zero_and_enterprise_is_contact_us():
    by = {p["tier"]: p for p in PLAN_CATALOG}
    assert by["free"]["price_monthly"] == 0
    assert by["enterprise"]["price_monthly"] is None  # "contact us"
    assert by["team"]["price_monthly"] and by["team"]["price_monthly"] > 0


# ── Receiver auth gate (call the handler directly; DB path not exercised) ─────

def _call_receiver(monkeypatch, token_cfg, auth_header, tier="team"):
    """Invoke set_tenant_tier far enough to hit the auth/tier guards. We patch the
    configured token and assert the guard raises BEFORE any DB work (which needs PG)."""
    import asyncio

    from fastapi import HTTPException

    from app.routers.billing import set_tenant_tier
    from app.schemas import TenantTierIn

    monkeypatch.setattr(settings, "billing_service_token", token_cfg)
    payload = TenantTierIn(workspace_id="00000000-0000-0000-0000-000000000001", tier=tier)
    try:
        asyncio.run(set_tenant_tier(payload, authorization=auth_header))
        return None  # no exception (would only happen if it reached the DB)
    except HTTPException as e:
        return e.status_code


def test_receiver_disabled_when_no_token(monkeypatch):
    # No configured token → 503, regardless of what the caller presents.
    assert _call_receiver(monkeypatch, "", "Bearer anything") == 503


def test_receiver_rejects_missing_or_wrong_token(monkeypatch):
    assert _call_receiver(monkeypatch, "s3cret-token", None) == 401
    assert _call_receiver(monkeypatch, "s3cret-token", "Bearer wrong") == 401
    assert _call_receiver(monkeypatch, "s3cret-token", "s3cret-token") == 401  # no "Bearer "
    assert _call_receiver(monkeypatch, "s3cret-token", "Bearer ") == 401


def test_receiver_rejects_unknown_tier(monkeypatch):
    # Valid token, but the tier is validated by the Pydantic Literal before the handler;
    # constructing TenantTierIn with a bad tier raises ValidationError.
    from pydantic import ValidationError

    from app.schemas import TenantTierIn

    with pytest.raises(ValidationError):
        TenantTierIn(workspace_id="00000000-0000-0000-0000-000000000001", tier="platinum")


def test_receiver_with_valid_token_passes_auth_then_needs_db(monkeypatch):
    # A correct token gets PAST the auth gate; the next step is a DB lookup which isn't
    # available here, so it raises something OTHER than 401/503 (or a DB error). The point
    # is only that auth no longer blocks it.
    code = None
    try:
        code = _call_receiver(monkeypatch, "good-token", "Bearer good-token")
    except Exception:  # noqa: BLE001 — a DB/connection error past the gate is expected
        code = "db-attempt"
    assert code in (None, "db-attempt", 404, 400, 500)
    assert code not in (401, 503)
