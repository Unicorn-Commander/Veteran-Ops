"""Tests for the override resolver layer (app/overrides.py).

Pure unit tests: we manipulate the module-level cache directly and verify that
effective() falls through to settings defaults when the cache is cold, returns
overrides when present, secrets are redacted, and — the part that matters most —
the PII model guard holds under the effective (env + override) privacy mode.
"""

from __future__ import annotations

import pytest

from app import overrides
from app.config import settings


def _populate_cache(data: dict) -> None:
    """Helper: directly inject data into the module cache."""
    overrides._cache = dict(data)


def _clear_cache():
    overrides._cache = None


@pytest.fixture(autouse=True)
def _reset_cache():
    """Every test starts and ends with a cold cache — no cross-test bleed."""
    _clear_cache()
    yield
    _clear_cache()


# ── Lifecycle ───────────────────────────────────────────────────────────────


def test_cache_starts_empty():
    assert overrides._cache is None


def test_invalidate_clears_cache():
    _populate_cache({"llm_model": "gpt-4"})
    overrides.invalidate_cache()
    assert overrides._cache is None


# ── effective() fallthrough ────────────────────────────────────────────────


def test_effective_falls_back_to_settings_when_cache_cold():
    val = overrides.effective("llm_model")
    assert val == settings.llm_model


def test_effective_falls_back_to_settings_when_key_missing():
    _populate_cache({"llm_base_url": "http://override"})
    val = overrides.effective("llm_model")
    assert val == settings.llm_model


def test_effective_returns_override_when_present():
    _populate_cache({"llm_base_url": "http://override:8000"})
    assert overrides.effective("llm_base_url") == "http://override:8000"


def test_effective_returns_none_for_unknown_key():
    assert overrides.effective("non_existent_key") is None


def test_effective_honors_explicit_false_override():
    # A subtle-but-important case: an explicit False must NOT be clobbered back to
    # the env default (privacy_mode defaults True). effective() must return False.
    _populate_cache({"privacy_mode": False})
    assert overrides.effective("privacy_mode") is False


# ── effective_settings() ────────────────────────────────────────────────────


def test_effective_settings_contains_all_keys():
    result = overrides.effective_settings()
    for key in overrides.OVERRIDE_KEYS:
        assert key in result


def test_effective_settings_layers_overrides():
    _populate_cache({"llm_base_url": "http://override", "privacy_mode": False})
    result = overrides.effective_settings()
    assert result["llm_base_url"] == "http://override"
    assert result["privacy_mode"] is False
    # Other keys still come from env defaults.
    assert result["llm_model"] == settings.llm_model


# ── effective_settings_redacted() ───────────────────────────────────────────


def test_redacted_hides_api_keys():
    _populate_cache({"llm_api_key": "sk-abc123", "embeddings_api_key": "sk-xyz"})
    result = overrides.effective_settings_redacted()
    assert result["llm_api_key"] is None
    assert result["embeddings_api_key"] is None


def test_redacted_passes_through_non_secrets():
    _populate_cache({"llm_base_url": "http://override"})
    result = overrides.effective_settings_redacted()
    assert result["llm_base_url"] == "http://override"


def test_redacted_leaves_absent_secrets_as_none():
    _populate_cache({})
    assert overrides.effective_settings_redacted()["llm_api_key"] is None


# ── effective_model_for() — THE PII guard ───────────────────────────────────


def test_model_for_default_tier_uses_llm_model():
    _populate_cache({"llm_model": "local-fast", "reasoning_model": "cloud-big"})
    assert overrides.effective_model_for() == "local-fast"


def test_model_for_reasoning_tier_uses_reasoning_model():
    _populate_cache(
        {"llm_model": "local-fast", "reasoning_model": "cloud-big", "privacy_mode": False}
    )
    assert overrides.effective_model_for(tier="reasoning") == "cloud-big"


def test_privacy_on_forces_pii_call_to_local_even_with_cloud_reasoning():
    # THE guarantee: privacy_mode ON + a cloud reasoning model configured →
    # a PII-touching reasoning call STILL resolves to the LOCAL llm_model.
    _populate_cache(
        {"llm_model": "local-fast", "reasoning_model": "cloud-big", "privacy_mode": True}
    )
    assert (
        overrides.effective_model_for(tier="reasoning", touches_pii=True) == "local-fast"
    )


