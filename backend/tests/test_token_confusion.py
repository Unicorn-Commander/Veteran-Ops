"""Wave 12 security regression — purpose/state tokens must NOT authenticate as native
session bearers (audit Finding 1). All three are HS256-signed with the same jwt_secret,
so only a claim-level guard separates them; this locks that guard in."""

from __future__ import annotations

import jwt
import pytest

from app import security
from app.config import settings


@pytest.fixture(autouse=True)
def _strong_secret(monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "x" * 40)
    monkeypatch.setattr(settings, "jwt_algorithm", "HS256")


def test_session_token_still_decodes():
    tok = security.create_access_token("11111111-1111-1111-1111-111111111111", "a@e.com")
    claims = security.decode_token(tok)
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"


def test_verify_email_token_rejected_as_session():
    tok = security.make_purpose_token("verify-email", "victim-id", 60, email="v@e.com")
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(tok)


def test_password_reset_token_rejected_as_session():
    tok = security.make_purpose_token("pw-reset", "victim-id", 60, fp="abcd")
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(tok)


def test_sso_state_token_rejected_as_session():
    state = security.make_sso_state()
    with pytest.raises(jwt.InvalidTokenError):
        security.decode_token(state)


def test_reverse_confusion_still_closed():
    # A real session token must not pass as a purpose or state token either.
    tok = security.create_access_token("22222222-2222-2222-2222-222222222222", "b@e.com")
    with pytest.raises(jwt.InvalidTokenError):
        security.verify_purpose_token(tok, "verify-email")
    with pytest.raises(jwt.InvalidTokenError):
        security.verify_sso_state(tok)
