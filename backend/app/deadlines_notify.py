"""Deadline Guardian email notifications.

Pure formatting + best-effort delivery for urgent clocks (soon / overdue).
Load path reuses the same sources as GET /deadlines (ITF, decoded decisions,
dependents). No LLM. Legal lane: informs only — never files.

CLI (cron-friendly)::

    cd backend && python -m app.deadlines_notify

Authenticated test surface: POST /api/deadlines/notify-me
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .deadlines import Deadline, compute_deadlines
from .email import send_deadline_digest
from .models import Document, ItfRecord, User, VeteranProfile

log = logging.getLogger("veteran_ops.deadlines_notify")

# Urgencies that warrant an outbound email (ok = too far out; skip noise).
_URGENT = frozenset({"soon", "overdue"})


def format_deadline_email(
    deadlines: list[dict[str, Any]] | list[Deadline],
    *,
    public_base: str = "",
) -> tuple[str, str]:
    """Pure: build (subject, body_summary) from deadline dicts or Deadline objects.

    Each item needs at least title/urgency; due_date, days_left, what_to_do,
    related_route are included when present. Empty input → empty body still has
    a stable subject (callers should skip send when there is nothing urgent).
    """
    rows: list[dict[str, Any]] = []
    for item in deadlines:
        if isinstance(item, Deadline):
            rows.append(asdict(item))
        elif isinstance(item, dict):
            rows.append(item)
        else:
            continue

    urgent = [r for r in rows if str(r.get("urgency") or "") in _URGENT]
    # If the caller already filtered, still format whatever they passed.
    use = urgent if urgent else rows

    subject = "Rating Raider: deadline reminders"
    if use:
        n = len(use)
        overdue_n = sum(1 for r in use if r.get("urgency") == "overdue")
        if overdue_n:
            subject = (
                f"Rating Raider: {overdue_n} overdue deadline"
                f"{'s' if overdue_n != 1 else ''}"
            )
        else:
            subject = (
                f"Rating Raider: {n} upcoming deadline"
                f"{'s' if n != 1 else ''}"
            )

    lines: list[str] = []
    for r in use:
        title = (r.get("title") or "Deadline").strip()
        urgency = (r.get("urgency") or "soon").strip().upper()
        due = r.get("due_date")
        due_s = str(due) if due is not None else "date not detected"
        days = r.get("days_left")
        if days is None:
            days_s = "unknown days left"
        elif int(days) < 0:
            days_s = f"{abs(int(days))} day(s) overdue"
        else:
            days_s = f"{int(days)} day(s) left"
        what = (r.get("what_to_do") or "").strip()
        route = (r.get("related_route") or "").strip()
        block = [f"[{urgency}] {title}", f"  Due: {due_s} ({days_s})"]
        if what:
            block.append(f"  What to do: {what}")
        if route and public_base:
            block.append(f"  In app: {public_base.rstrip('/')}{route}")
        elif route:
            block.append(f"  In app: {route}")
        lines.append("\n".join(block))

    body = "\n\n".join(lines) if lines else "(No urgent deadlines.)"
    return subject, body


async def load_deadlines_for_user(
    db: AsyncSession,
    user_id: uuid.UUID | str,
    *,
    today=None,
) -> list[Deadline]:
    """Same source assembly as GET /deadlines (RLS-scoped session expected)."""
    user_uuid = uuid.UUID(str(user_id)) if not isinstance(user_id, uuid.UUID) else user_id

    itf_rows = (
        await db.execute(select(ItfRecord).where(ItfRecord.user_id == user_uuid))
    ).scalars().all()
    itf_records = [{"type": r.type, "filed_date": r.filed_date} for r in itf_rows]

    docs = (
        await db.execute(
            select(Document).where(
                Document.user_id == user_uuid, Document.status == "ready"
            )
        )
    ).scalars().all()
    decodes: list[dict] = []
    for d in docs:
        extracted = d.extracted or {}
        decode = extracted.get("decode") if isinstance(extracted, dict) else None
        if isinstance(decode, dict):
            decodes.append(decode)

    profile = (
        await db.execute(
            select(VeteranProfile).where(VeteranProfile.user_id == user_uuid)
        )
    ).scalar_one_or_none()
    dependents = list(profile.dependents or []) if profile else []

    if today is None:
        today = datetime.now(timezone.utc).date()
    return compute_deadlines(
        itf_records=itf_records,
        decodes=decodes,
        dependents=dependents,
        today=today,
    )


async def notify_user_deadlines(
    db: AsyncSession,
    user: Any,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Load deadlines for `user`; email if any urgent and settings allow.

    `user` needs ``.id`` and ``.email`` (ORM User or a lightweight stand-in).
    Returns a small status dict for the API/CLI (never raises on send failure).
    `force=True` skips the urgency filter (send full digest for testing).
    """
    if not settings.deadline_emails_enabled:
        return {"sent": False, "reason": "deadline_emails_disabled", "urgent_count": 0}

    email = (getattr(user, "email", None) or "").strip()
    if not email or "@" not in email:
        return {"sent": False, "reason": "no_email", "urgent_count": 0}

    deadlines = await load_deadlines_for_user(db, user.id)
    urgent = [d for d in deadlines if d.urgency in _URGENT]
    to_send = deadlines if force else urgent
    if not to_send:
        return {
            "sent": False,
            "reason": "no_urgent" if not force else "no_deadlines",
            "urgent_count": 0,
            "deadline_count": len(deadlines),
        }

    subject, summary = format_deadline_email(
        to_send, public_base=settings.public_base or ""
    )
    delivery = await send_deadline_digest(email, summary, subject=subject)
    if not isinstance(delivery, dict):
        delivery = {"ok": True, "reason": "ok"}
    if not delivery.get("ok", True):
        return {
            "sent": False,
            "reason": str(delivery.get("reason") or "send_failed"),
            "urgent_count": len(urgent),
            "deadline_count": len(to_send),
            "to": email,
        }
    return {
        "sent": True,
        "reason": str(delivery.get("reason") or "ok"),
        "urgent_count": len(urgent),
        "deadline_count": len(to_send),
        "to": email,  # account email is not a secret; useful for CLI logs
    }