def test_privacy_on_allows_local_long_context_alias_for_pii():
    # Local long-context pool (fleet) is not cloud — PII may use it under privacy.
    _populate_cache(
        {
            "llm_model": "qwen3.6-35b",
            "reasoning_model": "qwen3.6-35b-64k",
            "privacy_mode": True,
        }
    )
    assert (
        overrides.effective_model_for(tier="reasoning", touches_pii=True)
        == "qwen3.6-35b-64k"
    )


def test_privacy_off_lets_pii_reasoning_call_use_reasoning_model():
    _populate_cache(
        {"llm_model": "local-fast", "reasoning_model": "cloud-big", "privacy_mode": False}
    )
    assert (
        overrides.effective_model_for(tier="reasoning", touches_pii=True) == "cloud-big"
    )


def test_privacy_on_non_pii_reasoning_call_may_use_reasoning_model():
    # Privacy mode constrains ONLY PII-touching calls; public-CFR reasoning is free.
    _populate_cache(
        {"llm_model": "local-fast", "reasoning_model": "cloud-big", "privacy_mode": True}
    )
    assert (
        overrides.effective_model_for(tier="reasoning", touches_pii=False) == "cloud-big"
    )


def test_model_for_falls_back_to_env_when_cache_cold():
    assert overrides.effective_model_for() == settings.llm_model


def test_model_for_matches_settings_model_for_under_env():
    # With no overrides, the override path must be IDENTICAL to the trusted
    # settings.model_for() for every tier/PII combination — a regression anchor.
    for tier in ("default", "reasoning"):
        for pii in (False, True):
            assert overrides.effective_model_for(
                tier=tier, touches_pii=pii
            ) == settings.model_for(tier=tier, touches_pii=pii)


# ── effective_allowed_models() ──────────────────────────────────────────────


def test_allowed_models_falls_back_to_settings_allowlist():
    allowed = overrides.effective_allowed_models()
    assert settings.llm_model in allowed
    # The local vision id must remain permitted — the scanned-image OCR fallback.
    assert settings.vision_model in allowed


def test_allowed_models_layers_override_ids():
    _populate_cache({"llm_model": "custom-local", "reasoning_model": "custom-reason"})
    allowed = overrides.effective_allowed_models()
    assert "custom-local" in allowed
    assert "custom-reason" in allowed
    # Still a superset of the env allowlist (vision preserved).
    assert settings.vision_model in allowed


def test_allowed_models_returns_a_set():
    assert isinstance(overrides.effective_allowed_models(), set)


# ── Invariants ──────────────────────────────────────────────────────────────


def test_override_keys_are_valid_settings_attrs():
    """Every OVERRIDE_KEYS entry must be a real Settings attribute name."""
    for key in overrides.OVERRIDE_KEYS:
        assert hasattr(settings, key), f"{key} is not a Settings attribute"


def test_secret_keys_are_subset_of_override_keys():
    for key in overrides.SECRET_KEYS:
        assert key in overrides.OVERRIDE_KEYS


# ── NEW (Phase 0): quality-first tiers ───────────────────────────────────────


def test_new_tiers_resolve_to_their_own_model_when_set():
    _populate_cache({
        "llm_model": "local", "reasoning_model": "reason",
        "briefing_model": "brief-m", "extraction_model": "extract-m",
        "classification_model": "classify-m", "privacy_mode": False,
    })
    assert overrides.effective_model_for(tier="briefing") == "brief-m"
    assert overrides.effective_model_for(tier="extraction") == "extract-m"
    assert overrides.effective_model_for(tier="classification") == "classify-m"


def test_unset_tier_inherits_reasoning_then_llm():
    _populate_cache({"llm_model": "local", "reasoning_model": "reason", "privacy_mode": False})
    assert overrides.effective_model_for(tier="briefing") == "reason"  # inherits reasoning
    _populate_cache({"llm_model": "local"})
    assert overrides.effective_model_for(tier="classification") == "local"  # inherits llm


