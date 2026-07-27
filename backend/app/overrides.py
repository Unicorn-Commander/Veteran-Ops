"""Override resolver — layers DB-stored overrides on top of env defaults.

The in-process cache is populated lazily from ``app_service_settings`` (single-row
JSONB table) and invalidated on admin write. Every accessor falls through to the
``settings`` singleton (pure env) when the cache is cold or the key is absent.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings

log = logging.getLogger("veteran_ops.overrides")

# Module-level cache: populated lazily, invalidated on write.
_cache: dict[str, Any] | None = None

# All override keys the DB can carry (lowercase, matching Settings attrs).
OVERRIDE_KEYS: frozenset[str] = frozenset({
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "reasoning_model",
    "briefing_model",
    "extraction_model",
    "classification_model",
    "embeddings_base_url",
    "embeddings_api_key",
    "embeddings_model",
    "reranker_base_url",
    "reranker_model",
    "ocr_base_url",
    "ocr_model",
    "ocr_engine",
    "center_deep_url_default",
    "center_deep_url_unicorncommander",
    "privacy_mode",
})

# Keys whose values are secrets (redacted in GET responses).
SECRET_KEYS: frozenset[str] = frozenset({"llm_api_key", "embeddings_api_key"})


async def refresh_cache(db: AsyncSession) -> None:
    """Query ``app_service_settings`` and populate the in-process cache."""
    global _cache
    row = (
        await db.execute(
            text("SELECT settings FROM app_service_settings WHERE id = 1")
        )
    ).first()
    raw: dict[str, Any] = row[0] if row else {}
    _cache = {k: v for k, v in raw.items() if k in OVERRIDE_KEYS}
    log.info("overrides cache refreshed (%d keys)", len(_cache))


def invalidate_cache() -> None:
    """Clear the in-process cache (called after an admin write)."""
    global _cache
    _cache = None
    log.info("overrides cache invalidated")


def effective(key: str) -> Any:
    """Return the override value for *key*, or the env default.

    ``_cache`` may be stale (multiple process workers). That is acceptable:
    the override is an ops convenience, not a strongly-consistent surface. A
    cache miss just means the current process picks up the env default until
    the next refresh.
    """
    global _cache
    if _cache and key in _cache:
        return _cache[key]
    return getattr(settings, key, None)


def effective_settings() -> dict[str, Any]:
    """Return ALL override keys with env defaults + DB overrides layered on top.

    Secret values ARE included (callers that render responses must redact them).
    """
    global _cache
    result: dict[str, Any] = {}
    for key in OVERRIDE_KEYS:
        if _cache and key in _cache:
            result[key] = _cache[key]
        else:
            result[key] = getattr(settings, key, None)
    return result


def effective_settings_redacted() -> dict[str, Any]:
    """Like ``effective_settings()`` but replaces secret values with ``None``."""
    result = effective_settings()
    for k in SECRET_KEYS:
        if k in result and result[k] is not None:
            result[k] = None
    return result


def effective_model_for(
    *, tier: str = "default", touches_pii: bool = False,
    privacy_mode: bool | None = None,
) -> str:
    """Override-aware mirror of ``settings.model_for()``.

    ``tier`` selects a job-class model (reasoning / briefing / extraction /
    classification), each inheriting ``reasoning_model`` → local ``llm_model`` when
    unconfigured; any other tier uses ``llm_model``. A PII-touching call under
    privacy mode is FORCED back to the local ``llm_model`` — the exact guarantee
    ``settings.model_for()`` enforces, reading the EFFECTIVE (env + DB override)
    ids. ``privacy_mode`` overrides the env/global default for THIS call (the
    per-workspace toggle, resolved by ``workspace_privacy_mode``); None → the
    effective global. It never returns a non-local model for a PII call while
    privacy mode is on.
    """
    reasoning = effective("reasoning_model") or settings.reasoning_model
    llm = effective("llm_model") or settings.llm_model
    tiers = {
        "reasoning": reasoning,
        "briefing": (effective("briefing_model") or settings.briefing_model or reasoning),
        "extraction": (effective("extraction_model") or settings.extraction_model or reasoning),
        "classification": (effective("classification_model") or settings.classification_model or reasoning),
    }
    chosen = tiers.get(tier, "") or llm
    if privacy_mode is None:
        pm = effective("privacy_mode")
        if pm is None:
            pm = settings.privacy_mode
    else:
        pm = privacy_mode
    # privacy_mode ON: PII must stay on-fleet. Cloud/frontier ids are forced back
    # to llm_model; other local aliases (long-context qwen3.6-35b-64k, vision, …)
    # remain allowed so batch vs long routing works under privacy.
    if touches_pii and pm and settings.is_off_fleet_model(str(chosen or "")):
        return llm
    return chosen


def effective_allowed_models() -> set[str]:
    """Model ids a caller may request (the gateway's steer-guard allowlist).

    Mirrors ``settings.allowed_models`` (local ``llm_model`` + ``vision_model`` +
    every configured tier id + the ``llm_allowed_models`` CSV) and layers the
    operator's DB tier overrides on top so their chosen ids are permitted — WITHOUT
    this, the gateway silently drops a quality-first tier id back to local. This is
    NOT the PII guard (that is ``effective_model_for`` / ``settings.model_for``); it
    only stops a caller steering to an unknown id.
    """
    base = set(settings.allowed_models)
    for key in ("llm_model", "reasoning_model", "briefing_model",
                "extraction_model", "classification_model"):
        v = effective(key)
        if v:
            base.add(v)
    return base


async def workspace_privacy_mode(db: AsyncSession) -> bool:
    """Resolve the effective privacy_mode for the CURRENT request's workspace.

    Precedence: the ``organizations.privacy_mode`` column for the active workspace
    (when non-NULL) > the global DB override > the env default. Reads the
    ``app.current_workspace`` GUC the request already pins on its RLS session, so it
    only means anything inside a workspace-scoped session; anywhere else it falls
    back to the global default. Quality-first is the global default; a privacy-
    preferring veteran/org sets the column to force local-only.
    """
    try:
        row = (
            await db.execute(
                text(
                    "SELECT privacy_mode FROM organizations WHERE id = "
                    "CAST(NULLIF(current_setting('app.current_workspace', true), '') AS uuid) "
                    "LIMIT 1"
                )
            )
        ).first()
    except Exception:  # noqa: BLE001 — a missing/unscoped GUC just means "use the global"
        row = None
    if row and row[0] is not None:
        return bool(row[0])
    ov = effective("privacy_mode")
    return bool(ov) if ov is not None else bool(settings.privacy_mode)


async def pii_cloud_consent(db: AsyncSession) -> bool:
    """Whether the CURRENT request's workspace has recorded PII→cloud consent.

    Reads ``organizations.pii_cloud_consent_at`` for the active workspace via the same
    ``app.current_workspace`` GUC ``workspace_privacy_mode`` uses. A non-NULL timestamp
    means the workspace explicitly consented to the veteran's OWN record text being
    processed by a frontier/cloud model. Fail-safe: no GUC, no row, or a NULL column →
    ``False`` (no consent), so PII never leaves the fleet by default.
    """
    try:
        row = (
            await db.execute(
                text(
                    "SELECT pii_cloud_consent_at FROM organizations WHERE id = "
                    "CAST(NULLIF(current_setting('app.current_workspace', true), '') AS uuid) "
                    "LIMIT 1"
                )
            )
        ).first()
    except Exception:  # noqa: BLE001 — a missing/unscoped GUC just means "no consent"
        return False
    return bool(row and row[0] is not None)


async def resolve_pii_model(db: AsyncSession, *, tier: str) -> tuple[str, bool, bool]:
    """Consent-aware model resolution for a call that touches the veteran's OWN record.

    Applies BOTH per-workspace gates, in order:
      1. the privacy toggle (``workspace_privacy_mode``) — privacy ON forces local;
      2. the PII→cloud CONSENT gate — even with privacy OFF, releasing record text to a
         non-local (frontier/cloud) model additionally requires the workspace to have
         explicitly consented (``pii_cloud_consent``).

    Fail-safe: privacy ON *or* consent ABSENT → the call is forced to the LOCAL
    ``llm_model``, exactly as if privacy mode were on — so an unconsented workspace with
    privacy off still keeps PII local. Returns ``(model_id, privacy_effective,
    released_to_cloud)`` where ``released_to_cloud`` is True only when the resolved model
    is a non-local id (the caller should audit-log that release).
    """
    pm = await workspace_privacy_mode(db)
    if not pm and not await pii_cloud_consent(db):
        pm = True  # privacy off but NO consent → treat as privacy-on (force local)
    model = effective_model_for(tier=tier, touches_pii=True, privacy_mode=pm)
    local = effective("llm_model") or settings.llm_model
    released = (not pm) and model != local
    return model, pm, released
