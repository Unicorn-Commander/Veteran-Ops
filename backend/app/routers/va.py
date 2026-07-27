"""VA Lighthouse connection — the veteran links their own VA.gov sign-in.

  GET  /va/status      connection state (works even when the feature is off)
  GET  /va/connect     begin OAuth (PKCE S256) → 302 to VA's sign-in
  GET  /va/callback    VA returns here → token exchange → store → back to SPA
  POST /va/disconnect  revoke (best-effort) + delete the stored connection
  POST /va/sync        pull service history / ratings / P&T → diff-style
                       PREVIEW with suggestions — NEVER auto-applies
  POST /va/apply       apply ONLY the suggestions the veteran picked
  GET  /va/claims      normalized benefits-claim status list
  GET  /va/itf/active  current Intent to File (form 0966), if any
  POST /va/itf         file an Intent to File — explicit confirm required

Legal lane: everything here runs on the veteran's OWN VA.gov-consented token —
the veteran acting through software they operate, exactly like using VA.gov's
UI. The two writes (ITF; local apply) demand explicit confirmation and are
audited. Token values never appear in logs or audit meta.

The callback is a top-level browser navigation carrying no app session, so the
initiating user + PKCE verifier are recovered from a signed `state` JWT
(sso.py's stateless pattern, hardened with a purpose claim) pointing at a
one-time va_connect_states row — the verifier itself never round-trips through
the browser (Glitter Mane's proven FhirConnectState pattern).
"""

from __future__ import annotations

import logging
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..config import settings
from ..db import SessionLocal
from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, VaConnection, VaConnectState, VeteranProfile
from ..schemas import (
    VaApplyIn,
    VaApplyOut,
    VaClaimsOut,
    VaConnectionStatusOut,
    VaDisconnectIn,
    VaItfFileIn,
    VaItfOut,
    VaReconcileIn,
    VaReconcileMatch,
    VaReconcileOut,
    VaReconcileUnmatched,
    VaStatusOut,
    VaSyncOut,
)
from ..va import lighthouse, normalize, service
from ..va.reconcile import ClaimedRef, VaCondition, reconcile
from .profile import _get_or_create
from ..va.lighthouse import VaAuthError, VaError, VaNotFound
from ..va.token_crypto import TokenEncryptionError, decrypt_token

log = logging.getLogger("veteran_ops.va")
router = APIRouter(prefix="/va", tags=["va"])

_STATE_TTL = timedelta(minutes=15)

SYNC_DISCLAIMER = (
    "This is a read-only preview of what VA has on file for you. Nothing in "
    "your Rating Raider workspace changes unless you choose to apply it."
)


# ── Guards / helpers ─────────────────────────────────────────────────────────

def _require_enabled() -> None:
    if not settings.va_enabled:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The VA connection isn't configured on this instance.",
        )


async def _require_connection(
    db: AsyncSession, uid: str, api_key: str
) -> VaConnection:
    conn = await service.get_connection(db, uid, api_key)
    if conn is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"VA isn't connected for {lighthouse.get_api(api_key).label} — "
            "connect it from Settings first.",
        )
    return conn


