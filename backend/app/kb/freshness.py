"""eCFR freshness monitor — is our KB older than the last 38 CFR amendment?

The KB cards were hand-verified against eCFR as of `KB_VERIFIED_AS_OF`. The
eCFR versioner API reports when Title 38 was last amended; if that date is
AFTER our verification date, the KB may be describing superseded criteria and
the app should say so (legal lane: "verify current rating criteria at eCFR").

Design: one pure comparison (`is_stale`, unit-tested with mock dates), one
network fetch (httpx, short timeout), a module-level cache so GET /api/meta
never blocks on eCFR, and a lightweight periodic loop that records an observable
refresh-needed signal when Title 38 changed after the verified-as-of date.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone

import httpx

from ..config import settings

log = logging.getLogger("veteran_ops.kb.freshness")

ECFR_TITLES_URL = "https://www.ecfr.gov/api/versioner/v1/titles.json"

# The date the KB card corpus was last verified against eCFR. Bump this when
# re-verifying the cards (see data/vendor/README.md refresh procedure).
#
# 2026-07-25 re-verification: Title 38 `latest_amended_on` moved to 2026-07-13 for
# Federal Register 2026-14084 (Loan Guaranty civil monetary penalties inflation
# notice — no change to 38 CFR Parts 3/4 rating or eligibility criteria). Authored
# rating_criteria / presumptives / secondary_map / process cards re-confirmed
# current; content fingerprint unchanged. See rule_versions.json.
KB_VERIFIED_AS_OF = date(2026, 7, 25)

# Last successful check result (set by check_freshness); read by /api/meta.
_last_result: dict | None = None
_verified_as_of_override: date | None = None


def _parse_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def is_stale(latest_amended_on, verified_as_of: date = KB_VERIFIED_AS_OF) -> bool:
    """PURE: stale when Title 38 was amended AFTER the KB verification date.
    Unknown/unparseable amendment date → not stale (no false alarms — the
    global disclaimer already tells veterans to verify at eCFR)."""
    amended = _parse_date(latest_amended_on)
    if amended is None:
        return False
    return amended > verified_as_of


async def fetch_title38_latest_amended(timeout: float = 10.0) -> str | None:
    """Title 38's latest_amended_on from the eCFR versioner API (raises on
    network/HTTP failure — callers decide how to degrade)."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(ECFR_TITLES_URL)
        resp.raise_for_status()
        payload = resp.json() or {}
    for title in payload.get("titles", []):
        if isinstance(title, dict) and title.get("number") == 38:
            value = title.get("latest_amended_on")
            return str(value) if value else None
    return None


def mark_kb_verified_as_of(verified_as_of: date) -> None:
    """Process-local bump after a successful curated criteria refresh."""
    global _verified_as_of_override, _last_result
    _verified_as_of_override = max(_verified_as_of_override or KB_VERIFIED_AS_OF, verified_as_of)
    if _last_result is not None:
        _last_result = {
            **_last_result,
            "kb_verified_as_of": _verified_as_of_override.isoformat(),
            "stale": is_stale(
                _last_result.get("title38_latest_amended_on"),
                _verified_as_of_override,
            ),
        }


async def effective_kb_verified_as_of() -> date:
    """Latest applied rating-criteria verified date, falling back to the authored
    corpus constant. Uses the revision log when the DB is reachable."""
    global _verified_as_of_override
    verified = _verified_as_of_override or KB_VERIFIED_AS_OF
    try:
        from sqlalchemy import func, select

        from ..db import SessionLocal
        from ..models import KBRevision

        async with SessionLocal() as db:
            row = (
                await db.execute(
                    select(func.max(KBRevision.verified_as_of)).where(
                        KBRevision.kind == "rating_criteria"
                    )
                )
            ).scalar_one_or_none()
            if row:
                verified = max(verified, row)
    except Exception:  # noqa: BLE001
        return verified
    _verified_as_of_override = verified
    return verified


async def check_freshness(verified_as_of: date | None = None) -> dict:
    """Live check → {title38_latest_amended_on, kb_verified_as_of, stale}.
    Caches the result module-wide on success; raises on network failure."""
    global _last_result
    verified = verified_as_of or _verified_as_of_override or KB_VERIFIED_AS_OF
    latest = await fetch_title38_latest_amended()
    result = {
        "title38_latest_amended_on": latest,
        "kb_verified_as_of": verified.isoformat(),
        "stale": is_stale(latest, verified),
    }
    _last_result = result
    return result


def cached_freshness() -> dict | None:
    """The last successful check result (None before the first success)."""
    return _last_result


def cached_effective_freshness() -> dict:
    """Non-blocking operational snapshot for request middleware."""
    verified = _verified_as_of_override or KB_VERIFIED_AS_OF
    cached = cached_freshness()
    if not cached:
        return {
            "status": "unknown",
            "stale": None,
            "kb_verified_as_of": verified.isoformat(),
            "title38_latest_amended_on": None,
        }
    latest = cached.get("title38_latest_amended_on")
    stale = is_stale(latest, verified)
    return {
        **cached,
        "status": "stale" if stale else "current",
        "stale": stale,
        "kb_verified_as_of": verified.isoformat(),
    }


