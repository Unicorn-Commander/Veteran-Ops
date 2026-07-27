"""Application-layer encryption for VA OAuth credentials.

Database and volume encryption remain required infrastructure controls. This layer
limits the impact of a database-only disclosure: VA access/refresh tokens are stored
as authenticated ciphertext and are decrypted only immediately before an OAuth call.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

_PREFIX = "enc:v1:"


class TokenEncryptionError(ValueError):
    """The token encryption key is missing or the ciphertext is not trustworthy."""


def _fernet() -> Fernet:
    secret = settings.va_token_encryption_key
    if len(secret) < 32:
        raise TokenEncryptionError("VA token encryption is not configured")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_token(value: str) -> str:
    if not value:
        raise TokenEncryptionError("cannot encrypt an empty token")
    if value.startswith(_PREFIX):
        return value
    encrypted = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{encrypted}"


def decrypt_token(value: str | None) -> str | None:
    if value is None:
        return None
    # Fail closed on legacy plaintext. Enabling encryption requires veterans to
    # reconnect rather than briefly continuing to store usable plaintext.
    if not value.startswith(_PREFIX):
        raise TokenEncryptionError("legacy plaintext token requires reconnect")
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise TokenEncryptionError("VA token ciphertext could not be verified") from exc