def _reconnect_409(api_key: str) -> JSONResponse:
    """RETURNED (not raised): raising would roll back the request transaction
    and lose the needs_reconnect flag the service just flushed onto the
    connection row — /va/status must keep reflecting it."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": (
                "Your VA connection is no longer valid — please reconnect at "
                f"Settings ({lighthouse.get_api(api_key).label})."
            )
        },
    )


def _bad_gateway(exc: VaError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


def _sign_state(row_id: str) -> str:
    now = datetime.now(timezone.utc)
    return pyjwt.encode(
        {"k": "va-connect", "sid": row_id, "iat": now, "exp": now + _STATE_TTL},
        settings.jwt_secret,
        algorithm="HS256",
    )


def _verify_state(state: str) -> str:
    claims = pyjwt.decode(
        state, settings.jwt_secret, algorithms=["HS256"],
        options={"require": ["exp"]}, leeway=10,
    )
    # Purpose claim: a native session JWT must never pass as connect state.
    if claims.get("k") != "va-connect" or not claims.get("sid"):
        raise pyjwt.InvalidTokenError("not a va-connect state token")
    return str(claims["sid"])


def _landing(**params: str) -> RedirectResponse:
    url = settings.va_settings_landing
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


# ── Status ───────────────────────────────────────────────────────────────────

@router.get("/status", response_model=VaStatusOut)
async def va_status(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> VaStatusOut:
    """Connection state. Never 503s — the SPA uses this to decide whether to
    show the feature at all."""
    if not settings.va_enabled:
        return VaStatusOut(enabled=False)
    conns = await service.list_connections(db, uid)
    out: list[VaConnectionStatusOut] = []
    scopes: list[str] = []
    last_sync: datetime | None = None
    stale = False
    for c in conns:
        c_scopes = (c.scope_set or "").split()
        scopes.extend(s for s in c_scopes if s not in scopes)
        if c.last_sync_at and (last_sync is None or c.last_sync_at > last_sync):
            last_sync = c.last_sync_at
        c_stale = service.needs_reconnect(c)
        stale = stale or c_stale
        out.append(
            VaConnectionStatusOut(
                api=c.api,
                label=lighthouse.get_api(c.api).label,
                scopes=c_scopes,
                connected_at=c.connected_at,
                last_sync_at=c.last_sync_at,
                needs_reconnect=c_stale,
            )
        )
    return VaStatusOut(
        enabled=True,
        connected=bool(conns),
        scopes=scopes,
        last_sync=last_sync,
        needs_reconnect=stale,
        connections=out,
    )


# ── Connect / callback / disconnect ──────────────────────────────────────────

@router.get("/connect")
async def va_connect(
    api: str = Query(default="verification"),
    redirect: bool = Query(default=True, description="false → JSON {authorize_url}"),
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Begin the OAuth flow: stash a one-time PKCE row, then send the browser
    to VA's sign-in (Login.gov / ID.me) where the VETERAN consents."""
    _require_enabled()
    if api not in lighthouse.APIS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"api must be one of {sorted(lighthouse.APIS)}")
    va_api = lighthouse.get_api(api)
    verifier, challenge = lighthouse.make_pkce()

    # Prune this user's abandoned handshakes so they don't accumulate.
    await db.execute(
        delete(VaConnectState).where(
            VaConnectState.user_id == uuid.UUID(uid),
            VaConnectState.created_at
            < datetime.now(timezone.utc) - _STATE_TTL,
        )
    )
    row = VaConnectState(
        user_id=uuid.UUID(uid), api=api, code_verifier=verifier, scopes=va_api.scopes
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)

    authorize_url = lighthouse.build_authorize_url(
        va_api, state=_sign_state(str(row.id)), code_challenge=challenge
    )
    await audit.log(db, uid, "va.connect_start", entity="va_connection",
                    meta={"api": api})
    if not redirect:
        return {"authorize_url": authorize_url}
    return RedirectResponse(authorize_url, status_code=status.HTTP_302_FOUND)


