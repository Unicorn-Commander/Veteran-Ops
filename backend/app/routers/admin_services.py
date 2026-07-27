"""Runtime service overrides plus workspace privacy controls.

Instance-wide service settings require an explicitly allowlisted platform operator.
Workspace privacy settings require an admin or owner in the active workspace.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..deps import current_user_id, current_workspace_id, get_db, require_platform_admin
from ..overrides import (
    SECRET_KEYS,
    effective_settings,
    invalidate_cache,
    refresh_cache,
    workspace_privacy_mode,
)
from ..rbac import require_role
from ..schemas import (
    PiiCloudConsentIn,
    PiiCloudConsentOut,
    ServiceOverridesIn,
    ServiceSettingsOut,
    TestConnectionIn,
    TestConnectionOut,
    WorkspacePrivacyIn,
    WorkspacePrivacyOut,
)

log = logging.getLogger("veteran_ops.admin_services")

router = APIRouter(
    prefix="/admin/services",
    tags=["admin", "services"],
)

_WORKSPACE_ADMIN = Depends(require_role("admin"))
_PLATFORM_ADMIN = Depends(require_platform_admin)


def _settings_response() -> ServiceSettingsOut:
    """Build the admin response: every secret redacted to ``None`` on the wire,
    plus a boolean ``*_set`` telling the UI whether that key is configured (env or
    override) WITHOUT ever revealing it."""
    raw = effective_settings()
    redacted = {k: (None if k in SECRET_KEYS else v) for k, v in raw.items()}
    return ServiceSettingsOut(
        **redacted,
        llm_api_key_set=bool(raw.get("llm_api_key")),
        embeddings_api_key_set=bool(raw.get("embeddings_api_key")),
    )


@router.get("/settings", response_model=ServiceSettingsOut)
async def get_settings(_operator=_PLATFORM_ADMIN) -> ServiceSettingsOut:
    """Return the current effective settings (env defaults + DB overrides).

    Secret values (API keys) are never returned — redacted to ``None``, with a
    boolean ``*_set`` flag instead.
    """
    return _settings_response()


@router.put("/settings", response_model=ServiceSettingsOut)
async def update_settings(
    body: ServiceOverridesIn,
    db: AsyncSession = Depends(get_db),
    _operator=_PLATFORM_ADMIN,
) -> ServiceSettingsOut:
    """Merge the supplied overrides into ``app_service_settings``.

    A field set to ``None`` explicitly removes that key (falling back to the
    env default). An omitted field is left untouched. Invalidates the in-process
    cache on success so subsequent reads pick up the new values.
    """
    now = await db.scalar(text("SELECT now()"))

    # Read current blob
    row = (
        await db.execute(
            text("SELECT settings FROM app_service_settings WHERE id = 1")
        )
    ).first()
    current: dict = dict(row[0]) if row else {}

    # Merge: set supplied values (including None = remove key)
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value

    # Upsert
    if row:
        await db.execute(
            text(
                "UPDATE app_service_settings SET settings = :settings, "
                "updated_at = :now WHERE id = 1"
            ),
            {"settings": current, "now": now},
        )
    else:
        await db.execute(
            text(
                "INSERT INTO app_service_settings (id, settings, updated_at) "
                "VALUES (1, :settings, :now)"
            ),
            {"settings": current, "now": now},
        )

    invalidate_cache()
    await refresh_cache(db)

    return _settings_response()


@router.put("/workspace-privacy")
async def set_workspace_privacy(
    body: WorkspacePrivacyIn,
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
    _admin_role: str = _WORKSPACE_ADMIN,
) -> dict:
    """Set THIS workspace's privacy choice on ``organizations.privacy_mode``.

    ``True`` forces local-only (privacy-first) for the workspace; ``False`` allows
    quality-first (frontier) routing; ``None`` inherits the global/env default. The
    router-level ``require_role('admin')`` gate means an org admin sets org policy
    and a veteran on their personal workspace (sole owner, rank ≥ admin) sets their
    own. Read live per request by ``overrides.workspace_privacy_mode``.
    """
    await db.execute(
        text("UPDATE organizations SET privacy_mode = :pm WHERE id = CAST(:w AS uuid)"),
        {"pm": body.privacy_mode, "w": workspace_id},
    )
    log.info("workspace %s privacy_mode set to %s", workspace_id, body.privacy_mode)
    return {"workspace_id": workspace_id, "privacy_mode": body.privacy_mode}


@router.get("/workspace-privacy", response_model=WorkspacePrivacyOut)
async def get_workspace_privacy(
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
    _admin_role: str = _WORKSPACE_ADMIN,
) -> WorkspacePrivacyOut:
    """Read THIS workspace's privacy choice: the raw ``organizations.privacy_mode``
    column (``None`` = inherit the global/env default) plus the ``effective`` value
    actually applied after resolution. Lets the UI show current state before a flip."""
    row = (
        await db.execute(
            text(
                "SELECT privacy_mode FROM organizations WHERE id = CAST(:w AS uuid) LIMIT 1"
            ),
            {"w": workspace_id},
        )
    ).first()
    raw = row[0] if row else None
    effective_pm = await workspace_privacy_mode(db)
    return WorkspacePrivacyOut(
        workspace_id=workspace_id,
        privacy_mode=None if raw is None else bool(raw),
        effective=effective_pm,
    )


@router.get("/pii-cloud-consent", response_model=PiiCloudConsentOut)
async def get_pii_cloud_consent(
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
    _admin_role: str = _WORKSPACE_ADMIN,
) -> PiiCloudConsentOut:
    """Read THIS workspace's PII→cloud consent state. ``consented`` is what the C-file
    quality mode checks before it may send the veteran's record text to a frontier
    model (only relevant when privacy mode is off)."""
    row = (
        await db.execute(
            text(
                "SELECT pii_cloud_consent_at, pii_cloud_consent_by FROM organizations "
                "WHERE id = CAST(:w AS uuid) LIMIT 1"
            ),
            {"w": workspace_id},
        )
    ).first()
    at = row[0] if row else None
    by = row[1] if row else None
    return PiiCloudConsentOut(
        workspace_id=workspace_id,
        consented=at is not None,
        consent_at=at,
        consent_by=str(by) if by is not None else None,
    )


@router.put("/pii-cloud-consent", response_model=PiiCloudConsentOut)
async def set_pii_cloud_consent(
    body: PiiCloudConsentIn,
    uid: str = Depends(current_user_id),
    workspace_id: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
    _admin_role: str = _WORKSPACE_ADMIN,
) -> PiiCloudConsentOut:
    """Grant or revoke this workspace's consent to process the veteran's OWN record
    text on a frontier/cloud model when privacy mode is off — the explicit, auditable
    gate the C-file quality mode requires before any PII leaves the fleet.

    Grant stamps ``pii_cloud_consent_at``/``_by``; revoke clears them. Both write an
    append-only audit row. Router-level ``require_role('admin')`` means an org admin
    sets org policy and a veteran on their personal workspace (owner) sets their own.
    Turning consent off never deletes past releases — it only stops future ones.
    """
    if body.consent:
        await db.execute(
            text(
                "UPDATE organizations SET pii_cloud_consent_at = now(), "
                "pii_cloud_consent_by = CAST(:u AS uuid) WHERE id = CAST(:w AS uuid)"
            ),
            {"u": uid, "w": workspace_id},
        )
        action = "privacy.pii_cloud_consent_granted"
    else:
        await db.execute(
            text(
                "UPDATE organizations SET pii_cloud_consent_at = NULL, "
                "pii_cloud_consent_by = NULL WHERE id = CAST(:w AS uuid)"
            ),
            {"w": workspace_id},
        )
        action = "privacy.pii_cloud_consent_revoked"
    await audit.log(
        db, uid, action, entity="workspace", entity_id=workspace_id,
        meta={"consent": body.consent},
    )
    log.info("workspace %s pii_cloud_consent set to %s by %s", workspace_id, body.consent, uid)
    return await get_pii_cloud_consent(workspace_id=workspace_id, db=db)


@router.post("/settings/test", response_model=TestConnectionOut)
async def test_connection(
    body: TestConnectionIn,
    _operator=_PLATFORM_ADMIN,
) -> TestConnectionOut:
    """Test a candidate configuration by making a lightweight call.

    This is intentionally a lightweight read-only check (e.g. list models or
    a health ping) and does NOT save the supplied values. The admin UI calls
    this before ``PUT /settings`` to validate connectivity.
    """
    overrides = body.overrides.model_dump(exclude_none=True)
    test_key = overrides.get("llm_base_url") or overrides.get("embeddings_base_url")

    if not test_key:
        return TestConnectionOut(
            ok=False,
            message="Nothing to test — supply at least one base URL.",
        )

    # Lightweight test: fire a GET against the supplied base URL's health/
    # models endpoint. Time out fast so a wrong URL doesn't hang the UI.
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            base = str(test_key).rstrip("/")
            resp = await client.get(f"{base}/models", headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
            models = data if isinstance(data, list) else data.get("data", [])
            count = len(models) if isinstance(models, list) else 0
            return TestConnectionOut(
                ok=True,
                message=f"Reached {base} — {count} model(s) available.",
            )
    except httpx.TimeoutException:
        return TestConnectionOut(
            ok=False,
            message="Connection timed out after 10 seconds.",
            detail="Check the URL and ensure the service is reachable from this server.",
        )
    except httpx.HTTPStatusError as exc:
        return TestConnectionOut(
            ok=False,
            message=f"HTTP {exc.response.status_code} from {test_key}.",
            detail=str(exc),
        )
    except httpx.RequestError as exc:
        return TestConnectionOut(
            ok=False,
            message=f"Cannot reach {test_key}.",
            detail=str(exc),
        )
