"""Service-only KB refresh receiver and audit/status reads."""

from __future__ import annotations

import hmac
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, status
from sqlalchemy import select

from ..config import settings
from ..db import SessionLocal
from ..kb import freshness
from ..kb.refresh import (
    KBRefreshApplyError,
    KBRefreshDuplicateBatchError,
    KBRefreshValidationError,
    apply_refresh_batch,
    preview_refresh_batch,
)
from ..models import KBRefreshSignal, KBRevision
from ..schemas import (
    KBRefreshBatch,
    KBRefreshOut,
    KBRefreshSignalOut,
    KBRevisionsOut,
    KBRevisionOut,
    KBStatusOut,
)

router = APIRouter(prefix="/kb", tags=["kb-admin"])


def _changed_rating_dcs(diff) -> list[str]:
    """Diagnostic-code keys whose curated rating cards actually changed."""
    return [
        item.key.split(":", 1)[1]
        for item in diff.items
        if item.action != "unchanged" and item.key.startswith("rating_criteria:")
    ]


# Legal lane: an update that DRIVES rating criteria may only cite an authoritative
# government source. Explainer content (content_kind="explainer") is exempt.
_TRUSTED_CRITERIA_HOSTS = (
    "ecfr.gov", "www.ecfr.gov",
    "va.gov", "www.va.gov", "benefits.va.gov",
    "federalregister.gov", "www.federalregister.gov",
    "govinfo.gov", "www.govinfo.gov",
)


def _validate_criteria_sources(payload: "KBRefreshBatch") -> None:
    if payload.kind != "rating_criteria":
        return
    for item in payload.items:
        if getattr(item, "content_kind", "criteria") != "criteria":
            continue
        host = (urlparse(getattr(item, "source_url", "") or "").hostname or "").lower()
        if host not in _TRUSTED_CRITERIA_HOSTS:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Rating-criteria updates must cite an authoritative source "
                f"(eCFR, VA.gov, Federal Register, GovInfo); got host '{host or '(none)'}'.",
            )


def _require_service_token(authorization: str | None) -> None:
    expected = settings.kb_refresh_service_token
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "KB refresh receiver is not configured.",
        )
    presented = ""
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid KB refresh service token.")


@router.post("/refresh", response_model=KBRefreshOut)
async def refresh_kb(
    payload: KBRefreshBatch,
    background: BackgroundTasks = None,
    dry_run: bool = Query(default=False),
    authorization: str | None = Header(default=None),
    x_service_actor: str | None = Header(default=None, alias="X-Service-Actor"),
) -> KBRefreshOut:
    """Trusted receiver for curated KB updates. Analysis never calls this path."""
    _require_service_token(authorization)
    _validate_criteria_sources(payload)
    applied_by = x_service_actor or payload.applied_by or payload.source.name
    async with SessionLocal() as db:
        try:
            if dry_run:
                batch_id, diff = await preview_refresh_batch(db, payload)
                return KBRefreshOut(ok=True, dry_run=True, batch_id=batch_id, diff=diff)
            batch_id, revision_id, diff = await apply_refresh_batch(
                db,
                payload,
                applied_by=applied_by,
            )
            await db.commit()
        except KBRefreshDuplicateBatchError as exc:
            await db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
        except KBRefreshValidationError as exc:
            await db.rollback()
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        except KBRefreshApplyError as exc:
            await db.rollback()
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
        except Exception:
            await db.rollback()
            raise
    if payload.kind == "rating_criteria":
        freshness.mark_kb_verified_as_of(payload.verified_as_of)
        await freshness.resolve_refresh_signals(payload.verified_as_of)
        changed_dcs = _changed_rating_dcs(diff)
        if changed_dcs and settings.deep_dive_on_rule_change and background is not None:
            # The receiver's SessionLocal has no veteran RLS context.  The runner
            # therefore enumerates global user ids only, then maps candidates and
            # refreshes inside one session_for_user transaction per veteran.
            from ..firm.jobs import sweep_changed_dcs

            background.add_task(sweep_changed_dcs, changed_dcs)
    return KBRefreshOut(
        ok=True,
        dry_run=False,
        batch_id=batch_id,
        revision_id=revision_id,
        diff=diff,
    )


async def _open_signals(db) -> list[KBRefreshSignalOut]:
    rows = (
        await db.execute(
            select(KBRefreshSignal)
            .where(KBRefreshSignal.status == "open")
            .order_by(KBRefreshSignal.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [KBRefreshSignalOut.model_validate(row, from_attributes=True) for row in rows]


@router.get("/revisions", response_model=KBRevisionsOut)
async def list_revisions(
    limit: int = Query(default=50, ge=1, le=200),
    authorization: str | None = Header(default=None),
) -> KBRevisionsOut:
    _require_service_token(authorization)
    async with SessionLocal() as db:
        revisions = (
            await db.execute(
                select(KBRevision).order_by(KBRevision.created_at.desc()).limit(limit)
            )
        ).scalars().all()
        return KBRevisionsOut(
            revisions=[KBRevisionOut.model_validate(row, from_attributes=True) for row in revisions],
            open_signals=await _open_signals(db),
        )


@router.get("/status", response_model=KBStatusOut)
async def kb_status(
    authorization: str | None = Header(default=None),
) -> KBStatusOut:
    _require_service_token(authorization)
    verified_as_of = await freshness.effective_kb_verified_as_of()
    async with SessionLocal() as db:
        return KBStatusOut(
            kb_verified_as_of=verified_as_of,
            freshness=freshness.cached_freshness(),
            open_signals=await _open_signals(db),
        )
