"""
SQLAlchemy TypeDecorator that transparently encrypts a column's value on
write and decrypts on read, using app.core.field_encryption. Because
Fernet ciphertext is non-deterministic (a fresh IV each time), an
encrypted column can't be queried by equality directly — pair it with a
separate deterministic-token column (via `tokenize()`) for lookups/unique
constraints, as done for `User.phone_number` / `User.phone_number_token`.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

from app.core.field_encryption import decrypt_field, encrypt_field


class EncryptedString(TypeDecorator):
    """A String column that is encrypted at rest and decrypted transparently on read."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return encrypt_field(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return decrypt_field(value)
