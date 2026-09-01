import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from geoalchemy2 import Geography
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DispatchConfidenceTier(str, PyEnum):
    HIGH = "high"        # automated dispatch proceeds
    MEDIUM = "medium"     # routed to human dispatcher with model reasoning attached
    LOW = "low"           # flagged, held pending additional verification


class DispatchStatus(str, PyEnum):
    PENDING_SCORING = "pending_scoring"
    PENDING_REVERSE_CALL = "pending_reverse_call"
    PENDING_DISPATCHER_REVIEW = "pending_dispatcher_review"
    FLAGGED_HELD = "flagged_held"
    CONFIRMED_DISPATCHED = "confirmed_dispatched"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class DispatchRequest(Base):
    """
    A single emergency-dispatch attempt. This is the audit-trail row
    required by concept paper Section 5.3: every scored decision (features,
    score, tier, eventual outcome) is logged, both to retrain the model and
    to support liability review.

    NOTE on live dispatch: whether a HIGH-confidence request is actually
    auto-dispatched to a real ambulance is additionally gated by
    `settings.ENABLE_LIVE_DISPATCH`. With that flag off (the shipped
    default), the full scoring/audit pipeline runs end-to-end but the
    terminal action is a simulated dispatch, matching the concept paper's
    explicit staged-rollout requirement (Section 8.3): dispatch only goes
    live after legal review and a consented pilot partnership.
    """

    __tablename__ = "dispatch_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    triage_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("triage_sessions.id"), nullable=True
    )
    target_hospital_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    used_silent_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reported_location: Mapped[str] = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    device_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Ambulance assigned once a dispatcher/fleet operator confirms rollout.
    # Set by the dispatcher dashboard (Section 4.2); the ambulance crew's
    # own device then reports position against this dispatch (see
    # app.api.routes.dispatch.submit_ambulance_location), and the patient
    # app subscribes to those updates for live, Uber-style tracking.
    assigned_ambulance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    status: Mapped[DispatchStatus] = mapped_column(
        Enum(DispatchStatus, name="dispatch_status"),
        default=DispatchStatus.PENDING_SCORING,
        nullable=False,
    )

    # --- Dispatch Confidence Engine output (Section 5.2) ---
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_tier: Mapped[DispatchConfidenceTier | None] = mapped_column(
        Enum(DispatchConfidenceTier, name="dispatch_confidence_tier"), nullable=True
    )
    # Full feature vector + SHAP-style per-feature contributions, so every
    # decision is explainable to a hospital, regulator, or liability review.
    scoring_features: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scoring_explanation: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # --- Reverse Call verification ---
    reverse_call_initiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverse_call_answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverse_call_confirmed_emergency: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reverse_call_dispatcher_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Outcome ground truth, filled in after the fact — the training
    # signal for continuously improving the Dispatch Confidence model. ---
    outcome_confirmed_real: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome_notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    patient: Mapped["User"] = relationship(back_populates="dispatch_requests")  # noqa: F821
    gps_pings: Mapped[list["LiveLocationPing"]] = relationship(
        back_populates="dispatch_request", cascade="all, delete-orphan"
    )


class LocationPingSource(str, PyEnum):
    PATIENT_DEVICE = "patient_device"
    AMBULANCE_DEVICE = "ambulance_device"


class LiveLocationPing(Base):
    """
    Streaming GPS pings. Active for the duration of an active, verified
    dispatch (concept paper 4.1 "Live GPS Tracking"). Two independent
    streams share this table, distinguished by `source`:
      - PATIENT_DEVICE: the patient's own phone, used for the GPS
        Telemetry Matching abuse signal (Section 5.1.C) and, once en
        route, to help the crew navigate to a moving patient.
      - AMBULANCE_DEVICE: the responding ambulance's position, which the
        patient app subscribes to for real-time "where's my ambulance"
        tracking, the same interaction pattern as a rideshare app.
    Retained for the audit trail and for post-hoc plausibility scoring on
    future requests.
    """

    __tablename__ = "live_location_pings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dispatch_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dispatch_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[LocationPingSource] = mapped_column(
        Enum(LocationPingSource, name="location_ping_source"),
        default=LocationPingSource.PATIENT_DEVICE,
        nullable=False,
    )
    location: Mapped[str] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_degrees: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    dispatch_request: Mapped["DispatchRequest"] = relationship(back_populates="gps_pings")
