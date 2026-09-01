from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# --- Auth ---
class OTPRequestIn(BaseModel):
    phone_number: str = Field(..., pattern=r"^\+[1-9]\d{6,14}$", description="E.164 format, e.g. +254712345678")


class OTPVerifyIn(BaseModel):
    phone_number: str = Field(..., pattern=r"^\+[1-9]\d{6,14}$")
    code: str = Field(..., min_length=4, max_length=8)
    device_fingerprint: str | None = Field(
        None, description="Client-generated device fingerprint, used for device-binding / new-device challenge."
    )


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


# --- Triage ---
class TriageStartIn(BaseModel):
    initial_symptoms: dict[str, int] = Field(
        default_factory=dict, description="symptom_key -> 1 (present) / 0 (absent)"
    )


class RankedCondition(BaseModel):
    condition: str
    probability: float


class TriageStepOut(BaseModel):
    session_id: UUID
    ranked_conditions: list[RankedCondition]
    top_condition: str | None
    top_probability: float
    urgency_level: str
    next_question_symptom: str | None
    next_question_label: str | None
    is_complete: bool


class TriageAnswerIn(BaseModel):
    symptom: str
    value: int = Field(..., ge=0, le=1)

    @field_validator("value")
    @classmethod
    def must_be_binary(cls, v: int) -> int:
        if v not in (0, 1):
            raise ValueError("value must be 0 or 1")
        return v


# --- Facility matching ---
class FacilityMatchOut(BaseModel):
    hospital_id: str
    name: str
    address: str
    phone_number: str
    distance_km: float
    capability_match_count: int
    capability_match_ratio: float
    matched_capabilities: list[str]
    missing_capabilities: list[str]
    is_verified_partner: bool
    capability_data_is_stale: bool


class NearbyFacilitiesIn(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    condition: str
    radius_km: float = Field(50.0, gt=0, le=300)


# --- Facility capability management (hospital dashboard) ---
class CapabilityToggleIn(BaseModel):
    capability: str
    is_available: bool


class ICUBedUpdateIn(BaseModel):
    icu_beds_available: int = Field(..., ge=0)
    icu_beds_total: int = Field(..., ge=0)


# --- Dispatch ---
class DispatchTriggerIn(BaseModel):
    triage_session_id: UUID | None = None
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    target_hospital_id: UUID
    used_silent_override: bool = False
    device_fingerprint: str | None = None
    gps_accuracy_meters: float | None = None
    # The requesting device's OWN live GPS reading, captured via the
    # browser/app Geolocation permission prompt at the moment of dispatch.
    # May differ from (latitude, longitude) above when the user manually
    # typed/adjusted a pickup address — that gap is exactly the "GPS
    # Telemetry Matching" signal the anti-prank spec calls for.
    device_gps_latitude: float | None = Field(None, ge=-90, le=90)
    device_gps_longitude: float | None = Field(None, ge=-180, le=180)


class DispatchOut(BaseModel):
    id: UUID
    status: str
    confidence_score: float | None
    confidence_tier: str | None
    scoring_explanation: list[dict] | None
    live_dispatch_enabled: bool
    created_at: datetime


class ReverseCallResultIn(BaseModel):
    confirmed_emergency: bool
    notes: str | None = None


class DispatchOutcomeIn(BaseModel):
    confirmed_real: bool
    notes: str | None = None


class GPSPingIn(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    accuracy_meters: float | None = None
    heading_degrees: float | None = None
    speed_kmh: float | None = None


class AmbulanceAssignIn(BaseModel):
    ambulance_id: UUID
    estimated_arrival_minutes: float | None = Field(None, gt=0, le=180)


class TrackingPointOut(BaseModel):
    latitude: float
    longitude: float
    recorded_at: datetime
    heading_degrees: float | None = None
    speed_kmh: float | None = None


class DispatchTrackingOut(BaseModel):
    dispatch_id: UUID
    status: str
    assigned_ambulance_call_sign: str | None
    estimated_arrival_at: datetime | None
    patient_location: TrackingPointOut | None
    ambulance_location: TrackingPointOut | None
    hospital_name: str | None
    hospital_location: TrackingPointOut | None