async def notify_all_users(*, force: bool = False) -> dict[str, Any]:
    """Cron entry: walk every user with an email and notify on urgent clocks.

    Uses a per-user RLS session (personal workspace) so fenced tables are visible.
    Failures for one user never stop the sweep.
    """
    from contextlib import asynccontextmanager

    from .db import SessionLocal, session_for_user

    if not settings.deadline_emails_enabled:
        log.info("deadline notify sweep skipped (deadline_emails_enabled=false)")
        return {"users": 0, "sent": 0, "skipped": 0, "errors": 0}

    async with SessionLocal() as db:
        users = (
            await db.execute(select(User).where(User.email.isnot(None)))
        ).scalars().all()
        # Materialize ids/emails before closing the unscoped session.
        roster = [(u.id, u.email, u.full_name) for u in users]

    sent = skipped = errors = 0
    scoped = asynccontextmanager(session_for_user)
    for user_id, email, full_name in roster:
        try:
            async with scoped(str(user_id)) as db:
                # Lightweight stand-in: notify_user_deadlines only needs id + email.
                user = type(
                    "_NotifyUser",
                    (),
                    {"id": user_id, "email": email or "", "full_name": full_name or ""},
                )()
                result = await notify_user_deadlines(db, user, force=force)
            if result.get("sent"):
                sent += 1
                log.info(
                    "deadline digest sent user=%s urgent=%s",
                    user_id,
                    result.get("urgent_count"),
                )
            else:
                skipped += 1
        except Exception:  # noqa: BLE001 — sweep must continue
            errors += 1
            log.warning("deadline notify failed user=%s", user_id, exc_info=True)

    summary = {
        "users": len(roster),
        "sent": sent,
        "skipped": skipped,
        "errors": errors,
    }
    log.info("deadline notify sweep done %s", summary)
    return summary


async def _cli_main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = await notify_all_users()
    print(result)
    return 0 if result.get("errors", 0) == 0 else 1


if __name__ == "__main__":
    import asyncio
    import sys

    sys.exit(asyncio.run(_cli_main()))
