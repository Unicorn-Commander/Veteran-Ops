"""Account data portability + erasure (Wave 9 — privacy).

Two self-service, RLS-scoped endpoints the veteran runs on their OWN account:
- GET  /account/export  → their entire case file as downloadable JSON: entered data,
  derived facts/analysis, billing records, sanitized activity, team memberships, and
  VA connection metadata — never secrets or embeddings.
- GET  /account/export/archive → the same JSON plus user-confined uploaded originals.
- DELETE /account       → right-to-erasure. Deletes the user row (every user-owned
  table cascades via ON DELETE CASCADE) AND removes their on-disk upload directory.
  Guarded by a typed-email confirmation so it can't fire by accident.

Sensitive veteran data (military service, medical conditions, decision letters) —
so export deliberately EXCLUDES VA OAuth tokens/API keys and staff identity from the
sanitized activity history; delete is irreversible and logged.
"""

from __future__ import annotations

import logging
import json
import shutil
import tempfile
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from collections.abc import Iterator

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import delete as sqla_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..deps import current_user, current_user_id, get_db
from ..models import (
    AnalysisRun,
    AuditLog,
    CFilePictureCache,
    ChecklistItem,
    ClaimedCondition,
    CreditBalance,
    CreditTransaction,
    Document,
    DocumentChunk,
    DocumentFact,
    EvidenceCitation,
    EvidenceItem,
    GamePlanBriefingCache,
    GamePlanFirmCache,
    GrantApplication,
    ItfRecord,
    Organization,
    OrganizationMember,
    RatingScenario,
    Sponsorship,
    SymptomLogEntry,
    User,
    VaConnection,
    VeteranProfile,
)
from ..schemas import AccountDeleteIn
from .documents import UPLOAD_DIR

log = logging.getLogger("veteran_ops")

router = APIRouter(prefix="/account", tags=["account"])


def _jsonable(value):
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row(obj) -> dict:
    """Serialize an ORM row to a plain dict of its columns (UUID/date → str)."""
    return {c.name: _jsonable(getattr(obj, c.name)) for c in obj.__table__.columns}


def _row_without(obj, *excluded: str) -> dict:
    return {
        c.name: _jsonable(getattr(obj, c.name))
        for c in obj.__table__.columns
        if c.name not in excluded
    }


async def _all(db: AsyncSession, model, uid: uuid.UUID, order=None) -> list[dict]:
    stmt = select(model).where(model.user_id == uid)
    if order is not None:
        stmt = stmt.order_by(order)
    rows = (await db.execute(stmt)).scalars().all()
    return [_row(r) for r in rows]


async def _export_payload(
    db: AsyncSession, user_uuid: uuid.UUID
) -> tuple[dict, list[Document]]:
    """Build the portable, secret-free account payload and return its source docs."""
    user = await db.get(User, user_uuid)

    profile = (
        await db.execute(select(VeteranProfile).where(VeteranProfile.user_id == user_uuid))
    ).scalar_one_or_none()

    memberships = (
        await db.execute(
            select(OrganizationMember).where(OrganizationMember.user_id == user_uuid)
        )
    ).scalars().all()
    org_ids = [membership.org_id for membership in memberships]
    organizations = []
    if org_ids:
        organizations = (
            await db.execute(select(Organization).where(Organization.id.in_(org_ids)))
        ).scalars().all()
    va_connections = (
        await db.execute(select(VaConnection).where(VaConnection.user_id == user_uuid))
    ).scalars().all()
    activity = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user_uuid)
            .order_by(AuditLog.created_at)
        )
    ).scalars().all()
    documents = (
        await db.execute(
            select(Document)
            .where(Document.user_id == user_uuid)
            .order_by(Document.created_at)
        )
    ).scalars().all()

    payload = {
        "export_version": 2,
        "exported_at": datetime.now().astimezone().isoformat(),
        "notice": (
            "This is your own Rating Raider data, for your records. It is not a VA "
            "filing. Keep it private — it contains your service and medical claim "
            "details."
        ),
        "account": {
            "email": user.email if user else None,
            "full_name": user.full_name if user else None,
            "email_verified": user.email_verified if user else None,
            "avatar_url": user.avatar_url if user else None,
            "created_at": _jsonable(user.created_at) if user else None,
        },
        "organizations": [
            _row_without(org, "pii_cloud_consent_by") for org in organizations
        ],
        "organization_memberships": [_row(row) for row in memberships],
        "profile": _row(profile) if profile else None,
        "conditions": await _all(db, ClaimedCondition, user_uuid, ClaimedCondition.created_at),
        "evidence": await _all(db, EvidenceItem, user_uuid, EvidenceItem.created_at),
        "evidence_citations": await _all(db, EvidenceCitation, user_uuid, EvidenceCitation.created_at),
        "checklist": await _all(db, ChecklistItem, user_uuid),
        "rating_scenarios": await _all(db, RatingScenario, user_uuid),
        "symptom_log": await _all(db, SymptomLogEntry, user_uuid, SymptomLogEntry.entry_date),
        "intent_to_file": await _all(db, ItfRecord, user_uuid),
        # Absolute storage paths are implementation details and never portable.
        "documents": [_row_without(row, "file_ref") for row in documents],
        "document_facts": await _all(db, DocumentFact, user_uuid),
        # Search text is portable; embeddings are implementation-specific and can be
        # deterministically rebuilt, so they are deliberately omitted.
        "document_chunks": [
            _row_without(row, "embedding")
            for row in (
                await db.execute(
                    select(DocumentChunk)
                    .where(DocumentChunk.user_id == user_uuid)
                    .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
                )
            ).scalars().all()
        ],
        "analysis_runs": await _all(db, AnalysisRun, user_uuid, AnalysisRun.created_at),
        "generated_analysis": {
            "briefings": await _all(db, GamePlanBriefingCache, user_uuid, GamePlanBriefingCache.created_at),
            "firm_reviews": await _all(db, GamePlanFirmCache, user_uuid, GamePlanFirmCache.created_at),
            "case_pictures": await _all(db, CFilePictureCache, user_uuid, CFilePictureCache.created_at),
        },
        "billing": {
            "credit_balances": await _all(db, CreditBalance, user_uuid),
            "credit_transactions": await _all(db, CreditTransaction, user_uuid, CreditTransaction.created_at),
            "grant_applications": await _all(db, GrantApplication, user_uuid, GrantApplication.created_at),
            "sponsorships": await _all(db, Sponsorship, user_uuid, Sponsorship.created_at),
        },
        # OAuth credentials are intentionally absent; connection/sync metadata remains
        # portable so the veteran can understand what was linked and when.
        "va_connections": [
            _row_without(row, "access_token", "refresh_token") for row in va_connections
        ],
        "activity_history": [
            _row_without(row, "actor_label", "actor_user_id") for row in activity
        ],
    }

    return payload, list(documents)


