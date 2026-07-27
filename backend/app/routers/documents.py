"""Document intake — upload, list, review/correct, link, reprocess, delete.

Processing runs as an in-process asyncio background task per document (the
Glitter Mane pattern): background-producing endpoints use a function-scoped DB
dependency so the request transaction commits first, then the task re-establishes
the veteran's RLS context via its own session (see intake/process.py).

Fencing: `documents` is an RLS FENCED table — the GUC-pinned request session is
the primary isolation. Queries here ALSO filter by user_id explicitly
(defense-in-depth, and it keeps cross-user 404 behavior testable without a live
Postgres).

The veteran drives: classification output is validated suggestions only.
POST /documents/{id}/link is the sole way a document becomes evidence, and only
on the veteran's explicit request. Ratings are never updated from here.
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from anyio import to_thread
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel
from starlette.responses import StreamingResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..crediting import CreditConfig, require_credits
from ..deps import current_user_id, current_workspace_id, get_db
from ..intake.doc_guidance import DOC_TYPE_GUIDANCE
from ..intake.process import (
    process_document_safe,
    process_documents_batch,
    reindex_documents_batch,
)
from ..models import (
    CFilePictureCache,
    ChecklistItem,
    ClaimedCondition,
    Document,
    DocumentChunk,
    DocumentFact,
    EvidenceCitation,
    EvidenceItem,
    GamePlanBriefingCache,
    GamePlanFirmCache,
    KBCard,
    RatingScenario,
    VeteranProfile,
)
from ..rag import search_document_chunks
from ..schemas import (
    BulkReconcileDocOut,
    BulkReconcileIn,
    BulkReconcileOut,
    DecodeOut,
    DocGuidanceOut,
    DocumentDetailOut,
    DocumentLinkIn,
    DocumentLinkOut,
    DocumentOut,
    DocumentReviewOut,
    DocumentReviewQueueItem,
    DocumentSearchHit,
    DocumentSearchOut,
    DocumentUpdate,
    DocumentUploadItem,
    DocumentUploadOut,
    EvidenceOut,
    ReconcileIn,
    ReconcileOut,
    ReviewFieldOut,
)

router = APIRouter(prefix="/documents", tags=["documents"])

# In-container the workdir is /app, so the default lands on /app/uploads —
# matching the compose volume (valor-uploads:/app/uploads).
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "uploads")).resolve()

# Max files accepted in ONE multipart upload (a .zip counts as one; it expands
# server-side under its own bomb caps). Bounds request fan-out beyond nginx's body cap.
_MAX_FILES_PER_REQUEST = 100
# 50 MB per file — matches the effective nginx client_max_body_size lane and
# covers even big single decision packets; whole C-files arrive as ZIPs.
MAX_BYTES = 50 * 1024 * 1024
# Plain-text / health-summary formats get a bigger lane: a MyHealtheVet Blue
# Button "text" export (or a C-CDA XML) routinely runs tens of MB in ONE file,
# and text has no OCR/raster cost — we store it and chunk it, and the classifier
# only ever reads the head (classify.py caps its LLM input). Kept under the ~100 MB
# edge/Cloudflare request-body ceiling so the upload actually reaches us.
MAX_TEXT_BYTES = 95 * 1024 * 1024
_TEXT_EXTS = {".txt", ".csv", ".xml"}
TOO_LARGE_DETAIL = "File is larger than 50 MB — split it or upload a smaller copy."
TOO_LARGE_TEXT_DETAIL = "File is larger than 95 MB — download a smaller date range or split it."


def _max_bytes_for(filename: str, content_type: str | None) -> int:
    """Per-file size cap: text/XML health summaries get the larger lane."""
    ext = Path(filename or "").suffix.lower()
    if ext in _TEXT_EXTS:
        return MAX_TEXT_BYTES
    ct = (content_type or "").lower()
    if ext not in ALLOWED_EXTS and ct.startswith(("text/plain", "text/csv", "text/xml", "application/xml")):
        return MAX_TEXT_BYTES
    return MAX_BYTES
# .xml admits C-CDA health summaries (VA Blue Button "VA Health Summary") —
# detected and parsed deterministically by intake/ccd.py, no LLM involved.
# Images (incl. HEIC from iPhones, BMP/WebP/GIF) → OCR; Office/RTF/OpenDocument/
# spreadsheets → deterministic text extraction (intake/ocr.py). NOT accepted:
# DICOM medical imaging (.dcm) — Valor organizes claim evidence, not pixel data;
# upload the radiology REPORT (PDF) instead.
ALLOWED_EXTS = {
    # PDF + scans/photos
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp",
    ".heic", ".heif",
    # plain text + health-summary XML
    ".txt", ".csv", ".xml",
    # Office / word-processing / spreadsheets
    ".docx", ".doc", ".rtf", ".odt", ".xlsx", ".xls",
}
ALLOWED_CONTENT_PREFIXES = (
    "application/pdf", "image/", "text/plain", "text/csv", "text/xml",
    "application/xml", "text/rtf", "application/rtf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",  # .docx/.xlsx
    "application/vnd.ms-excel",                        # .xls
    "application/vnd.oasis.opendocument",              # .odt
)

# ── ZIP dumps (a whole C-file / records folder in one upload) ────────────────
# The archive is expanded SERVER-SIDE: each valid member becomes its own
# Document row exactly as if uploaded individually; the zip itself is never
# stored. Zip-bomb guards: member-count cap, total-uncompressed cap, and a
# compression-ratio ceiling (applied only above a floor so tiny, legitimately
# repetitive text archives aren't punished).
ZIP_CONTENT_TYPES = ("application/zip", "application/x-zip-compressed")
MAX_ZIP_BYTES = 200 * 1024 * 1024          # the .zip itself
MAX_ZIP_MEMBERS = 400
MAX_ZIP_TOTAL_UNCOMPRESSED = 400 * 1024 * 1024
MAX_ZIP_RATIO = 100                        # declared uncompressed : compressed
_ZIP_RATIO_FLOOR = 10 * 1024 * 1024        # ratio guard kicks in above this

DOC_STATUSES = {"uploaded", "processing", "ready", "failed"}
DOC_TYPES = {
    "rating_decision", "decision_letter", "str", "dbq",
    "treatment_record", "private_medical_opinion", "lay_statement",
    "service_record", "other",
}


class DocumentsSummaryOut(BaseModel):
    """GET /documents/summary — dump-progress header for massive uploads."""

    total: int
    by_status: dict[str, int]
    by_type: dict[str, int]
    processing: int  # convenience mirrors of by_status
    queued: int      # status=uploaded (waiting for an intake slot)


class ReprocessFailedOut(BaseModel):
    requeued: int


class ResetRecordsIn(BaseModel):
    confirm: bool = False


class ResetRecordsOut(BaseModel):
    """POST /documents/reset — exactly what the erasure cleared, per table."""

    documents: int
    facts: int
    chunks: int
    conditions: int
    evidence: int
    citations: int
    scenarios: int
    checklist: int
    caches: int


class ReindexOut(BaseModel):
    """POST /documents/reindex — how many ready docs were queued to (re)build
    their search index, and how many were already fully searchable."""

    queued: int          # ready docs sent to (re)chunk + (re)embed
    already_indexed: int  # ready docs whose every chunk already has a vector
    skipped_no_text: int  # ready docs with no stored text to index


def _type_allowed(filename: str, content_type: str | None) -> bool:
    ext = Path(filename or "").suffix.lower()
    # A caller controls Content-Type, so it can refine handling but must never turn
    # an arbitrary extension into an accepted executable/script upload.
    return ext in ALLOWED_EXTS


_EXECUTABLE_PREFIXES = (
    b"MZ", b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
)


def _content_rejection(filename: str, data: bytes) -> str | None:
    """Reject obvious executable masquerades and mismatched structured formats."""
    ext = Path(filename or "").suffix.lower()
    if any(data.startswith(prefix) for prefix in _EXECUTABLE_PREFIXES):
        return "Executable files aren't accepted. Upload the record as PDF, image, or text."
    if ext == ".pdf" and not data[:1024].lstrip().startswith(b"%PDF-"):
        return "This file is named .pdf but does not contain a valid PDF header."
    if ext in {".docx", ".xlsx", ".odt"} and not data.startswith(b"PK\x03\x04"):
        return f"This file is named {ext} but does not contain the expected document format."
    if ext in {".doc", ".xls"} and not data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return f"This file is named {ext} but does not contain the expected legacy Office format."
    if ext == ".rtf" and not data[:32].lstrip().startswith(b"{\\rtf"):
        return "This file is named .rtf but does not contain an RTF document."
    return None


async def _read_upload_bounded(file: UploadFile, limit: int) -> bytes | None:
    """Read at most limit+1 bytes so direct-to-backend callers cannot bypass nginx."""
    chunks: list[bytes] = []
    total = 0
    while total <= limit:
        chunk = await file.read(min(1024 * 1024, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
    return None


def _write_private(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise


def _stored_path(file_ref: str) -> Path:
    path = Path(file_ref).resolve(strict=True)
    try:
        path.relative_to(UPLOAD_DIR)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file not found.") from exc
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file not found.")
    return path


def _is_zip(filename: str, content_type: str | None) -> bool:
    if Path(filename or "").suffix.lower() == ".zip":
        return True
    return (content_type or "").lower() in ZIP_CONTENT_TYPES


def _safe_member_name(raw: str) -> str | None:
    """Normalized archive-member path, or None for traversal/absolute names."""
    name = (raw or "").replace("\\", "/")
    if not name or name.startswith("/") or ":" in name.split("/", 1)[0]:
        return None
    parts = PurePosixPath(name).parts
    if not parts or any(part == ".." for part in parts):
        return None
    return name


async def _get_document(
    db: AsyncSession, uid: str, document_id: uuid.UUID
) -> Document:
    obj = (
        await db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return obj


async def _get_condition(
    db: AsyncSession, uid: str, condition_id: uuid.UUID
) -> ClaimedCondition:
    obj = (
        await db.execute(
            select(ClaimedCondition).where(
                ClaimedCondition.id == condition_id,
                ClaimedCondition.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found")
    return obj


async def _ingest_one(
    db: AsyncSession,
    uid: str,
    name: str,
    data: bytes,
    content_type: str | None,
) -> tuple[DocumentUploadItem, str | None]:
    """The per-file pipeline (validate → dedupe → store → row). Shared by loose
    uploads and expanded ZIP members. Returns (result item, new doc id|None) —
    scheduling is the caller's job so a batch drains through ONE gathered task."""
    cap = _max_bytes_for(name, content_type)
    if len(data) > cap:
        return DocumentUploadItem(
            filename=name, accepted=False,
            detail=TOO_LARGE_TEXT_DETAIL if cap == MAX_TEXT_BYTES else TOO_LARGE_DETAIL,
        ), None
    if not data:
        return DocumentUploadItem(
            filename=name, accepted=False, detail="File is empty.",
        ), None
    if not _type_allowed(name, content_type):
        return DocumentUploadItem(
            filename=name, accepted=False,
            detail="Unsupported file type — upload PDF, PNG, JPG, TIFF, TXT, or XML.",
        ), None
    rejection = _content_rejection(name, data)
    if rejection:
        return DocumentUploadItem(filename=name, accepted=False, detail=rejection), None

    user_uuid = uuid.UUID(uid)
    sha = hashlib.sha256(data).hexdigest()
    existing = (
        await db.execute(
            select(Document.id).where(
                Document.user_id == user_uuid, Document.sha256 == sha
            ).limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return DocumentUploadItem(
            filename=name, accepted=False, duplicate=True,
            existing_document_id=existing,
            detail="You already uploaded this exact file.",
        ), None

    doc = Document(
        user_id=user_uuid,
        filename=name[:255],
        content_type=content_type,
        size_bytes=len(data),
        sha256=sha,
        status="uploaded",
    )
    db.add(doc)
    await db.flush()  # obtain id for the on-disk name

    user_dir = UPLOAD_DIR / uid
    await to_thread.run_sync(user_dir.mkdir, 0o700, True, True)  # parents, exist_ok
    await to_thread.run_sync(os.chmod, user_dir, 0o700)
    path = user_dir / f"{doc.id}{Path(name).suffix.lower()}"
    await to_thread.run_sync(_write_private, path, data)
    doc.file_ref = str(path)
    await db.flush()
    await db.refresh(doc)

    await audit.log(
        db, uid, "document.upload", entity="document", entity_id=str(doc.id),
        meta={"filename": doc.filename, "size_bytes": doc.size_bytes, "sha256": sha},
    )
    return DocumentUploadItem(filename=name, accepted=True, document=doc), str(doc.id)


def _zip_guard(zf: zipfile.ZipFile) -> str | None:
    """Human-readable rejection for a suspicious archive, else None."""
    members = [i for i in zf.infolist() if not i.is_dir()]
    if len(members) > MAX_ZIP_MEMBERS:
        return (
            f"ZIP contains {len(members)} files — the limit is {MAX_ZIP_MEMBERS}. "
            "Split it into smaller archives."
        )
    total = sum(i.file_size for i in members)
    if total > MAX_ZIP_TOTAL_UNCOMPRESSED:
        return (
            "ZIP expands to more than "
            f"{MAX_ZIP_TOTAL_UNCOMPRESSED // (1024 * 1024)} MB — split it into "
            "smaller archives."
        )
    compressed = sum(i.compress_size for i in members)
    if total > _ZIP_RATIO_FLOOR and total > MAX_ZIP_RATIO * max(compressed, 1):
        return "ZIP compression ratio looks unsafe — the archive was rejected."
    return None


def _read_zip_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Decompress one member, never more than the per-file cap + 1 byte (so an
    understated header can't flood memory — the extra byte trips the size cap)."""
    with zf.open(info) as fh:
        return fh.read(MAX_BYTES + 1)


async def _expand_zip(
    db: AsyncSession, uid: str, zip_name: str, data: bytes
) -> tuple[list[DocumentUploadItem], list[str]]:
    """Expand an uploaded archive: one upload-result item per member (named
    'archive.zip/inner.pdf'), one Document row per VALID member — the same
    validation + dedupe as a loose upload. The zip itself is not stored."""
    if len(data) > MAX_ZIP_BYTES:
        return [DocumentUploadItem(
            filename=zip_name, accepted=False,
            detail=(
                f"ZIP is larger than {MAX_ZIP_BYTES // (1024 * 1024)} MB — "
                "split it into smaller archives."
            ),
        )], []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return [DocumentUploadItem(
            filename=zip_name, accepted=False,
            detail="This ZIP file is damaged or not a ZIP — re-export and try again.",
        )], []

    with zf:
        guard = _zip_guard(zf)
        if guard is not None:
            return [DocumentUploadItem(
                filename=zip_name, accepted=False, detail=guard,
            )], []

        items: list[DocumentUploadItem] = []
        doc_ids: list[str] = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            display = f"{zip_name}/{info.filename}"
            member = _safe_member_name(info.filename)
            if member is None:
                items.append(DocumentUploadItem(
                    filename=display, accepted=False,
                    detail="Skipped — unsafe path inside the archive.",
                ))
                continue
            if Path(member).suffix.lower() == ".zip":
                items.append(DocumentUploadItem(
                    filename=display, accepted=False,
                    detail=(
                        "Nested ZIP archives aren't expanded — upload the inner "
                        "archive separately."
                    ),
                ))
                continue
            try:
                blob = await to_thread.run_sync(_read_zip_member, zf, info)
            except Exception:  # noqa: BLE001 — encrypted/corrupt member
                items.append(DocumentUploadItem(
                    filename=display, accepted=False,
                    detail="Couldn't read this file from the archive (encrypted or corrupt).",
                ))
                continue
            item, doc_id = await _ingest_one(
                db, uid, f"{zip_name}/{member}", blob,
                mimetypes.guess_type(member)[0],
            )
            items.append(item)
            if doc_id is not None:
                doc_ids.append(doc_id)
        return items, doc_ids


@router.post("", response_model=DocumentUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_documents(
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Multi-file upload. Per-file outcome (nothing all-or-nothing): accepted →
    stored + queued for processing; duplicate (same sha256 already on file) →
    409-style skip flag with the existing id; unsupported/oversized → rejected
    with a human-readable detail. A .zip is expanded server-side: each valid
    member becomes its own document ('archive.zip/inner.pdf'); the zip itself
    is not stored. All accepted files drain through ONE background batch task —
    the intake semaphore turns a massive dump into an orderly queue."""
    # Bound a single request's fan-out. nginx caps the total body (210m); this caps
    # the FILE COUNT so a caller reaching the app directly can't push tens of
    # thousands of tiny files into one transaction (memory/DB exhaustion). A ZIP is
    # one file here and expands server-side under its own bomb caps.
    if len(files) > _MAX_FILES_PER_REQUEST:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Too many files in one upload (max {_MAX_FILES_PER_REQUEST}). "
            "Upload in smaller batches, or bundle them into a .zip.",
        )
    items: list[DocumentUploadItem] = []
    doc_ids: list[str] = []
    for file in files:
        name = file.filename or "upload"
        limit = MAX_ZIP_BYTES if _is_zip(name, file.content_type) else _max_bytes_for(name, file.content_type)
        data = await _read_upload_bounded(file, limit)
        if data is None:
            detail = (
                f"ZIP is larger than {MAX_ZIP_BYTES // (1024 * 1024)} MB — split it into smaller archives."
                if _is_zip(name, file.content_type)
                else (TOO_LARGE_TEXT_DETAIL if limit == MAX_TEXT_BYTES else TOO_LARGE_DETAIL)
            )
            items.append(DocumentUploadItem(filename=name, accepted=False, detail=detail))
            continue
        if _is_zip(name, file.content_type):
            zip_items, zip_ids = await _expand_zip(db, uid, name, data)
            items.extend(zip_items)
            doc_ids.extend(zip_ids)
            continue
        item, doc_id = await _ingest_one(db, uid, name, data, file.content_type)
        items.append(item)
        if doc_id is not None:
            doc_ids.append(doc_id)

    if doc_ids:
        # Runs after the response (and after this request's txn commits).
        background.add_task(process_documents_batch, uid, doc_ids, wsid)
    return DocumentUploadOut(items=items)


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    status: str | None = None,  # noqa: A002 — query param name per spec
    doc_type: str | None = None,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    # List responses never need multi-MB OCR text — defer text_content to get-by-id.
    from sqlalchemy.orm import load_only

    stmt = (
        select(Document)
        .options(
            load_only(
                Document.id,
                Document.user_id,
                Document.workspace_id,
                Document.filename,
                Document.content_type,
                Document.size_bytes,
                Document.sha256,
                Document.status,
                Document.doc_type,
                Document.doc_date,
                Document.title,
                Document.summary,
                Document.extracted,
                Document.page_offsets,
                Document.condition_id,
                Document.file_ref,
                Document.error,
                Document.text_fingerprint,
                Document.simhash,
                Document.duplicate_of,
                Document.review_status,
                Document.created_at,
                Document.updated_at,
            )
        )
        .where(Document.user_id == uuid.UUID(uid))
    )
    if status:
        if status not in DOC_STATUSES:
            raise HTTPException(422, f"status must be one of {sorted(DOC_STATUSES)}")
        stmt = stmt.where(Document.status == status)
    if doc_type:
        if doc_type not in DOC_TYPES:
            raise HTTPException(422, f"doc_type must be one of {sorted(DOC_TYPES)}")
        stmt = stmt.where(Document.doc_type == doc_type)
    rows = (await db.execute(stmt.order_by(Document.created_at.desc()))).scalars().all()
    return rows


# NOTE: registered before /{document_id} so the literal path wins the match.
@router.get("/upload-guidance", response_model=DocGuidanceOut)
async def upload_guidance(
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Plain-language 'what to upload' guidance for every document type Valor
    recognizes: what it is, concrete examples of what counts, and why it helps
    a claim. Educational self-help content only (never legal advice, never an
    outcome promise) — the veteran decides what to actually upload."""
    return DocGuidanceOut(guidance=DOC_TYPE_GUIDANCE)


# NOTE: registered before /{document_id} so the literal path wins the match.
@router.get("/summary", response_model=DocumentsSummaryOut)
async def documents_summary(
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Dump-progress header: counts by status and type. 'queued' = uploaded rows
    waiting for an intake slot; 'processing' = rows holding one right now."""
    user_uuid = uuid.UUID(uid)
    by_status = {
        row_status: count
        for row_status, count in (
            await db.execute(
                select(Document.status, func.count())
                .where(Document.user_id == user_uuid)
                .group_by(Document.status)
            )
        ).all()
    }
    by_type = {
        (doc_type or "unclassified"): count
        for doc_type, count in (
            await db.execute(
                select(Document.doc_type, func.count())
                .where(Document.user_id == user_uuid)
                .group_by(Document.doc_type)
            )
        ).all()
    }
    return DocumentsSummaryOut(
        total=sum(by_status.values()),
        by_status=by_status,
        by_type=by_type,
        processing=by_status.get("processing", 0),
        queued=by_status.get("uploaded", 0),
    )


@router.post("/reprocess-failed", response_model=ReprocessFailedOut)
async def reprocess_failed_documents(
    background: BackgroundTasks,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Requeue every failed document (e.g. after an LLM-gateway outage during a
    big dump). Requeued rows go back to 'uploaded' (queued in the UI) and drain
    through the bounded intake queue. Rows with nothing left to work from
    (stored file gone AND no parsed text) are left failed."""
    rows = (
        await db.execute(
            select(Document).where(
                Document.user_id == uuid.UUID(uid),
                Document.status == "failed",
            )
        )
    ).scalars().all()

    doc_ids: list[str] = []
    for doc in rows:
        has_file = bool(doc.file_ref) and os.path.exists(doc.file_ref)
        if not has_file and not (doc.text_content or "").strip():
            continue
        doc.status = "uploaded"  # queued — the UI already renders this state
        doc.error = None
        doc_ids.append(str(doc.id))
    await db.flush()

    if doc_ids:
        await audit.log(
            db, uid, "document.reprocess_failed", entity="document",
            meta={"requeued": len(doc_ids)},
        )
        background.add_task(process_documents_batch, uid, doc_ids, wsid)
    return ReprocessFailedOut(requeued=len(doc_ids))


@router.post("/reprocess-ocr", response_model=ReprocessFailedOut)
async def reprocess_all_ocr(
    background: BackgroundTasks,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Re-OCR every already-read document that still has its stored file, so the
    records are re-read through the CURRENT OCR pipeline (page preprocessing + the
    decorrelated cross-read engine). Clears each document's cached text so intake
    re-extracts from the file; documents whose file is gone are skipped (nothing to
    re-read). This is the explicit 're-OCR my records' action — it costs one
    document-process credit per re-read, so it is never automatic."""
    rows = (
        await db.execute(
            select(Document).where(
                Document.user_id == uuid.UUID(uid),
                Document.status.in_(("ready", "failed")),
            )
        )
    ).scalars().all()

    doc_ids: list[str] = []
    for doc in rows:
        has_file = bool(doc.file_ref) and os.path.exists(doc.file_ref)
        if not has_file:
            continue  # can't re-read a document whose file is gone
        doc.text_content = None  # force re-OCR from the file
        doc.status = "uploaded"  # queued — drains through the bounded intake queue
        doc.error = None
        doc_ids.append(str(doc.id))
    await db.flush()

    if doc_ids:
        await audit.log(
            db, uid, "document.reprocess_ocr", entity="document",
            meta={"reocr": len(doc_ids)},
        )
        background.add_task(process_documents_batch, uid, doc_ids, wsid)
    return ReprocessFailedOut(requeued=len(doc_ids))


@router.post("/reset", response_model=ResetRecordsOut)
async def reset_records(
    payload: ResetRecordsIn,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Erase ALL of the caller's uploaded records and the analysis derived from them:
    documents (+ their stored files), mapped facts, embedded chunks, auto-extracted
    conditions / evidence / citations, saved rating scenarios, checklist items, and the
    Game Plan / specialist-firm / C-file-picture caches. This is the veteran's own
    right-to-erasure of their C-file — and the clean slate for re-uploading to
    benchmark a cold, first-time run.

    PRESERVED (account state, not C-file-derived records): the account + workspace, the
    veteran profile ROW and its onboarding inputs (service periods, exposures, the
    combat/retired-pay flags), ITF deadlines, symptom-log entries, VA connections,
    credits, the audit trail, and prior analysis-run benchmark rows. The profile's
    document-EXTRACTED identity + dependents ARE cleared (they came from the wiped
    records).

    DESTRUCTIVE + IRREVERSIBLE — requires an explicit ``confirm: true``. RLS plus an
    explicit user_id filter fence every delete to the caller's own rows.
    """
    if not payload.confirm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Confirm required — this permanently deletes all your records.",
        )
    u = uuid.UUID(uid)

    async def _count(model) -> int:
        return int(
            (
                await db.execute(
                    select(func.count()).select_from(model).where(model.user_id == u)
                )
            ).scalar()
            or 0
        )

    # Counts BEFORE deleting — an ON DELETE CASCADE would otherwise hide child rowcounts.
    counts = {
        "documents": await _count(Document),
        "facts": await _count(DocumentFact),
        "chunks": await _count(DocumentChunk),
        "conditions": await _count(ClaimedCondition),
        "evidence": await _count(EvidenceItem),
        "citations": await _count(EvidenceCitation),
        "scenarios": await _count(RatingScenario),
        "checklist": await _count(ChecklistItem),
    }
    caches = 0
    for cache_model in (GamePlanBriefingCache, GamePlanFirmCache, CFilePictureCache):
        caches += await _count(cache_model)

    # Reclaim disk first (the row is the source of truth; a stray file is harmless).
    file_refs = (
        await db.execute(select(Document.file_ref).where(Document.user_id == u))
    ).scalars().all()
    for ref in file_refs:
        try:
            if ref and os.path.exists(ref):
                await to_thread.run_sync(os.remove, ref)
        except OSError:
            pass

    # Delete leaves → parents. FKs (evidence→conditions, facts/chunks/citations→
    # documents) are ON DELETE CASCADE, but ordered explicit deletes keep the returned
    # counts exact and never depend on cascade order.
    for model in (
        EvidenceCitation,
        EvidenceItem,
        ChecklistItem,
        RatingScenario,
        DocumentFact,
        DocumentChunk,
        Document,
        ClaimedCondition,
        GamePlanBriefingCache,
        GamePlanFirmCache,
        CFilePictureCache,
    ):
        await db.execute(delete(model).where(model.user_id == u))

    # Clear the C-file-DERIVED PII off the profile too (identity + dependents are
    # extracted from uploaded documents by the intake pipeline), so a right-to-erasure
    # leaves nothing pulled from the wiped records. The profile ROW stays (it's the
    # account link) and the veteran's own onboarding inputs — service periods,
    # exposures, and the combat/retired-pay flags — are preserved.
    await db.execute(
        update(VeteranProfile)
        .where(VeteranProfile.user_id == u)
        .values(identity=None, dependents=None)
    )

    await audit.log(
        db, uid, "records.reset", entity="user", entity_id=uid,
        meta={**counts, "caches": caches},
    )
    return ResetRecordsOut(**counts, caches=caches)


def _needs_reindex(total_chunks: int, embedded_chunks: int) -> bool:
    """A ready doc needs (re)indexing when it isn't fully vector-searchable:
    never chunked (total==0, predates document-RAG) OR some chunk carries no
    vector (embedded<total, chunked during an embeddings outage). Fully embedded
    docs (embedded==total>0) are left alone so reindex is idempotent."""
    return total_chunks == 0 or embedded_chunks < total_chunks


@router.post("/reindex", response_model=ReindexOut)
async def reindex_documents(
    background: BackgroundTasks,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Make older / degraded records searchable.

    Document-RAG chunks a record when it's processed, but a doc that reached
    'ready' BEFORE this feature shipped has no chunks at all, and a doc chunked
    DURING an embeddings outage has chunks with no vectors (keyword-only). Both
    are 'ready', so reprocess-failed never touches them. This queues every ready
    doc that isn't fully vector-indexed to (re)chunk + (re)embed from its
    ALREADY-stored text — no re-OCR, no re-classification. Idempotent: a doc
    whose every chunk already has a vector is left alone."""
    ready = (
        await db.execute(
            select(Document.id, Document.text_content).where(
                Document.user_id == uuid.UUID(uid),
                Document.status == "ready",
            )
        )
    ).all()

    # Per-document chunk coverage: total chunks and how many carry a vector.
    # count(embedding) counts only non-NULL vectors, so total > embedded means
    # some chunk is keyword-only (outage) and the doc should be re-embedded.
    coverage = {
        doc_id: (total, embedded)
        for doc_id, total, embedded in (
            await db.execute(
                select(
                    DocumentChunk.document_id,
                    func.count(),
                    func.count(DocumentChunk.embedding),
                )
                .where(DocumentChunk.user_id == uuid.UUID(uid))
                .group_by(DocumentChunk.document_id)
            )
        ).all()
    }

    doc_ids: list[str] = []
    already_indexed = 0
    skipped_no_text = 0
    for doc_id, text in ready:
        if not (text or "").strip():
            skipped_no_text += 1
            continue
        total, embedded = coverage.get(doc_id, (0, 0))
        if not _needs_reindex(total, embedded):
            already_indexed += 1
            continue
        doc_ids.append(str(doc_id))

    if doc_ids:
        await audit.log(
            db, uid, "document.reindex_requested", entity="document",
            meta={"queued": len(doc_ids)},
        )
        background.add_task(reindex_documents_batch, uid, doc_ids, wsid)
    return ReindexOut(
        queued=len(doc_ids),
        already_indexed=already_indexed,
        skipped_no_text=skipped_no_text,
    )


_VA_DECISION_TYPES = ("rating_decision", "decision_letter")


def _is_va_decision(doc: Document) -> bool:
    """A decision the decoder can work on: classified as a VA decision by type,
    or flagged is_va_decision by the intake extraction."""
    if doc.doc_type in _VA_DECISION_TYPES:
        return True
    return bool((doc.extracted or {}).get("is_va_decision"))


async def _review_source(db: AsyncSession) -> str | None:
    """Best-effort: the exact citation from the KB decision-review-lanes card, so
    the decoder's 'your options' cite the same source the KB does. Degrades to
    None (analyze stamps its faithful default) on any lookup miss."""
    try:
        row = (
            await db.execute(
                select(KBCard.source)
                .where(
                    KBCard.card_type == "process",
                    KBCard.title.ilike("%decision review lanes%"),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row or None
    except Exception:  # noqa: BLE001 — grounding is optional, never fatal
        return None


# NOTE: registered before /{document_id} so the literal path wins the match.
@router.get("/decodable", response_model=list[DocumentOut])
async def decodable_documents(
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Every ready document the decoder can decode: a VA rating decision / decision
    letter (by classified type OR the is_va_decision extraction flag). The flag
    lives in JSONB; we filter it in Python so the query stays dialect-independent
    and reuses the same _is_va_decision rule the decode endpoint enforces."""
    rows = (
        await db.execute(
            select(Document)
            .where(
                Document.user_id == uuid.UUID(uid),
                Document.status == "ready",
            )
            .order_by(Document.doc_date.desc().nullslast(), Document.created_at.desc())
        )
    ).scalars().all()
    return [d for d in rows if _is_va_decision(d)]


# NOTE: registered before /{document_id} so the literal path wins the match.
@router.get("/search", response_model=DocumentSearchOut)
async def search_documents(
    q: str = Query(..., min_length=2, max_length=400, description="What to find in your records"),
    k: int = Query(6, ge=1, le=20),
    document_id: uuid.UUID | None = Query(None, description="Limit to one document"),
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Search the veteran's OWN uploaded documents and return matching excerpts.

    Semantic (embedding) ranking when available, keyword fallback otherwise —
    `semantic` says which. Every excerpt is the veteran's uploaded text verbatim
    with a link back to its source document; nothing is interpreted or diagnosed.
    """
    chunks, semantic = await search_document_chunks(
        db, uid, q, k=k, document_id=str(document_id) if document_id else None
    )
    if not chunks:
        return DocumentSearchOut(query=q, semantic=semantic, hits=[])

    # Enrich with parent-document metadata (one batched, RLS-fenced lookup).
    doc_ids = {c.document_id for c in chunks}
    docs = {
        d.id: d
        for d in (
            await db.execute(
                select(Document).where(
                    Document.id.in_(doc_ids),
                    Document.user_id == uuid.UUID(uid),
                )
            )
        ).scalars().all()
    }
    hits: list[DocumentSearchHit] = []
    for c in chunks:
        doc = docs.get(c.document_id)
        if doc is None:  # parent deleted between retrieval and enrichment
            continue
        hits.append(DocumentSearchHit(
            document_id=doc.id,
            filename=doc.filename,
            title=doc.title,
            doc_type=doc.doc_type,
            doc_date=doc.doc_date,
            chunk_index=c.chunk_index,
            char_start=c.char_start,
            char_end=c.char_end,
            excerpt=c.content,
        ))
    return DocumentSearchOut(query=q, semantic=semantic, hits=hits)


def _content_disposition(mode: str, filename: str) -> str:
    ascii_name = filename.replace("\\", "_").replace("/", "_").replace('"', "'")
    return f"{mode}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


# NOTE: registered before /{document_id} so the literal path wins the match.
@router.get("/review-queue", response_model=list[DocumentReviewQueueItem])
async def documents_review_queue(
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Every document whose extraction needs the veteran's eye — a value the
    extract-verify pass couldn't confirm (disputed/unsupported), a condition it
    thinks was missed, or two OCR engines that read a page differently. Nothing here
    was silently accepted as fact; the veteran reconciles each on
    POST /documents/{id}/reconcile."""
    rows = (
        await db.execute(
            select(Document)
            .where(
                Document.user_id == uuid.UUID(uid),
                Document.review_status == "flagged",
            )
            .order_by(Document.created_at.desc())
        )
    ).scalars().all()
    out: list[DocumentReviewQueueItem] = []
    for doc in rows:
        review = (doc.extracted or {}).get("review") or {}
        crossread = review.get("crossread") or {}
        out.append(
            DocumentReviewQueueItem(
                id=doc.id,
                filename=doc.filename,
                title=doc.title,
                doc_type=doc.doc_type,
                doc_date=doc.doc_date,
                review_status=doc.review_status,
                fields_pending=len(review.get("fields") or []),
                missing_conditions=len(review.get("missing_conditions") or []),
                crossread_pages_flagged=int(crossread.get("pages_flagged") or 0),
                created_at=doc.created_at,
            )
        )
    return out


@router.post("/review-queue/bulk-reconcile", response_model=BulkReconcileOut)
async def bulk_reconcile_review_queue(
    payload: BulkReconcileIn,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Veteran-confirmed bulk resolve of the review queue.

    Applies one resolution policy across all flagged documents. Defaults to
    ``accept_agreed`` (only where both readers show the same value) — the
    safest bulk path. Never invents values; never files with VA.
    """
    rows = (
        await db.execute(
            select(Document).where(
                Document.user_id == uuid.UUID(uid),
                Document.review_status == "flagged",
            )
        )
    ).scalars().all()

    results: list[BulkReconcileDocOut] = []
    fields_applied = 0
    fields_skipped = 0
    resolved_docs = 0

    for doc in rows:
        extracted = dict(doc.extracted or {})
        review = dict(extracted.get("review") or {})
        fields = [f for f in (review.get("fields") or []) if isinstance(f, dict)]
        missing_raw = [m for m in (review.get("missing_conditions") or []) if isinstance(m, dict)]

        # Orphan flags: review_status=flagged but nothing actionable (e.g. OCR
        # cross-read only). Clear so the veteran is not stuck forever.
        if not fields and not missing_raw:
            review["status"] = "resolved"
            review["fields"] = []
            review["missing_conditions"] = []
            doc.review_status = "resolved"
            extracted["review"] = review
            doc.extracted = extracted
            await db.flush()
            resolved_docs += 1
            results.append(
                BulkReconcileDocOut(
                    document_id=doc.id,
                    applied=0,
                    skipped=0,
                    review_status="resolved",
                )
            )
            continue

        if payload.mode == "clear_all":
            review["fields"] = []
            review["missing_conditions"] = []
            review["status"] = "resolved"
            doc.review_status = "resolved"
            extracted["review"] = review
            doc.extracted = extracted
            await db.flush()
            resolved_docs += 1
            results.append(
                BulkReconcileDocOut(
                    document_id=doc.id,
                    applied=0,
                    skipped=0,
                    review_status="resolved",
                )
            )
            continue

        extracted["conditions_mentioned"] = [
            dict(c) if isinstance(c, dict) else c
            for c in extracted.get("conditions_mentioned", [])
        ]
        applied = 0
        skipped = 0
        resolved_ids: set[str] = set()

        for f in fields:
            fid = f.get("field_id")
            if not fid:
                skipped += 1
                continue
            candidate = f.get("candidate_value")
            extracted_v = f.get("extracted_value")
            value = None
            use = False
            if payload.mode == "accept_record":
                value, use = candidate, True
            elif payload.mode == "accept_extracted":
                value, use = extracted_v, True
            else:  # accept_agreed
                if candidate is not None and candidate == extracted_v:
                    value, use = candidate, True
                else:
                    skipped += 1
            if use:
                # Always drop the flag when the veteran chose a bulk policy for
                # this field — even if write-back fails (stale index). Stuck queue
                # is worse than a skipped write.
                if _apply_resolution(extracted, str(fid), value):
                    applied += 1
                else:
                    skipped += 1
                resolved_ids.add(str(fid))

        remaining = [f for f in fields if f.get("field_id") not in resolved_ids]
        missing = missing_raw
        if payload.dismiss_all_missing:
            missing = []
        review["fields"] = remaining
        review["missing_conditions"] = missing
        pending = bool(remaining) or bool(missing)
        review["status"] = "flagged" if pending else "resolved"
        doc.review_status = "flagged" if pending else "resolved"
        extracted["review"] = review
        doc.extracted = extracted
        await db.flush()

        fields_applied += applied
        fields_skipped += skipped
        if not pending:
            resolved_docs += 1
        results.append(
            BulkReconcileDocOut(
                document_id=doc.id,
                applied=applied,
                skipped=skipped,
                review_status=doc.review_status,
            )
        )

    await audit.log(
        db,
        uid,
        "document.bulk_reconcile",
        entity="document",
        entity_id=None,
        meta={
            "mode": payload.mode,
            "dismiss_all_missing": payload.dismiss_all_missing,
            "documents_touched": len(results),
            "fields_applied": fields_applied,
            "fields_skipped": fields_skipped,
            "resolved_documents": resolved_docs,
        },
    )
    return BulkReconcileOut(
        documents_touched=len(results),
        fields_applied=fields_applied,
        fields_skipped=fields_skipped,
        resolved_documents=resolved_docs,
        results=results,
    )


# NOTE: registered before /{document_id} so the literal suffix wins the match.
@router.get("/{document_id}/file")
async def get_document_file(
    document_id: uuid.UUID,
    download: bool = Query(False, description="Set to 1 to download the original file"),
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Stream the veteran's uploaded original file.

    Same ownership fence as GET /documents/{id}: RLS is active for the request
    session, and the lookup also filters user_id explicitly for predictable 404s.
    """
    doc = await _get_document(db, uid, document_id)
    if not doc.file_ref:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file not found. Delete and re-upload.")
    try:
        path = _stored_path(doc.file_ref)
    except (HTTPException, OSError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stored file not found. Delete and re-upload.") from None
    media_type = doc.content_type or mimetypes.guess_type(doc.filename)[0] or "application/octet-stream"
    safe_inline = media_type == "application/pdf" or media_type.startswith("image/")
    mode = "inline" if safe_inline and not download else "attachment"
    return StreamingResponse(
        path.open("rb"),
        media_type=media_type,
        headers={
            "Content-Disposition": _content_disposition(mode, doc.filename),
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@router.get("/{document_id}", response_model=DocumentDetailOut)
async def get_document(
    document_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    return await _get_document(db, uid, document_id)


@router.get("/{document_id}/review", response_model=DocumentReviewOut)
async def get_document_review(
    document_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """The extraction disagreements this document is flagged for: each field the
    extract-verify pass couldn't confirm (with the machine's value, the value the
    source/other engine shows, and the verbatim quote), the conditions it thinks
    were missed, and any conflicting OCR pages. The veteran resolves these on
    POST /reconcile — nothing here is treated as fact until they do."""
    doc = await _get_document(db, uid, document_id)
    review = (doc.extracted or {}).get("review") or {}
    fields = [
        ReviewFieldOut(**f)
        for f in (review.get("fields") or [])
        if isinstance(f, dict) and f.get("field_id")
    ]
    return DocumentReviewOut(
        document_id=doc.id,
        review_status=doc.review_status,
        fields=fields,
        missing_conditions=[m for m in (review.get("missing_conditions") or []) if isinstance(m, dict)],
        crossread=review.get("crossread"),
    )


def _apply_resolution(extracted: dict, field_id: str, value) -> bool:
    """Write the veteran's chosen value onto the exact (condition, field) the flag
    named, re-validated with the SAME pure cleaners intake uses — so a reconcile
    can't reintroduce an off-grid percent or a malformed DC. Returns whether it
    applied."""
    from ..intake.classify import _DECISIONS, _clean_dc, _clean_percent, _clean_str

    try:
        idx_str, field = field_id.split(":", 1)
        idx = int(idx_str)
    except (ValueError, AttributeError):
        return False
    conditions = extracted.get("conditions_mentioned")
    if not isinstance(conditions, list) or not (0 <= idx < len(conditions)):
        return False
    cond = conditions[idx]
    if not isinstance(cond, dict):
        return False
    if field == "rating_percent":
        cond["rating_percent"] = _clean_percent(value) if value is not None else None
    elif field == "diagnostic_code":
        cond["diagnostic_code"] = _clean_dc(value) if value is not None else None
    elif field == "decision":
        cond["decision"] = value if value in _DECISIONS else None
    elif field == "name":
        name = _clean_str(value, 255)
        if not name:
            return False  # a condition can't be blank-named via reconcile
        cond["name"] = name
    else:
        return False
    return True


@router.post("/{document_id}/reconcile", response_model=ReconcileOut)
async def reconcile_document(
    document_id: uuid.UUID,
    payload: ReconcileIn,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """The veteran resolves a flagged document: pick the correct value per field
    (writing the corrected tuple), and/or dismiss a 'missed condition' note. When
    nothing remains pending the flag clears (review_status='resolved'); a partial
    reconcile keeps the doc flagged with the remaining fields. Audit-logged."""
    doc = await _get_document(db, uid, document_id)
    extracted = dict(doc.extracted or {})
    review = dict(extracted.get("review") or {})
    if not review or doc.review_status not in ("flagged", "resolved"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Nothing to reconcile — this document isn't flagged for review.",
        )
    # Copy the conditions so the JSONB reassignment below is change-tracked.
    extracted["conditions_mentioned"] = [
        dict(c) if isinstance(c, dict) else c
        for c in extracted.get("conditions_mentioned", [])
    ]
    fields = [f for f in (review.get("fields") or []) if isinstance(f, dict)]
    by_id = {f.get("field_id"): f for f in fields}
    applied = 0
    resolved_ids: set[str] = set()
    # Always defined — clear_document used to skip this branch and 500 on audit.
    dismiss: set[str] = {d.strip().casefold() for d in (payload.dismiss_missing or []) if d}

    if payload.clear_document:
        remaining = []
        missing = []
        # Count every pending miss as dismissed for audit when the veteran
        # clears the whole flag ("Clear flag and continue").
        for m in review.get("missing_conditions") or []:
            if isinstance(m, dict) and (m.get("name") or "").strip():
                dismiss.add((m.get("name") or "").strip().casefold())
    else:
        for r in payload.resolutions:
            if r.field_id not in by_id:
                continue
            if _apply_resolution(extracted, r.field_id, r.value):
                applied += 1
            # Drop the flag either way once the veteran chose a value (or clear).
            resolved_ids.add(r.field_id)

        remaining = [f for f in fields if f.get("field_id") not in resolved_ids]
        missing = [
            m for m in (review.get("missing_conditions") or [])
            if isinstance(m, dict) and (m.get("name") or "").strip().casefold() not in dismiss
        ]
        # No actionable items left (e.g. only OCR cross-read noise) → clear.
        if not remaining and not missing:
            remaining, missing = [], []

    review["fields"] = remaining
    review["missing_conditions"] = missing
    # Cross-read is informational; clearing fields/missing resolves the flag.
    if payload.clear_document and isinstance(review.get("crossread"), dict):
        review["crossread"] = {**review["crossread"], "cleared": True}
    pending = bool(remaining) or bool(missing)
    review["status"] = "flagged" if pending else "resolved"
    doc.review_status = "flagged" if pending else "resolved"
    extracted["review"] = review
    doc.extracted = extracted  # reassign — JSONB in-place mutation isn't tracked
    await db.flush()
    await db.refresh(doc)
    await audit.log(
        db, uid, "document.reconcile", entity="document", entity_id=str(doc.id),
        meta={
            "applied": applied,
            "resolved_fields": sorted(resolved_ids),
            "dismissed_missing": len(dismiss),
            "clear_document": bool(payload.clear_document),
            "review_status": doc.review_status,
        },
    )
    return ReconcileOut(
        document_id=doc.id,
        review_status=doc.review_status,
        applied=applied,
        conditions_mentioned=extracted.get("conditions_mentioned", []),
    )


@router.patch("/{document_id}", response_model=DocumentDetailOut)
async def update_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """The veteran corrects the machine: doc_type / title / doc_date / primary
    condition link. condition_id=null clears the link."""
    doc = await _get_document(db, uid, document_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("condition_id") is not None:
        await _get_condition(db, uid, changes["condition_id"])  # 404 if not theirs
    for key, value in changes.items():
        setattr(doc, key, value)
    await db.flush()
    await db.refresh(doc)
    await audit.log(
        db, uid, "document.update", entity="document", entity_id=str(doc.id),
        meta={"fields": sorted(changes.keys())},
    )
    return doc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_document(db, uid, document_id)
    try:
        if doc.file_ref and os.path.exists(doc.file_ref):
            await to_thread.run_sync(os.remove, doc.file_ref)
    except OSError:
        pass  # the row is the source of truth; a stray file is harmless
    await db.delete(doc)
    await audit.log(db, uid, "document.delete", entity="document", entity_id=str(document_id))


@router.post("/{document_id}/reprocess", response_model=DocumentOut)
async def reprocess_document(
    document_id: uuid.UUID,
    background: BackgroundTasks,
    force_ocr: bool = False,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db, scope="function"),
):
    """Re-run the pipeline (e.g. after 'LLM unavailable'). Already-parsed text is
    reused — a failed classification never forces a re-OCR — UNLESS force_ocr=true,
    which CLEARS the stored text so the document is re-read from its file. That is how
    an OCR-pipeline improvement (page preprocessing, a new cross-read engine) reaches
    a document that was already extracted. Needs the stored file."""
    doc = await _get_document(db, uid, document_id)
    if doc.status == "processing":
        raise HTTPException(status.HTTP_409_CONFLICT, "Document is already processing")
    has_file = bool(doc.file_ref) and os.path.exists(doc.file_ref)
    if force_ocr and not has_file:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Can't re-OCR — the stored file is missing. Delete and re-upload to re-read it.",
        )
    if not has_file and not (doc.text_content or "").strip():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Nothing to reprocess — the stored file is missing. Delete and re-upload.",
        )
    if force_ocr:
        doc.text_content = None  # forces the OCR/extract path in process_document
    doc.status = "processing"
    doc.error = None
    await db.flush()
    await db.refresh(doc)
    await audit.log(
        db, uid, "document.reprocess", entity="document", entity_id=str(doc.id),
        meta={"force_ocr": force_ocr},
    )
    background.add_task(process_document_safe, uid, str(doc.id), wsid)
    return doc


@router.post("/{document_id}/link", response_model=DocumentLinkOut)
async def link_document(
    document_id: uuid.UUID,
    payload: DocumentLinkIn,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """The veteran's EXPLICIT confirmation of a suggested (or manual) link:
    creates an evidence item (status=have, file_ref → the stored document) on the
    chosen condition and records the document's primary condition link."""
    doc = await _get_document(db, uid, document_id)
    condition = await _get_condition(db, uid, payload.condition_id)
    evidence = EvidenceItem(
        user_id=uuid.UUID(uid),
        condition_id=condition.id,
        kind=payload.kind,
        title=(doc.title or doc.filename)[:255],
        status="have",
        source="Uploaded document",
        file_ref=doc.file_ref,
        notes=doc.summary,
    )
    db.add(evidence)
    doc.condition_id = condition.id
    await db.flush()
    await db.refresh(evidence)
    await db.refresh(doc)
    await audit.log(
        db, uid, "document.link", entity="document", entity_id=str(doc.id),
        meta={
            "condition_id": str(condition.id),
            "evidence_id": str(evidence.id),
            "kind": payload.kind,
        },
    )
    return DocumentLinkOut(
        document=DocumentOut.model_validate(doc),
        evidence=EvidenceOut.model_validate(evidence),
    )


# ── Decision-letter decoder (WAVE4-DECODER-SPEC.md) ──────────────────────────
@router.post("/{document_id}/decode", response_model=DecodeOut)
async def decode_document(
    document_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Decode an uploaded VA decision letter into plain English + next steps.

    Runs on the already-stored parsed text (no re-upload). The LOCAL model
    proposes; pure validators dispose; the §4.25 combined cross-check and the
    1-year appeal-window math are deterministic. Educational only — nothing is
    filed or appealed. The result is cached in extracted['decode']. If the LLM
    gateway is down the decode still returns, falling back to the grant/deny grid
    from the intake extraction (retry later for the plain-English narrative)."""
    from ..decoder.analyze import build_decode
    from ..decoder.decode import decode_text
    from ..kb.store import load_contention_map

    doc = await _get_document(db, uid, document_id)
    if doc.status != "ready" or not (doc.text_content or "").strip():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This document has no readable text yet — let it finish processing (or reprocess it) first.",
        )
    if not _is_va_decision(doc):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This doesn't look like a VA decision. If it is one, set its type to "
            "'Rating decision' or 'Decision letter' and try again.",
        )
    await require_credits(
        db,
        uid,
        -CreditConfig.decoder,
        operation="document.decode",
        reference_type="document",
        reference_id=str(document_id),
    )

    decode = await decode_text(doc.text_content)
    now = datetime.now(timezone.utc)
    payload = build_decode(
        decode=decode,
        extracted=doc.extracted,
        doc_date=doc.doc_date,
        today=now.date(),
        decoded_at=now.isoformat(),
        document_id=str(doc.id),
        review_source=await _review_source(db),
        contention_map=load_contention_map(),
    )

    # Cache on the document (reassign — JSONB in-place mutation isn't tracked).
    doc.extracted = {**(doc.extracted or {}), "decode": payload}
    await db.flush()
    await db.refresh(doc)
    await audit.log(
        db, uid, "document.decode", entity="document", entity_id=str(doc.id),
        meta={
            "decisions": len(payload["decisions"]),
            "has_denials": payload["has_denials"],
            "llm": decode is not None,
        },
    )
    return payload


@router.get("/{document_id}/decode", response_model=DecodeOut)
async def get_decode(
    document_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    wsid: str = Depends(current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the cached decode (POST it first). 404 if never decoded."""
    doc = await _get_document(db, uid, document_id)
    cached = (doc.extracted or {}).get("decode")
    if not cached:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Not decoded yet — decode this decision first."
        )
    return cached
