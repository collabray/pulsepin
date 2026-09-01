from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_hospital_admin
from app.db.session import get_db
from app.models.hospital import FacilityCapability, Hospital
from app.models.user import User
from app.schemas.schemas import (
    CapabilityToggleIn,
    FacilityMatchOut,
    ICUBedUpdateIn,
    NearbyFacilitiesIn,
)
from app.services.facility_matching import find_matching_facilities

router = APIRouter(prefix="/hospitals", tags=["hospitals"])


@router.post("/nearby", response_model=list[FacilityMatchOut])
def nearby_facilities(
    payload: NearbyFacilitiesIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    matches = find_matching_facilities(
        db,
        latitude=payload.latitude,
        longitude=payload.longitude,
        condition=payload.condition,
        radius_km=payload.radius_km,
    )
    return [FacilityMatchOut(**m.__dict__) for m in matches]


@router.patch("/{hospital_id}/capabilities", status_code=status.HTTP_204_NO_CONTENT)
def toggle_capability(
    hospital_id: UUID,
    payload: CapabilityToggleIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_hospital_admin),
):
    if user.hospital_id != hospital_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your hospital.")

    row = (
        db.query(FacilityCapability)
        .filter(
            FacilityCapability.hospital_id == hospital_id,
            FacilityCapability.capability == payload.capability,
        )
        .one_or_none()
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = FacilityCapability(
            hospital_id=hospital_id,
            capability=payload.capability,
            is_available=payload.is_available,
            updated_by_user_id=user.id,
        )
        db.add(row)
    else:
        row.is_available = payload.is_available
        row.updated_at = now
        row.updated_by_user_id = user.id

    hospital = db.get(Hospital, hospital_id)
    hospital.capability_last_confirmed_at = now
    db.commit()


@router.patch("/{hospital_id}/icu-beds", status_code=status.HTTP_204_NO_CONTENT)
def update_icu_beds(
    hospital_id: UUID,
    payload: ICUBedUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_hospital_admin),
):
    if user.hospital_id != hospital_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your hospital.")
    hospital = db.get(Hospital, hospital_id)
    if hospital is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if payload.icu_beds_available > payload.icu_beds_total:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="icu_beds_available cannot exceed icu_beds_total.",
        )
    hospital.icu_beds_available = payload.icu_beds_available
    hospital.icu_beds_total = payload.icu_beds_total
    hospital.capability_last_confirmed_at = datetime.now(timezone.utc)
    db.commit()
