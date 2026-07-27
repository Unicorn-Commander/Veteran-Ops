"""Evidence items — nested under a condition for list/create, flat for edit/delete."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..evidence_rationale import (
    citation_quote_from_chunk,
    evidence_query_terms,
    evidence_rationale,
    page_for_char_offset,
    rank_chunk_rows,
)
from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, Document, DocumentChunk, EvidenceCitation, EvidenceItem
from ..schemas import (
    EvidenceCitationIn,
    EvidenceCitationOut,
    EvidenceCreate,
    EvidenceUpdate,
    EvidenceWithRationaleOut,
)

router = APIRouter(tags=["evidence"])


# Defense-in-depth: every fetch-by-id filters user_id explicitly (not RLS-only), so
# a guessed/wrong-owner id is a 404 even if RLS is ever misconfigured.
async def _get_condition(
    db: AsyncSession, condition_id: uuid.UUID, uid: str
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


async def _get_evidence(db: AsyncSession, evidence_id: uuid.UUID, uid: str) -> EvidenceItem:
    obj = (
        await db.execute(
            select(EvidenceItem).where(
                EvidenceItem.id == evidence_id,
                EvidenceItem.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evidence item not found")
    return obj


async def _document_for_evidence(
    db: AsyncSession, item: EvidenceItem, uid: str
) -> Document | None:
    if not item.file_ref:
        return None
    return (
        await db.execute(
            select(Document).where(
                Document.user_id == uuid.UUID(uid),
                Document.file_ref == item.file_ref,
            )
        )
    ).scalar_one_or_none()


async def _citation_row(
    db: AsyncSession, evidence_id: uuid.UUID, uid: str
) -> EvidenceCitation | None:
    return (
        await db.execute(
            select(EvidenceCitation).where(
                EvidenceCitation.evidence_id == evidence_id,
                EvidenceCitation.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()


def _citation_out(row: EvidenceCitation, *, source_title: str, selected: bool = False) -> EvidenceCitationOut:
    return EvidenceCitationOut(
        document_id=row.document_id,
        source_title=source_title,
        quote=row.quote,
        char_start=row.char_start,
        char_end=row.char_end,
        page=row.page,
        chunk_index=row.chunk_index,
        note=row.note,
        selected=selected,
    )


async def _evidence_payload(
    db: AsyncSession, item: EvidenceItem, uid: str, *, condition_name: str
) -> EvidenceWithRationaleOut:
    document = await _document_for_evidence(db, item, uid)
    document_id = document.id if document is not None else None
    base = EvidenceWithRationaleOut.model_validate(item).model_dump()
    base["document_id"] = document_id
    base["rationale"] = evidence_rationale(item.kind)
    citations: list[EvidenceCitationOut] = []

    if document is not None:
        chunk_rows = (
            await db.execute(
                select(DocumentChunk).where(
                    DocumentChunk.user_id == uuid.UUID(uid),
                    DocumentChunk.document_id == document.id,
                ).order_by(DocumentChunk.chunk_index)
            )
        ).scalars().all()
        terms = evidence_query_terms(condition_name, item.kind)
        ranked = rank_chunk_rows(chunk_rows, terms, k=3)
        citations = [
            EvidenceCitationOut(
                document_id=document.id,
                source_title=document.title or document.filename,
                quote=citation_quote_from_chunk(chunk.content),
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                page=page_for_char_offset(document.page_offsets, chunk.char_start),
                chunk_index=chunk.chunk_index,
                note=None,
                selected=False,
            )
            for chunk in ranked
        ]

    pinned = await _citation_row(db, item.id, uid)
    if pinned is not None and document is not None:
        pinned_out = _citation_out(
            pinned,
            source_title=document.title or document.filename,
            selected=True,
        )
        matched = False
        for i, citation in enumerate(citations):
            if (
                citation.document_id == pinned_out.document_id
                and citation.char_start == pinned_out.char_start
                and citation.char_end == pinned_out.char_end
                and citation.chunk_index == pinned_out.chunk_index
                and citation.quote == pinned_out.quote
            ):
                citations[i] = citation.model_copy(update={"selected": True, "note": pinned_out.note})
                matched = True
                break
        if not matched:
            citations.insert(0, pinned_out)
    elif citations:
        citations[0] = citations[0].model_copy(update={"selected": True})

    base["citations"] = citations
    return EvidenceWithRationaleOut(**base)


@router.get("/conditions/{condition_id}/evidence", response_model=list[EvidenceWithRationaleOut])
async def list_evidence(
    condition_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    cond = await _get_condition(db, condition_id, uid)
    rows = (
        await db.execute(
            select(EvidenceItem)
            .where(EvidenceItem.condition_id == condition_id)
            .order_by(EvidenceItem.created_at.desc())
        )
    ).scalars().all()
    return [await _evidence_payload(db, item, uid, condition_name=cond.name) for item in list(rows)]


@router.post(
    "/conditions/{condition_id}/evidence",
    response_model=EvidenceWithRationaleOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_evidence(
    condition_id: uuid.UUID,
    payload: EvidenceCreate,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    cond = await _get_condition(db, condition_id, uid)
    obj = EvidenceItem(
        user_id=uuid.UUID(uid),
        condition_id=condition_id,
        **payload.model_dump(exclude_unset=True),
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    await audit.log(
        db, uid, "evidence.create", entity="evidence_item", entity_id=str(obj.id),
        meta={"condition_id": str(condition_id), "kind": obj.kind, "status": obj.status},
    )
    return await _evidence_payload(db, obj, uid, condition_name=cond.name)


@router.patch("/evidence/{evidence_id}", response_model=EvidenceWithRationaleOut)
async def update_evidence(
    evidence_id: uuid.UUID,
    payload: EvidenceUpdate,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = await _get_evidence(db, evidence_id, uid)
    changes = payload.model_dump(exclude_unset=True)
    changes.pop("file_ref", None)  # server-controlled; never trust a client value
    for key, value in changes.items():
        setattr(obj, key, value)
    await db.flush()
    await db.refresh(obj)
    await audit.log(
        db, uid, "evidence.update", entity="evidence_item", entity_id=str(obj.id),
        meta={"fields": sorted(changes.keys())},
    )
    cond = await _get_condition(db, obj.condition_id, uid)
    return await _evidence_payload(db, obj, uid, condition_name=cond.name)


@router.post("/evidence/{evidence_id}/citation", response_model=EvidenceWithRationaleOut)
async def pin_evidence_citation(
    evidence_id: uuid.UUID,
    payload: EvidenceCitationIn,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = await _get_evidence(db, evidence_id, uid)
    if obj.file_ref is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This evidence is not linked to a document")
    document = await _document_for_evidence(db, obj, uid)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source document not found")
    existing = await _citation_row(db, evidence_id, uid)
    if existing is None:
        existing = EvidenceCitation(
            evidence_id=evidence_id,
            user_id=uuid.UUID(uid),
            document_id=document.id,
            quote=payload.quote,
            char_start=payload.char_start,
            char_end=payload.char_end,
            page=payload.page,
            chunk_index=payload.chunk_index,
            note=payload.note,
        )
        db.add(existing)
    else:
        existing.document_id = document.id
        existing.quote = payload.quote
        existing.char_start = payload.char_start
        existing.char_end = payload.char_end
        existing.page = payload.page
        existing.chunk_index = payload.chunk_index
        existing.note = payload.note
    await db.flush()
    await db.refresh(existing)
    await audit.log(
        db, uid, "evidence.citation_pin", entity="evidence_item", entity_id=str(evidence_id),
        meta={"document_id": str(document.id), "chunk_index": payload.chunk_index},
    )
    cond = await _get_condition(db, obj.condition_id, uid)
    return await _evidence_payload(db, obj, uid, condition_name=cond.name)


@router.delete("/evidence/{evidence_id}/citation", status_code=status.HTTP_204_NO_CONTENT)
async def clear_evidence_citation(
    evidence_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = await _get_evidence(db, evidence_id, uid)
    await db.execute(
        delete(EvidenceCitation).where(
            EvidenceCitation.evidence_id == evidence_id,
            EvidenceCitation.user_id == uuid.UUID(uid),
        )
    )
    await audit.log(
        db, uid, "evidence.citation_clear", entity="evidence_item", entity_id=str(evidence_id),
    )


@router.delete("/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evidence(
    evidence_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    obj = await _get_evidence(db, evidence_id, uid)
    await db.execute(
        delete(EvidenceCitation).where(
            EvidenceCitation.evidence_id == evidence_id,
            EvidenceCitation.user_id == uuid.UUID(uid),
        )
    )
    await db.delete(obj)
    await audit.log(db, uid, "evidence.delete", entity="evidence_item", entity_id=str(evidence_id))


# ── Proactive evidence: auto-link what's in the file + review the picture ──────────
@router.get("/evidence/review")
async def get_evidence_review(
    uid: str = Depends(current_user_id), db: AsyncSession = Depends(get_db)
) -> dict:
    """What evidence is already in the file (matched to conditions) + where a nexus or
    buddy statement is obviously worth adding. Deterministic — no GPU."""
    from ..evidence.proactive import evidence_review
    from ..firm.context import build_dossier

    dossier = await build_dossier(db, uid)
    return evidence_review(dossier)


@router.post("/evidence/auto-link")
async def post_auto_link(
    uid: str = Depends(current_user_id), db: AsyncSession = Depends(get_db)
) -> dict:
    """File the confident evidence detections as linked EvidenceItems automatically —
    the app does the linking so the veteran doesn't. Idempotent."""
    from ..evidence.autolink import auto_link_evidence

    return await auto_link_evidence(db, uid)
