"""Billing — suite-aligned tier surface (Wave 14).

Valor-Ops does NOT own billing. The suite's billing/entitlement service (Lago) is the
source of truth for what an organization pays for; this app only:
  1. READS the active workspace's `plan_tier` to gate org features (features.py), and
  2. exposes a RECEIVER the suite calls to PUSH a tenant's tier when a subscription
     changes (POST /billing/tenant-tier, service-token authed).
It never writes to Lago or the shared entitlement store — that shared infra is operated
by Aaron + the entitlement-service owner. The pricing catalog + status endpoints here
are descriptive (drive the upgrade UI); they don't charge anyone.

Individual veteran self-help is free forever on a personal workspace and is never
affected by any of this — these endpoints concern ORG/team plans only.
"""

from __future__ import annotations

import json
import hmac
import hashlib
import time
import uuid
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import log as audit_log
from ..crediting import (
    CreditConfig,
    grant_credits,
    record_pool_claim,
    sponsorship_by_session,
)
from ..config import settings
from ..db import SessionLocal, session_for_user
from ..deps import current_user_id, current_workspace_id, get_db
from ..features import PLAN_CATALOG, SEAT_LIMIT, TIERS, active_tier, features_for
from ..models import Sponsorship, User
from ..rbac import current_role, is_manager
from ..schemas import (
    BillingStatusOut,
    CheckoutSessionIn,
    CheckoutSessionOut,
    PlanOut,
    PlansOut,
    TenantTierIn,
)

router = APIRouter(prefix="/billing", tags=["billing"])


def _plan_name(tier: str) -> str:
    for p in PLAN_CATALOG:
        if p["tier"] == tier:
            return p["name"]
    return tier.capitalize()


def _require_stripe_enabled() -> None:
    if not settings.billing_self_serve:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Self-serve checkout is disabled right now.",
        )
    if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Stripe checkout is not configured.",
        )


def _checkout_plan(product: str) -> tuple[int, int, str]:
    if product == "full_claim":
        return CreditConfig.full_claim_amount_cents, CreditConfig.full_claim_credits, "Full Claim"
    if product == "topup":
        return CreditConfig.topup_amount_cents, CreditConfig.topup_credits, "Top-up"
    if product == "sponsor":
        return CreditConfig.sponsor_amount_cents, CreditConfig.sponsor_claims, "Sponsor"
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown checkout product.")


def _public_base(request_origin: str | None = None) -> str:
    base = (request_origin or settings.public_base or "").strip().rstrip("/")
    if not base:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "A public checkout base URL is not configured.",
        )
    return base


async def _stripe_create_session(
    *,
    product: str,
    amount_cents: int,
    credits: int,
    success_url: str,
    cancel_url: str,
    metadata: dict[str, str],
) -> dict:
    payload: dict[str, str] = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": metadata.get("user_id", ""),
        "metadata[product]": product,
        "metadata[credits]": str(credits),
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": settings.stripe_currency,
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][price_data][product_data][name]": (
            "Full Claim - $100" if product == "full_claim"
            else "Top-up - $25"
            if product == "topup"
            else "Sponsor a veteran - $100"
        ),
    }
    for key, value in metadata.items():
        payload[f"metadata[{key}]"] = value
    headers = {"Authorization": f"Bearer {settings.stripe_secret_key}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post("https://api.stripe.com/v1/checkout/sessions", data=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


def _verify_stripe_signature(payload: bytes, signature: str) -> None:
    secret = settings.stripe_webhook_secret
    if not secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Stripe webhook is not configured.")
    parts: dict[str, list[str]] = {}
    for chunk in signature.split(","):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        parts.setdefault(key.strip(), []).append(value.strip())
    ts = parts.get("t", [None])[0]
    sigs = parts.get("v1", [])
    if not ts or not sigs:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe signature header.")
    signed = f"{ts}.{payload.decode('utf-8')}".encode()
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in sigs):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Stripe signature verification failed.")
    # Reject stale events; Stripe recommends a five-minute tolerance.
    try:
        if abs(int(time.time()) - int(ts)) > 300:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Stripe event timestamp is too old.")
    except ValueError as exc:  # pragma: no cover - malformed header
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe signature timestamp.") from exc


