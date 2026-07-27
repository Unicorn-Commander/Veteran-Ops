"""Tests for refresh_authored_cards: the safe file-card upsert path.

Validates the four-element contract:
  1. A changed file card updates the matching DB card and nulls its embedding.
  2. A new file card inserts.
  3. A DB-only card (no matching (card_type, title) in files) is untouched.
  4. A second call with no file changes is a no-op (idempotency).
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

from app.kb.seed import refresh_authored_cards


# ── Fake DB helpers ──────────────────────────────────────────────────────────

class _ScalarResult:
    def __init__(self, scalars=None):
        self._scalars = scalars or []

    def scalars(self):
        return self

    def all(self):
        return self._scalars


class _FakeCard:
    """Simulates a KBCard ORM row with the fields refresh_authored_cards reads."""
    def __init__(self, *, card_type, title, body_system=None, diagnostic_code=None,
                 source="", source_name=None, source_url=None,
                 effective_date=None, verified_as_of=None,
                 content="", data=None, embedding=None):
        self.card_type = card_type
        self.title = title
        self.body_system = body_system
        self.diagnostic_code = diagnostic_code
        self.source = source
        self.source_name = source_name
        self.source_url = source_url
        self.effective_date = effective_date
        self.verified_as_of = verified_as_of
        self.content = content
        self.data = data
        self.embedding = embedding


class _FakeDB:
    def __init__(self, existing_cards=None):
        # existing_cards is a flat list of _FakeCard instances.
        self._cards = existing_cards or []
        self.added = []
        self.committed = False

    async def execute(self, _stmt):
        return _ScalarResult(self._cards)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True


# ── Fixtures ─────────────────────────────────────────────────────────────────

FILE_BASE_CARDS = [
    {
        "card_type": "rule",
        "title": "Combined ratings — why 50 + 30 ≠ 80",
        "body_system": "general",
        "diagnostic_code": None,
        "source": "38 CFR §4.25 (Combined Ratings Table)",
        "content": "VA does not ADD ratings…",
        "data": {"examples": [{"inputs": [50, 30]}]},
    },
    {
        "card_type": "presumptive",
        "title": "PACT Act — burn pits",
        "body_system": "general",
        "diagnostic_code": None,
        "source": "PACT Act",
        "content": "Veterans with qualifying service…",
        "data": {"program": "pact_burn_pits"},
    },
]


@pytest.fixture
def fake_db():
    return _FakeDB()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _set_file_cards(monkeypatch, cards):
    """Override load_cards so refresh_authored_cards sees controlled input."""
    import app.kb.seed as seed_mod
    monkeypatch.setattr(seed_mod, "load_cards", lambda: cards)


# ── Tests ────────────────────────────────────────────────────────────────────

def test_inserts_new_file_card(monkeypatch, fake_db):
    """Case 2: a file card not in the DB is inserted."""
    _set_file_cards(monkeypatch, FILE_BASE_CARDS)
    result = asyncio.run(refresh_authored_cards(fake_db))

    assert result["inserted"] == 2
    assert result["updated"] == 0
    assert result["skipped"] == 0
    assert fake_db.committed
    assert len(fake_db.added) == 2
    assert fake_db.added[0].title == FILE_BASE_CARDS[0]["title"]
    assert fake_db.added[0].embedding is None


def test_updates_changed_card_and_nulls_embedding(monkeypatch):
    """Case 1: changed content/data on a matching card triggers update + embed null."""
    existing = [
        _FakeCard(
            card_type="rule",
            title="Combined ratings — why 50 + 30 ≠ 80",
            body_system="general",
            diagnostic_code=None,
            source="38 CFR §4.25 (Combined Ratings Table)",
            content="Old content that needs updating.",
            data={"examples": [{"inputs": [50, 30]}]},
            embedding=[0.1, 0.2, 0.3],
        ),
    ]
    db = _FakeDB(existing_cards=existing)
    _set_file_cards(monkeypatch, FILE_BASE_CARDS)

    result = asyncio.run(refresh_authored_cards(db))

    assert result["inserted"] == 1  # the presumptive card
    assert result["updated"] == 1   # the rule card
    assert result["skipped"] == 0
    assert db.committed
    # The rule card's embedding was nulled
    assert existing[0].embedding is None
    assert existing[0].content == FILE_BASE_CARDS[0]["content"]


def test_does_not_touch_db_only_card(monkeypatch):
    """Case 3: a DB card whose (card_type, title) is not in files is untouched."""
    corpus_card = _FakeCard(
        card_type="rating_criteria",
        title="Tinnitus (curated corpus)",
        body_system="Auditory",
        diagnostic_code="6260",
        source="38 CFR §4.87, DC 6260",
        content="Curated content from /kb/refresh.",
        data={"tiers": [{"percent": 10}]},
        embedding=[0.5, 0.6, 0.7],
    )
    db = _FakeDB(existing_cards=[corpus_card])
    # Only return file cards that do NOT include the corpus card's key
    _set_file_cards(monkeypatch, FILE_BASE_CARDS)

    result = asyncio.run(refresh_authored_cards(db))

    assert result["inserted"] == 2
    assert result["updated"] == 0
    assert result["skipped"] == 0
    # The corpus card is unchanged
    assert corpus_card.embedding == [0.5, 0.6, 0.7]
    assert corpus_card.content == "Curated content from /kb/refresh."


def test_idempotent_second_call(monkeypatch):
    """Case 4: running twice with no file changes skips everything the second time."""
    existing = [
        _FakeCard(
            card_type="rule",
            title="Combined ratings — why 50 + 30 ≠ 80",
            body_system="general",
            diagnostic_code=None,
            source="38 CFR §4.25 (Combined Ratings Table)",
            content="VA does not ADD ratings…",
            data={"examples": [{"inputs": [50, 30]}]},
        ),
    ]
    db = _FakeDB(existing_cards=existing)
    _set_file_cards(monkeypatch, FILE_BASE_CARDS)

    # First call — inserts one, updates zero (data matches), skips one
    first = asyncio.run(refresh_authored_cards(db))
    assert first["inserted"] == 1
    assert first["skipped"] == 1

    # Simulate second call: rebuild existing set to include inserted card
    all_cards = existing + [_FakeCard(
        card_type="presumptive",
        title="PACT Act — burn pits",
        body_system="general",
        diagnostic_code=None,
        source="PACT Act",
        content="Veterans with qualifying service…",
        data={"program": "pact_burn_pits"},
    )]
    db2 = _FakeDB(existing_cards=all_cards)

    second = asyncio.run(refresh_authored_cards(db2))
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert second["skipped"] == 2
    assert db2.committed