@router.get("/callback")
async def va_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
):
    """VA redirects the browser here (no app session). Resolve + consume the
    one-time state row, exchange the code (PKCE), store the connection under
    the initiating user's RLS scope, then bounce back to the SPA settings."""
    if not settings.va_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The VA connection isn't configured on this instance.")
    if error:
        log.info("VA connect declined at VA.gov: %s", error)
        return _landing(va="error", reason=error_description or error)
    if not code or not state:
        return _landing(va="error", reason="missing_parameters")
    try:
        row_id = _verify_state(state)
    except Exception:  # noqa: BLE001
        return _landing(va="error", reason="invalid_or_expired")

    # Consume the one-time row (NOT RLS-fenced; resolved by the signed state).
    async with SessionLocal() as s:
        row = (
            await s.execute(
                select(VaConnectState).where(VaConnectState.id == uuid.UUID(row_id))
            )
        ).scalar_one_or_none()
        if row is None:
            return _landing(va="error", reason="invalid_or_expired")
        ctx = {
            "user_id": str(row.user_id),
            "api": row.api,
            "code_verifier": row.code_verifier,
        }
        created = row.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        expired = (
            created is not None
            and datetime.now(timezone.utc) - created > _STATE_TTL
        )
        await s.execute(delete(VaConnectState).where(VaConnectState.id == row.id))
        await s.commit()
    if expired:
        return _landing(va="error", reason="invalid_or_expired")

    va_api = lighthouse.get_api(ctx["api"])
    try:
        tokens = await lighthouse.exchange_code(
            va_api, code=code, code_verifier=ctx["code_verifier"]
        )
    except VaError as exc:
        log.info("VA token exchange failed (api=%s): %s", va_api.key, exc)
        return _landing(va="error", reason="exchange_failed")

    async with service.user_session(ctx["user_id"]) as db:
        await service.upsert_connection(db, ctx["user_id"], va_api, tokens)
        await audit.log(
            db, ctx["user_id"], "va.connected", entity="va_connection",
            meta={"api": va_api.key,
                  "scopes": (tokens.get("scope") or va_api.scopes).split()},
        )
    return _landing(va="connected", api=va_api.key)


@router.post("/disconnect")
async def va_disconnect(
    payload: VaDisconnectIn | None = None,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Revoke the stored tokens with VA (best-effort — VA.gov's connected-apps
    page also works) and delete the local connection either way."""
    _require_enabled()
    want = payload.api if payload else None
    conns = await service.list_connections(db, uid)
    removed: list[str] = []
    for conn in conns:
        if want and conn.api != want:
            continue
        va_api = lighthouse.get_api(conn.api)
        revoked = False
        try:
            refresh_token = decrypt_token(conn.refresh_token)
            access_token = decrypt_token(conn.access_token)
            if refresh_token:
                revoked = await lighthouse.revoke_token(
                    va_api, token=refresh_token, token_type_hint="refresh_token"
                )
            if not revoked and access_token:
                await lighthouse.revoke_token(
                    va_api, token=access_token, token_type_hint="access_token"
                )
        except TokenEncryptionError:
            # A corrupt/legacy credential is still removed locally. Never send an
            # unverifiable value to VA's revocation endpoint.
            revoked = False
        await db.delete(conn)
        removed.append(conn.api)
        await audit.log(db, uid, "va.disconnected", entity="va_connection",
                        meta={"api": conn.api, "revoked_upstream": revoked})
    return {"disconnected": removed}


# ── Sync (preview) + apply (veteran-confirmed) ───────────────────────────────

@router.post("/sync", response_model=VaSyncOut)
async def va_sync(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> VaSyncOut:
    """Pull service history + disability ratings + P&T + veteran status, store
    the normalized snapshot on the connection, and return a diff-style preview.
    READ-ONLY: nothing in the veteran's workspace is modified here."""
    _require_enabled()
    conn = await _require_connection(db, uid, "verification")
    try:
        raw_history = await service.va_call(db, conn, "GET", "service_history")
        raw_rating = await service.va_call(db, conn, "GET", "disability_rating")
        try:
            raw_pt = await service.va_call(
                db, conn, "GET", "permanent_and_total_disability"
            )
        except VaNotFound:
            raw_pt = {}
        try:
            raw_status = await service.va_call(db, conn, "GET", "status")
        except (VaNotFound, VaError):
            raw_status = {}
    except VaAuthError:
        return _reconnect_409("verification")
    except VaNotFound as exc:
        raise _bad_gateway(exc) from None
    except VaError as exc:
        raise _bad_gateway(exc) from None

    service_periods = normalize.normalize_service_history(raw_history)
    rating = normalize.normalize_disability_rating(raw_rating)
    pt_status = normalize.normalize_pt(raw_pt)
    veteran_status = normalize.normalize_veteran_status(raw_status)

    profile_row = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid))
        )
    ).scalar_one_or_none()
    profile = (
        {
            "service_periods": profile_row.service_periods,
            "current_combined_rating": profile_row.current_combined_rating,
        }
        if profile_row
        else None
    )
    conditions = [
        {
            "id": c.id,
            "name": c.name,
            "diagnostic_code": c.diagnostic_code,
            "current_rating": c.current_rating,
        }
        for c in (
            await db.execute(
                select(ClaimedCondition).where(
                    ClaimedCondition.user_id == uuid.UUID(uid)
                )
            )
        ).scalars()
    ]
    suggestions = normalize.build_suggestions(
        service_periods=service_periods,
        rating=rating,
        profile=profile,
        conditions=conditions,
    )

    now = datetime.now(timezone.utc)
    conn.last_sync_at = now
    conn.meta = {
        **(conn.meta or {}),
        "sync": {
            "at": now.isoformat(),
            "service_periods": service_periods,
            "rating": rating,
            "pt_status": pt_status,
            "veteran_status": veteran_status,
        },
    }
    await db.flush()
    await audit.log(
        db, uid, "va.sync", entity="va_connection",
        meta={
            "api": "verification",
            "service_periods": len(service_periods),
            "individual_ratings": len(rating.get("ratings") or []),
            "combined": rating.get("combined"),
            "suggested_condition_updates": len(suggestions["condition_updates"]),
        },
    )
    return VaSyncOut(
        synced_at=now,
        service_periods=service_periods,
        ratings=rating.get("ratings") or [],
        combined=rating.get("combined"),
        combined_effective_date=rating.get("combined_effective_date"),
        pt_status=pt_status,
        veteran_status=veteran_status,
        suggestions=suggestions,
        disclaimer=SYNC_DISCLAIMER,
    )