@router.get("/plans", response_model=PlansOut)
async def plans(
    tier: str = Depends(active_tier),
) -> PlansOut:
    """The public plan catalog for the pricing / upgrade UI, with the active workspace's
    tier flagged as current."""
    out = [
        PlanOut(
            tier=p["tier"], name=p["name"], price_monthly=p["price_monthly"],
            audience=p["audience"], highlights=list(p["highlights"]),
            seat_limit=SEAT_LIMIT.get(p["tier"], 1), current=(p["tier"] == tier),
        )
        for p in PLAN_CATALOG
    ]
    return PlansOut(
        plans=out,
        self_serve=settings.billing_self_serve,
        portal_url=settings.billing_portal_url or None,
    )


@router.get("/status", response_model=BillingStatusOut)
async def billing_status(
    workspace_id: str = Depends(current_workspace_id),
    tier: str = Depends(active_tier),
    role: str = Depends(current_role),
    db: AsyncSession = Depends(get_db),
) -> BillingStatusOut:
    """The active workspace's billing picture: tier, seat usage, what's included, and the
    manage-billing link. Any member may view; only a manager (admin/owner) may act."""
    row = (await db.execute(
        text(
            "SELECT kind, "
            "  (SELECT count(*) FROM organization_members m WHERE m.org_id = o.id) AS seats "
            "FROM organizations o WHERE o.id = CAST(:w AS uuid) LIMIT 1"
        ),
        {"w": workspace_id},
    )).mappings().first()
    kind = row["kind"] if row else "personal"
    seats_used = int(row["seats"]) if row else 1
    return BillingStatusOut(
        workspace_id=workspace_id,
        kind=kind,
        tier=tier,
        plan_name=_plan_name(tier),
        seat_limit=SEAT_LIMIT.get(tier, 1),
        seats_used=seats_used,
        features=features_for(tier),
        self_serve=settings.billing_self_serve,
        portal_url=settings.billing_portal_url or None,
        manageable=is_manager(role),
    )


@router.post("/tenant-tier", status_code=status.HTTP_200_OK)
async def set_tenant_tier(
    payload: TenantTierIn,
    authorization: str | None = Header(default=None),
):
    """RECEIVER: the suite billing/entitlement service (Lago) sets an org's tier when a
    subscription changes. Authenticated by the shared billing service token (constant-
    time compared); DISABLED (503) when no token is configured, so it can't be left open.

    Runs in its own admin session (NO RLS workspace context) because the caller is a
    trusted service acting cross-tenant, not a workspace member. Idempotent + audited.
    """
    expected = settings.billing_service_token
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Billing receiver is not configured."
        )
    presented = ""
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid billing service token.")

    if payload.tier not in TIERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown tier.")

    # A trusted cross-tenant service write — use a plain admin session (no workspace GUC).
    # organizations is RLS-enabled, but plan_tier is not workspace-fenced data the way
    # veteran rows are; the service is authorized by its token, and we scope the UPDATE
    # to the exact workspace id. We DON'T bypass RLS silently: set the workspace GUC to
    # the target so the org_update policy (member-or-active-workspace) is satisfied.
    async with SessionLocal() as db:
        await db.execute(
            text("SELECT set_config('app.current_workspace', :w, true)"),
            {"w": payload.workspace_id},
        )
        row = (await db.execute(
            text(
                "SELECT kind, plan_tier FROM organizations "
                "WHERE id = CAST(:w AS uuid) LIMIT 1"
            ),
            {"w": payload.workspace_id},
        )).mappings().first()
        if not row:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such workspace.")
        if row["kind"] != "org":
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Tier applies to team workspaces; a personal workspace is always free.",
            )
        previous = row["plan_tier"]
        await db.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = CAST(:w AS uuid)"),
            {"t": payload.tier, "w": payload.workspace_id},
        )
        # Audit into the org's own workspace trail (workspace GUC already = the org). A
        # service action has NO human subject → user_id NULL, actor_label names it.
        await audit_log(
            db, None, "billing.tier.set",
            entity="organization", entity_id=payload.workspace_id,
            meta={"from": previous, "to": payload.tier, "reason": payload.reason,
                  "source": "billing-service"},
            actor_label="billing-service",
        )
        await db.commit()
    return {"ok": True, "workspace_id": payload.workspace_id,
            "tier": payload.tier, "previous": previous}


