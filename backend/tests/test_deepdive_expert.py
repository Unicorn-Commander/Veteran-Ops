"""Focused tests for the per-rating deep-dive graduation boundary."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.firm.candidates import CandidateRating
from app.firm.context import VeteranDossier
from app.firm.deepdive import deep_dive_candidate
from app.llm.gateway import gateway


def _candidate(*, seed_signal: str = "condition c1 carries DC 5257") -> CandidateRating:
    return CandidateRating(
        diagnostic_code="5257",
        title="Knee instability",
        body_system="musculoskeletal",
        origin="increase",
        seed_signal=seed_signal,
        source_ref="c1",
        primary_dc=None,
    )


def _dossier() -> VeteranDossier:
    return VeteranDossier(
        uid=str(uuid.uuid4()),
        conditions=[
            {
                "id": "c1",
                "name": "Left knee instability",
                "diagnostic_code": "5257",
                "current_rating": 10,
                "target_rating": 20,
                "band": "strong",
                "missing": ["current severity evidence"],
            }
        ],
    )


def _card(dc: str = "5257") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        card_type="rating_criteria",
        title="Knee instability",
        body_system="musculoskeletal",
        diagnostic_code=dc,
        source=f"38 CFR §4.71a, DC {dc}",
        content="Instability is evaluated at authored severity tiers.",
        data={
            "tiers": [
                {"percent": 0, "criteria": "none"},
                {"percent": 10, "criteria": "first tier"},
                {"percent": 20, "criteria": "second tier"},
                {"percent": 30, "criteria": "highest tier"},
            ]
        },
    )


async def _no_chunks(*args, **kwargs):  # noqa: ANN002, ANN003
    return []


def _retrieval_with(card):  # noqa: ANN001
    async def retrieve(db, query, *, k, card_type, **kwargs):  # noqa: ANN001
        return [card] if card_type == "rating_criteria" else []

    return retrieve


def _gate_returns(card):  # noqa: ANN001
    """Emulate the exact-DC graduation gate: return the card only when its DC
    matches the requested code, else None (the sibling-DC / no-card case)."""
    async def lookup(db, dc, *, card_type="rating_criteria"):  # noqa: ANN001
        if card is not None and getattr(card, "diagnostic_code", None) == dc:
            return card
        return None

    return lookup


@pytest.mark.asyncio
async def test_deep_dive_requires_nonempty_deterministic_seed(monkeypatch):
    async def must_not_retrieve(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("an empty seed must fail before retrieval")

    monkeypatch.setattr("app.firm.deepdive.card_by_diagnostic_code", must_not_retrieve)
    assert await deep_dive_candidate(object(), _dossier(), _candidate(seed_signal="   ")) is None


@pytest.mark.asyncio
async def test_deep_dive_requires_exact_retrieved_diagnostic_code(monkeypatch):
    # Only a SIBLING card (5258) exists — the exact-DC gate for 5257 returns None,
    # so a semantically-near sibling can never graduate the candidate.
    wrong_card = _card("5258")
    monkeypatch.setattr(
        "app.firm.deepdive.card_by_diagnostic_code",
        _gate_returns(wrong_card),
    )
    assert await deep_dive_candidate(object(), _dossier(), _candidate()) is None


@pytest.mark.asyncio
async def test_deep_dive_drops_hallucinated_percent_to_deterministic_body(monkeypatch):
    card = _card()
    monkeypatch.setattr("app.firm.deepdive.card_by_diagnostic_code", _gate_returns(card))
    monkeypatch.setattr("app.firm.deepdive.retrieve_cards", _retrieval_with(card))
    monkeypatch.setattr("app.firm.deepdive.retrieve_document_chunks", _no_chunks)

    async def invented_percent(messages, **kwargs):  # noqa: ANN001
        return json.dumps(
            {
                "body": (
                "What this is: DC 5257 uses a 90% tier. What your record shows: "
                "the knee is listed. What's still needed: review the record."
                )
            }
        )

    monkeypatch.setattr(gateway, "complete", invented_percent)
    finding = await deep_dive_candidate(object(), _dossier(), _candidate())

    assert finding is not None
    assert finding.enriched is False
    assert finding.body == finding.det_body
    assert "90%" not in finding.body
    assert finding.seed["tier_percents"] == [0, 10, 20, 30]
    assert finding.seed["max_tier_percent"] == 30
    assert finding.seed["rating_percent"] == 20  # explicit target, present in card
    assert finding.seed["side"] == "left"


@pytest.mark.asyncio
async def test_deep_dive_keeps_card_grounded_rewrite(monkeypatch):
    card = _card()
    monkeypatch.setattr("app.firm.deepdive.card_by_diagnostic_code", _gate_returns(card))
    monkeypatch.setattr("app.firm.deepdive.retrieve_cards", _retrieval_with(card))
    monkeypatch.setattr("app.firm.deepdive.retrieve_document_chunks", _no_chunks)

    async def grounded(messages, **kwargs):  # noqa: ANN001
        return (
            '{"body":"What this is: DC 5257 includes a 20% authored tier. '
            "What your record shows: your dossier lists this knee for review. "
            "What's still needed: compare the record with the cited criteria.\"}"
        )

    monkeypatch.setattr(gateway, "complete", grounded)
    finding = await deep_dive_candidate(object(), _dossier(), _candidate())

    assert finding is not None
    assert finding.enriched is True
    assert "20%" in finding.body
    assert finding.card_ids == [str(card.id)]