@router.post("/apply", response_model=VaApplyOut)
async def va_apply(
    payload: VaApplyIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> VaApplyOut:
    """Apply ONLY what the veteran picked from the last sync preview. Every
    value is validated against the stored snapshot — this endpoint can't write
    anything VA didn't return. Audited."""
    _require_enabled()
    conn = await _require_connection(db, uid, "verification")
    snapshot = (conn.meta or {}).get("sync")
    if not snapshot:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Run a VA sync first — apply only works from a synced snapshot.",
        )
    snap_ratings = (snapshot.get("rating") or {}).get("ratings") or []

    def _snapshot_has(name: str | None, dc: str | None, percent: int | None) -> bool:
        for r in snap_ratings:
            if percent is not None and r.get("percent") != percent:
                continue
            if dc and (r.get("diagnostic_code") or "") == dc:
                return True
            r_name = (r.get("name") or "").strip().casefold()
            if name and r_name and (name.strip().casefold() in r_name
                                    or r_name in name.strip().casefold()):
                return True
        return False

    user_uuid = uuid.UUID(uid)
    profile_updated = False
    applied_fields: list[str] = []

    if payload.service_periods or payload.combined_rating:
        profile = (
            await db.execute(
                select(VeteranProfile).where(VeteranProfile.user_id == user_uuid)
            )
        ).scalar_one_or_none()
        if profile is None:
            profile = VeteranProfile(user_id=user_uuid)
            db.add(profile)
        if payload.service_periods:
            periods = snapshot.get("service_periods") or []
            if not periods:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "The last VA sync returned no service periods to apply.",
                )
            # Store in the profile's shape; VA extras stay in the synced preview.
            profile.service_periods = [
                {
                    "branch": p.get("branch") or "",
                    "component": p.get("component") or "",
                    "start_date": p.get("start_date"),
                    "end_date": p.get("end_date"),
                    "discharge_character": p.get("discharge_character") or "",
                }
                for p in periods
            ]
            applied_fields.append("service_periods")
            profile_updated = True
        if payload.combined_rating:
            combined = (snapshot.get("rating") or {}).get("combined")
            if combined is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "The last VA sync returned no combined rating to apply.",
                )
            profile.current_combined_rating = int(combined)
            applied_fields.append("current_combined_rating")
            profile_updated = True

    updated: list[ClaimedCondition] = []
    for upd in payload.condition_updates:
        cond = (
            await db.execute(
                select(ClaimedCondition).where(
                    ClaimedCondition.id == upd.condition_id,
                    ClaimedCondition.user_id == user_uuid,
                )
            )
        ).scalar_one_or_none()
        if cond is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found")
        if not _snapshot_has(cond.name, cond.diagnostic_code, upd.percent):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{upd.percent}% for {cond.name!r} isn't in the last VA sync — "
                "sync again and retry.",
            )
        cond.current_rating = upd.percent
        updated.append(cond)

    created: list[ClaimedCondition] = []
    for new in payload.condition_creates:
        if not _snapshot_has(new.name, new.diagnostic_code, new.percent):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{new.name!r} isn't in the last VA sync — sync again and retry.",
            )
        cond = ClaimedCondition(
            user_id=user_uuid,
            name=new.name[:255],
            diagnostic_code=new.diagnostic_code,
            claim_type="increase",  # already service-connected and rated
            status="considering",
            current_rating=new.percent,
        )
        db.add(cond)
        created.append(cond)

    if not (profile_updated or updated or created):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Nothing selected to apply.",
        )

    await db.flush()
    for cond in updated + created:
        await db.refresh(cond)
    await audit.log(
        db, uid, "va.apply", entity="va_connection",
        meta={
            "profile_fields": applied_fields,
            "conditions_updated": [str(c.id) for c in updated],
            "conditions_created": [str(c.id) for c in created],
        },
    )
    return VaApplyOut(
        profile_updated=profile_updated, updated=updated, created=created
    )


