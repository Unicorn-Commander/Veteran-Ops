"""Appeals draft-assist router (Wave 7 Track A) — extends the decoder.

Two endpoints, RLS via `current_user_id`/`get_db` (the form526.py pattern):
  GET  /appeals/candidates → conditions to supplement/appeal (from decoded letters
       + claimed conditions), each with the veteran's matching have-status evidence.
  POST /appeals/draft      → a print-ready decision-review response (Supplemental
       Claim / Higher-Level Review / Board Appeal).

The router does DB reads only and hands plain data to the PURE assembly helpers in
appeals/draft.py. Educational self-help only: Rating Raider does not file or appeal
anything and never renders a medical opinion; the veteran's words pass VERBATIM.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..appeals.draft import build_appeal_draft, build_candidates
from ..deps import current_user_id, get_db
from ..models import ClaimedCondition, Document, EvidenceItem
from ..schemas import AppealCandidatesOut, AppealDraftIn, AppealDraftOut

router = APIRouter(prefix="/appeals", tags=["appeals"])

_VA_DECISION_TYPES = ("rating_decision", "decision_letter")


def _is_va_decision(doc: Document) -> bool:
    """Same rule the decoder enforces: a VA decision by classified type OR the
    is_va_decision intake flag."""
    if doc.doc_type in _VA_DECISION_TYPES:
        return True
    return bool((doc.extracted or {}).get("is_va_decision"))


@router.get("/candidates", response_model=AppealCandidatesOut)
async def appeal_candidates(
    uid: str = Depends(current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Conditions the veteran could supplement or appeal, from two sources: every
    DENIED row of a decoded decision letter (extracted['decode']) and every claimed
    condition. Each carries the veteran's matching have-status evidence (the "new
    and relevant" material a Supplemental Claim needs)."""
    user_uuid = uuid.UUID(uid)
    today = datetime.now(timezone.utc).date()

    conditions = (
        await db.execute(
            select(ClaimedCondition)
            .where(ClaimedCondition.user_id == user_uuid)
            .order_by(ClaimedCondition.created_at)
        )
    ).scalars().all()
    cond_name_by_id = {c.id: c.name for c in conditions}

    evidence = (
        await db.execute(
            select(EvidenceItem).where(
                EvidenceItem.user_id == user_uuid,
                EvidenceItem.status == "have",
            )
        )
    ).scalars().all()
    have_evidence = [
        {
            "condition_id": str(e.condition_id),
            "condition_name": cond_name_by_id.get(e.condition_id, ""),
            "kind": e.kind,
            "title": e.title,
        }
        for e in evidence
    ]

    documents = (
        await db.execute(
            select(Document).where(
                Document.user_id == user_uuid,
                Document.status == "ready",
            )
        )
    ).scalars().all()
    decoded_docs = []
    for d in documents:
        if not _is_va_decision(d):
            continue
        decode = (d.extracted or {}).get("decode")
        if not decode:
            continue
        decoded_docs.append({"document_id": str(d.id), "decode": decode})

    conditions_in = [
        {
            "condition_id": str(c.id),
            "name": c.name,
            "diagnostic_code": c.diagnostic_code,
        }
        for c in conditions
    ]

    return build_candidates(
        decoded_docs=decoded_docs,
        conditions=conditions_in,
        have_evidence=have_evidence,
        today=today,
    )


@router.post("/draft", response_model=AppealDraftOut)
async def appeal_draft(
    payload: AppealDraftIn,
    uid: str = Depends(current_user_id),
):
    """Assemble a print-ready decision-review response from the veteran's picks.
    PURE assembly — the router only stamps the clock (today + prepared_on) and
    passes the validated body through. The veteran's statement is preserved
    VERBATIM; nothing is filed."""
    today = datetime.now(timezone.utc).date()
    return build_appeal_draft(payload, today, today.isoformat())
