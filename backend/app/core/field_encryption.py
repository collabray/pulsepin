"""
Field-level encryption for the most sensitive columns (Security
Architecture Section 4): phone numbers and precise GPS history are
encrypted independently of disk/transport encryption, so a raw database
dump does not expose readable PII without this application-level key.

Key management: `FIELD_ENCRYPTION_KEY` is read from the environment (or,
in production, injected by whatever secrets manager you run — see
SECURITY.md "Secrets Management"). It is never generated automatically at
runtime and never has a working default, so the app fails to start rather
than silently encrypting with a key nobody has a copy of.

This module also provides `tokenize()`, a one-way HMAC token for using a
phone number as a lookup/log key without exposing or reversibly storing
the raw number in places that don't need it (Security Architecture
Section 4, "Tokenization of sensitive identifiers").
"""
from __future__ import annotations

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


class FieldEncryptionError(Exception):
    pass


def _fernet() -> Fernet:
    settings = get_settings()
    if not settings.FIELD_ENCRYPTION_KEY:
        raise FieldEncryptionError(
            "FIELD_ENCRYPTION_KEY is not configured. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"` "
            "and store it in your secrets manager / vault, not in code."
        )
    return Fernet(settings.FIELD_ENCRYPTION_KEY.encode())


def encrypt_field(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_field(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as e:
        raise FieldEncryptionError("Field decryption failed: invalid key or corrupted ciphertext.") from e


def tokenize(value: str) -> str:
    """
    One-way, deterministic token (HMAC-SHA256) for using a sensitive value
    as an index/log key without storing or logging the raw value. Uses a
    key separate from FIELD_ENCRYPTION_KEY so rotating one does not require
    rotating the other.
    """
    settings = get_settings()
    if not settings.TOKENIZATION_KEY:
        raise FieldEncryptionError("TOKENIZATION_KEY is not configured.")
    return hmac.new(
        settings.TOKENIZATION_KEY.encode(), value.encode(), hashlib.sha256
    ).hexdigest()
