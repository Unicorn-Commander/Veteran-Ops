"""Provider/DBQ-prep packet — everything a veteran brings to an appointment or
a VSO for ONE condition, as JSON (the frontend renders the print view).

Contents: veteran (name only — no SSN/DOB in the packet), the condition, the
matched rating-criteria card (tiers + source), evidence on hand / missing, the
deterministic gap analysis, continuity from Glitter Mane when the bridge is
configured (degrades to []), condition-appropriate lay-statement prompts, the
DBQ mapping, and the legal-lane disclaimer. Access is audited.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import audit
from ..analysis.gaps import analyze_gaps, map_dbq
from ..analysis.mapping import extract_tiers
from ..evidence_rationale import (
    citation_quote_from_chunk,
    evidence_query_terms,
    evidence_rationale,
    page_for_char_offset,
    rank_chunk_rows,
)
from ..config import settings
from ..deps import current_user_id, get_db
from ..kb.store import cached_max_ratings, load_dbq_catalog, retrieve_cards
from ..models import ClaimedCondition, Document, DocumentChunk, EvidenceCitation, EvidenceItem, User, VeteranProfile
from ..rag import retrieve_document_chunks
from ..schemas import PacketCitationOut, PacketOut
from .glitter import fetch_continuity

log = logging.getLogger("veteran_ops.packet")

router = APIRouter(prefix="/packet", tags=["packet"])


def _disclaimer() -> str:
    try:
        from ..main import DISCLAIMER

        return DISCLAIMER
    except Exception:  # noqa: BLE001
        return (
            "Veteran-Ops is self-help educational software, not legal advice and not a "
            "VA-accredited representative. Verify current criteria at eCFR / VA.gov."
        )


def _lay_statement_prompts(name: str, body_system: str | None, claim_type: str) -> list[str]:
    """3–5 condition-appropriate prompts for the veteran (and people who know
    them) to write specific, dated, first-person lay statements against."""
    name_l = (name or "").lower()
    prompts: list[str] = [
        (
            f"Describe when your {name} symptoms began and what was happening in your "
            "service at the time — dates, unit, location, and the specific event or "
            "duties involved."
        ),
        (
            "Describe a typical BAD day: which symptoms, how long they last, and what "
            "they stop you from doing (work tasks, chores, driving, sleep, family life)."
        ),
    ]
    if body_system == "mental" or any(
        k in name_l for k in ("ptsd", "anxiety", "depress", "mental")
    ):
        prompts.append(
            "Describe changes people around you have noticed since service — mood, "
            "temper, withdrawal, nightmares, avoiding crowds — with examples and rough "
            "dates. A statement from a spouse or close friend describing the same "
            "changes is powerful."
        )
    elif body_system == "musculoskeletal" or any(
        k in name_l for k in ("back", "knee", "shoulder", "ankle", "spine", "neck", "hip")
    ):
        prompts.append(
            "Describe flare-ups: how often, what triggers them, how far you can move "
            "before pain starts, and what you can no longer do (lifting, stairs, "
            "standing, sitting through a shift)."
        )
    elif any(k in name_l for k in ("tinnitus", "hearing")):
        prompts.append(
            "Describe the noise exposure in service (weapons, aircraft, engine rooms, "
            "no hearing protection) and how the ringing/hearing loss affects daily "
            "life — conversations, TV volume, sleep."
        )
    elif any(k in name_l for k in ("migraine", "headache")):
        prompts.append(
            "Keep and reference a headache log: dates, duration, whether you had to "
            "lie down in a dark room, missed work or left early."
        )
    elif any(k in name_l for k in ("apnea", "sleep")):
        prompts.append(
            "Have your bed partner describe what they observe at night — snoring, "
            "gasping, stopped breathing — and how tired you are during the day."
        )
    else:
        prompts.append(
            "Describe how often symptoms occur, any treatment you've sought, and how "
            "the condition has progressed year over year since it started."
        )
    if claim_type == "secondary":
        prompts.append(
            "Describe the timeline between your service-connected condition and this "
            "one: when this condition appeared, and how the primary condition (or its "
            "treatment/medications) preceded and relates to it."
        )
    else:
        prompts.append(
            "List everyone who has treated this condition since service (VA, private, "
            "urgent care) with rough dates — continuity of treatment supports the claim."
        )
    return prompts[:5]


@router.get("/{condition_id}")
async def get_packet(
    condition_id: uuid.UUID,
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
) -> PacketOut:
    cond = (
        await db.execute(
            select(ClaimedCondition).where(
                ClaimedCondition.id == condition_id,
                ClaimedCondition.user_id == uuid.UUID(uid),
            )
        )
    ).scalar_one_or_none()
    if cond is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Condition not found")

    user = await db.get(User, uuid.UUID(uid))
    profile = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == uuid.UUID(uid))
        )
    ).scalar_one_or_none()
    evidence = (
        await db.execute(
            select(EvidenceItem)
            .where(EvidenceItem.condition_id == condition_id)
            .order_by(EvidenceItem.created_at)
        )
    ).scalars().all()

    # Matched rating-criteria card: prefer the condition's own DC, else retrieve —
    # but only attach a card that is actually RELEVANT. Retrieval always returns
    # top-k of *something*; a packet showing IBS criteria for sinusitis is worse
    # than no criteria section at all.
    dc_card: dict | None = None
    rows = await retrieve_cards(db, cond.name, k=4, card_type="rating_criteria")
    if cond.diagnostic_code:
        rows = sorted(rows, key=lambda r: r.diagnostic_code != cond.diagnostic_code)

    def _relevant(r) -> bool:
        if cond.diagnostic_code and r.diagnostic_code == cond.diagnostic_code:
            return True
        from ..kb.store import _GENERIC_TERMS

        name_tokens = {
            t for t in (cond.name or "").lower().split()
            if len(t) >= 4 and t not in _GENERIC_TERMS
        }
        card_text = f"{r.title} {r.content}".lower()
        return any(t in card_text for t in name_tokens)

    rows = [r for r in rows if _relevant(r)]
    if rows:
        r = rows[0]
        dc_card = {
            "title": r.title,
            "diagnostic_code": r.diagnostic_code,
            "source": r.source,
            "content": r.content,
            "tiers": extract_tiers(r.data),
        }

    cond_dict = {
        "name": cond.name,
        "claim_type": cond.claim_type,
        "secondary_to": str(cond.secondary_to) if cond.secondary_to else None,
        "in_service_event": cond.in_service_event,
        "nexus_notes": cond.nexus_notes,
        "diagnostic_code": cond.diagnostic_code,
        "current_rating": cond.current_rating,
    }
    ev_dicts = [{"kind": e.kind, "status": e.status} for e in evidence]
    prof_dict = (
        {"service_periods": profile.service_periods, "exposures": profile.exposures}
        if profile
        else None
    )
    gaps = analyze_gaps(cond_dict, ev_dicts, prof_dict, max_ratings=cached_max_ratings())

    def _ev(e: EvidenceItem) -> dict:
        return {
            "id": str(e.id), "kind": e.kind, "title": e.title, "status": e.status,
            "source": e.source, "notes": e.notes,
        }

    async def _evidence_index_row(e: EvidenceItem) -> dict:
        document = None
        if e.file_ref:
            document = (
                await db.execute(
                    select(Document).where(
                        Document.user_id == uuid.UUID(uid),
                        Document.file_ref == e.file_ref,
                    )
                )
            ).scalar_one_or_none()
        rationale = evidence_rationale(e.kind)
        citations: list[PacketCitationOut] = []
        if document is not None:
            chunk_rows = (
                await db.execute(
                    select(DocumentChunk).where(
                        DocumentChunk.user_id == uuid.UUID(uid),
                        DocumentChunk.document_id == document.id,
                    ).order_by(DocumentChunk.chunk_index)
                )
            ).scalars().all()
            terms = evidence_query_terms(cond.name, e.kind)
            ranked = rank_chunk_rows(chunk_rows, terms, k=3)
            citations = [
                PacketCitationOut(
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
        pinned = (
            await db.execute(
                select(EvidenceCitation).where(
                    EvidenceCitation.evidence_id == e.id,
                    EvidenceCitation.user_id == uuid.UUID(uid),
                )
            )
        ).scalar_one_or_none()
        if pinned is not None and document is not None:
            pinned_out = PacketCitationOut(
                document_id=document.id,
                source_title=document.title or document.filename,
                quote=pinned.quote,
                char_start=pinned.char_start,
                char_end=pinned.char_end,
                page=pinned.page,
                chunk_index=pinned.chunk_index,
                note=pinned.note,
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
        return {
            "id": e.id,
            "title": e.title,
            "kind": e.kind,
            "status": e.status,
            "source": e.source,
            "notes": e.notes,
            "document_id": document.id if document is not None else None,
            "rationale": rationale,
            "citations": citations,
        }

    # Continuity from Glitter Mane — optional, degrades to [].
    continuity: list[dict] = []
    if settings.glitter_enabled and user is not None:
        try:
            continuity = await fetch_continuity(user.email, cond.name)
        except Exception:  # noqa: BLE001 — the packet must render without GM
            log.info("Glitter Mane continuity unavailable for packet %s.", condition_id)

    dbq = cond.dbq_form or map_dbq(cond.name, cond.body_system, load_dbq_catalog())

    # Grounded excerpts: WHERE in the veteran's OWN uploaded records this condition
    # is discussed. Evidence organization, not interpretation — the excerpts are
    # the veteran's uploaded text verbatim so they (or their VSO) can point the
    # rater straight to the page. Degrades to [] with no chunks / no embeddings.
    evidence_excerpts: list[dict] = []
    try:
        chunks = await retrieve_document_chunks(db, uid, cond.name, k=4)
        if chunks:
            rows = (
                await db.execute(
                    select(Document.id, Document.title, Document.filename).where(
                        Document.id.in_({c.document_id for c in chunks}),
                        Document.user_id == uuid.UUID(uid),
                    )
                )
            ).all()
            titles = {rid: (rtitle or rfile) for rid, rtitle, rfile in rows}
            evidence_excerpts = [
                {
                    "document_id": str(c.document_id),
                    "source": titles.get(c.document_id, "Your records"),
                    "excerpt": c.content,
                    "chunk_index": c.chunk_index,
                }
                for c in chunks
                if c.document_id in titles
            ]
    except Exception:  # noqa: BLE001 — grounding is best-effort, never fatal
        log.info("Evidence excerpts unavailable for packet %s.", condition_id)

    evidence_index = []
    try:
        evidence_index = [await _evidence_index_row(e) for e in evidence]
    except Exception:  # noqa: BLE001 — packet must still render
        log.info("Evidence index unavailable for packet %s.", condition_id)

    await audit.log(
        db, uid, "packet.view", entity="claimed_condition", entity_id=str(condition_id),
    )

    return PacketOut(
        veteran={"name": user.full_name if user else ""},
        condition={
            "id": str(cond.id),
            "name": cond.name,
            "body_system": cond.body_system,
            "diagnostic_code": cond.diagnostic_code,
            "claim_type": cond.claim_type,
            "status": cond.status,
            "current_rating": cond.current_rating,
            "onset_date": cond.onset_date.isoformat() if cond.onset_date else None,
            "in_service_event": cond.in_service_event,
            "nexus_notes": cond.nexus_notes,
        },
        dc_card=dc_card,
        evidence_have=[_ev(e) for e in evidence if e.status == "have"],
        evidence_missing=[_ev(e) for e in evidence if e.status in ("need", "requested")],
        evidence_excerpts=evidence_excerpts,
        evidence_index=evidence_index,
        gaps=gaps,
        continuity=continuity,
        lay_statement_prompts=_lay_statement_prompts(
            cond.name, cond.body_system, cond.claim_type
        ),
        dbq=dbq,
        disclaimer=_disclaimer(),
    )
