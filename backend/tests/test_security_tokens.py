"""WAVE12 — purpose-scoped tokens + digest helpers (app/security.py). Pure unit tests.
Covers make/verify_purpose_token (purpose binding, expiry, tamper), password_fingerprint
(deterministic, 16 chars), and invite-token generation/hashing. A strong jwt_secret is
patched onto the live settings object because make/verify read it at call time.
"""

from __future__ import annotations

import jwt
import pytest

from app.config import settings
from app.security import (
    generate_invite_token,
    hash_invite_token,
    make_purpose_token,
    password_fingerprint,
    verify_purpose_token,
)

_STRONG = "x" * 40  # a 40-char secret, not the weak placeholder


@pytest.fixture(autouse=True)
def _strong_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", _STRONG, raising=False)


def test_purpose_token_roundtrip_returns_sub_and_extras():
    tok = make_purpose_token("verify-email", "user-123", 60, email="a@e.test")
    claims = verify_purpose_token(tok, "verify-email")
    assert claims["sub"] == "user-123"
    assert claims["p"] == "verify-email"
    assert claims["email"] == "a@e.test"


def test_purpose_token_rejects_wrong_purpose():
    tok = make_purpose_token("verify-email", "user-123", 60)
    with pytest.raises(jwt.InvalidTokenError):
        verify_purpose_token(tok, "pw-reset")


def test_purpose_token_expired_rejected():
    tok = make_purpose_token("verify-email", "user-123", -1)  # already expired
    with pytest.raises(jwt.ExpiredSignatureError):
        verify_purpose_token(tok, "verify-email")


def test_purpose_token_garbage_rejected():
    with pytest.raises(jwt.InvalidTokenError):
        verify_purpose_token("not-a-jwt", "verify-email")


def test_purpose_token_wrong_secret_rejected(monkeypatch):
    tok = make_purpose_token("verify-email", "user-123", 60)
    monkeypatch.setattr(settings, "jwt_secret", "y" * 40, raising=False)
    with pytest.raises(jwt.InvalidTokenError):
        verify_purpose_token(tok, "verify-email")


def test_password_fingerprint_deterministic_and_16_chars():
    a = password_fingerprint("hash-one")
    assert a == password_fingerprint("hash-one")
    assert len(a) == 16
    assert a != password_fingerprint("hash-two")


def test_generate_invite_token_is_high_entropy_urlsafe():
    t1 = generate_invite_token()
    t2 = generate_invite_token()
    assert t1 != t2
    assert len(t1) >= 32
    # urlsafe base64 alphabet only.
    assert all(c.isalnum() or c in "-_" for c in t1)


def test_hash_invite_token_stable_64_hex():
    raw = "some-raw-invite-token"
    h = hash_invite_token(raw)
    assert h == hash_invite_token(raw)
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)
    assert hash_invite_token("other") != h