def test_quality_first_routes_pii_to_tier_model_when_privacy_off():
    # THE inversion: privacy OFF + a configured tier → a PII-touching call uses the
    # (possibly frontier) tier model, NOT the forced-local one.
    _populate_cache({"llm_model": "local", "extraction_model": "cloud-x", "privacy_mode": False})
    assert overrides.effective_model_for(tier="extraction", touches_pii=True) == "cloud-x"


def test_explicit_privacy_mode_param_overrides_cache_both_directions():
    # The per-workspace toggle: an explicit privacy_mode arg wins over the global.
    _populate_cache({"llm_model": "local", "reasoning_model": "cloud", "privacy_mode": False})
    # workspace forces privacy ON → PII call goes local despite global OFF
    assert overrides.effective_model_for(tier="reasoning", touches_pii=True, privacy_mode=True) == "local"
    _populate_cache({"llm_model": "local", "reasoning_model": "cloud", "privacy_mode": True})
    # workspace allows quality-first → PII call may use cloud despite global ON
    assert overrides.effective_model_for(tier="reasoning", touches_pii=True, privacy_mode=False) == "cloud"


def test_allowed_models_includes_tier_ids():
    _populate_cache({
        "briefing_model": "brief-m", "extraction_model": "extract-m",
        "classification_model": "classify-m",
    })
    allowed = overrides.effective_allowed_models()
    assert {"brief-m", "extract-m", "classify-m"} <= allowed


def test_regression_anchor_covers_all_tiers():
    # No overrides → the override path must equal settings.model_for for EVERY tier.
    for tier in ("default", "reasoning", "briefing", "extraction", "classification"):
        for pii in (False, True):
            assert overrides.effective_model_for(tier=tier, touches_pii=pii) == \
                settings.model_for(tier=tier, touches_pii=pii)


# ── NEW (Phase 0): gateway steer-guard is now mode-aware ─────────────────────


def test_steer_guard_drops_unknown_id_to_local():
    from app.llm.gateway import gateway
    _clear_cache()
    assert gateway._resolve_model("some-unlisted-cloud-id") == settings.llm_model


def test_steer_guard_allows_listed_cloud_id_when_privacy_off():
    from app.llm.gateway import gateway
    _populate_cache({"llm_model": "local", "reasoning_model": "cloud-big", "privacy_mode": False})
    assert gateway._resolve_model("cloud-big", touches_pii=True) == "cloud-big"


def test_steer_guard_forces_pii_local_under_privacy_even_for_listed_id():
    # The CLOSED HOLE: a caller passing the reasoning id used to reach cloud even
    # under privacy mode. The mode backstop now forces it local.
    from app.llm.gateway import gateway
    _populate_cache({"llm_model": "local", "reasoning_model": "cloud-big", "privacy_mode": True})
    assert gateway._resolve_model("cloud-big", touches_pii=True) == "local"


def test_steer_guard_explicit_privacy_param_wins():
    from app.llm.gateway import gateway
    _populate_cache({"llm_model": "local", "reasoning_model": "cloud-big", "privacy_mode": False})
    assert gateway._resolve_model("cloud-big", privacy_mode=True, touches_pii=True) == "local"


# ── NEW (Phase 0): per-workspace privacy resolution precedence ───────────────


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeDB:
    """Minimal async db stub: execute() ignores the SQL, returns a fixed row."""

    def __init__(self, row):
        self._row = row

    async def execute(self, *a, **k):
        return _FakeResult(self._row)


@pytest.mark.asyncio
async def test_workspace_privacy_column_wins_over_global():
    _populate_cache({"privacy_mode": False})  # global = quality-first
    assert await overrides.workspace_privacy_mode(_FakeDB((True,))) is True
    assert await overrides.workspace_privacy_mode(_FakeDB((False,))) is False


@pytest.mark.asyncio
async def test_workspace_privacy_falls_back_to_global_when_column_null():
    _populate_cache({"privacy_mode": True})
    assert await overrides.workspace_privacy_mode(_FakeDB((None,))) is True
    assert await overrides.workspace_privacy_mode(_FakeDB(None)) is True


@pytest.mark.asyncio
async def test_workspace_privacy_falls_back_to_env_when_no_override():
    _clear_cache()
    assert await overrides.workspace_privacy_mode(_FakeDB(None)) == settings.privacy_mode
