"""Append-only audit logging.

Every mutating endpoint should leave a trail (accountability for a tool that
organizes someone's federal disability claim). Intentionally simple for v1;
a hash-chain (tamper-evidence) is a planned follow-up, mirroring the
Ops-Center audit_log pattern.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog


async def log(
    db: AsyncSession,
    user_id: uuid.UUID | str | None,
    action: str,
    *,
    entity: str | None = None,
    entity_id: str | None = None,
    meta: dict | None = None,
    actor_user_id: uuid.UUID | str | None = None,
    actor_label: str | None = None,
) -> None:
    """Append one audit row inside the caller's RLS transaction (flush, no commit).

    `user_id` is the subject — the account acted on. It may be None for a SERVICE action
    with no human subject (e.g. the billing receiver setting a tenant's tier); the column
    is nullable (ON DELETE SET NULL) so `actor_label` carries the "who" in that case.

    `actor_user_id` is a shared-access seam: who actually performed the action when it
    wasn't the veteran themself. A self action never records a separate actor.

    `actor_label` denormalizes WHO did this so the trail stays readable after the acting
    user's account is erased (user_id → NULL) or when there's no user at all. When not
    supplied AND there is a subject/actor user, we best-effort resolve their email — the
    `users` table isn't RLS-fenced, so the lookup works regardless of workspace scope.
    """
    subject = (
        user_id if isinstance(user_id, uuid.UUID)
        else (uuid.UUID(str(user_id)) if user_id else None)
    )
    actor = uuid.UUID(str(actor_user_id)) if actor_user_id else None
    if actor is not None and actor == subject:
        actor = None  # self actions carry no separate actor

    if actor_label is None:
        who = actor or subject
        if who is not None:
            try:
                actor_label = (await db.execute(
                    text("SELECT email FROM users WHERE id = :i"), {"i": str(who)}
                )).scalar()
            except Exception:  # noqa: BLE001 — the label is a nicety, never fail the action
                actor_label = None

    db.add(
        AuditLog(
            user_id=subject,
            actor_user_id=actor,
            actor_label=actor_label,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            meta=meta,
        )
    )
    await db.flush()
