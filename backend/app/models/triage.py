import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import DateTime, Enum, Float, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class UrgencyLevel(str, PyEnum):
    SELF_CARE = "self_care"
    CLINIC_VISIT = "clinic_visit"
    EMERGENCY = "emergency"
    UNCERTAIN = "uncertain"  # below confidence floor — explicitly defers to a doctor


class TriageSessionStatus(str, PyEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class TriageSession(Base):
    """
    One symptom-triage conversation. Stores every answered symptom, the
    question-selection trace (for explainability/audit), and the final
    model output. This row is also a primary input signal to the Dispatch
    Confidence Engine (was triage completed? how long ago? what urgency did
    it conclude with?).
    """

    __tablename__ = "triage_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[TriageSessionStatus] = mapped_column(
        Enum(TriageSessionStatus, name="triage_session_status"),
        default=TriageSessionStatus.IN_PROGRESS,
        nullable=False,
    )

    # symptom_key -> 1 (present) / 0 (absent). Populated incrementally as the
    # Dynamic Follow-Up Engine asks questions.
    symptom_responses: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # Ordered list of symptom keys the engine asked, for explainability.
    question_trace: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Final output once status == COMPLETED
    predicted_conditions: Mapped[list | None] = mapped_column(
        JSON, nullable=True
    )  # [{"condition": str, "probability": float}, ...] ranked desc
    top_condition: Mapped[str | None] = mapped_column(String(255), nullable=True)
    top_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    urgency_level: Mapped[UrgencyLevel | None] = mapped_column(
        Enum(UrgencyLevel, name="urgency_level"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="triage_sessions")  # noqa: F821
