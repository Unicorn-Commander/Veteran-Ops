"""kb_cards bootstrap seeding (called from main.py startup, off the critical path).

CRITICAL CONTRACT — seed must COEXIST with the /kb/refresh receiver, which adds
curated corpus cards (38 CFR distiller, Center Deep) ON TOP of the hand-authored
file cards. A prior version rebuilt the whole table whenever the row count didn't
equal the file-card count; because refresh makes count > files, EVERY restart wiped
the entire curated corpus back to the file stub. That is the bug this file fixes.

Rules now:
  * BOOTSTRAP ONLY ON AN EMPTY TABLE. A fresh DB (or DR restore) is seeded from
    data/*.json. Once ANY cards exist (seeded and/or refreshed), the table is
    NEVER rebuilt or truncated — the curated corpus is authoritative and durable.
  * On a populated table, the only action is to BACKFILL embeddings for any card
    lacking a vector (e.g. process cards the refresh receiver inserted without
    embedding them) so vector retrieval covers the whole corpus.
  * Embed BEFORE writing — a transient embeddings outage never destroys or churns
    a good corpus; it just retries on the next boot. Embeddings unavailable on a
    fresh DB → seed WITHOUT vectors (ILIKE fallback), retry embedding next boot.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import func, select

from ..models import KBCard
from .store import load_cards

log = logging.getLogger("veteran_ops.kb")


# Match the /kb/refresh receiver's embed text so a card embedded by either path is
# comparable in vector space (title + DC discriminator up front, bounded body).
def _embed_text(card: dict) -> str:
    dc = f" (DC {card['diagnostic_code']})" if card.get("diagnostic_code") else ""
    return f"{card.get('title', '')}{dc}\n{(card.get('content') or '')[:2000]}"


async def _backfill_embeddings(db) -> None:
    """Embed any existing card that has no vector (refresh-inserted process cards,
    or a prior boot that seeded during an embeddings outage). Never deletes."""
    rows = (
        await db.execute(select(KBCard).where(KBCard.embedding.is_(None)))
    ).scalars().all()
    if not rows:
        return
    try:
        from ..llm.gateway import gateway

        vecs = await gateway.embed(
            [
                _embed_text(
                    {
                        "title": r.title,
                        "diagnostic_code": r.diagnostic_code,
                        "content": r.content,
                    }
                )
                for r in rows
            ]
        )
    except Exception:  # noqa: BLE001 — retry next boot; ILIKE covers the gap meanwhile
        log.warning("KB embed backfill unavailable; %d cards stay ILIKE-only.", len(rows))
        return
    if not vecs or len(vecs) != len(rows):
        log.warning(
            "KB embed backfill returned %d for %d cards — skipped.",
            len(vecs) if vecs else 0,
            len(rows),
        )
        return
    for r, v in zip(rows, vecs):
        r.embedding = v
    await db.commit()
    log.info("KB embed backfill: embedded %d previously-unembedded cards.", len(rows))


async def seed_kb() -> None:
    from ..db import SessionLocal

    cards = load_cards()
    if not cards:
        log.warning("No KB card data found — nothing to seed.")
        return

    async with SessionLocal() as db:
        total = (await db.execute(select(func.count()).select_from(KBCard))).scalar() or 0

        # POPULATED TABLE → never rebuild. The curated corpus is durable; only make
        # sure every card (incl. refresh-inserted ones) is embedded.
        if total > 0:
            await _backfill_embeddings(db)
            return

        # EMPTY TABLE → bootstrap from files (embed-first; table is empty so there is
        # nothing to destroy).
        embeddings: list[list[float]] | None
        try:
            from ..llm.gateway import gateway  # lazy import (openai optional in dev/tests)

            embeddings = await gateway.embed([_embed_text(c) for c in cards])
        except Exception:  # noqa: BLE001
            embeddings = None
        if embeddings is not None and len(embeddings) != len(cards):
            embeddings = None  # partial => treat as unavailable
        if not embeddings:
            embeddings = None
            log.warning(
                "KB embeddings unavailable; seeding %d cards without vectors.", len(cards)
            )

        for i, c in enumerate(cards):
            db.add(
                KBCard(
                    card_type=c.get("card_type", "rule"),
                    title=c.get("title", ""),
                    body_system=c.get("body_system"),
                    diagnostic_code=c.get("diagnostic_code"),
                    source=c.get("source", ""),
                    content=c.get("content", ""),
                    data=c.get("data"),
                    embedding=embeddings[i] if embeddings else None,
                )
            )
        await db.commit()
        log.info(
            "Bootstrapped %d KB cards on empty table (%s).",
            len(cards),
            "embedded" if embeddings else "no embeddings — ILIKE fallback",
        )


# ── File-card refresh (admin-only, NEVER touches curated corpus) ─────────────

# Tracked fields from hand-authored data files. Curated-metadata fields
# (effective_date, verified_as_of) are intentionally excluded — they are
# set by the /kb/refresh receiver and must never be overwritten by an
# authored-card refresh. Only fields actually present in the file dict are
# synced, preserving any existing curated metadata on matching cards.
_COMPARE_FIELDS = frozenset(
    {"body_system", "diagnostic_code", "source", "source_name", "source_url", "content", "data"}
)
_DATE_FIELDS = frozenset({"effective_date", "verified_as_of"})


def _parse_date(val):
    if val is None or isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None


def _val_differs(new_val, old_val) -> bool:
    """Check if a file-card value differs from the DB value, handling types."""
    if new_val is None and old_val is None:
        return False
    if new_val is None or old_val is None:
        return True
    if isinstance(old_val, date) and isinstance(new_val, str):
        try:
            return date.fromisoformat(new_val) != old_val
        except (ValueError, TypeError):
            return True
    if isinstance(new_val, date) and isinstance(old_val, str):
        try:
            return new_val != date.fromisoformat(old_val)
        except (ValueError, TypeError):
            return True
    return new_val != old_val


async def refresh_authored_cards(db) -> dict:
    """Upsert-only refresh of hand-authored KB file cards (*.json in data/).

    Matches file cards to DB cards by (card_type, title).  For each match,
    updates tracked fields when they differ and nulls the embedding (the
    existing _backfill_embeddings path re-embeds it on the next boot).
    Inserts file cards not yet in the DB.  NEVER deletes and NEVER touches a
    DB card whose (card_type, title) is absent from the files — preserving
    the curated corpus (+ /kb/refresh) contract.

    Intended to be triggered via POST /admin/kb/refresh-authored (admin-only)
    or called programmatically.  Safe to run repeatedly — second run is a no-op.

    Returns:
        dict with inserted / updated / skipped counts.
    """
    cards = load_cards()
    if not cards:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    all_db = (await db.execute(select(KBCard))).scalars().all()
    db_by_key = {(r.card_type, r.title): r for r in all_db}

    inserted = 0
    updated = 0
    skipped = 0

    for fc in cards:
        key = (fc.get("card_type", "rule"), fc.get("title", ""))
        existing = db_by_key.get(key)

        if existing is None:
            kwargs: dict = {
                "card_type": fc.get("card_type", "rule"),
                "title": fc.get("title", ""),
            }
            for field in _COMPARE_FIELDS:
                if field in fc:
                    kwargs[field] = fc[field]
            for field in _DATE_FIELDS:
                if field in fc:
                    kwargs[field] = _parse_date(fc[field])
            db.add(KBCard(**kwargs, embedding=None))
            inserted += 1
            continue

        changed = False
        for field in _COMPARE_FIELDS:
            if field not in fc:
                continue
            new_val = fc[field]
            old_val = getattr(existing, field)
            if _val_differs(new_val, old_val):
                setattr(existing, field, new_val)
                changed = True

        for field in _DATE_FIELDS:
            if field not in fc:
                continue
            new_val = fc[field]
            old_val = getattr(existing, field)
            if _val_differs(new_val, old_val):
                setattr(existing, field, _parse_date(new_val))
                changed = True

        if changed:
            existing.embedding = None
            updated += 1
        else:
            skipped += 1

    await db.commit()
    log.info(
        "refresh_authored_cards: %d inserted, %d updated, %d skipped",
        inserted, updated, skipped,
    )
    return {"inserted": inserted, "updated": updated, "skipped": skipped}