@router.get("/export")
async def export_account(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Download portable account data as JSON, excluding secrets and storage paths."""
    payload, _ = await _export_payload(db, uuid.UUID(uid))
    stamp = date.today().isoformat()
    return JSONResponse(
        content=payload,
        headers={
            "Content-Disposition": f'attachment; filename="rating-raider-my-data-{stamp}.json"',
            "Cache-Control": "private, no-store",
        },
    )


def _safe_archive_name(document: Document) -> str:
    base = Path(document.filename or "record").name.strip() or "record"
    safe = "".join(
        char if char.isprintable() and char not in '\\/:*?"<>|' else "_"
        for char in base
    ).strip(" .")
    return safe or "record"


def _build_account_archive(
    payload: dict, documents: list[Document], user_uuid: uuid.UUID
):
    """Build a bounded ZIP only from originals confined to this user's directory."""
    payload_json = json.dumps(payload, indent=2, ensure_ascii=True, default=str).encode("utf-8")
    max_bytes = max(0, settings.account_export_max_bytes)
    total_bytes = len(payload_json)
    sources: list[tuple[Path, str]] = []
    user_root = (UPLOAD_DIR / str(user_uuid)).resolve()
    unavailable = 0

    for document in documents:
        try:
            if not document.file_ref:
                raise OSError("missing file reference")
            path = Path(document.file_ref).resolve(strict=True)
            path.relative_to(user_root)
            if not path.is_file():
                raise OSError("not a file")
            total_bytes += path.stat().st_size
            sources.append((path, f"documents/{document.id}/{_safe_archive_name(document)}"))
        except (OSError, ValueError):
            unavailable += 1

    if unavailable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"The archive could not include {unavailable} original file(s). "
                "Review the affected records or download the JSON-only export instead."
            ),
        )
    if total_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"This archive is larger than the configured {max_bytes}-byte limit. "
                "Download the JSON-only export or download originals individually."
            ),
        )

    archive = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024, mode="w+b")
    try:
        with zipfile.ZipFile(
            archive, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=True
        ) as bundle:
            bundle.writestr("rating-raider-data.json", payload_json)
            for path, archive_name in sources:
                bundle.write(path, archive_name)
        archive.seek(0)
        return archive
    except Exception:
        archive.close()
        raise


def _stream_archive(archive) -> Iterator[bytes]:
    try:
        while chunk := archive.read(1024 * 1024):
            yield chunk
    finally:
        archive.close()


@router.get("/export/archive")
async def export_account_archive(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Download portable JSON plus every retained uploaded original as a safe ZIP."""
    user_uuid = uuid.UUID(uid)
    payload, documents = await _export_payload(db, user_uuid)
    archive = await to_thread.run_sync(_build_account_archive, payload, documents, user_uuid)
    stamp = date.today().isoformat()
    return StreamingResponse(
        _stream_archive(archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="rating-raider-my-data-{stamp}.zip"'
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    payload: AccountDeleteIn,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete this account and ALL its data. Irreversible. Requires the
    caller to type their own email to confirm (guards against accidental clicks).
    Every user-owned table cascades from the users row; the on-disk upload directory
    is removed separately."""
    typed = (payload.confirm_email or "").strip().lower()
    if typed != (user.email or "").strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Type your account email exactly to confirm deletion.",
        )

    user_uuid = user.id
    # Remove uploaded files first (best-effort; a leftover dir must never block the
    # DB erasure the veteran asked for).
    try:
        user_dir = (UPLOAD_DIR / str(user_uuid)).resolve()
        if user_dir.is_dir() and str(user_dir).startswith(str(UPLOAD_DIR)):
            shutil.rmtree(user_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001 — disk cleanup is best-effort
        log.warning("account delete: upload dir cleanup failed for %s", user_uuid)

    # Delete the user's PERSONAL workspace first — its ON DELETE CASCADE (workspace_id)
    # wipes all their veteran data, and it removes the (now-orphaned) org row. Org
    # workspaces they merely belong to are left intact for the other members.
    from ..db import personal_workspace_id  # local import avoids a cycle at module load
    from ..models import Organization

    await db.execute(
        sqla_delete(Organization).where(
            Organization.id == uuid.UUID(personal_workspace_id(str(user_uuid)))
        )
    )

    # Delete the user row; ON DELETE CASCADE (models._user_fk) wipes anything still
    # keyed on user_id (memberships in other workspaces, plus any personal rows) and
    # the account itself.
    await db.execute(sqla_delete(User).where(User.id == user_uuid))
    log.info("account deleted: %s", user_uuid)
    return None
