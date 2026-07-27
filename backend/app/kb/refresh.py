"""Curated KB refresh application.

This module is the Valor-side spine for out-of-band KB updates. It validates
trusted batches, computes a deterministic diff, applies DB upserts, and records an
audit revision. It never researches live sources during veteran analysis.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import KBBenefit, KBCard, KBRevision
from ..schemas import (
    KBRefreshBatch,
    KBRefreshBenefitItem,
    KBRefreshDiffItem,
    KBRefreshDiffOut,
    KBRefreshRatingCriteriaItem,
)
from .store import validate_kb_max_ratings

log = logging.getLogger("veteran_ops.kb.refresh")


class KBRefreshValidationError(ValueError):
    """The curated batch failed legal-lane validation."""


class KBRefreshApplyError(RuntimeError):
    """The curated batch could not be safely applied."""


class KBRefreshDuplicateBatchError(KBRefreshValidationError):
    """The caller reused an already-applied batch id."""


_HIGH_TRUST_CRITERIA_SUFFIXES = (
    "ecfr.gov",
    "va.gov",
    "federalregister.gov",
)


def _host(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        return ""
    return (parsed.hostname or "").lower().strip(".")


def is_high_trust_criteria_url(url: str) -> bool:
    """Criteria-changing sources must be eCFR, VA.gov, or Federal Register hosts."""
    host = _host(url)
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in _HIGH_TRUST_CRITERIA_SUFFIXES)


def _require_https_url(url: str, *, label: str) -> None:
    if not _host(url):
        raise KBRefreshValidationError(f"{label} must be a valid https URL.")


def validate_refresh_batch_sources(batch: KBRefreshBatch) -> None:
    """Strict legal-lane source validation for a refresh batch."""
    _require_https_url(batch.source.url, label="Batch source URL")
    errors: list[str] = []
    for idx, item in enumerate(batch.items):
        _require_https_url(item.source_url, label=f"Item {idx + 1} source_url")
        if batch.kind == "rating_criteria":
            if not isinstance(item, KBRefreshRatingCriteriaItem):
                errors.append(f"Item {idx + 1} must be a rating criteria item.")
                continue
            if item.content_kind == "criteria":
                if not item.affects_advice:
                    errors.append(f"Item {idx + 1} criteria content must affect advice.")
                if not is_high_trust_criteria_url(item.source_url):
                    errors.append(
                        f"Item {idx + 1} criteria source must be eCFR, VA.gov, or Federal Register."
                    )
            else:
                if item.affects_advice:
                    errors.append(
                        f"Item {idx + 1} explainer content must be flagged affects_advice=false."
                    )
        elif not isinstance(item, KBRefreshBenefitItem):
            errors.append(f"Item {idx + 1} must be a benefit item.")
    if errors:
        raise KBRefreshValidationError(" ".join(errors))


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _rating_source(item: KBRefreshRatingCriteriaItem) -> str:
    if item.source:
        return item.source
    if item.diagnostic_code:
        return f"{item.source_name}, DC {item.diagnostic_code}"
    return item.source_name


def normalize_rating_item(item: KBRefreshRatingCriteriaItem, batch: KBRefreshBatch) -> dict[str, Any]:
    data = dict(item.data or {})
    data["_refresh"] = {
        "source_name": item.source_name,
        "source_url": item.source_url,
        "effective_date": item.effective_date.isoformat(),
        "verified_as_of": batch.verified_as_of.isoformat(),
        "content_kind": item.content_kind,
        "affects_advice": item.affects_advice,
        "batch_source": batch.source.model_dump(mode="json"),
    }
    return {
        "card_type": "rating_criteria" if item.content_kind == "criteria" else "process",
        "title": item.title.strip(),
        "body_system": item.body_system.strip() if item.body_system else None,
        "diagnostic_code": item.diagnostic_code.strip() if item.diagnostic_code else None,
        "source": _rating_source(item),
        "source_name": item.source_name,
        "source_url": item.source_url,
        "effective_date": item.effective_date,
        "verified_as_of": batch.verified_as_of,
        "content": item.content,
        "data": data,
    }


def normalize_benefit_item(item: KBRefreshBenefitItem, batch: KBRefreshBatch) -> dict[str, Any]:
    states = [s.strip().upper() for s in item.states if s and len(s.strip()) == 2]
    return {
        "id": item.id.strip(),
        "name": item.name.strip(),
        "description": item.description.strip(),
        "category": item.category,
        "min_rating": item.min_rating,
        "requires_pt": item.requires_pt,
        "states": states,
        "source_name": item.source_name,
        "source_url": item.source_url,
        "confidence": item.confidence,
        "effective_date": item.effective_date,
        "verified_as_of": batch.verified_as_of,
        "source": batch.source.model_dump(mode="json"),
    }


def _card_key(card: dict[str, Any]) -> str:
    card_type = str(card.get("card_type") or "rating_criteria")
    dc = str(card.get("diagnostic_code") or "").strip()
    if card_type == "rating_criteria" and dc:
        return f"rating_criteria:{dc}"
    return f"{card_type}:{str(card.get('title') or '').strip().casefold()}"


def _benefit_key(item: dict[str, Any]) -> str:
    return str(item.get("id") or "").strip()


_CARD_COMPARE_FIELDS = (
    "card_type",
    "title",
    "body_system",
    "diagnostic_code",
    "source",
    "source_name",
    "source_url",
    "effective_date",
    "verified_as_of",
    "content",
    "data",
)

_BENEFIT_COMPARE_FIELDS = (
    "name",
    "description",
    "category",
    "min_rating",
    "requires_pt",
    "states",
    "source_name",
    "source_url",
    "confidence",
    "effective_date",
    "verified_as_of",
)


def _changes(current: dict[str, Any] | None, proposed: dict[str, Any], fields: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    if current is None:
        return {field: {"from": None, "to": _jsonable(proposed.get(field))} for field in fields}
    out: dict[str, dict[str, Any]] = {}
    for field in fields:
        before = _jsonable(current.get(field))
        after = _jsonable(proposed.get(field))
        if before != after:
            out[field] = {"from": before, "to": after}
    return out


def diff_refresh_batch(
    batch: KBRefreshBatch,
    *,
    current_cards: list[dict[str, Any]] | None = None,
    current_benefits: list[dict[str, Any]] | None = None,
) -> KBRefreshDiffOut:
    if batch.kind == "rating_criteria":
        current = {_card_key(card): card for card in current_cards or []}
        proposed = [
            normalize_rating_item(item, batch)
            for item in batch.items
            if isinstance(item, KBRefreshRatingCriteriaItem)
        ]
        fields = _CARD_COMPARE_FIELDS
        key_fn = _card_key
    else:
        current = {_benefit_key(item): item for item in current_benefits or []}
        proposed = [
            normalize_benefit_item(item, batch)
            for item in batch.items
            if isinstance(item, KBRefreshBenefitItem)
        ]
        fields = _BENEFIT_COMPARE_FIELDS
        key_fn = _benefit_key

    diff_items: list[KBRefreshDiffItem] = []
    created = updated = unchanged = 0
    for item in proposed:
        key = key_fn(item)
        changes = _changes(current.get(key), item, fields)
        if current.get(key) is None:
            action = "create"
            created += 1
        elif changes:
            action = "update"
            updated += 1
        else:
            action = "unchanged"
            unchanged += 1
        diff_items.append(
            KBRefreshDiffItem(
                key=key,
                title=item.get("title") or item.get("name"),
                action=action,
                changes=changes,
            )
        )
    return KBRefreshDiffOut(
        kind=batch.kind,
        verified_as_of=batch.verified_as_of,
        created=created,
        updated=updated,
        unchanged=unchanged,
        items=diff_items,
    )


def _card_from_row(row: KBCard) -> dict[str, Any]:
    return {
        "card_type": row.card_type,
        "title": row.title,
        "body_system": row.body_system,
        "diagnostic_code": row.diagnostic_code,
        "source": row.source,
        "source_name": row.source_name,
        "source_url": row.source_url,
        "effective_date": row.effective_date,
        "verified_as_of": row.verified_as_of,
        "content": row.content,
        "data": row.data,
    }


def benefit_from_row(row: KBBenefit) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "category": row.category,
        "min_rating": row.min_rating,
        "requires_pt": row.requires_pt,
        "states": list(row.states or []),
        "source_name": row.source_name,
        "source_url": row.source_url,
        "confidence": row.confidence,
        "effective_date": row.effective_date,
        "verified_as_of": row.verified_as_of,
        "source": row.source,
    }


async def current_rating_cards(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(KBCard).where(KBCard.card_type.in_(["rating_criteria", "process"]))
        )
    ).scalars().all()
    return [_card_from_row(row) for row in rows]


async def current_benefits(db: AsyncSession) -> list[dict[str, Any]]:
    rows = (await db.execute(select(KBBenefit))).scalars().all()
    return [benefit_from_row(row) for row in rows]


async def _embed_cards(cards: list[dict[str, Any]]) -> dict[str, list[float]]:
    if not cards:
        return {}
    try:
        from ..llm.gateway import gateway

        vectors = await gateway.embed([f"{c.get('title', '')}. {c.get('content', '')}" for c in cards])
    except Exception as exc:  # noqa: BLE001
        raise KBRefreshApplyError("Embeddings are unavailable. Rating criteria were not changed.") from exc
    if len(vectors or []) != len(cards):
        raise KBRefreshApplyError("Embeddings returned an unexpected vector count. Rating criteria were not changed.")
    return {_card_key(card): vector for card, vector in zip(cards, vectors, strict=True)}


def _merge_for_max_validation(existing: list[dict[str, Any]], proposed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {_card_key(card): card for card in existing if card.get("card_type") == "rating_criteria"}
    for card in proposed:
        if card.get("card_type") == "rating_criteria":
            merged[_card_key(card)] = card
    return list(merged.values())


def _changed_keys(diff: KBRefreshDiffOut) -> set[str]:
    return {item.key for item in diff.items if item.action != "unchanged"}


async def preview_refresh_batch(db: AsyncSession, batch: KBRefreshBatch) -> tuple[str, KBRefreshDiffOut]:
    validate_refresh_batch_sources(batch)
    batch_id = batch.batch_id or str(uuid.uuid4())
    if batch.kind == "rating_criteria":
        cards = await current_rating_cards(db)
        diff = diff_refresh_batch(batch, current_cards=cards)
        proposed = [
            normalize_rating_item(item, batch)
            for item in batch.items
            if isinstance(item, KBRefreshRatingCriteriaItem)
        ]
        issues = validate_kb_max_ratings(cards=_merge_for_max_validation(cards, proposed))
        if issues:
            raise KBRefreshValidationError(f"Rating criteria exceed VA max-rating dataset ceilings: {issues}")
    else:
        diff = diff_refresh_batch(batch, current_benefits=await current_benefits(db))
    return batch_id, diff


async def _upsert_rating_cards(
    db: AsyncSession,
    cards: list[dict[str, Any]],
    embeddings: dict[str, list[float]],
) -> None:
    for card in cards:
        key = _card_key(card)
        stmt = select(KBCard).where(KBCard.card_type == card["card_type"])
        if card["card_type"] == "rating_criteria" and card.get("diagnostic_code"):
            stmt = stmt.where(KBCard.diagnostic_code == card["diagnostic_code"])
        else:
            stmt = stmt.where(KBCard.title == card["title"])
        row = (await db.execute(stmt.limit(1))).scalar_one_or_none()
        if row is None:
            row = KBCard(
                card_type=card["card_type"],
                title=card["title"],
                body_system=card["body_system"],
                diagnostic_code=card["diagnostic_code"],
                source=card["source"],
                source_name=card["source_name"],
                source_url=card["source_url"],
                effective_date=card["effective_date"],
                verified_as_of=card["verified_as_of"],
                content=card["content"],
                data=card["data"],
                embedding=embeddings.get(key),
            )
            db.add(row)
            continue
        row.title = card["title"]
        row.body_system = card["body_system"]
        row.diagnostic_code = card["diagnostic_code"]
        row.source = card["source"]
        row.source_name = card["source_name"]
        row.source_url = card["source_url"]
        row.effective_date = card["effective_date"]
        row.verified_as_of = card["verified_as_of"]
        row.content = card["content"]
        row.data = card["data"]
        if key in embeddings:
            row.embedding = embeddings[key]


async def _upsert_benefits(db: AsyncSession, benefits: list[dict[str, Any]]) -> None:
    for item in benefits:
        row = await db.get(KBBenefit, item["id"])
        if row is None:
            row = KBBenefit(**item)
            db.add(row)
            continue
        row.name = item["name"]
        row.description = item["description"]
        row.category = item["category"]
        row.min_rating = item["min_rating"]
        row.requires_pt = item["requires_pt"]
        row.states = item["states"]
        row.source_name = item["source_name"]
        row.source_url = item["source_url"]
        row.confidence = item["confidence"]
        row.effective_date = item["effective_date"]
        row.verified_as_of = item["verified_as_of"]
        row.source = item["source"]


async def apply_refresh_batch(
    db: AsyncSession,
    batch: KBRefreshBatch,
    *,
    applied_by: str,
) -> tuple[str, uuid.UUID, KBRefreshDiffOut]:
    batch_id, diff = await preview_refresh_batch(db, batch)
    existing_revision = (
        await db.execute(select(KBRevision.id).where(KBRevision.batch_id == batch_id).limit(1))
    ).scalar_one_or_none()
    if existing_revision is not None:
        raise KBRefreshDuplicateBatchError("Batch id has already been applied.")

    if batch.kind == "rating_criteria":
        current = await current_rating_cards(db)
        proposed = [
            normalize_rating_item(item, batch)
            for item in batch.items
            if isinstance(item, KBRefreshRatingCriteriaItem)
        ]
        changed = [card for card in proposed if _card_key(card) in _changed_keys(diff)]
        changed_criteria = [card for card in changed if card["card_type"] == "rating_criteria"]
        embeddings = await _embed_cards(changed_criteria)
        await _upsert_rating_cards(db, changed, embeddings)
        await db.flush()
        issues = validate_kb_max_ratings(cards=await current_rating_cards(db))
        if issues:
            raise KBRefreshValidationError(f"Rating criteria exceed VA max-rating dataset ceilings: {issues}")
        if not changed:
            log.info("KB refresh batch %s had no rating criteria changes.", batch_id)
    else:
        proposed_benefits = [
            normalize_benefit_item(item, batch)
            for item in batch.items
            if isinstance(item, KBRefreshBenefitItem)
        ]
        changed_keys = _changed_keys(diff)
        await _upsert_benefits(
            db,
            [item for item in proposed_benefits if _benefit_key(item) in changed_keys],
        )
        await db.flush()

    revision = KBRevision(
        batch_id=batch_id,
        kind=batch.kind,
        source=batch.source.model_dump(mode="json"),
        verified_as_of=batch.verified_as_of,
        item_count=len(batch.items),
        diff=diff.model_dump(mode="json"),
        applied_by=applied_by or batch.applied_by or "kb-refresh-service",
    )
    db.add(revision)
    await db.flush()
    return batch_id, revision.id, diff