async def effective_freshness() -> dict:
    """Current operational view using the latest curated verification date.

    A curated refresh can advance the persisted verified-as-of date before the next
    network poll. Recompute against the cached amendment date so stale gating clears
    immediately after that approved refresh instead of waiting for the scheduler.
    """
    verified = await effective_kb_verified_as_of()
    cached = cached_freshness()
    if not cached:
        return cached_effective_freshness()
    latest = cached.get("title38_latest_amended_on")
    stale = is_stale(latest, verified)
    return {
        **cached,
        "status": "stale" if stale else "current",
        "stale": stale,
        "kb_verified_as_of": verified.isoformat(),
    }


def _monitored_terms() -> list[str]:
    return [t.strip() for t in settings.kb_freshness_monitored_terms.split(",") if t.strip()]


async def record_refresh_needed_signal(result: dict) -> None:
    """Persist an observable operational signal for Center Deep phase 2 wiring."""
    detected = _parse_date(result.get("title38_latest_amended_on"))
    if detected is None:
        return
    try:
        from sqlalchemy import select

        from ..db import SessionLocal
        from ..models import KBRefreshSignal

        detail = {
            "title38_latest_amended_on": result.get("title38_latest_amended_on"),
            "kb_verified_as_of": result.get("kb_verified_as_of"),
            "monitored_terms": _monitored_terms(),
        }
        # TODO phase 2: enqueue a Center Deep research job for these monitored terms,
        # then have Center Deep POST its validated batch back to /kb/refresh.
        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            existing = (
                await db.execute(
                    select(KBRefreshSignal).where(
                        KBRefreshSignal.topic == "38 CFR Title 38",
                        KBRefreshSignal.status == "open",
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    KBRefreshSignal(
                        topic="38 CFR Title 38",
                        status="open",
                        reason="Title 38 was amended after the rating criteria verified-as-of date.",
                        kb_verified_as_of=date.fromisoformat(str(result["kb_verified_as_of"])[:10]),
                        detected_source_date=detected,
                        detail=detail,
                        last_seen_at=now,
                    )
                )
            else:
                existing.last_seen_at = now
                existing.detected_source_date = detected
                existing.kb_verified_as_of = date.fromisoformat(str(result["kb_verified_as_of"])[:10])
                existing.detail = detail
            await db.commit()
    except Exception:  # noqa: BLE001
        log.exception("KB freshness signal could not be recorded")


async def resolve_refresh_signals(verified_as_of: date) -> None:
    """Mark open freshness signals resolved once a curated refresh catches up."""
    try:
        from sqlalchemy import select

        from ..db import SessionLocal
        from ..models import KBRefreshSignal

        now = datetime.now(timezone.utc)
        async with SessionLocal() as db:
            rows = (
                await db.execute(
                    select(KBRefreshSignal).where(
                        KBRefreshSignal.status == "open",
                        KBRefreshSignal.detected_source_date.is_not(None),
                        KBRefreshSignal.detected_source_date <= verified_as_of,
                    )
                )
            ).scalars().all()
            for row in rows:
                row.status = "resolved"
                row.resolved_at = now
            await db.commit()
    except Exception:  # noqa: BLE001
        log.exception("KB freshness signals could not be resolved")


async def scheduled_check_once() -> None:
    """One freshness check. Never raises: eCFR being down must not affect serving."""
    try:
        verified = await effective_kb_verified_as_of()
        result = await check_freshness(verified)
    except Exception as exc:  # noqa: BLE001 — degradation-safe by contract
        log.info("KB freshness check skipped (eCFR unreachable: %s).", exc)
        return
    if result["stale"]:
        log.warning(
            "KB freshness: 38 CFR was amended %s — AFTER the KB verified-as-of "
            "date %s. Review the rating-criteria cards against eCFR.",
            result["title38_latest_amended_on"], result["kb_verified_as_of"],
        )
        await record_refresh_needed_signal(result)
    else:
        log.info(
            "KB freshness: Title 38 last amended %s; KB verified as of %s — current.",
            result["title38_latest_amended_on"], result["kb_verified_as_of"],
        )


async def startup_check() -> None:
    """Backward-compatible name for callers that want a single check."""
    await scheduled_check_once()


async def run_periodic_checks(interval_hours: float | None = None) -> None:
    """Run an immediate check, then repeat on the configured cadence."""
    interval = settings.kb_freshness_interval_hours if interval_hours is None else interval_hours
    if interval <= 0:
        log.info("KB freshness scheduler disabled.")
        return
    while True:
        await scheduled_check_once()
        await asyncio.sleep(max(interval, 0.01) * 3600)
