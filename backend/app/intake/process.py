"""The per-document background processing task (in-process asyncio, mirroring
Glitter Mane's extract_document pattern).

RLS: the task runs OUTSIDE any request, so it re-establishes the veteran's RLS
context itself — every DB touch goes through `user_session(user_id)` (db.py's
session_for_user), which pins the `app.current_user_id` GUC for its transaction.
Two transactions: a short one to flip status → processing (so the UI's 3s poll
sees it immediately), then the work, then one to persist the outcome.

Failure contract (WAVE2-SPEC §4):
  • no text extractable (bad scan, OCR + vision both failed) → status=failed
    with a human-readable `error` the UI shows;
  • LLM down/garbage → the parsed text IS stored, status=failed with a
    retry-worded error — POST /documents/{id}/reprocess re-runs classification
    without re-OCR-ing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date

from sqlalchemy import delete, select

from .. import audit
from .. import overrides
from ..crediting import CreditConfig, CreditLimitError, adjust_credits
from ..config import settings
from ..db import session_for_user
from ..models import ClaimedCondition, Document, DocumentChunk
from . import dedup
from ..rag import build_chunk_rows
from . import ccd
from .classify import (
    attach_va_classifications,
    build_rating_summary,
    classify_text,
    suggest_links,
)
from .crossread import cross_read_document
from .identity_extract import extract_identity
from .ocr import extract_text
from .verify import validate_verification, verify_extraction

log = logging.getLogger("veteran_ops.intake")

# Wrapped so the task can `async with` it; tests monkeypatch this symbol to
# point at their own session factory (SQLite has no set_config).
user_session = asynccontextmanager(session_for_user)

LLM_DOWN_ERROR = (
    "We read the text, but AI classification isn't available right now. "
    "Your document is safe — press Reprocess in a little while to finish it."
)

TRUNCATION_NOTE = (
    "Large document — key sections read; the full text stored may be partial."
)

# ── Intake concurrency gate ──────────────────────────────────────────────────
# A massive dump (hundreds of files) must drain as an orderly queue, not a
# stampede on the OCR service / LLM gateway. The semaphore bounds the expensive
# phase; a document waiting for a slot keeps status 'uploaded' (the UI shows it
# as queued) and only flips to 'processing' once it holds a slot.
#
# asyncio primitives are loop-bound, so the semaphore is created lazily per
# running loop (prod has one loop; each test client gets its own).
_intake_semaphores: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def intake_concurrency() -> int:
    """Slots for the expensive phase. INTAKE_CONCURRENCY env / settings; min 1."""
    raw = getattr(settings, "intake_concurrency", None)
    if raw is None:
        raw = os.environ.get("INTAKE_CONCURRENCY", "")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 3


def _intake_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    limit = intake_concurrency()
    sem = _intake_semaphores.get(loop)
    if sem is None or getattr(sem, "_intake_limit", None) != limit:
        for stale in [lp for lp in _intake_semaphores if lp.is_closed()]:
            del _intake_semaphores[stale]
        sem = asyncio.Semaphore(limit)
        sem._intake_limit = limit  # type: ignore[attr-defined]
        _intake_semaphores[loop] = sem
    return sem


@asynccontextmanager
async def _session(user_id: str, workspace_id: str | None = None):
    """Compatibility wrapper for tests that monkeypatch `user_session` with a
    single-argument factory."""
    if workspace_id is not None:
        try:
            async with user_session(user_id, workspace_id) as db:
                yield db
                return
        except TypeError:
            pass
    async with user_session(user_id) as db:
        yield db


async def _get_doc(db, user_id: str, doc_uuid: uuid.UUID) -> Document | None:
    """RLS is the primary fence; the explicit user_id filter is defense-in-depth."""
    return (
        await db.execute(
            select(Document).where(
                Document.id == doc_uuid,
                Document.user_id == uuid.UUID(str(user_id)),
            )
        )
    ).scalar_one_or_none()


async def _replace_document_chunks(
    db, user_id: str, document_id: uuid.UUID, chunk_rows: list[dict]
) -> None:
    """Delete this document's existing chunks and insert the fresh set.

    RLS-fenced (workspace + user_id): the DELETE only reaches this workspace's
    rows, and the BEFORE-INSERT trigger stamps workspace_id from the session GUC.
    """
    await db.execute(
        delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
    )
    user_uuid = uuid.UUID(str(user_id))
    for row in chunk_rows:
        db.add(DocumentChunk(user_id=user_uuid, document_id=document_id, **row))


def _assemble_review(
    text: str,
    extracted: dict,
    verification_raw: dict | None,
    crossread_result: dict | None,
) -> dict:
    """Combine the extract-verify verdict (PURE validate_verification) with the OCR
    cross-read into ONE review record. status='flagged' when a value is disputed /
    unsupported, a condition was missed, OR two OCR engines conflicted on a page —
    the disagreement goes to the veteran, the disputed value is never silently kept."""
    review: dict = {
        "status": "clear",
        "fields": [],
        "conditions": [],
        "missing_conditions": [],
        "crossread": None,
    }
    if verification_raw is not None:
        verdict = validate_verification(text, extracted, verification_raw)
        review["fields"] = verdict["fields"]
        review["conditions"] = verdict["conditions"]
        review["missing_conditions"] = verdict["missing_conditions"]
    if crossread_result and crossread_result.get("pages_flagged"):
        review["crossread"] = {
            "pages_flagged": crossread_result["pages_flagged"],
            "pages_cross_read": crossread_result.get("pages_cross_read"),
            "min_confidence": crossread_result.get("min_confidence"),
            "flagged_pages": crossread_result.get("flagged_pages"),
        }
    flagged = bool(review["fields"]) or bool(review["missing_conditions"]) or bool(review["crossread"])
    review["status"] = "flagged" if flagged else "clear"
    return review


async def process_document(user_id: str, document_id: str, workspace_id: str | None = None) -> None:
    """OCR/parse → classify+validate → deterministic link suggestions.

    Bounded: the whole run (status flip included) happens inside an intake
    slot, so while a document waits its turn it stays 'uploaded' — the UI
    already renders that as queued. A hard wall-clock timeout releases the
    slot so one giant Blue Button cannot pin the fleet for an hour.
    """
    timeout = float(getattr(settings, "intake_doc_timeout_seconds", 900) or 900)
    timeout = max(60.0, timeout)
    async with _intake_semaphore():
        try:
            await asyncio.wait_for(
                _process_document_slotted(user_id, document_id, workspace_id),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            log.error(
                "document processing timed out after %ss (doc=%s)",
                int(timeout),
                document_id,
            )
            try:
                async with _session(str(user_id), workspace_id) as db:
                    doc = await _get_doc(db, user_id, uuid.UUID(str(document_id)))
                    if doc is not None and doc.status == "processing":
                        # Keep any early-persisted text so Reprocess skips OCR.
                        doc.status = "failed"
                        doc.error = (
                            f"Processing timed out after {int(timeout) // 60} minutes "
                            "(large records are classified in sampled sections). "
                            "Your text is saved when available — press Reprocess to finish."
                        )
            except Exception:  # noqa: BLE001
                log.exception("could not mark timed-out document failed (doc=%s)", document_id)


async def process_documents_batch(user_id: str, document_ids: list[str], workspace_id: str | None = None) -> None:
    """Process many documents concurrently — the semaphore inside
    process_document turns a 300-file dump into an orderly queue of width
    intake_concurrency(). One document crashing never poisons the rest
    (each is individually wrapped by process_document_safe)."""
    await asyncio.gather(
        *(
            process_document_safe(
                user_id,
                doc_id,
                workspace_id,
                trigger_deep_dive=False,
            )
            for doc_id in document_ids
        )
    )
    # One sweep per completed upload batch, not one per file in a large C-file
    # dump.  The status check runs in a fresh scoped transaction after every
    # document transaction has committed.
    if await _any_documents_ready(user_id, document_ids, workspace_id):
        await _trigger_intake_deep_dive(user_id, workspace_id)
        await _trigger_comprehension(user_id, workspace_id)


async def _process_document_slotted(user_id: str, document_id: str, workspace_id: str | None = None) -> None:
    doc_uuid = uuid.UUID(str(document_id))

    # Txn 1 — claim the document and grab what the work needs.
    async with _session(str(user_id), workspace_id) as db:
        doc = await _get_doc(db, user_id, doc_uuid)
        if doc is None:  # deleted (or not this user's — RLS) before we started
            return
        doc.status = "processing"
        doc.error = None
        file_ref, content_type = doc.file_ref, doc.content_type
        prior_text = doc.text_content

    # Heavy work — no transaction held open across network calls.
    if (prior_text or "").strip():
        text, text_error, extract_meta = prior_text, None, {}
    else:
        text, text_error, extract_meta = await extract_text(
            file_ref or "", content_type, full_read=settings.full_read_default
        )
    # Postgres rejects U+0000 in text columns; OCR/PDF layers sometimes emit NUL.
    if text:
        text = text.replace("\x00", "")
    # Content signatures first — used for early persist + same-batch dedupe.
    text_fp = dedup.content_fingerprint(text)
    text_sh = dedup.simhash64(text)

    # Persist extracted text + fingerprints ASAP (before multi-segment classify).
    # Also enables same-batch PDF+TXT Blue Button dedupe: the second file sees the
    # first's fingerprint even while the first is still classifying.
    if (text or "").strip():
        try:
            async with _session(str(user_id), workspace_id) as db:
                doc = await _get_doc(db, user_id, doc_uuid)
                if doc is not None and doc.status == "processing":
                    doc.text_content = text
                    doc.text_fingerprint = text_fp
                    doc.simhash = text_sh
                    doc.error = None
        except Exception:  # noqa: BLE001 — best-effort progress stamp
            log.warning("early text persist failed (doc=%s)", document_id, exc_info=True)

    # Content-level near-duplicate check BEFORE credit charge + classify.
    # Candidates include ready AND in-flight (processing with a fingerprint), so
    # mhv_….pdf + mhv_….txt uploaded together don't both burn the GPU.
    dup_verdict, dup_of = "distinct", None
    if (text or "").strip() and (text_fp or text_sh):
        async with _session(str(user_id), workspace_id) as db:
            me = await _get_doc(db, user_id, doc_uuid)
            my_name = (me.filename if me else "") or ""
            my_created = me.created_at if me else None
            candidates = (
                await db.execute(
                    select(
                        Document.id,
                        Document.text_fingerprint,
                        Document.simhash,
                        Document.status,
                        Document.filename,
                        Document.created_at,
                    ).where(
                        Document.user_id == uuid.UUID(str(user_id)),
                        Document.id != doc_uuid,
                        Document.status.in_(("ready", "processing", "duplicate")),
                    )
                )
            ).all()
            # Prefer exact fingerprint match against any ready/processing peer.
            fp_rows = [
                (str(cid), fp, sh)
                for cid, fp, sh, st, _fn, _ca in candidates
                if fp or sh
            ]
            dup_verdict, dup_of = dedup.duplicate_verdict(text_fp, text_sh, fp_rows)
            # Same-batch race: both still "processing" with identical fingerprints —
            # keep the earlier (or preferred) file, skip this one.
            if dup_verdict == "distinct" and text_fp:
                for cid, fp, _sh, st, fn, ca in candidates:
                    if not fp or fp != text_fp:
                        continue
                    if st not in ("ready", "processing", "duplicate"):
                        continue
                    # Deterministic winner: earlier created_at, then smaller id.
                    i_lose = False
                    if my_created is not None and ca is not None:
                        i_lose = (ca, str(cid)) <= (my_created, str(doc_uuid))
                    else:
                        i_lose = str(cid) < str(doc_uuid)
                    # Prefer keeping .txt Blue Button over a same-content .pdf.
                    if dedup.prefer_keep_other(my_name, fn or ""):
                        i_lose = True
                    if i_lose:
                        dup_verdict, dup_of = "skip", str(cid)
                        break
            # Filename stem pair (mhv_X.pdf + mhv_X.txt) when peer is already ready.
            if dup_verdict == "distinct":
                stem_hit = dedup.same_export_stem_peer(my_name, list(candidates))
                if stem_hit is not None:
                    dup_verdict, dup_of = "skip", stem_hit
    if dup_verdict == "skip":
        async with _session(str(user_id), workspace_id) as db:
            doc = await _get_doc(db, user_id, doc_uuid)
            if doc is None:
                return
            doc.text_content = text or None
            doc.text_fingerprint = text_fp
            doc.simhash = text_sh
            doc.duplicate_of = uuid.UUID(dup_of) if dup_of else None
            doc.status = "duplicate"
            doc.error = None
            await audit.log(
                db, user_id, "document.duplicate_skipped", entity="document",
                entity_id=str(doc.id), meta={"duplicate_of": dup_of},
            )
        return

    if (text or "").strip():
        try:
            async with _session(str(user_id), workspace_id) as db:
                await adjust_credits(
                    db,
                    user_id,
                    -CreditConfig.document_process,
                    operation="document.process",
                    reference_type="document",
                    reference_id=str(doc_uuid),
                    note="Document intake / classification",
                )
        except CreditLimitError as exc:
            async with _session(str(user_id), workspace_id) as db:
                doc = await _get_doc(db, user_id, doc_uuid)
                if doc is None:
                    return
                doc.status = "failed"
                doc.error = exc.message
                await audit.log(
                    db,
                    user_id,
                    "document.process_failed",
                    entity="document",
                    entity_id=str(doc.id),
                    meta={"reason": "insufficient_credits", "balance": exc.balance},
                )
            return
    extracted = None
    if (text or "").strip():
        # C-CDA (VA Health Summary / CCD) XML bypasses the LLM entirely:
        # structured clinical XML parses DETERMINISTICALLY (intake/ccd.py) —
        # doc_type=treatment_record, extracted.ccd carries the parsed sections,
        # conditions_mentioned mirrors the problems list. A sniffed-but-broken
        # CCD falls back to the normal classification path.
        if ccd.sniff_ccd(text):
            extracted = ccd.extract_ccd(text)
        if extracted is None:
            extracted = await classify_text(text)

    # Chunk + embed for retrieval over the veteran's OWN records (document RAG).
    # Done HERE — outside any open transaction — because the embedding call hits
    # the network. Gated on being headed for `ready` (text parsed AND classified):
    # a doc that will land `failed` (LLM down) gets chunked on its later
    # successful reprocess, so an outage never spends embeddings on docs we fail.
    chunk_rows: list[dict] | None = None
    if (text or "").strip() and extracted is not None:
        chunk_rows = await build_chunk_rows(text)

    # Best-effort: pull the veteran's OWN identity (name / DOB / address / phone /
    # dependents) from authoritative records so their profile can be pre-filled
    # instead of hand-typed. This is a SUGGESTION only — stashed non-destructively
    # in extracted['identity_suggestion']; the veteran confirms it via
    # GET /profile/identity-suggestions → "Use these". It NEVER writes
    # profile.identity, NEVER collects an SSN (see intake/identity_extract.py), and
    # (double-wrapped here) must NEVER break processing a document.
    if extracted is not None:
        try:
            suggestion = await extract_identity(text, extracted.get("doc_type"))
        except Exception:  # noqa: BLE001 — identity is a bonus; intake must not fail
            log.warning("identity extraction crashed; document unaffected", exc_info=True)
            suggestion = {}
        if suggestion:
            extracted["identity_suggestion"] = suggestion

    # OCR cross-read (PURE, no model): when the scanned-page reader ran BOTH engines
    # (dots + vision), compare them on the tokens a rating turns on so a 50-vs-70
    # page misread is caught. Always-on — cheap and off the gateway.
    crossread_result = None
    page_reads = extract_meta.get("page_reads")
    if isinstance(page_reads, list) and page_reads:
        crossread_result = cross_read_document(page_reads)

    # Extract-verify (gated): a 2nd, decorrelated model pass that must QUOTE the
    # source for every extracted tuple. Disagreements are FLAGGED for the veteran to
    # reconcile — never silently persisted. Resolves the privacy-aware model exactly
    # as the spec requires (workspace_privacy_mode → effective_model_for reasoning
    # tier, PII-forced local). Off by default so intake never depends on a live
    # gateway; prod turns it on (INTAKE_VERIFY=true).
    verification = None
    if extracted is not None and settings.intake_verify_default:
        try:
            async with _session(str(user_id), workspace_id) as db:
                pm = await overrides.workspace_privacy_mode(db)
            model = overrides.effective_model_for(
                tier="reasoning", touches_pii=True, privacy_mode=pm
            )
            verification = await verify_extraction(text, extracted, model=model)
        except Exception:  # noqa: BLE001 — verification is additive; a miss just doesn't flag
            log.warning("extract-verify pass failed; document not flagged", exc_info=True)

    # Txn 2 — persist the outcome (fresh RLS context; the row may have been
    # deleted while we worked).
    async with _session(str(user_id), workspace_id) as db:
        doc = await _get_doc(db, user_id, doc_uuid)
        if doc is None:
            return
        # Final persist (NUL already stripped after extract; belt-and-suspenders).
        clean = (text or "").replace("\x00", "") or None
        doc.text_content = clean
        # Stamp the content signatures so LATER uploads can be checked against this
        # document; a borderline near-match is kept but softly flagged via duplicate_of
        # (status stays "ready" — the veteran decides, nothing is silently dropped).
        doc.text_fingerprint = text_fp
        doc.simhash = text_sh
        if dup_verdict == "flag" and dup_of:
            doc.duplicate_of = uuid.UUID(dup_of)

        if not (clean or "").strip():
            doc.status = "failed"
            doc.error = text_error or (
                "We couldn't read any text from this file."
            )
            await audit.log(
                db, user_id, "document.process_failed", entity="document",
                entity_id=str(doc.id), meta={"reason": "no_text"},
            )
            return

        if extracted is None:
            # Text stored; classification retryable via /reprocess.
            doc.status = "failed"
            doc.error = LLM_DOWN_ERROR
            await audit.log(
                db, user_id, "document.process_failed", entity="document",
                entity_id=str(doc.id), meta={"reason": "llm_unavailable"},
            )
            return

        # Deterministic: stamp VA's official contention-classification taxonomy
        # onto each extracted condition (vendored CC0 dataset — no extra LLM
        # call; the UI shows it as the official-category chip).
        attach_va_classifications(extracted.get("conditions_mentioned", []))

        # Deterministic suggestions against the veteran's claimed conditions
        # (RLS-fenced query + explicit user filter). Suggestions only — the
        # veteran confirms via POST /documents/{id}/link; nothing is auto-linked
        # or auto-updated.
        conditions = (
            await db.execute(
                select(ClaimedCondition.id, ClaimedCondition.name).where(
                    ClaimedCondition.user_id == uuid.UUID(str(user_id))
                )
            )
        ).all()
        extracted["suggested_links"] = suggest_links(
            extracted.get("conditions_mentioned", []),
            [{"id": str(cid), "name": cname} for cid, cname in conditions],
        )
        extracted["rating_summary"] = build_rating_summary(extracted)

        summary = extracted.get("summary")
        if extract_meta.get("truncated"):
            # Honest about partial reads: a very large scanned C-file exceeded the
            # OCR ceiling even under full-read — say so in the extraction AND summary.
            extracted["truncated"] = True
            extracted["truncation_note"] = TRUNCATION_NOTE
            summary = f"{summary} {TRUNCATION_NOTE}" if summary else TRUNCATION_NOTE
            extracted["summary"] = summary
        # Honest about a partial *classification*: if some segments of a whole-doc
        # read couldn't be classified (a transient gateway hiccup mid-file), say how
        # much was read rather than implying full coverage.
        cov = extracted.get("read_coverage") or {}
        if cov.get("segments_failed"):
            note = (
                f"Note: {cov['segments_read']} of {cov['segments_total']} sections of "
                "this document were analyzed; the rest can be re-read with Reprocess."
            )
            summary = f"{summary} {note}" if summary else note
            extracted["summary"] = summary
        # Honest partial-read: pages BOTH OCR engines returned nothing for are
        # skipped, not silently dropped — say so (extends read_coverage/TRUNCATION_NOTE).
        unreadable = extract_meta.get("unreadable_pages")
        if unreadable:
            note = f"Note: {unreadable} page(s) could not be read and were skipped."
            summary = f"{summary} {note}" if summary else note
            extracted["summary"] = summary
            extracted["unreadable_pages"] = int(unreadable)

        # Extract-verify + OCR cross-read → review flag. The disputed/unsupported
        # value is NOT silently persisted as fact: the extraction is kept as the best
        # guess, but the doc is flagged so the veteran reconciles it (review queue).
        review = _assemble_review(text, extracted, verification, crossread_result)
        if review["status"] == "flagged":
            extracted["review"] = review
            doc.review_status = "flagged"
        else:
            doc.review_status = "clear"

        doc.extracted = extracted
        doc.doc_type = extracted.get("doc_type")
        if extracted.get("doc_date"):
            doc.doc_date = date.fromisoformat(extracted["doc_date"])
        doc.title = extracted.get("title") or doc.title or doc.filename
        doc.summary = summary
        page_offsets = extract_meta.get("page_offsets")
        doc.page_offsets = page_offsets if isinstance(page_offsets, list) else None
        doc.status = "ready"
        doc.error = None

        # Persist retrieval chunks (replace any from a prior run — reprocess is
        # idempotent). The trigger stamps workspace_id from the session GUC; the
        # explicit user_id keeps ownership testable without a live Postgres.
        if chunk_rows is not None:
            await _replace_document_chunks(db, user_id, doc.id, chunk_rows)

        await audit.log(
            db, user_id, "document.processed", entity="document",
            entity_id=str(doc.id),
            meta={
                "doc_type": doc.doc_type,
                "conditions_mentioned": len(extracted.get("conditions_mentioned", [])),
                "suggested_links": len(extracted["suggested_links"]),
                "is_va_decision": extracted.get("is_va_decision", False),
                "chunks": len(chunk_rows or []),
                "review_status": doc.review_status,
                "review_fields": len(review.get("fields", [])),
            },
        )


async def reindex_document(user_id: str, document_id: str, workspace_id: str | None = None) -> int:
    """(Re)build a READY document's retrieval chunks from its ALREADY-stored text.

    The light path next to a full reprocess: no OCR, no LLM classification — it
    reuses `text_content` and only re-chunks + re-embeds. This is what heals a doc
    that reached `ready` BEFORE document-RAG existed (zero chunks) or that got
    chunked DURING an embeddings outage (chunks with NULL vectors) — neither is
    `failed`, so reprocess-failed never reaches them. Bounded by the intake
    semaphore so a bulk reindex doesn't stampede the embeddings endpoint. Returns
    the chunk count written (0 if the doc vanished / left `ready` / had no text)."""
    doc_uuid = uuid.UUID(str(document_id))
    async with _intake_semaphore():
        async with _session(str(user_id), workspace_id) as db:
            doc = await _get_doc(db, user_id, doc_uuid)
            if doc is None or doc.status != "ready":
                return 0
            text = doc.text_content
        if not (text or "").strip():
            return 0

        chunk_rows = await build_chunk_rows(text)  # network embed — no txn held

        async with _session(str(user_id), workspace_id) as db:
            doc = await _get_doc(db, user_id, doc_uuid)
            if doc is None or doc.status != "ready":  # deleted/re-queued meanwhile
                return 0
            await _replace_document_chunks(db, user_id, doc_uuid, chunk_rows)
            await audit.log(
                db, user_id, "document.reindex", entity="document",
                entity_id=str(doc_uuid), meta={"chunks": len(chunk_rows)},
            )
        return len(chunk_rows)


async def reindex_document_safe(user_id: str, document_id: str, workspace_id: str | None = None) -> None:
    """One doc reindexing must never take the batch (or the app) down."""
    try:
        await reindex_document(user_id, document_id, workspace_id)
    except Exception:  # noqa: BLE001
        log.exception("document reindex crashed (doc=%s)", document_id)


async def reindex_documents_batch(user_id: str, document_ids: list[str], workspace_id: str | None = None) -> None:
    """Reindex many documents concurrently — the intake semaphore inside
    reindex_document turns the set into an orderly queue; one crash never poisons
    the rest."""
    await asyncio.gather(
        *(reindex_document_safe(user_id, doc_id, workspace_id) for doc_id in document_ids)
    )


async def _any_documents_ready(
    user_id: str,
    document_ids: list[str],
    workspace_id: str | None = None,
) -> bool:
    if not document_ids:
        return False
    try:
        ids = [uuid.UUID(str(document_id)) for document_id in document_ids]
        async with _session(str(user_id), workspace_id) as db:
            row = (
                await db.execute(
                    select(Document.id).where(
                        Document.user_id == uuid.UUID(str(user_id)),
                        Document.id.in_(ids),
                        Document.status == "ready",
                    ).limit(1)
                )
            ).scalar_one_or_none()
            return row is not None
    except Exception:  # noqa: BLE001 — trigger status is strictly best-effort
        log.warning("could not check document readiness for deep-dive trigger", exc_info=True)
        return False


async def _trigger_intake_deep_dive(
    user_id: str, workspace_id: str | None = None
) -> None:
    if not settings.deep_dive_on_intake:
        return
    try:
        from ..firm.jobs import run_deep_dive_in_session

        # Fresh transaction after the document's ready/chunk transaction committed.
        # `_session` is the production RLS session factory and the established test
        # seam, so this never falls back to an unscoped/global veteran read.
        async with _session(str(user_id), workspace_id) as db:
            await run_deep_dive_in_session(
                db,
                str(user_id),
                trigger="intake",
                force=False,
            )
    except Exception:  # noqa: BLE001 — document readiness is already committed
        log.warning("intake deep-dive trigger failed; intake remains ready.", exc_info=True)


async def _trigger_comprehension(
    user_id: str, workspace_id: str | None = None
) -> None:
    """Rebuild the whole-C-file case picture after intake (gated, background).
    Best-effort — the document is already committed ready; a comprehension miss
    never affects it. Runs a fresh RLS-scoped transaction of its own."""
    if not settings.comprehension_on_intake:
        return
    try:
        from ..analysis.comprehension import run_comprehension_for_user

        await run_comprehension_for_user(str(user_id), workspace_id, force=False)
    except Exception:  # noqa: BLE001 — comprehension is additive, never blocks intake
        log.warning("intake comprehension trigger failed; intake remains ready.", exc_info=True)


async def process_document_safe(
    user_id: str,
    document_id: str,
    workspace_id: str | None = None,
    *,
    trigger_deep_dive: bool = True,
) -> None:
    """Wrapper for background scheduling: a crash must mark the doc failed (not
    strand it in 'processing' forever) and never take the app down."""
    try:
        await process_document(user_id, document_id, workspace_id)
        if trigger_deep_dive and await _any_documents_ready(
            user_id, [document_id], workspace_id
        ):
            await _trigger_intake_deep_dive(user_id, workspace_id)
            await _trigger_comprehension(user_id, workspace_id)
    except Exception:  # noqa: BLE001
        log.exception("document processing crashed (doc=%s)", document_id)
        try:
            async with _session(str(user_id), workspace_id) as db:
                doc = await _get_doc(db, user_id, uuid.UUID(str(document_id)))
                if doc is not None and doc.status == "processing":
                    doc.status = "failed"
                    doc.error = (
                        "Something went wrong while processing this document. "
                        "Press Reprocess to try again."
                    )
        except Exception:  # noqa: BLE001
            log.exception("could not mark document failed (doc=%s)", document_id)


async def recover_stuck_processing(*, older_than_minutes: int | None = None) -> int:
    """Fail documents left in status=processing past a wall clock budget.

    Background intake is in-process asyncio: a container restart or hung OCR/LLM
    call can leave rows 'processing' forever (no worker heartbeats). Call on
    app startup so customer UX self-heals after deploys. Returns the number of
    rows recovered. Uses a direct admin session (no per-user RLS) — startup only.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..db import engine

    minutes = older_than_minutes
    if minutes is None:
        minutes = int(getattr(settings, "intake_stuck_minutes", 20) or 20)
    minutes = max(5, minutes)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    err = (
        f"Processing was interrupted or exceeded {minutes} minutes. "
        "Press Reprocess to try again — any extracted text is kept when available."
    )
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db:
            result = await db.execute(
                update(Document)
                .where(
                    Document.status == "processing",
                    Document.updated_at < cutoff,
                )
                .values(status="failed", error=err)
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            n = int(result.rowcount or 0)
            if n:
                log.warning("recovered %s stuck processing document(s) (>%sm)", n, minutes)
            return n
    except Exception:  # noqa: BLE001 — never block boot
        log.exception("recover_stuck_processing failed")
        return 0
