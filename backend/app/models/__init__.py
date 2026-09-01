"""
Importing this package registers every ORM model on the shared declarative
Base, which SQLAlchemy needs before it can resolve the string-based
`relationship()` references used across modules (e.g. User.triage_sessions
-> "TriageSession"). Alembic's env.py and app startup both import this
module before touching the metadata.
"""
from app.db.base import Base  # noqa: F401
from app.models.user import User, UserDevice, UserRole, AuditLog  # noqa: F401
from app.models.hospital import (  # noqa: F401
    Ambulance,
    AmbulanceFleet,
    CapabilityCode,
    FacilityCapability,
    Hospital,
    SpecialistOnDuty,
)
from app.models.triage import TriageSession, TriageSessionStatus, UrgencyLevel  # noqa: F401
from app.models.dispatch import (  # noqa: F401
    DispatchConfidenceTier,
    DispatchRequest,
    DispatchStatus,
    LiveLocationPing,
    LocationPingSource,
)

__all__ = [
    "Base",
    "User",
    "UserDevice",
    "UserRole",
    "AuditLog",
    "Hospital",
    "FacilityCapability",
    "SpecialistOnDuty",
    "AmbulanceFleet",
    "Ambulance",
    "CapabilityCode",
    "TriageSession",
    "TriageSessionStatus",
    "UrgencyLevel",
    "DispatchRequest",
    "DispatchStatus",
    "DispatchConfidenceTier",
    "LiveLocationPing",
    "LocationPingSource",
]
