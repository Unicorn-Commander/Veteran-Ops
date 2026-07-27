"""Focused regression gates for the July 2026 production hardening lane."""

from __future__ import annotations

import asyncio
import io
import json
import os

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile
from starlette.routing import Match

from app import main
from app.config import settings
from app.deps import require_platform_admin
from app.kb import freshness
from app.kb.guard import guards_path
from app.routers import documents
from app.va.token_crypto import TokenEncryptionError, decrypt_token, encrypt_token


async def test_platform_admin_is_an_explicit_instance_allowlist(monkeypatch):
    monkeypatch.setattr(
        settings,
        "platform_admin_emails",
        "first@example.test, Operator@Example.test",
    )
    operator = type("Operator", (), {"email": "operator@example.test"})()
    workspace_owner = type("Owner", (), {"email": "owner@example.test"})()

    assert await require_platform_admin(user=operator) is operator
    with pytest.raises(HTTPException) as exc:
        await require_platform_admin(user=workspace_owner)
    assert exc.value.status_code == 403


def test_va_tokens_are_authenticated_ciphertext(monkeypatch):
    monkeypatch.setattr(settings, "va_token_encryption_key", "k" * 40)
    ciphertext = encrypt_token("veteran-oauth-secret")
    assert ciphertext.startswith("enc:v1:")
    assert "veteran-oauth-secret" not in ciphertext
    assert decrypt_token(ciphertext) == "veteran-oauth-secret"

    tampered = ciphertext[:-1] + ("A" if ciphertext[-1] != "A" else "B")
    with pytest.raises(TokenEncryptionError):
        decrypt_token(tampered)
    with pytest.raises(TokenEncryptionError):
        decrypt_token("legacy-plaintext-token")


def test_va_feature_requires_independent_encryption_key(monkeypatch):
    monkeypatch.setattr(settings, "va_client_id", "client")
    monkeypatch.setattr(settings, "va_redirect_base", "https://valor.example.test")
    monkeypatch.setattr(settings, "va_token_encryption_key", "")
    assert settings.va_enabled is False
    monkeypatch.setattr(settings, "va_token_encryption_key", "e" * 32)
    assert settings.va_enabled is True


def test_email_enabled_postmark_and_smtp(monkeypatch):
    monkeypatch.setattr(settings, "email_from", "rating-raider@magicunicorn.dev")
    monkeypatch.setattr(settings, "email_provider", "")
    monkeypatch.setattr(settings, "postmark_server_token", "")
    monkeypatch.setattr(settings, "smtp_host", "")
    assert settings.email_enabled is False

    monkeypatch.setattr(settings, "email_provider", "postmark")
    monkeypatch.setattr(settings, "postmark_server_token", "tok")
    assert settings.email_enabled is True

    monkeypatch.setattr(settings, "email_provider", "smtp")
    monkeypatch.setattr(settings, "postmark_server_token", "")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.test")
    assert settings.email_enabled is True

    monkeypatch.setattr(settings, "smtp_host", "")
    assert settings.email_enabled is False


def test_kb_guard_blocks_new_guidance_but_preserves_history():
    assert guards_path("POST", "/api/raider/chat")
    assert guards_path("GET", "/api/strategy")
    assert guards_path("POST", "/api/analysis/comprehensive")
    assert guards_path("GET", "/api/kb/cards")
    assert not guards_path("GET", "/api/kb/freshness")
    assert not guards_path("GET", "/api/analysis/comprehensive/latest")
    assert not guards_path("GET", "/api/analysis/comprehensive/runs/abc")
    assert not guards_path("GET", "/api/documents")


def test_effective_freshness_recomputes_after_curated_refresh(monkeypatch):
    # Amendment must be AFTER the authored KB_VERIFIED_AS_OF constant so the
    # corpus is genuinely stale until mark_kb_verified_as_of catches up.
    monkeypatch.setattr(freshness, "_verified_as_of_override", None)
    monkeypatch.setattr(
        freshness,
        "_last_result",
        {"title38_latest_amended_on": "2099-01-15", "stale": True},
    )
    assert freshness.cached_effective_freshness()["status"] == "stale"
    freshness.mark_kb_verified_as_of(freshness.date(2099, 1, 15))
    assert freshness.cached_effective_freshness()["status"] == "current"


def test_stale_guidance_is_stopped_before_handler_and_secured(monkeypatch):
    monkeypatch.setattr(freshness, "_verified_as_of_override", None)
    monkeypatch.setattr(
        freshness,
        "_last_result",
        {"title38_latest_amended_on": "2999-01-01", "stale": True},
    )
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/api/raider/chat",
        "raw_path": b"/api/raider/chat",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("valor.test", 443),
        "root_path": "",
    }

    async def must_not_run(_scope, _receive, _send):
        raise AssertionError("stale guidance reached its handler")

    async def invoke_middleware():
        messages = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            messages.append(message)

        middleware = main.SecurityAndFreshnessMiddleware(must_not_run)
        await middleware(scope, receive, send)
        return messages

    messages = asyncio.run(invoke_middleware())
    start = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    headers = Headers(raw=start["headers"])
    assert start["status"] == 503
    assert json.loads(body)["code"] == "kb_stale"
    assert headers["x-knowledge-status"] == "stale"
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["cache-control"] == "no-store"


def test_liveness_is_dependency_free_and_public_aliases_exist():
    assert asyncio.run(main.healthz())["status"] == "alive"
    for path in ("/healthz", "/api/healthz", "/readyz", "/api/readyz"):
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "root_path": "",
        }
        assert any(route.matches(scope)[0] is Match.FULL for route in main.app.routes)


def test_upload_validation_and_private_storage(tmp_path, monkeypatch):
    assert documents._content_rejection("claim.pdf", b"MZ executable")
    assert documents._content_rejection("claim.pdf", b"not a pdf")
    assert documents._content_rejection("claim.docx", b"not a zip")
    assert documents._content_rejection("claim.pdf", b"%PDF-1.7\n") is None

    monkeypatch.setattr(documents, "UPLOAD_DIR", tmp_path.resolve())
    user_dir = tmp_path / "user"
    user_dir.mkdir(mode=0o700)
    stored = user_dir / "record.pdf"
    documents._write_private(stored, b"%PDF-1.7\n")
    assert documents._stored_path(str(stored)) == stored.resolve()
    assert os.stat(stored).st_mode & 0o777 == 0o600

    outside = tmp_path.parent / "outside-valor-upload.txt"
    outside.write_text("not veteran data", encoding="utf-8")
    try:
        with pytest.raises(Exception):
            documents._stored_path(str(outside))
    finally:
        outside.unlink(missing_ok=True)


def test_direct_upload_reader_enforces_limit():
    allowed = UploadFile(io.BytesIO(b"1234"), filename="record.txt")
    too_large = UploadFile(io.BytesIO(b"12345"), filename="record.txt")
    assert asyncio.run(documents._read_upload_bounded(allowed, 4)) == b"1234"
    assert asyncio.run(documents._read_upload_bounded(too_large, 4)) is None
