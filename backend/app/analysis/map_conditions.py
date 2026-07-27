"""Rating-floor mapping — map claimed conditions to VA schedule tiers.

Results are cached in GamePlanFirmCache under a conditions-scoped facts_hash so
a veteran runs this once (or when conditions change), not on every panel open.
Comprehensive analysis reuses the same runner and persists the same cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ..analysis.mapping import (
    MAPPING_CAVEAT,
    build_mapping_prompt,
    extract_tiers,
    parse_llm_json,
    validate_selection,
)
from ..kb.store import retrieve_cards
from ..models import ClaimedCondition, GamePlanFirmCache

log = logging.getLogger("veteran_ops.analysis.map_conditions")


def conditions_facts_hash(conditions: list[ClaimedCondition]) -> str:
    """Stable key over the claimed-condition set that drives mapping."""
    rows = [
        {
            "name": (c.name or "").strip().lower(),
            "dc": (c.diagnostic_code or "").strip(),
            "rating": c.current_rating,
            "target": c.target_rating,
        }
        for c in conditions
    ]
    rows.sort(key=lambda r: r["name"])
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    # Salt so this hash never collides with firm/deep-dive dossier hashes.
    return hashlib.sha256(f"map-conditions\0{raw}".encode()).hexdigest()


async def get_cached_map(
    db: AsyncSession, uid: str, facts_hash: str
) -> dict | None:
    """Return cached map payload {items, disclaimer, generated_at} or None."""
    try:
        row = (
            await db.execute(
                select(GamePlanFirmCache)
                .where(
                    GamePlanFirmCache.user_id == uuid.UUID(uid),
                    GamePlanFirmCache.facts_hash == facts_hash,
                )
                .order_by(GamePlanFirmCache.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    except SQLAlchemyError:
        return None
    if row is None or not isinstance(row.payload, dict):
        return None
    blob = row.payload.get("map_conditions")
    if not isinstance(blob, dict) or not isinstance(blob.get("items"), list):
        return None
    return blob


async def store_cached_map(
    db: AsyncSession, uid: str, facts_hash: str, blob: dict
) -> None:
    """Upsert map_conditions into GamePlanFirmCache (merge-safe with firm/deep_dive)."""
    patch = {"map_conditions": blob}
    try:
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            stmt = pg_insert(GamePlanFirmCache).values(
                user_id=uuid.UUID(uid), facts_hash=facts_hash, payload=patch
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    GamePlanFirmCache.user_id,
                    GamePlanFirmCache.workspace_id,
                    GamePlanFirmCache.facts_hash,
                ],
                set_={
                    "payload": GamePlanFirmCache.payload.op("||")(stmt.excluded.payload)
                },
            )
            await db.execute(stmt)
        else:
            row = (
                await db.execute(
                    select(GamePlanFirmCache)
                    .where(
                        GamePlanFirmCache.user_id == uuid.UUID(uid),
                        GamePlanFirmCache.facts_hash == facts_hash,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is None:
                db.add(
                    GamePlanFirmCache(
                        user_id=uuid.UUID(uid),
                        facts_hash=facts_hash,
                        payload=patch,
                    )
                )
            else:
                row.payload = {**(row.payload or {}), **patch}
        await db.flush()
    except SQLAlchemyError:
        log.warning("map-conditions cache write failed", exc_info=True)


def _item_to_dict(item: Any) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return item
    return dict(item)


async def compute_map_items(
    db: AsyncSession,
    conditions: list[ClaimedCondition],
    names: list[str] | None = None,
) -> tuple[list[dict], str]:
    """Run retrieval + optional LLM mapping for each condition. Returns (items, disclaimer)."""
    from ..llm.gateway import gateway
    from ..main import DISCLAIMER

    by_name = {c.name.lower(): c for c in conditions}
    chosen = [n.strip() for n in (names or []) if n and n.strip()] or [c.name for c in conditions]
    chosen = chosen[:20]

    items: list[dict] = []
    for name in chosen:
        claimed = by_name.get(name.lower())
        notes_parts = [
            p
            for p in (
                claimed.notes if claimed else None,
                claimed.nexus_notes if claimed else None,
                claimed.in_service_event if claimed else None,
            )
            if p
        ]
        notes = "\n".join(notes_parts) or None
        current_rating = claimed.current_rating if claimed else None

        rows = await retrieve_cards(db, name, k=4, card_type="rating_criteria")
        cards = [
            {
                "title": r.title,
                "diagnostic_code": r.diagnostic_code,
                "body_system": r.body_system,
                "source": r.source,
                "data": r.data,
            }
            for r in rows
        ]
        if not cards:
            items.append(
                {
                    "name": name,
                    "diagnostic_code": None,
                    "body_system": None,
                    "tiers": [],
                    "under_rated": False,
                    "rationale": None,
                    "source": "",
                    "card_title": None,
                    "suggested_discussion_tier": None,
                    "caveat": (
                        "No matching rating-criteria card in the knowledge base for this "
                        "condition — check the full schedule at eCFR (38 CFR Part 4) or "
                        "ask an accredited VSO. " + MAPPING_CAVEAT
                    ),
                }
            )
            continue

        idx: int | None = None
        suggested: int | None = None
        rationale: str | None = None
        try:
            prompt_cards = [
                {
                    "index": i,
                    "title": c["title"],
                    "diagnostic_code": c["diagnostic_code"],
                    "source": c["source"],
                    "tiers": [
                        {"percent": t["percent"], "criteria": t["criteria"]}
                        for t in extract_tiers(c["data"])
                    ],
                }
                for i, c in enumerate(cards)
            ]
            raw = await gateway.complete(
                build_mapping_prompt(name, notes, current_rating, prompt_cards),
                temperature=0.1,
                max_tokens=512,
            )
            idx, suggested, rationale = validate_selection(parse_llm_json(raw), cards)
        except Exception:  # noqa: BLE001
            log.warning("LLM unavailable for map-conditions(%s); retrieval-only.", name)

        card = cards[idx if idx is not None else 0]
        tiers = extract_tiers(card["data"])
        under_rated = (
            current_rating is not None
            and suggested is not None
            and current_rating < suggested
        )
        items.append(
            {
                "name": name,
                "diagnostic_code": card["diagnostic_code"],
                "body_system": card["body_system"],
                "tiers": tiers,
                "under_rated": under_rated,
                "rationale": rationale,
                "source": card["source"] or "",
                "card_title": card["title"],
                "suggested_discussion_tier": suggested,
                "caveat": MAPPING_CAVEAT,
            }
        )

    return items, DISCLAIMER


async def run_map_conditions(
    db: AsyncSession,
    uid: str,
    *,
    names: list[str] | None = None,
    force: bool = False,
    conditions: list[ClaimedCondition] | None = None,
) -> dict:
    """Return map_conditions blob (items, disclaimer, generated_at, cached).

    Cache hit when not force and conditions hash matches. Never raises to callers
    that wrap it — they own credit charging for compute paths.
    """
    if conditions is None:
        conditions = list(
            (
                await db.execute(
                    select(ClaimedCondition).order_by(ClaimedCondition.created_at)
                )
            ).scalars().all()
        )
    chash = conditions_facts_hash(conditions)
    if not force:
        cached = await get_cached_map(db, uid, chash)
        if cached is not None:
            return {**cached, "cached": True, "conditions_hash": chash}

    items, disclaimer = await compute_map_items(db, conditions, names)
    blob = {
        "items": items,
        "disclaimer": disclaimer,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "conditions_hash": chash,
    }
    await store_cached_map(db, uid, chash, blob)
    return {**blob, "cached": False}
