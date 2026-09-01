"""
Hospital Capability Matching (concept paper Section 4.1): ranks nearby
facilities by capability fit first, distance second, using live facility
status from the Facility Capability Manager.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.hospital import CapabilityCode, Hospital


@dataclass
class FacilityMatch:
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


# Condition -> required capabilities. A small, explicit, human-editable
# mapping (not ML-guessed) so a clinician can review and correct it — the
# concept paper treats stale/wrong facility routing as the platform's
# single largest credibility risk (Section 8.4), so this mapping is kept
# simple and auditable rather than inferred.
CONDITION_CAPABILITY_MAP: dict[str, list[CapabilityCode]] = {
    "Heart attack": [CapabilityCode.CATH_LAB, CapabilityCode.ICU, CapabilityCode.EMERGENCY_ROOM],
    "Paralysis (brain hemorrhage)": [CapabilityCode.ICU, CapabilityCode.CT_SCAN, CapabilityCode.TRAUMA_CENTER],
    "Malaria": [CapabilityCode.MALARIA_TESTING, CapabilityCode.EMERGENCY_ROOM],
    "Typhoid": [CapabilityCode.TYPHOID_TESTING, CapabilityCode.EMERGENCY_ROOM],
    "Dengue": [CapabilityCode.DENGUE_TESTING, CapabilityCode.BLOOD_BANK, CapabilityCode.EMERGENCY_ROOM],
    "Tuberculosis": [CapabilityCode.ISOLATION_WARD, CapabilityCode.XRAY],
    "Pneumonia": [CapabilityCode.XRAY, CapabilityCode.EMERGENCY_ROOM],
    "hepatitis A": [CapabilityCode.EMERGENCY_ROOM],
    "Hepatitis B": [CapabilityCode.EMERGENCY_ROOM, CapabilityCode.BLOOD_BANK],
    "Hepatitis C": [CapabilityCode.EMERGENCY_ROOM, CapabilityCode.BLOOD_BANK],
    "Hepatitis D": [CapabilityCode.EMERGENCY_ROOM, CapabilityCode.BLOOD_BANK],
    "Hepatitis E": [CapabilityCode.EMERGENCY_ROOM, CapabilityCode.ICU],
    "Alcoholic hepatitis": [CapabilityCode.ICU, CapabilityCode.EMERGENCY_ROOM],
    "Diabetes": [CapabilityCode.EMERGENCY_ROOM],
    "Hypoglycemia": [CapabilityCode.EMERGENCY_ROOM],
    "Chronic cholestasis": [CapabilityCode.EMERGENCY_ROOM],
    "Peptic ulcer diseae": [CapabilityCode.EMERGENCY_ROOM],
    "AIDS": [CapabilityCode.ISOLATION_WARD, CapabilityCode.BLOOD_BANK],
    "Urinary tract infection": [CapabilityCode.EMERGENCY_ROOM],
    "Bronchial Asthma": [CapabilityCode.EMERGENCY_ROOM],
    "Hypertension": [CapabilityCode.EMERGENCY_ROOM],
    "Migraine": [CapabilityCode.EMERGENCY_ROOM],
    "Cervical spondylosis": [CapabilityCode.EMERGENCY_ROOM],
    "Jaundice": [CapabilityCode.EMERGENCY_ROOM],
    "Chicken pox": [CapabilityCode.ISOLATION_WARD],
    "Dimorphic hemmorhoids(piles)": [CapabilityCode.OPERATING_ROOM],
    "Varicose veins": [CapabilityCode.OPERATING_ROOM],
    "Hypothyroidism": [CapabilityCode.EMERGENCY_ROOM],
    "Hyperthyroidism": [CapabilityCode.EMERGENCY_ROOM],
    "Osteoarthristis": [CapabilityCode.EMERGENCY_ROOM],
    "Arthritis": [CapabilityCode.EMERGENCY_ROOM],
    "(vertigo) Paroymsal  Positional Vertigo": [CapabilityCode.EMERGENCY_ROOM],
    "Acne": [],
    "Urinary  tract infection": [CapabilityCode.EMERGENCY_ROOM],
    "Psoriasis": [],
    "Impetigo": [],
    "GERD": [CapabilityCode.EMERGENCY_ROOM],
    "Gastroenteritis": [CapabilityCode.EMERGENCY_ROOM],
    "Drug Reaction": [CapabilityCode.EMERGENCY_ROOM, CapabilityCode.ICU],
    "Fungal infection": [],
    "Allergy": [CapabilityCode.EMERGENCY_ROOM],
    "Common Cold": [],
}

# Data considered stale if not confirmed by hospital staff within this window.
STALE_AFTER_HOURS = 24


def capabilities_required_for(condition: str) -> list[CapabilityCode]:
    return CONDITION_CAPABILITY_MAP.get(condition, [CapabilityCode.EMERGENCY_ROOM])


def find_matching_facilities(
    db: Session,
    *,
    latitude: float,
    longitude: float,
    condition: str,
    radius_km: float = 50.0,
    limit: int = 10,
) -> list[FacilityMatch]:
    """
    ST_DWithin/ST_Distance run inside Postgres via PostGIS — this scales to
    a large hospital table far better than pulling every row into Python
    and computing haversine distance in a loop. Facilities within
    `radius_km` are fetched ordered by raw distance, then re-ranked in
    Python by capability fit first / distance second, per concept paper
    Section 4.1.
    """
    from geoalchemy2.functions import ST_Distance, ST_DWithin, ST_MakePoint, ST_SetSRID

    point = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
    point_geog = point.cast(Hospital.__table__.c.location.type)

    distance_expr = ST_Distance(Hospital.location, point_geog) / 1000.0

    stmt = (
        select(Hospital, distance_expr.label("distance_km"))
        .where(ST_DWithin(Hospital.location, point_geog, radius_km * 1000))
        .order_by(distance_expr.asc())
        .limit(limit * 3)  # over-fetch by distance, then re-rank by capability fit in Python
    )
    rows = db.execute(stmt).all()

    required = set(c.value for c in capabilities_required_for(condition))
    from datetime import datetime, timedelta, timezone

    results: list[FacilityMatch] = []
    for hospital, distance_km in rows:
        available = {
            fc.capability
            for fc in hospital.capabilities
            if fc.is_available and fc.capability in required
        }
        missing = required - available
        stale = (
            hospital.capability_last_confirmed_at is None
            or hospital.capability_last_confirmed_at
            < datetime.now(timezone.utc) - timedelta(hours=STALE_AFTER_HOURS)
        )
        results.append(
            FacilityMatch(
                hospital_id=str(hospital.id),
                name=hospital.name,
                address=hospital.address,
                phone_number=hospital.phone_number,
                distance_km=round(float(distance_km), 2),
                capability_match_count=len(available),
                capability_match_ratio=(len(available) / len(required)) if required else 1.0,
                matched_capabilities=sorted(available),
                missing_capabilities=sorted(missing),
                is_verified_partner=hospital.is_verified_partner,
                capability_data_is_stale=stale,
            )
        )

    # Capability fit first, distance second — exactly as specified in the
    # concept paper (Section 4.1, "Hospital Capability Matching").
    results.sort(key=lambda r: (-r.capability_match_ratio, r.distance_km))
    return results[:limit]
