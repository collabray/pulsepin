"""
Seeds a handful of demo hospitals/ambulances so the app is usable
immediately after `docker compose up` without a blank database. This is
explicitly demo/dev fixture data (Nairobi-area facilities, publicly known
to exist, but their listed capabilities here are illustrative placeholders
— NOT sourced from each hospital's real, current capability status). A
real deployment must have each hospital confirm its own capabilities
through the Facility Capability Manager (PATCH /hospitals/{id}/capabilities)
before going live — see LIMITATIONS.md "Facility data provenance."

Usage:
    python -m app.db.seed
"""
from datetime import datetime, timezone

from geoalchemy2.shape import from_shape
from shapely.geometry import Point

from app.db.session import SessionLocal
from app.models.hospital import (
    Ambulance,
    AmbulanceFleet,
    CapabilityCode,
    FacilityCapability,
    Hospital,
)

DEMO_HOSPITALS = [
    {
        "name": "Kenyatta National Hospital (demo record)",
        "address": "Hospital Rd, Nairobi",
        "phone_number": "+254202726300",
        "lat": -1.3009,
        "lon": 36.8073,
        "capabilities": [
            CapabilityCode.EMERGENCY_ROOM, CapabilityCode.ICU, CapabilityCode.TRAUMA_CENTER,
            CapabilityCode.CT_SCAN, CapabilityCode.BLOOD_BANK, CapabilityCode.CATH_LAB,
            CapabilityCode.OPERATING_ROOM, CapabilityCode.PEDIATRIC_WARD,
        ],
    },
    {
        "name": "Nairobi Hospital (demo record)",
        "address": "Argwings Kodhek Rd, Nairobi",
        "phone_number": "+254202845000",
        "lat": -1.2963,
        "lon": 36.7889,
        "capabilities": [
            CapabilityCode.EMERGENCY_ROOM, CapabilityCode.ICU, CapabilityCode.XRAY,
            CapabilityCode.MALARIA_TESTING, CapabilityCode.TYPHOID_TESTING, CapabilityCode.BLOOD_BANK,
        ],
    },
    {
        "name": "Aga Khan University Hospital (demo record)",
        "address": "3rd Parklands Ave, Nairobi",
        "phone_number": "+254203662000",
        "lat": -1.2626,
        "lon": 36.8083,
        "capabilities": [
            CapabilityCode.EMERGENCY_ROOM, CapabilityCode.ICU, CapabilityCode.NICU,
            CapabilityCode.CATH_LAB, CapabilityCode.DENGUE_TESTING, CapabilityCode.MRI,
            CapabilityCode.ISOLATION_WARD,
        ],
    },
]


def seed() -> None:
    db = SessionLocal()
    try:
        if db.query(Hospital).count() > 0:
            print("Hospitals already seeded — skipping.")
            return

        for entry in DEMO_HOSPITALS:
            hospital = Hospital(
                name=entry["name"],
                address=entry["address"],
                phone_number=entry["phone_number"],
                location=from_shape(Point(entry["lon"], entry["lat"]), srid=4326),
                is_verified_partner=True,
                icu_beds_available=6,
                icu_beds_total=10,
                operating_rooms_active=1,
                operating_rooms_total=2,
                capability_last_confirmed_at=datetime.now(timezone.utc),
            )
            db.add(hospital)
            db.flush()

            for cap in entry["capabilities"]:
                db.add(
                    FacilityCapability(
                        hospital_id=hospital.id, capability=cap.value, is_available=True
                    )
                )

            fleet = AmbulanceFleet(
                operator_name=f"{entry['name']} Ambulance Fleet",
                phone_number=entry["phone_number"],
                hospital_id=hospital.id,
            )
            db.add(fleet)
            db.flush()
            for i in range(1, 3):
                db.add(
                    Ambulance(
                        fleet_id=fleet.id,
                        call_sign=f"{entry['name'].split()[0].upper()}-{i}",
                        current_location=from_shape(Point(entry["lon"], entry["lat"]), srid=4326),
                        is_available=True,
                    )
                )

        db.commit()
        print(f"Seeded {len(DEMO_HOSPITALS)} demo hospitals.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
