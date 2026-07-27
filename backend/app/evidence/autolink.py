"""Auto-link detected evidence — the app files what it finds, so the veteran doesn't.

The proactive engine detects nexus letters / buddy statements / DBQs already in the
file and matches them to a condition. This creates the EvidenceItem link
automatically for the CONFIDENT matches (a nexus/buddy/DBQ document that clearly names
exactly one of the veteran's conditions), idempotently and marked as auto-linked so
the veteran can review or undo it. Ambiguous matches are left as suggestions for the
veteran to confirm — automation where it's safe, a question only where it isn't.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..firm.context import build_dossier
from ..models import ClaimedCondition, EvidenceItem
from .proactive import existing_evidence

log = logging.getLogger("veteran_ops.evidence.autolink")

_AUTO_SOURCE = "Auto-linked from your records"

# doc evidence_type (from proactive.existing_evidence) → EvidenceItem.kind
_KIND = {"nexus": "nexus_letter", "buddy_statement": "lay_statement", "dbq": "dbq"}


async def auto_link_evidence(db: AsyncSession, uid: str) -> dict:
    """File confident evidence detections as EvidenceItems. Idempotent; RLS-scoped.
    Returns {linked: [...], already_linked: int, ambiguous: [...]}. Never raises on a
    single bad row — automation must never corrupt the record."""
    user_id = uuid.UUID(uid)
    dossier = await build_dossier(db, uid)
    detections = existing_evidence(dossier)

    # condition name → id, and the set of (condition_id, file_ref, kind) already linked.
    conds = (
        await db.execute(select(ClaimedCondition).where(ClaimedCondition.user_id == user_id))
    ).scalars().all()
    by_name = {(c.name or "").strip().lower(): c for c in conds}
    existing = (
        await db.execute(select(EvidenceItem).where(EvidenceItem.user_id == user_id))
    ).scalars().all()
    linked_keys = {
        (str(e.condition_id), (e.file_ref or ""), e.kind) for e in existing
    }

    linked: list[dict] = []
    ambiguous: list[dict] = []
    already = 0

    # A document may appear once per matched condition; auto-link only when a detection
    # names exactly one KNOWN condition (unambiguous). No-condition or multi-match
    # detections stay as review suggestions.
    known_by_document: dict[str, set[str]] = {}
    for det in detections:
        document_id = str(det.get("document_id") or "")
        cname = (det.get("condition") or "").strip().lower()
        if document_id and cname in by_name:
            known_by_document.setdefault(document_id, set()).add(cname)

    ambiguous_documents: set[str] = set()
    for det in detections:
        cname = (det.get("condition") or "").strip().lower()
        cond = by_name.get(cname) if cname else None
        document_id = str(det.get("document_id") or "")
        if len(known_by_document.get(document_id, set())) > 1:
            if document_id not in ambiguous_documents:
                ambiguous.append({"document": det.get("document_title"), "reason": "multiple known condition matches"})
                ambiguous_documents.add(document_id)
            continue
        if cond is None:
            ambiguous.append({"document": det.get("document_title"), "reason": "no clear condition match"})
            continue
        kind = _KIND.get(det.get("evidence_type"), "other")
        # file_ref for the detected document — look it up from the dossier docs.
        file_ref = _file_ref_for(dossier, det.get("document_id"))
        key = (str(cond.id), (file_ref or ""), kind)
        if key in linked_keys:
            already += 1
            continue
        try:
            db.add(
                EvidenceItem(
                    user_id=user_id,
                    condition_id=cond.id,
                    kind=kind,
                    title=(det.get("document_title") or "Evidence document")[:255],
                    status="have",
                    source=_AUTO_SOURCE,
                    file_ref=file_ref,
                )
            )
            linked_keys.add(key)
            linked.append(
                {"condition": cond.name, "evidence_type": det.get("evidence_type"), "document": det.get("document_title")}
            )
        except Exception:  # noqa: BLE001 — one bad row must not sink the sweep
            log.warning("auto-link failed for a detection", exc_info=True)

    if linked:
        await db.commit()
    return {"linked": linked, "already_linked": already, "ambiguous": ambiguous}


def _file_ref_for(dossier, document_id: str | None) -> str | None:
    if not document_id:
        return None
    for doc in dossier.documents or []:
        if str(getattr(doc, "id", "")) == str(document_id):
            return getattr(doc, "file_ref", None)
    return None
