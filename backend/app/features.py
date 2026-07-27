"""Tier-based feature entitlements — Wave 12.

Two principles, load-bearing for the product:
1. A veteran's OWN self-help is never paywalled. Every claim tool (conditions,
   evidence, rating math, documents, appeals, corrections, the whole individual
   experience) is free, forever, on a personal workspace. That's the mission.
2. Tiers gate ORG / ENTERPRISE capabilities — multiple seats, staff-see-their-
   veterans, the admin console, bulk operations, white-label. This is what a VSO,
   clinic, or agency pays for.

The tier is the ACTIVE workspace's `plan_tier` (organizations.plan_tier). Billing
(Wave 14, Lago) sets it; this module only READS it. `require_feature(...)` is the
gate; `entitlements_for(...)` produces the summary the frontend uses to show/hide UI.

Personal workspaces are implicitly 'free' but get every INDIVIDUAL feature — the
gated feature keys below are all team/enterprise concerns a personal workspace never
needs, so nothing here restricts a solo veteran.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .deps import current_workspace_id, get_db

# Ordered low → high. Rank by index.
TIERS: list[str] = ["free", "pro", "team", "enterprise"]


def tier_rank(tier: str | None) -> int:
    try:
        return TIERS.index((tier or "free").lower())
    except ValueError:
        return 0  # unknown tier code → treat as free (fail safe, never over-grant)


# Minimum tier required for each ORG feature. (Individual veteran tools are absent
# here on purpose — they are never gated.) Seat counts are advisory limits the org
# console/billing enforces; -1 = unlimited.
FEATURE_MIN_TIER: dict[str, str] = {
    "org_workspaces": "team",       # create/run a multi-member team workspace
    "org_invites": "team",          # invite teammates
    "staff_caseload": "team",       # staff see the veterans assigned to them (with consent)
    "org_admin_console": "team",    # the admin/seat-management console
    "bulk_operations": "team",      # batch actions across a caseload
    "white_label": "enterprise",    # custom branding
    "sso_byoidp": "enterprise",     # bring-your-own IdP
    "priority_support": "pro",
}

SEAT_LIMIT: dict[str, int] = {"free": 1, "pro": 1, "team": 25, "enterprise": -1}

# The public plan catalog (Wave 14) — what each tier is, for the pricing/upgrade UI.
# `price_monthly` is USD; None = "let's talk" (enterprise). Individual veteran self-help
# is free forever and lives OUTSIDE this catalog on a personal workspace — these plans
# describe ORG/team capability. Lago is the source of truth for actual billing; this is
# the descriptive catalog the app renders, not a charging authority.
PLAN_CATALOG: list[dict] = [
    {
        "tier": "free",
        "name": "Individual",
        "price_monthly": 0,
        "audience": "Every veteran, always free",
        "highlights": [
            "The complete self-help claim toolkit",
            "Conditions, evidence, rating math, documents",
            "Appeals, records corrections, Claim Plan",
            "Your private personal workspace",
        ],
    },
    {
        "tier": "team",
        "name": "Team",
        "price_monthly": 49,
        "audience": "VSOs, clinics, county veterans offices",
        "highlights": [
            "Everything in Individual, for your whole team",
            "Up to 25 seats, invite teammates",
            "Shared caseload — assign veterans to caseworkers",
            "Consent capture + full audit trail",
        ],
    },
    {
        "tier": "enterprise",
        "name": "Enterprise",
        "price_monthly": None,
        "audience": "Large service organizations & agencies",
        "highlights": [
            "Everything in Team, unlimited seats",
            "White-label branding",
            "Bring-your-own identity provider (SSO)",
            "Priority support",
        ],
    },
]


def has_feature(tier: str | None, feature: str) -> bool:
    need = FEATURE_MIN_TIER.get(feature)
    if need is None:
        return True  # ungated (individual) feature — always available
    return tier_rank(tier) >= tier_rank(need)


def features_for(tier: str | None) -> list[str]:
    return [f for f in FEATURE_MIN_TIER if has_feature(tier, f)]


async def active_tier(
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
) -> str:
    """The plan_tier of the active workspace ('free' if somehow unreadable)."""
    row = (
        await db.execute(
            text("SELECT plan_tier FROM organizations WHERE id = CAST(:w AS uuid) LIMIT 1"),
            {"w": workspace_id},
        )
    ).first()
    return (row[0] if row else None) or "free"


def require_feature(feature: str):
    """Dependency factory: 402/403 when the active workspace's tier lacks `feature`."""

    async def _dep(tier: str = Depends(active_tier)) -> str:
        if not has_feature(tier, feature):
            need = FEATURE_MIN_TIER.get(feature, "team")
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"This is a {need}-tier feature. Upgrade this workspace's plan to "
                    "enable it."
                ),
            )
        return tier

    return _dep
