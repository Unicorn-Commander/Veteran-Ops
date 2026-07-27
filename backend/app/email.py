"""Transactional email: verification, password reset, org invites, deadline digests.

Backends, chosen by `settings.email_provider` when `settings.email_enabled`:
- Postmark (`EMAIL_PROVIDER=postmark` + token + verified sender) — HTTP API.
- SMTP (`EMAIL_PROVIDER=smtp` + host + from) — stdlib smtplib (STARTTLS or SSL).
- Console fallback (empty/other provider, or incomplete config) — the message is
  LOGGED, never sent, so self-service flows work in dev/degraded with no mail
  dependency. Security-relevant links are always built by the caller so a router
  can also surface them (dev convenience).

Best-effort: a delivery failure NEVER raises into the request path (a veteran must
never see a 500 because the mail provider blipped) — it's logged and the flow
continues. The security-relevant links are single-purpose, short-lived signed
tokens (see security.py).
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

import httpx

from .config import settings

log = logging.getLogger("veteran_ops.email")

_POSTMARK_URL = "https://api.postmarkapp.com/email"


def _from_header() -> str:
    if settings.email_from_name:
        return f"{settings.email_from_name} <{settings.email_from}>"
    return settings.email_from


async def _send_postmark(to: str, subject: str, text_body: str) -> None:
    payload = {
        "From": _from_header(),
        "To": to,
        "Subject": subject,
        "TextBody": text_body,
        "MessageStream": "outbound",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            _POSTMARK_URL,
            json=payload,
            headers={
                "X-Postmark-Server-Token": settings.postmark_server_token,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()


def _send_smtp_sync(to: str, subject: str, text_body: str) -> None:
    """Blocking SMTP send (run via asyncio.to_thread). Never logs credentials."""
    msg = EmailMessage()
    msg["From"] = _from_header()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)

    host = settings.smtp_host
    port = int(settings.smtp_port or 587)
    user = settings.smtp_user or None
    password = settings.smtp_password or None

    if settings.smtp_use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            if user:
                smtp.login(user, password or "")
            smtp.send_message(msg)
        return

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        if settings.smtp_use_tls:
            smtp.starttls()
            smtp.ehlo()
        if user:
            smtp.login(user, password or "")
        smtp.send_message(msg)


async def _send_smtp(to: str, subject: str, text_body: str) -> None:
    await asyncio.to_thread(_send_smtp_sync, to, subject, text_body)


async def _send(to: str, subject: str, text_body: str) -> dict:
    """Deliver one plain-text email or log it (console fallback).

    Returns ``{"ok": True}`` or ``{"ok": False, "reason": "..."}``. Never raises —
    callers (auth, digests) treat mail as best-effort.
    """
    if not settings.email_enabled:
        log.info("EMAIL (console) → %s | %s\n%s", to, subject, text_body)
        return {"ok": True, "reason": "console"}
    provider = (settings.email_provider or "").strip().lower()
    try:
        if provider == "postmark":
            await _send_postmark(to, subject, text_body)
        elif provider == "smtp":
            await _send_smtp(to, subject, text_body)
        else:
            # Defensive: email_enabled should already be false for unknown providers.
            log.info("EMAIL (console) → %s | %s\n%s", to, subject, text_body)
            return {"ok": True, "reason": "console"}
        return {"ok": True, "reason": "ok"}
    except Exception as exc:  # noqa: BLE001 — email is best-effort; never fail the request
        log.warning("email send to %s failed (subject=%r)", to, subject, exc_info=True)
        msg = str(exc).lower()
        # Map common SMTP auth failures so operators get an actionable reason
        # (suite noreply password rotation) without leaking credentials.
        if "535" in msg or "authentication" in msg or "auth" in msg:
            return {"ok": False, "reason": "smtp_auth_failed"}
        if "connection" in msg or "timed out" in msg or "timeout" in msg:
            return {"ok": False, "reason": "smtp_unreachable"}
        return {"ok": False, "reason": "send_failed"}


_SIGNOFF = (
    "\n\n— Rating Raider\n\n"
    "Rating Raider is self-help educational software. It is not the U.S. Department of "
    "Veterans Affairs and is not a VA-accredited representative. If you didn't request "
    "this, you can ignore this email."
)


async def send_verification_email(to: str, link: str) -> None:
    body = (
        "Welcome to Rating Raider.\n\n"
        "Confirm your email address to secure your account:\n\n"
        f"{link}\n\n"
        "This link expires in a few days. You can keep using Rating Raider in the "
        "meantime." + _SIGNOFF
    )
    await _send(to, "Confirm your Rating Raider email", body)


async def send_password_reset_email(to: str, link: str) -> None:
    body = (
        "We received a request to reset your Rating Raider password.\n\n"
        f"Set a new password:\n\n{link}\n\n"
        "This link expires in one hour. If you didn't ask for this, no action is "
        "needed — your password stays the same." + _SIGNOFF
    )
    await _send(to, "Reset your Rating Raider password", body)


async def send_org_invite_email(to: str, org_name: str, inviter: str, link: str) -> None:
    who = f"{inviter} invited you" if inviter else "You've been invited"
    body = (
        f"{who} to join the “{org_name}” team on Rating Raider.\n\n"
        f"Accept the invitation:\n\n{link}\n\n"
        "You'll need to sign in (or create a free account) with THIS email address to "
        "accept." + _SIGNOFF
    )
    await _send(to, f"You're invited to join {org_name} on Rating Raider", body)


async def send_deadline_digest(
    to: str,
    deadlines_summary_text: str,
    *,
    subject: str | None = None,
) -> dict:
    """Send a Deadline Guardian digest (urgent clocks only). Plain text.

    Returns the same shape as ``_send`` so notify paths can surface SMTP status.
    """
    body = (
        "These are educational deadline reminders from Rating Raider, computed from "
        "dates in your own records so you don't miss an Intent to File, decision-review, "
        "or dependency window.\n\n"
        f"{deadlines_summary_text}"
        "\n\nOpen Rating Raider → Deadlines for the full list and what to do next."
        " Rating Raider never files anything for you."
        + _SIGNOFF
    )
    return await _send(to, subject or "Rating Raider: deadline reminders", body)