# ── Canonical reconcile ──────────────────────────────────────────────────────

@router.post("/reconcile", response_model=VaReconcileOut)
async def va_reconcile(
    payload: VaReconcileIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> VaReconcileOut:
    """The single 'brain' that turns structured VA rating/claim data — from ANY
    source (browser extension, manual paste, future Lighthouse pull) — into a
    reconciled claim: it sets the profile's combined rating and, per VA
    condition, the matching claimed condition's current_rating + va_status.

    `apply=false` (default) is a DRY-RUN preview that writes NOTHING; `apply=true`
    persists through the ORM and is audited. `create_new` only takes effect with
    apply — it creates claimed conditions for unmatched VA conditions.

    Legal lane: this only organizes what the veteran's own VA record says
    (disposition → va_status; service-connected percent → current_rating). No
    predictions, no outcome language."""
    user_uuid = uuid.UUID(uid)
    conds = (
        await db.execute(
            select(ClaimedCondition).where(ClaimedCondition.user_id == user_uuid)
        )
    ).scalars().all()
    by_id = {str(c.id): c for c in conds}

    plan = reconcile(
        combined_rating=payload.combined_rating,
        va_conditions=[
            VaCondition(
                name=vc.name,
                percent=vc.percent,
                effective_date=vc.effective_date,
                disposition=vc.disposition,
            )
            for vc in payload.conditions
        ],
        claimed=[
            ClaimedRef(
                id=str(c.id),
                name=c.name,
                current_rating=c.current_rating,
                va_status=c.va_status,
            )
            for c in conds
        ],
    )

    matched = [
        VaReconcileMatch(
            va_name=m.va_name,
            condition_id=m.condition_id,
            condition_name=m.condition_name,
            set_current_rating=m.set_current_rating,
            set_va_status=m.set_va_status,
            changed=m.changed,
        )
        for m in plan.matched
    ]

    unmatched: list[VaReconcileUnmatched] = []

    if payload.apply:
        # Persist matched updates onto the existing rows.
        for m in plan.matched:
            cond = by_id[m.condition_id]
            cond.va_status = m.set_va_status
            if m.set_current_rating is not None:
                cond.current_rating = m.set_current_rating

        # Combined rating: upsert the profile row (reuse profile's get-or-create
        # pattern), but only when a value was actually supplied.
        if payload.combined_rating is not None:
            profile = await _get_or_create(db, uid)
            profile.current_combined_rating = payload.combined_rating

        # Create claimed conditions for unmatched VA conditions when asked.
        for u in plan.unmatched:
            created = False
            if payload.create_new:
                db.add(
                    ClaimedCondition(
                        user_id=user_uuid,
                        name=u.name[:255],
                        claim_type="direct",
                        status="considering",
                        va_status=u.disposition,
                        current_rating=(
                            u.percent if u.disposition == "service_connected" else None
                        ),
                    )
                )
                created = True
            unmatched.append(
                VaReconcileUnmatched(
                    name=u.name, disposition=u.disposition, percent=u.percent,
                    created=created,
                )
            )

        await db.flush()
        await audit.log(
            db, uid, "va.reconcile", entity="veteran_profile",
            meta={
                "combined_rating": payload.combined_rating,
                "conditions_in": len(payload.conditions),
                "matched": len(plan.matched),
                "changed": sum(1 for m in plan.matched if m.changed),
                "unmatched": len(plan.unmatched),
                "created": sum(1 for u in unmatched if u.created),
            },
        )
    else:
        # DRY-RUN: write nothing, just report what WOULD happen.
        unmatched = [
            VaReconcileUnmatched(
                name=u.name, disposition=u.disposition, percent=u.percent,
                created=False,
            )
            for u in plan.unmatched
        ]

    return VaReconcileOut(
        combined_rating=plan.combined_rating,
        matched=matched,
        unmatched=unmatched,
        applied=payload.apply,
    )


# ── Benefits claims + Intent to File ─────────────────────────────────────────

@router.get("/claims", response_model=VaClaimsOut)
async def va_claims(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> VaClaimsOut:
    """The veteran's benefits claims, normalized (Benefits Claims v1)."""
    _require_enabled()
    conn = await _require_connection(db, uid, "claims")
    try:
        raw = await service.va_call(db, conn, "GET", "claims")
    except VaAuthError:
        return _reconnect_409("claims")
    except VaError as exc:
        raise _bad_gateway(exc) from None
    return VaClaimsOut(claims=normalize.normalize_claims(raw))


@router.get("/itf/active", response_model=VaItfOut)
async def va_itf_active(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> VaItfOut:
    """The active compensation Intent to File, if VA has one on record."""
    _require_enabled()
    conn = await _require_connection(db, uid, "claims")
    try:
        raw = await service.va_call(db, conn, "GET", "forms/0966/active")
    except VaNotFound:
        return VaItfOut(active=False)
    except VaAuthError:
        return _reconnect_409("claims")
    except VaError as exc:
        raise _bad_gateway(exc) from None
    itf = normalize.normalize_itf(raw)
    return VaItfOut(active=(itf.get("status") == "active"), **itf)


@router.post("/itf", response_model=VaItfOut, status_code=status.HTTP_201_CREATED)
async def va_file_itf(
    payload: VaItfFileIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> VaItfOut:
    """File a compensation Intent to File (VA Form 0966) — this SUBMITS to VA
    on the veteran's own consented token and locks in a potential effective
    date. Requires confirm=true (the UI shows exactly what will be filed and
    the veteran presses the button — the same act as filing it on VA.gov)."""
    _require_enabled()
    if not payload.confirm:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Filing an Intent to File submits VA Form 0966 to VA on your "
            "behalf. Set confirm=true after reviewing what will be filed.",
        )
    conn = await _require_connection(db, uid, "claims")
    try:
        raw = await service.va_call(
            db, conn, "POST", "forms/0966",
            json_body={"data": {"attributes": {"type": payload.type}}},
        )
    except VaAuthError:
        return _reconnect_409("claims")
    except VaError as exc:
        raise _bad_gateway(exc) from None
    itf = normalize.normalize_itf(raw)
    await audit.log(
        db, uid, "va.itf_filed", entity="va_itf", entity_id=itf.get("id"),
        meta={"type": payload.type, "status": itf.get("status"),
              "expiration_date": itf.get("expiration_date"),
              "veteran_confirmed": True},
    )
    return VaItfOut(active=(itf.get("status") in ("active", "duplicate")), **itf)
