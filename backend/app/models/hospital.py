import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from geoalchemy2 import Geography
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CapabilityCode(str, PyEnum):
    """
    Controlled vocabulary of facility capabilities the triage/routing engine
    can match against. Kept as an enum (not free text) so capability
    matching is exact, not fuzzy-string based.
    """

    EMERGENCY_ROOM = "emergency_room"
    ICU = "icu"
    NICU = "nicu"
    MATERNITY_WARD = "maternity_ward"
    CATH_LAB = "cath_lab"
    DIALYSIS = "dialysis"
    XRAY = "xray"
    CT_SCAN = "ct_scan"
    MRI = "mri"
    BLOOD_BANK = "blood_bank"
    MALARIA_TESTING = "malaria_testing"
    TYPHOID_TESTING = "typhoid_testing"
    DENGUE_TESTING = "dengue_testing"
    ISOLATION_WARD = "isolation_ward"
    BURN_UNIT = "burn_unit"
    TRAUMA_CENTER = "trauma_center"
    PEDIATRIC_WARD = "pediatric_ward"
    PSYCHIATRIC_CARE = "psychiatric_care"
    OPERATING_ROOM = "operating_room"
    PHARMACY_24H = "pharmacy_24h"


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)

    # Geography(Point) with SRID 4326 (WGS84 lat/lon) enables ST_DWithin /
    # ST_Distance queries directly in Postgres via PostGIS.
    location: Mapped[str] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)

    is_verified_partner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    accepts_live_dispatch: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    icu_beds_available: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    icu_beds_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    operating_rooms_active: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    operating_rooms_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # The single largest credibility risk per the concept paper (Section
    # 8.4) is stale facility data. We track when capability status was last
    # confirmed by hospital staff so routing/UI can visibly flag staleness.
    capability_last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    capabilities: Mapped[list["FacilityCapability"]] = relationship(
        back_populates="hospital", cascade="all, delete-orphan"
    )
    specialists_on_duty: Mapped[list["SpecialistOnDuty"]] = relationship(
        back_populates="hospital", cascade="all, delete-orphan"
    )


class FacilityCapability(Base):
    """One row per (hospital, capability) — hospital-controlled, toggleable."""

    __tablename__ = "facility_capabilities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    capability: Mapped[CapabilityCode] = mapped_column(
        String(64), nullable=False
    )  # stored as string to keep migrations additive as new codes are added
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    hospital: Mapped["Hospital"] = relationship(back_populates="capabilities")


class SpecialistOnDuty(Base):
    __tablename__ = "specialists_on_duty"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hospital_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hospitals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    specialty: Mapped[str] = mapped_column(String(120), nullable=False)
    on_duty: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    shift_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    hospital: Mapped["Hospital"] = relationship(back_populates="specialists_on_duty")


class AmbulanceFleet(Base):
    __tablename__ = "ambulance_fleets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operator_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(20), nullable=False)
    hospital_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hospitals.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Ambulance(Base):
    __tablename__ = "ambulances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fleet_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ambulance_fleets.id", ondelete="CASCADE"), nullable=False
    )
    call_sign: Mapped[str] = mapped_column(String(50), nullable=False)
    current_location: Mapped[str | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=True
    )
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_location_update: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
