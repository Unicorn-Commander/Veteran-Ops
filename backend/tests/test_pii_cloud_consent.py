"""Tests for the PII→cloud consent gate (app/overrides.py, Phase 3).

The C-file quality mode reads the veteran's RAW record text, so it may only send
that text to a frontier/cloud model when the workspace has BOTH privacy off AND an
explicit, recorded PII→cloud consent. These are pure unit tests: a routing fake-DB
returns the privacy row for the privacy query and the consent row for the consent
query, so we can exercise every gate combination without a live database.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from app import overrides


def _populate_cache(data: dict) -> None:
    overrides._cache = dict(data)


def _clear_cache() -> None:
    overrides._cache = None


@pytest.fixture(autouse=True)
def _reset_cache():
    _clear_cache()
    yield
    _clear_cache()


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _RoutingDB:
    """Minimal async db stub: routes SELECTs by the column they name. The consent
    query selects ``pii_cloud_consent_at``; everything else is the privacy query."""

    def __init__(self, *, privacy_row=None, consent_row=None):
        self._privacy = privacy_row
        self._consent = consent_row

    async def execute(self, statement, *a, **k):
        sql = str(statement)
        if "pii_cloud_consent_at" in sql:
            return _FakeResult(self._consent)
        return _FakeResult(self._privacy)


# ── pii_cloud_consent() ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_consent_true_when_timestamp_present():
    db = _RoutingDB(consent_row=(_dt.datetime(2026, 7, 11, tzinfo=_dt.timezone.utc),))
    assert await overrides.pii_cloud_consent(db) is True


@pytest.mark.asyncio
async def test_consent_false_when_null():
    assert await overrides.pii_cloud_consent(_RoutingDB(consent_row=(None,))) is False


@pytest.mark.asyncio
async def test_consent_false_when_no_row():
    # No organizations row (unscoped GUC) → fail-safe: not consented.
    assert await overrides.pii_cloud_consent(_RoutingDB(consent_row=None)) is False


# ── resolve_pii_model() — THE gate ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_privacy_on_forces_local_regardless_of_consent():
    # Even WITH consent, privacy mode on keeps the veteran's record text local.
    _populate_cache({"llm_model": "local", "extraction_model": "cloud-x"})
    db = _RoutingDB(
        privacy_row=(True,),
        consent_row=(_dt.datetime(2026, 7, 11, tzinfo=_dt.timezone.utc),),
    )
    model, pm, released = await overrides.resolve_pii_model(db, tier="extraction")
    assert model == "local"
    assert pm is True
    assert released is False


@pytest.mark.asyncio
async def test_privacy_off_without_consent_stays_local():
    # THE gate: privacy off but NO consent → PII still forced to the local model.
    _populate_cache({"llm_model": "local", "extraction_model": "cloud-x"})
    db = _RoutingDB(privacy_row=(False,), consent_row=(None,))
    model, pm, released = await overrides.resolve_pii_model(db, tier="extraction")
    assert model == "local"
    assert pm is True  # effective privacy is forced back on by the missing consent
    assert released is False


@pytest.mark.asyncio
async def test_privacy_off_with_consent_releases_to_cloud_tier():
    # Both gates satisfied → the (frontier) extraction tier is used, and the caller
    # is told a release happened so it can audit-log it.
    _populate_cache({"llm_model": "local", "extraction_model": "cloud-x"})
    db = _RoutingDB(
        privacy_row=(False,),
        consent_row=(_dt.datetime(2026, 7, 11, tzinfo=_dt.timezone.utc),),
    )
    model, pm, released = await overrides.resolve_pii_model(db, tier="extraction")
    assert model == "cloud-x"
    assert pm is False
    assert released is True


@pytest.mark.asyncio
async def test_consent_without_configured_cloud_tier_is_not_a_release():
    # Privacy off + consent, but NO frontier extraction model configured → the tier
    # falls back to the local model, so nothing is released (released=False).
    _populate_cache({"llm_model": "local"})  # no extraction_model / reasoning_model
    db = _RoutingDB(
        privacy_row=(False,),
        consent_row=(_dt.datetime(2026, 7, 11, tzinfo=_dt.timezone.utc),),
    )
    model, pm, released = await overrides.resolve_pii_model(db, tier="extraction")
    assert model == "local"
    assert pm is False
    assert released is False


@pytest.mark.asyncio
async def test_workspace_privacy_null_inherits_global_off_then_needs_consent():
    # Workspace column NULL, global override privacy off → privacy resolves off, so the
    # consent gate still governs: no consent → local.
    _populate_cache({"llm_model": "local", "extraction_model": "cloud-x", "privacy_mode": False})
    db = _RoutingDB(privacy_row=(None,), consent_row=(None,))
    model, _pm, released = await overrides.resolve_pii_model(db, tier="extraction")
    assert model == "local"
    assert released is False