@router.post("/checkout-session", response_model=CheckoutSessionOut)
async def create_checkout_session(
    payload: CheckoutSessionIn,
    request_origin: str | None = Header(default=None, alias="Origin"),
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
) -> CheckoutSessionOut:
    _require_stripe_enabled()
    amount_cents, credits, _label = _checkout_plan(payload.product)
    base = _public_base(request_origin)
    success_url = (
        f"{base}{settings.stripe_checkout_success_path}"
        f"?session_id={{CHECKOUT_SESSION_ID}}&product={quote(payload.product)}"
    )
    cancel_url = f"{base}{settings.stripe_checkout_cancel_path}"
    metadata = {
        "user_id": uid,
        "workspace_id": workspace_id,
        "product": payload.product,
    }
    if payload.beneficiary_email:
        metadata["beneficiary_email"] = str(payload.beneficiary_email).lower()
    session = await _stripe_create_session(
        product=payload.product,
        amount_cents=amount_cents,
        credits=credits,
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
    )
    return CheckoutSessionOut(
        session_id=session["id"],
        url=session["url"],
        product=payload.product,
        amount_cents=amount_cents,
        credits=credits if payload.product != "sponsor" else 1,
        message=(
            "Checkout ready. You can complete the purchase in Stripe without any card data touching this server."
        ),
    )


@router.post("/stripe/webhook")
async def stripe_webhook_raw(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
):
    _require_stripe_enabled()
    if not stripe_signature:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing Stripe-Signature header.")
    payload = await request.body()
    _verify_stripe_signature(payload, stripe_signature)
    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid Stripe payload.") from exc
    if event.get("type") != "checkout.session.completed":
        return {"received": True, "ignored": True}

    session = event.get("data", {}).get("object") or {}
    session_id = str(session.get("id") or "")
    if not session_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing checkout session id.")
    metadata = session.get("metadata") or {}
    user_id = str(metadata.get("user_id") or session.get("client_reference_id") or "").strip()
    if not user_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing buyer user id.")
    workspace_id = str(metadata.get("workspace_id") or "").strip() or None
    product = str(metadata.get("product") or "").strip()
    amount_cents = int(session.get("amount_total") or 0)
    payment_intent = str(session.get("payment_intent") or "")
    beneficiary_email = str(metadata.get("beneficiary_email") or "").strip().lower() or None

    async with session_for_user(user_id, workspace_id) as scoped:
        if product in ("full_claim", "topup"):
            credits = CreditConfig.full_claim_credits if product == "full_claim" else CreditConfig.topup_credits
            await grant_credits(
                scoped,
                user_id,
                credits,
                operation=f"stripe.checkout.{product}",
                reference_type="stripe_checkout_session",
                reference_id=session_id,
                note=f"{product.replace('_', ' ').title()} via Stripe Checkout",
                idempotency_key=f"stripe:{session_id}",
                meta={"payment_intent": payment_intent, "amount_cents": amount_cents},
            )
            await audit_log(
                scoped,
                user_id,
                f"billing.checkout.{product}",
                entity="credit_transaction",
                entity_id=session_id,
                meta={"product": product, "credits": credits, "amount_cents": amount_cents},
            )
        elif product == "sponsor":
            existing = await sponsorship_by_session(scoped, session_id)
            if existing is not None:
                return {"received": True, "idempotent": True}
            match_user_id = None
            if beneficiary_email:
                match_user_id = (
                    await scoped.execute(
                        text("SELECT id FROM users WHERE lower(email) = lower(:e) LIMIT 1"),
                        {"e": beneficiary_email},
                    )
                ).scalar_one_or_none()
                if match_user_id is not None:
                    match_user_id = uuid.UUID(str(match_user_id))
            sponsor = Sponsorship(
                user_id=uuid.UUID(user_id),
                workspace_id=uuid.UUID(workspace_id) if workspace_id else None,
                checkout_session_id=session_id,
                payment_intent_id=payment_intent or None,
                beneficiary_email=beneficiary_email,
                beneficiary_user_id=match_user_id,
                amount_cents=amount_cents or CreditConfig.sponsor_amount_cents,
                status="completed",
                earmark_status=(
                    "matched"
                    if match_user_id is not None
                    else "pending_match" if beneficiary_email else "general"
                ),
            )
            scoped.add(sponsor)
            await scoped.flush()
            pool_row = await record_pool_claim(
                scoped,
                claims_delta=1,
                kind="sponsor_received",
                sponsorship_id=sponsor.id,
                reserved_email=beneficiary_email,
                reserved_user_id=match_user_id,
                note=(
                    "Earmarked sponsor claim" if beneficiary_email else "General sponsor pool claim"
                ),
            )
            sponsor.pool_ledger_id = pool_row.id
            sponsor.status = "completed"
            await audit_log(
                scoped,
                user_id,
                "billing.sponsor.received",
                entity="sponsorship",
                entity_id=session_id,
                meta={
                    "beneficiary_email": beneficiary_email,
                    "matched": match_user_id is not None,
                },
            )
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown checkout product.")
    return {"received": True}
