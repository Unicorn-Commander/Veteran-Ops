# Valor-Ops billing integration (Wave 14)

Valor-Ops does **not** own billing. An organization's `plan_tier` (free / pro / team /
enterprise) is the source of truth for feature gating, and the **suite billing /
entitlement service (Lago)** owns what that tier should be. This app deliberately never
writes to Lago or the shared entitlement store — that shared infra is operated by Aaron
+ the entitlement-service owner. Valor exposes a small **receiver** the suite calls when
a subscription changes.

## What Valor provides

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /api/billing/plans` | user | Public plan catalog (drives the pricing/upgrade UI). |
| `GET /api/billing/status` | user (member) | Active workspace's tier, seat usage, included features, portal link. |
| `POST /api/billing/tenant-tier` | **service token** | RECEIVER: set an org's tier. Call this from Lago/the entitlement service. |

Feature → tier gating lives in `backend/app/features.py` (`FEATURE_MIN_TIER`,
`SEAT_LIMIT`, `PLAN_CATALOG`). Individual veteran self-help is free forever on a personal
workspace and is never gated.

## The receiver — `POST /api/billing/tenant-tier`

Set an organization's tier when its subscription is created / changed / cancelled.

```
POST https://valor.magicunicorn.dev/api/billing/tenant-tier
Authorization: Bearer <BILLING_SERVICE_TOKEN>
Content-Type: application/json

{ "workspace_id": "<org uuid>", "tier": "team", "reason": "lago_sub_abc123" }
```

- `tier` ∈ `free | pro | team | enterprise`.
- Idempotent — safe to retry; sending the same tier twice is a no-op that returns the
  current state.
- Audited into the org's own workspace audit trail as `billing.tier.set`
  (`actor_label = billing-service`), so an org admin sees when their plan changed.
- Returns `{ ok, workspace_id, tier, previous }`.
- `503` if `BILLING_SERVICE_TOKEN` is unset (the receiver is **disabled by default** so
  it can never be left open). `401` on a missing/wrong token (constant-time compared).
  `404` unknown workspace. `400` if the workspace is personal (personal = always free).

### Config (backend `infrastructure/.env` on app-host)

```
BILLING_SERVICE_TOKEN=<a strong shared secret the entitlement service presents>
BILLING_PORTAL_URL=https://<suite billing portal>   # shown as "Manage billing"; optional
BILLING_SELF_SERVE=false   # true once in-app checkout/portal is live suite-side
```

Until `BILLING_SERVICE_TOKEN` is set, the receiver returns 503 and org tiers can only be
changed by an operator (e.g. `UPDATE organizations SET plan_tier=… WHERE id=…`). That's
the safe interim state — nothing is auto-charged and nothing shared is touched.

## Wiring options (Aaron / entitlement-service owner)

1. **Lago webhook → receiver.** On `subscription.started` / `.terminated` (or your
   plan-change event), map the Lago plan code → a Valor tier and `POST` the receiver with
   the org's workspace id. You control the plan↔tier map on your side.
2. **Entitlement service push.** If the suite's `uc-entitlements` service already tracks
   per-org SKUs/tiers, have it call the receiver whenever an org's Valor entitlement
   changes. This keeps Keycloak/entitlements as the spine and Valor as a follower.
3. **Mapping the org ↔ Lago customer.** Valor's `organizations.id` (the workspace id) is
   the tenant key. Store it as the external id on the Lago customer / subscription so the
   webhook can resolve which org to update. (A future enhancement could add a
   `lago_customer_id` column to `organizations` if you want Valor to hold the linkage;
   not needed for the receiver to work.)

## Access vs. tier (two different gates)

- **Access** (can this user use Valor at all): the per-user Keycloak `entitlements` claim
  carrying the `valor-ops` SKU — already enforced at SSO login (Wave 12,
  `backend/app/routers/sso.py`). Unchanged by this wave.
- **Tier** (what an org's plan unlocks): the per-org `plan_tier`, set by this receiver.

These are independent: a user is *let in* by their entitlement; their *org's* capabilities
are set by the org's tier.
