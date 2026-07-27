from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.config import settings
from app.kb import refresh as refresh_mod
from app.kb.refresh import (
    KBRefreshValidationError,
    apply_refresh_batch,
    diff_refresh_batch,
    preview_refresh_batch,
    validate_refresh_batch_sources,
)
from app.models import KBRevision
from app.schemas import KBRefreshBatch, KBRefreshDiffOut


def _criteria_batch(**overrides) -> KBRefreshBatch:
    payload = {
        "kind": "rating_criteria",
        "batch_id": "criteria-2026-07-09",
        "source": {"name": "eCFR Title 38", "url": "https://www.ecfr.gov/current/title-38"},
        "verified_as_of": "2026-07-09",
        "items": [
            {
                "title": "Tinnitus",
                "diagnostic_code": "6260",
                "body_system": "Auditory",
                "source": "38 CFR §4.87, DC 6260",
                "source_name": "eCFR 38 CFR §4.87",
                "source_url": "https://www.ecfr.gov/current/title-38/chapter-I/part-4/subpart-B/subject-group-ECFR2a5963a5463f52b/section-4.87",
                "effective_date": "2026-07-01",
                "content": "Recurrent tinnitus criteria.",
                "data": {"tiers": [{"percent": 10, "criteria": "Recurrent tinnitus"}]},
            }
        ],
    }
    payload.update(overrides)
    return KBRefreshBatch(**payload)


def _benefit_batch(**overrides) -> KBRefreshBatch:
    payload = {
        "kind": "benefit",
        "batch_id": "benefit-2026-07-09",
        "source": {"name": "Manual curator", "url": "https://www.va.gov/resources/"},
        "verified_as_of": "2026-07-09",
        "items": [
            {
                "id": "test-benefit",
                "name": "Test benefit",
                "description": "A source-linked benefit.",
                "category": "federal",
                "min_rating": 10,
                "requires_pt": False,
                "states": [],
                "source_name": "VA.gov",
                "source_url": "https://www.va.gov/resources/",
                "effective_date": "2026-07-01",
                "confidence": "established",
            }
        ],
    }
    payload.update(overrides)
    return KBRefreshBatch(**payload)


class _ScalarResult:
    def __init__(self, value=None):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeDB:
    def __init__(self):
        self.added = []
        self.flushed = 0

    async def execute(self, _stmt):
        return _ScalarResult(None)

    async def flush(self):
        self.flushed += 1

    def add(self, obj):
        self.added.append(obj)


def test_criteria_source_validation_requires_high_trust_hosts():
    validate_refresh_batch_sources(_criteria_batch())

    bad = _criteria_batch()
    bad.items[0].source_url = "https://example.com/not-criteria"
    with pytest.raises(KBRefreshValidationError):
        validate_refresh_batch_sources(bad)

    explainer = _criteria_batch()
    explainer.items[0].source_url = "https://example.com/explainer"
    explainer.items[0].content_kind = "explainer"
    explainer.items[0].affects_advice = False
    validate_refresh_batch_sources(explainer)


def test_benefit_sources_allow_broader_https_sources():
    batch = _benefit_batch()
    batch.items[0].source_url = "https://example.com/benefits-guide"
    validate_refresh_batch_sources(batch)


def test_diff_reports_create_update_and_unchanged():
    batch = _criteria_batch()
    current = [
        {
            "card_type": "rating_criteria",
            "title": "Tinnitus",
            "body_system": "Auditory",
            "diagnostic_code": "6260",
            "source": "38 CFR §4.87, DC 6260",
            "source_name": "eCFR 38 CFR §4.87",
            "source_url": batch.items[0].source_url,
            "effective_date": date(2026, 7, 1),
            "verified_as_of": date(2026, 7, 9),
            "content": "Old content.",
            "data": {"tiers": [{"percent": 10, "criteria": "Recurrent tinnitus"}]},
        }
    ]
    diff = diff_refresh_batch(batch, current_cards=current)
    assert diff.updated == 1
    assert diff.items[0].key == "rating_criteria:6260"
    assert diff.items[0].changes["content"]["from"] == "Old content."

    current[0]["content"] = "Recurrent tinnitus criteria."
    current[0]["data"] = {
        "tiers": [{"percent": 10, "criteria": "Recurrent tinnitus"}],
        "_refresh": diff.items[0].changes["data"]["to"]["_refresh"],
    }
    assert diff_refresh_batch(batch, current_cards=current).unchanged == 1


def test_rule_change_trigger_uses_only_changed_rating_dcs():
    from app.routers.kb_admin import _changed_rating_dcs

    diff = KBRefreshDiffOut(
        kind="rating_criteria",
        verified_as_of=date(2026, 7, 9),
        items=[
            {"key": "rating_criteria:6260", "action": "update", "changes": {}},
            {"key": "rating_criteria:9411", "action": "unchanged", "changes": {}},
            {"key": "process:secondary claims", "action": "update", "changes": {}},
        ],
    )
    assert _changed_rating_dcs(diff) == ["6260"]


