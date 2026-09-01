import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.encrypted_types import EncryptedString


class UserRole(str, PyEnum):
    PATIENT = "patient"
    DISPATCHER = "dispatcher"
    HOSPITAL_ADMIN = "hospital_admin"
    PLATFORM_ADMIN = "platform_admin"


class User(Base):
    """
    A person who can authenticate. Patients, hospital dispatchers, hospital
    admins, and platform admins are all Users distinguished by `role`, which
    keeps auth and audit logging in one place while route-level dependencies
    still enforce role-specific access.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Encrypted at rest (Security Architecture Section 4: "field-level
    # encryption for the most sensitive data: phone numbers..."). Fernet
    # ciphertext is non-deterministic, so equality lookups use the
    # separate deterministic `phone_number_token` column instead — see
    # app.core.field_encryption.tokenize() and app/api/routes/auth.py.
    phone_number: Mapped[str] = mapped_column(EncryptedString(255), nullable=False)
    phone_number_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    phone_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Phone-number account age is a core dispatch-confidence signal (concept
    # paper Section 5.1.B) — created_at doubles as that signal.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )

    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"), default=UserRole.PATIENT, nullable=False
    )
    full_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- MFA (Security Architecture Section 1) — required for
    # dispatcher/hospital_admin/platform_admin, see app.core.mfa. Secret is
    # stored encrypted (app.core.field_encryption), never in plaintext. ---
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mfa_backup_codes_hashed: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # --- Abuse-prevention / financial-legal deterrence (Security
    # Architecture Section 5 + supplied anti-prank spec) ---
    dispatch_terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_method_on_file: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_banned_from_dispatch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ban_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone_line_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "mobile" / "landline" / "voip" / "unknown" — from carrier lookup, see app.services.line_type_lookup
    is_voip_flagged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    hospital_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # set for dispatcher / hospital_admin roles

    devices: Mapped[list["UserDevice"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    triage_sessions: Mapped[list["TriageSession"]] = relationship(back_populates="user")
    dispatch_requests: Mapped[list["DispatchRequest"]] = relationship(back_populates="patient")


class UserDevice(Base):
    """
    Device/SIM fingerprint history for a user, used by the Dispatch
    Confidence Engine to catch repeated false requests filed from different
    phone numbers on the same physical device (concept paper Section 5.1.B)
    and by auth for device-binding / new-device challenge (Security
    Architecture Section 1): a session appearing on a fingerprint not in
    this table for the user is treated as a new device and forces
    re-authentication (see app.api.deps).
    """

    __tablename__ = "user_devices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    device_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    is_trusted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped["User"] = relationship(back_populates="devices")


class AuditLog(Base):
    """
    Full dispatcher/admin action audit log (Security Architecture Section
    5, "every callback, override, and facility-status change is logged
    with who, when, and what changed"). Append-only by convention: the API
    never exposes an update/delete route for this table.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(60))
    target_id: Mapped[str | None] = mapped_column(String(64))
    changes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
