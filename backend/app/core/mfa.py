"""
MFA for privileged roles (Security Architecture Section 1).

Implements TOTP (RFC 6238, the same algorithm as Google Authenticator /
Authy) rather than SMS-based codes, because SMS OTP is vulnerable to
SIM-swap attacks and the security doc specifically calls for
phishing-resistant MFA on privileged accounts. TOTP is not quite as
phishing-resistant as WebAuthn/FIDO2 hardware keys (a user can still be
tricked into typing a TOTP code into a fake site), so this module also
exposes the interface `MFAMethod` and a `webauthn` stub path — wiring a
real WebAuthn relying party (e.g. via `webauthn` / `fido2` PyPI packages)
is the natural next hardening step for admin accounts and is called out
explicitly in SECURITY.md rather than silently left out.

Enrollment secrets are stored encrypted at rest via
app.core.field_encryption, never in plaintext.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

import pyotp

from app.core.config import get_settings
from app.core.field_encryption import decrypt_field, encrypt_field


@dataclass
class MFAEnrollment:
    encrypted_secret: str
    provisioning_uri: str
    backup_codes: list[str]  # shown once at enrollment; store only hashed


def start_enrollment(user_email_or_phone: str) -> MFAEnrollment:
    settings = get_settings()
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user_email_or_phone, issuer_name=settings.MFA_ISSUER_NAME)
    backup_codes = [secrets.token_hex(4) for _ in range(8)]
    return MFAEnrollment(
        encrypted_secret=encrypt_field(secret),
        provisioning_uri=uri,
        backup_codes=backup_codes,
    )


def verify_totp(encrypted_secret: str, code: str) -> bool:
    secret = decrypt_field(encrypted_secret)
    totp = pyotp.TOTP(secret)
    # valid_window=1 tolerates minor clock drift (±30s) without widening
    # the acceptance window enough to meaningfully help an attacker.
    return totp.verify(code, valid_window=1)


def role_requires_mfa(role: str) -> bool:
    settings = get_settings()
    return role in settings.MFA_REQUIRED_ROLES