def test_preview_refuses_rating_tier_above_va_max(monkeypatch):
    bad = _criteria_batch()
    bad.items[0].data = {"tiers": [{"percent": 100, "criteria": "Too high for tinnitus"}]}

    async def _empty_cards(_db):
        return []

    monkeypatch.setattr(refresh_mod, "current_rating_cards", _empty_cards)
    with pytest.raises(KBRefreshValidationError):
        asyncio.run(preview_refresh_batch(_FakeDB(), bad))


def test_apply_rating_batch_reembeds_upserts_and_versions(monkeypatch):
    batch = _criteria_batch()
    db = _FakeDB()
    calls = {"embedded": [], "upserted": None}

    async def _current_cards(_db):
        return []

    async def _embed(cards):
        calls["embedded"] = cards
        return {"rating_criteria:6260": [0.1, 0.2, 0.3]}

    async def _upsert(_db, cards, embeddings):
        calls["upserted"] = (cards, embeddings)

    monkeypatch.setattr(refresh_mod, "current_rating_cards", _current_cards)
    monkeypatch.setattr(refresh_mod, "_embed_cards", _embed)
    monkeypatch.setattr(refresh_mod, "_upsert_rating_cards", _upsert)
    monkeypatch.setattr(refresh_mod, "validate_kb_max_ratings", lambda cards=None: [])

    batch_id, revision_id, diff = asyncio.run(
        apply_refresh_batch(db, batch, applied_by="center-deep-test")
    )

    assert batch_id == "criteria-2026-07-09"
    assert revision_id is None  # fake DB does not populate server-generated ids
    assert diff.created == 1
    assert calls["embedded"][0]["diagnostic_code"] == "6260"
    cards, embeddings = calls["upserted"]
    assert cards[0]["content"] == "Recurrent tinnitus criteria."
    assert embeddings["rating_criteria:6260"] == [0.1, 0.2, 0.3]
    revision = next(obj for obj in db.added if isinstance(obj, KBRevision))
    assert revision.kind == "rating_criteria"
    assert revision.applied_by == "center-deep-test"
    assert revision.diff["created"] == 1


def test_apply_benefit_batch_upserts_and_versions(monkeypatch):
    batch = _benefit_batch()
    db = _FakeDB()
    captured = {}

    async def _current_benefits(_db):
        return []

    async def _upsert(_db, benefits):
        captured["benefits"] = benefits

    monkeypatch.setattr(refresh_mod, "current_benefits", _current_benefits)
    monkeypatch.setattr(refresh_mod, "_upsert_benefits", _upsert)

    _batch_id, _revision_id, diff = asyncio.run(
        apply_refresh_batch(db, batch, applied_by="manual-curator")
    )

    assert diff.created == 1
    assert captured["benefits"][0]["id"] == "test-benefit"
    assert captured["benefits"][0]["verified_as_of"] == date(2026, 7, 9)
    revision = next(obj for obj in db.added if isinstance(obj, KBRevision))
    assert revision.kind == "benefit"


class _FakeSessionContext:
    def __init__(self, db):
        self.db = db

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, *_exc):
        return False


class _RouterDB:
    async def commit(self):
        pass

    async def rollback(self):
        pass


def test_refresh_receiver_auth_and_dry_run(monkeypatch):
    from fastapi import HTTPException

    from app.routers import kb_admin

    batch = _criteria_batch()
    monkeypatch.setattr(settings, "kb_refresh_service_token", "", raising=False)
    with pytest.raises(HTTPException) as disabled:
        asyncio.run(kb_admin.refresh_kb(batch, authorization="Bearer anything", dry_run=True))
    assert disabled.value.status_code == 503

    monkeypatch.setattr(settings, "kb_refresh_service_token", "good-token", raising=False)
    with pytest.raises(HTTPException) as unauthorized:
        asyncio.run(kb_admin.refresh_kb(batch, authorization="Bearer wrong", dry_run=True))
    assert unauthorized.value.status_code == 401

    diff = KBRefreshDiffOut(kind="rating_criteria", verified_as_of=date(2026, 7, 9), created=1)

    async def _preview(_db, _payload):
        return "preview-batch", diff

    monkeypatch.setattr(kb_admin, "SessionLocal", lambda: _FakeSessionContext(_RouterDB()))
    monkeypatch.setattr(kb_admin, "preview_refresh_batch", _preview)

    out = asyncio.run(kb_admin.refresh_kb(batch, authorization="Bearer good-token", dry_run=True))
    assert out.dry_run is True
    assert out.batch_id == "preview-batch"
    assert out.diff.created == 1
