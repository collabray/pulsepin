import math
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_dispatcher
from app.core.config import get_settings
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.ml.dispatch_confidence import DispatchFeatures, score as score_dispatch
from app.models.dispatch import (
    DispatchConfidenceTier,
    DispatchRequest,
    DispatchStatus,
    LiveLocationPing,
    LocationPingSource,
)
from app.models.hospital import Ambulance, Hospital
from app.models.triage import TriageSession
from app.models.user import User, UserDevice
from app.schemas.schemas import (
    AmbulanceAssignIn,
    DispatchOut,
    DispatchOutcomeIn,
    DispatchTrackingOut,
    DispatchTriggerIn,
    GPSPingIn,
    ReverseCallResultIn,
    TrackingPointOut,
)
from app.services.audit_log import record_audit_event
from app.services.kill_switch import is_dispatch_kill_switch_active
from app.services.ws_hub import dispatcher_hub

router = APIRouter(prefix="/dispatch", tags=["dispatch"])
settings = get_settings()

dispatch_trigger_rate_limit = rate_limit(
    "dispatch_trigger", settings.RATE_LIMIT_DISPATCH_TRIGGER_PER_HOUR, 3600
)


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _build_features(db: Session, user: User, payload: DispatchTriggerIn) -> DispatchFeatures:
    triage_urgency = None
    seconds_since_triage = None
    triage_completed = False
    if payload.triage_session_id:
        session = db.get(TriageSession, payload.triage_session_id)
        if session and session.user_id == user.id:
            triage_urgency = session.urgency_level.value if session.urgency_level else None
            triage_completed = session.status.value == "completed"
            if session.completed_at:
                seconds_since_triage = (
                    datetime.now(timezone.utc) - session.completed_at
                ).total_seconds()

    account_age_days = (datetime.now(timezone.utc) - user.created_at).total_seconds() / 86400

    prior_q = db.execute(
        select(
            func.count(DispatchRequest.id),
            func.count(DispatchRequest.id).filter(DispatchRequest.outcome_confirmed_real.is_(True)),
            func.count(DispatchRequest.id).filter(DispatchRequest.outcome_confirmed_real.is_(False)),
        ).where(DispatchRequest.patient_id == user.id)
    ).one()
    prior_count, prior_real, prior_false = prior_q

    distinct_numbers_on_device = 1
    if payload.device_fingerprint:
        distinct_numbers_on_device = db.execute(
            select(func.count(func.distinct(UserDevice.user_id))).where(
                UserDevice.device_fingerprint == payload.device_fingerprint
            )
        ).scalar_one()
        distinct_numbers_on_device = max(distinct_numbers_on_device, 1)

    # --- GPS Telemetry Matching (anti-prank spec) ---
    gps_mismatch_km = None
    if payload.device_gps_latitude is not None and payload.device_gps_longitude is not None:
        gps_mismatch_km = _haversine_km(
            payload.latitude, payload.longitude, payload.device_gps_latitude, payload.device_gps_longitude
        )

    # Speed-between-consecutive-pings spoof detection (Section 5.1.C)
    # requires a location history keyed by user across sessions. That table
    # (distinct from the per-dispatch LiveLocationPing log) is a Phase 2+
    # addition — see LIMITATIONS.md. Until then this feature is left
    # unset and the deterministic scorer treats it as neutral.
    implied_speed = None
    distance_km = None

    return DispatchFeatures(
        triage_urgency_at_completion=triage_urgency,
        seconds_since_triage_completion=seconds_since_triage,
        used_silent_override=payload.used_silent_override,
        account_age_days=account_age_days,
        prior_dispatch_count=prior_count,
        prior_confirmed_real_count=prior_real,
        prior_confirmed_false_count=prior_false,
        distinct_phone_numbers_on_device=distinct_numbers_on_device,
        gps_accuracy_meters=payload.gps_accuracy_meters,
        implied_speed_kmh_since_last_ping=implied_speed,
        distance_to_target_hospital_km=distance_km,
        reported_vs_device_gps_distance_km=gps_mismatch_km,
        triage_fully_completed=triage_completed,
    )


def _detect_behavioral_anomalies(db: Session, user: User) -> list[str]:
    """
    Behavioral anomaly detection (Security Architecture Section 5 /
    anti-prank spec: "rapid consecutive bookings... sudden cancellations
    right after vehicle deployment"). Returns a list of human-readable
    flags; does not itself block the request — flags feed into the
    dispatcher's review view and into whether MEDIUM-tier requests get
    escalated to LOW.
    """
    flags: list[str] = []
    now = datetime.now(timezone.utc)

    recent_count = db.execute(
        select(func.count(DispatchRequest.id)).where(
            DispatchRequest.patient_id == user.id,
            DispatchRequest.created_at >= now - timedelta(minutes=30),
        )
    ).scalar_one()
    if recent_count >= 2:
        flags.append(f"burst_requests: {recent_count} dispatch requests in the last 30 minutes")

    cancelled_after_dispatch = db.execute(
        select(func.count(DispatchRequest.id)).where(
            DispatchRequest.patient_id == user.id,
            DispatchRequest.status == DispatchStatus.CANCELLED,
            DispatchRequest.created_at >= now - timedelta(days=30),
        )
    ).scalar_one()
    if cancelled_after_dispatch >= 2:
        flags.append(
            f"repeat_cancellations: {cancelled_after_dispatch} dispatches cancelled in the last 30 days"
        )

    return flags


@router.post(
    "",
    response_model=DispatchOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(dispatch_trigger_rate_limit)],
)
async def trigger_dispatch(
    payload: DispatchTriggerIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # --- Financial & legal deterrence / ban enforcement (Security
    # Architecture Section 5 + anti-prank spec) ---
    if user.is_banned_from_dispatch:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been suspended from requesting dispatch due to a confirmed false request.",
        )
    if payload.used_silent_override and settings.REQUIRE_TERMS_ACCEPTANCE_FOR_SILENT_OVERRIDE:
        if user.dispatch_terms_accepted_at is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You must accept the dispatch terms (including the false-dispatch fee policy) "
                    "before using Silent Override. Call PATCH /users/me/accept-dispatch-terms."
                ),
            )

    hospital = db.get(Hospital, payload.target_hospital_id)
    if hospital is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target hospital not found.")

    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    dispatch = DispatchRequest(
        patient_id=user.id,
        triage_session_id=payload.triage_session_id,
        target_hospital_id=payload.target_hospital_id,
        used_silent_override=payload.used_silent_override,
        reported_location=from_shape(Point(payload.longitude, payload.latitude), srid=4326),
        device_fingerprint=payload.device_fingerprint,
        status=DispatchStatus.PENDING_SCORING,
    )
    db.add(dispatch)
    db.flush()

    features = _build_features(db, user, payload)
    result = score_dispatch(features)
    anomaly_flags = _detect_behavioral_anomalies(db, user)

    dispatch.confidence_score = result.score
    dispatch.confidence_tier = DispatchConfidenceTier(result.tier.value)
    dispatch.scoring_features = asdict(features)
    dispatch.scoring_explanation = [
        {"feature": k, "weighted_contribution": round(v, 4)}
        for k, v in sorted(result.feature_contributions.items(), key=lambda kv: -kv[1])
    ]
    if anomaly_flags:
        dispatch.scoring_explanation.append({"feature": "behavioral_anomaly_flags", "detail": anomaly_flags})

    # Behavioral anomalies never silently auto-approve a request — at most
    # they downgrade a tier, never upgrade one.
    effective_tier = result.tier
    if anomaly_flags and effective_tier == DispatchConfidenceTier.HIGH:
        effective_tier = DispatchConfidenceTier.MEDIUM

    kill_switch_active = await is_dispatch_kill_switch_active()

    if kill_switch_active:
        # Incident-response kill switch (Security Architecture Section 7):
        # every request falls back to full human-mediated review regardless
        # of confidence tier.
        dispatch.status = DispatchStatus.PENDING_DISPATCHER_REVIEW
    elif effective_tier == DispatchConfidenceTier.HIGH:
        if payload.used_silent_override:
            dispatch.status = DispatchStatus.CONFIRMED_DISPATCHED if settings.ENABLE_LIVE_DISPATCH \
                else DispatchStatus.PENDING_DISPATCHER_REVIEW
        else:
            # Human Medical Triage Callback (anti-prank spec): even a
            # high-confidence request gets a live callback before rollout,
            # not a silent auto-dispatch — matching how real emergency
            # platforms operate.
            dispatch.status = DispatchStatus.PENDING_REVERSE_CALL
            dispatch.reverse_call_initiated_at = datetime.now(timezone.utc)
    elif effective_tier == DispatchConfidenceTier.MEDIUM:
        dispatch.status = DispatchStatus.PENDING_DISPATCHER_REVIEW
    else:
        dispatch.status = DispatchStatus.FLAGGED_HELD

    record_audit_event(
        db,
        actor=user,
        action="dispatch.trigger",
        target_type="dispatch_request",
        target_id=str(dispatch.id),
        changes={
            "confidence_tier": result.tier.value,
            "effective_tier": effective_tier.value,
            "status": dispatch.status.value,
            "kill_switch_active": kill_switch_active,
            "anomaly_flags": anomaly_flags,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    db.commit()
    db.refresh(dispatch)

    await dispatcher_hub.broadcast_new_dispatch(str(hospital.id), {
        "id": str(dispatch.id),
        "status": dispatch.status.value,
        "confidence_tier": dispatch.confidence_tier.value if dispatch.confidence_tier else None,
        "confidence_score": dispatch.confidence_score,
        "patient_phone": user.phone_number,
        "location": {"lat": payload.latitude, "lon": payload.longitude},
        "used_silent_override": dispatch.used_silent_override,
        "anomaly_flags": anomaly_flags,
    })

    return DispatchOut(
        id=dispatch.id,
        status=dispatch.status.value,
        confidence_score=dispatch.confidence_score,
        confidence_tier=dispatch.confidence_tier.value if dispatch.confidence_tier else None,
        scoring_explanation=dispatch.scoring_explanation,
        live_dispatch_enabled=settings.ENABLE_LIVE_DISPATCH and not kill_switch_active,
        created_at=dispatch.created_at,
    )


@router.post("/{dispatch_id}/reverse-call-result", response_model=DispatchOut)
async def submit_reverse_call_result(
    dispatch_id: UUID,
    payload: ReverseCallResultIn,
    request: Request,
    db: Session = Depends(get_db),
    dispatcher: User = Depends(require_dispatcher),
):
    """
    Reverse Call verification (Section 4.1) / Human Medical Triage Callback
    (anti-prank spec): the dispatcher calls the patient directly. The
    *judgment call* of whether the voice on the line sounds like a genuine
    emergency is deliberately made by the human dispatcher, not scored by
    the model (Section 5.1, "Deliberate Design Choice") — this endpoint
    only records that human decision, and audit-logs it (Security
    Architecture Section 5: "every callback... is logged with who, when,
    and what changed").
    """
    dispatch = db.get(DispatchRequest, dispatch_id)
    if dispatch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    dispatch.reverse_call_answered_at = datetime.now(timezone.utc)
    dispatch.reverse_call_confirmed_emergency = payload.confirmed_emergency
    dispatch.reverse_call_dispatcher_id = dispatcher.id

    if payload.confirmed_emergency:
        dispatch.status = (
            DispatchStatus.CONFIRMED_DISPATCHED if settings.ENABLE_LIVE_DISPATCH
            else DispatchStatus.PENDING_DISPATCHER_REVIEW
        )
        dispatch.resolved_at = datetime.now(timezone.utc)
    else:
        dispatch.status = DispatchStatus.REJECTED
        dispatch.resolved_at = datetime.now(timezone.utc)

    record_audit_event(
        db,
        actor=dispatcher,
        action="dispatch.reverse_call_result",
        target_type="dispatch_request",
        target_id=str(dispatch.id),
        changes={"confirmed_emergency": payload.confirmed_emergency, "notes": payload.notes},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    db.commit()
    db.refresh(dispatch)
    return DispatchOut(
        id=dispatch.id,
        status=dispatch.status.value,
        confidence_score=dispatch.confidence_score,
        confidence_tier=dispatch.confidence_tier.value if dispatch.confidence_tier else None,
        scoring_explanation=dispatch.scoring_explanation,
        live_dispatch_enabled=settings.ENABLE_LIVE_DISPATCH,
        created_at=dispatch.created_at,
    )


@router.post("/{dispatch_id}/gps-ping", status_code=status.HTTP_204_NO_CONTENT)
async def submit_patient_gps_ping(
    dispatch_id: UUID,
    payload: GPSPingIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    The PATIENT device's own live location, used for the GPS Telemetry
    Matching abuse signal and, once a crew is en route, to help them find
    a patient who may be moving (e.g. walking toward a main road). This is
    distinct from ambulance-location reporting below — see
    LocationPingSource.
    """
    dispatch = db.get(DispatchRequest, dispatch_id)
    if dispatch is None or dispatch.patient_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if dispatch.status not in (
        DispatchStatus.CONFIRMED_DISPATCHED,
        DispatchStatus.PENDING_DISPATCHER_REVIEW,
        DispatchStatus.PENDING_REVERSE_CALL,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Live GPS tracking is only active for an active dispatch request.",
        )

    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    ping = LiveLocationPing(
        dispatch_request_id=dispatch.id,
        source=LocationPingSource.PATIENT_DEVICE,
        location=from_shape(Point(payload.longitude, payload.latitude), srid=4326),
        accuracy_meters=payload.accuracy_meters,
        heading_degrees=payload.heading_degrees,
        speed_kmh=payload.speed_kmh,
    )
    db.add(ping)
    db.commit()

    await dispatcher_hub.broadcast_location_update(
        str(dispatch.target_hospital_id),
        {
            "dispatch_id": str(dispatch.id),
            "source": "patient_device",
            "lat": payload.latitude,
            "lon": payload.longitude,
        },
    )


@router.post("/{dispatch_id}/assign-ambulance", response_model=DispatchOut)
async def assign_ambulance(
    dispatch_id: UUID,
    payload: AmbulanceAssignIn,
    request: Request,
    db: Session = Depends(get_db),
    dispatcher: User = Depends(require_dispatcher),
):
    """
    Dispatcher confirms a specific ambulance is rolling out (Section 4.2
    dashboard action). Once assigned, the ambulance crew's own device
    calls /ambulance-location below, and the patient app's live map lights
    up — the same "your driver is on the way" moment as a rideshare app.
    """
    dispatch = db.get(DispatchRequest, dispatch_id)
    if dispatch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ambulance = db.get(Ambulance, payload.ambulance_id)
    if ambulance is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ambulance not found.")
    if not ambulance.is_available:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ambulance is not available.")

    dispatch.assigned_ambulance_id = ambulance.id
    dispatch.assigned_at = datetime.now(timezone.utc)
    if payload.estimated_arrival_minutes:
        dispatch.estimated_arrival_at = datetime.now(timezone.utc) + timedelta(
            minutes=payload.estimated_arrival_minutes
        )
    ambulance.is_available = False

    record_audit_event(
        db,
        actor=dispatcher,
        action="dispatch.assign_ambulance",
        target_type="dispatch_request",
        target_id=str(dispatch.id),
        changes={"ambulance_id": str(ambulance.id), "call_sign": ambulance.call_sign},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    db.refresh(dispatch)

    await dispatcher_hub.broadcast_patient_tracking_update(str(dispatch.id), {
        "event": "ambulance_assigned",
        "call_sign": ambulance.call_sign,
        "estimated_arrival_at": dispatch.estimated_arrival_at.isoformat() if dispatch.estimated_arrival_at else None,
    })

    return DispatchOut(
        id=dispatch.id,
        status=dispatch.status.value,
        confidence_score=dispatch.confidence_score,
        confidence_tier=dispatch.confidence_tier.value if dispatch.confidence_tier else None,
        scoring_explanation=dispatch.scoring_explanation,
        live_dispatch_enabled=settings.ENABLE_LIVE_DISPATCH,
        created_at=dispatch.created_at,
    )


@router.post("/{dispatch_id}/ambulance-location", status_code=status.HTTP_204_NO_CONTENT)
async def submit_ambulance_location(
    dispatch_id: UUID,
    payload: GPSPingIn,
    db: Session = Depends(get_db),
    # In production this would authenticate the ambulance crew's own
    # device/app identity (a distinct principal from patient or
    # dispatcher — see LIMITATIONS.md "Ambulance crew app"). For this
    # deployment stage, reuse the dispatcher/fleet-operator role, which is
    # the accurate description of who operates this endpoint today: fleet
    # dispatch staff relaying position from radio/GPS hardware already in
    # the vehicle, not yet a purpose-built driver app.
    dispatcher: User = Depends(require_dispatcher),
):
    """
    Real-time ambulance position feed — this is what powers the patient
    app's live "where's my ambulance" map, the same interaction as a
    rideshare app tracking a driver.
    """
    dispatch = db.get(DispatchRequest, dispatch_id)
    if dispatch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if dispatch.assigned_ambulance_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No ambulance assigned to this dispatch yet.")

    from geoalchemy2.shape import from_shape
    from shapely.geometry import Point

    ping = LiveLocationPing(
        dispatch_request_id=dispatch.id,
        source=LocationPingSource.AMBULANCE_DEVICE,
        location=from_shape(Point(payload.longitude, payload.latitude), srid=4326),
        accuracy_meters=payload.accuracy_meters,
        heading_degrees=payload.heading_degrees,
        speed_kmh=payload.speed_kmh,
    )
    db.add(ping)

    ambulance = db.get(Ambulance, dispatch.assigned_ambulance_id)
    if ambulance is not None:
        ambulance.current_location = from_shape(Point(payload.longitude, payload.latitude), srid=4326)
        ambulance.last_location_update = datetime.now(timezone.utc)

    db.commit()

    await dispatcher_hub.broadcast_patient_tracking_update(str(dispatch.id), {
        "event": "ambulance_location",
        "lat": payload.latitude,
        "lon": payload.longitude,
        "heading_degrees": payload.heading_degrees,
        "speed_kmh": payload.speed_kmh,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/{dispatch_id}/tracking", response_model=DispatchTrackingOut)
def get_tracking_snapshot(
    dispatch_id: UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """
    One-shot snapshot for the patient app's map on first load (the live
    WebSocket channel handles updates after that — see
    /ws/patient/{dispatch_id}).
    """
    dispatch = db.get(DispatchRequest, dispatch_id)
    if dispatch is None or dispatch.patient_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    from geoalchemy2.shape import to_shape

    patient_point = None
    latest_patient_ping = db.execute(
        select(LiveLocationPing)
        .where(
            LiveLocationPing.dispatch_request_id == dispatch.id,
            LiveLocationPing.source == LocationPingSource.PATIENT_DEVICE,
        )
        .order_by(LiveLocationPing.recorded_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest_patient_ping is not None:
        shp = to_shape(latest_patient_ping.location)
        patient_point = TrackingPointOut(
            latitude=shp.y, longitude=shp.x, recorded_at=latest_patient_ping.recorded_at,
        )
    else:
        shp = to_shape(dispatch.reported_location)
        patient_point = TrackingPointOut(latitude=shp.y, longitude=shp.x, recorded_at=dispatch.created_at)

    ambulance_point = None
    call_sign = None
    if dispatch.assigned_ambulance_id:
        ambulance = db.get(Ambulance, dispatch.assigned_ambulance_id)
        if ambulance is not None:
            call_sign = ambulance.call_sign
        latest_ambulance_ping = db.execute(
            select(LiveLocationPing)
            .where(
                LiveLocationPing.dispatch_request_id == dispatch.id,
                LiveLocationPing.source == LocationPingSource.AMBULANCE_DEVICE,
            )
            .order_by(LiveLocationPing.recorded_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest_ambulance_ping is not None:
            shp = to_shape(latest_ambulance_ping.location)
            ambulance_point = TrackingPointOut(
                latitude=shp.y,
                longitude=shp.x,
                recorded_at=latest_ambulance_ping.recorded_at,
                heading_degrees=latest_ambulance_ping.heading_degrees,
                speed_kmh=latest_ambulance_ping.speed_kmh,
            )

    hospital_point = None
    hospital_name = None
    if dispatch.target_hospital_id:
        hospital = db.get(Hospital, dispatch.target_hospital_id)
        if hospital is not None:
            hospital_name = hospital.name
            shp = to_shape(hospital.location)
            hospital_point = TrackingPointOut(latitude=shp.y, longitude=shp.x, recorded_at=dispatch.created_at)

    return DispatchTrackingOut(
        dispatch_id=dispatch.id,
        status=dispatch.status.value,
        assigned_ambulance_call_sign=call_sign,
        estimated_arrival_at=dispatch.estimated_arrival_at,
        patient_location=patient_point,
        ambulance_location=ambulance_point,
        hospital_name=hospital_name,
        hospital_location=hospital_point,
    )


@router.post("/{dispatch_id}/outcome", status_code=status.HTTP_204_NO_CONTENT)
def record_outcome(
    dispatch_id: UUID,
    payload: DispatchOutcomeIn,
    request: Request,
    db: Session = Depends(get_db),
    dispatcher: User = Depends(require_dispatcher),
):
    """
    Ground-truth labeling for the audit trail (Section 5.3) — was this
    request, in the end, a real emergency? This is what
    `dispatch_confidence.train_from_audit_log()` retrains against once
    enough labeled rows exist.

    Financial & legal deterrence (anti-prank spec): a confirmed-false
    dispatch is recorded against the account (fee flag + ban after
    repeated offenses) rather than silently discarded. Actual fee billing
    and law-enforcement referral are real-world processes this endpoint
    triggers a durable, auditable record for — it does not itself charge a
    card or file a police report, both of which require a human-operated
    process and, for billing, a real PCI-compliant payment processor (see
    LIMITATIONS.md).
    """
    dispatch = db.get(DispatchRequest, dispatch_id)
    if dispatch is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    dispatch.outcome_confirmed_real = payload.confirmed_real
    dispatch.outcome_notes = payload.notes
    dispatch.status = DispatchStatus.COMPLETED
    dispatch.resolved_at = datetime.now(timezone.utc)

    ban_triggered = False
    if payload.confirmed_real is False:
        patient = db.get(User, dispatch.patient_id)
        prior_false = db.execute(
            select(func.count(DispatchRequest.id)).where(
                DispatchRequest.patient_id == dispatch.patient_id,
                DispatchRequest.outcome_confirmed_real.is_(False),
            )
        ).scalar_one()
        # This request itself was just marked false above but not yet
        # committed, so prior_false does not include it — add 1 explicitly.
        if prior_false + 1 >= 2:
            patient.is_banned_from_dispatch = True
            patient.ban_reason = (
                f"Repeated confirmed-false dispatch requests ({prior_false + 1} total). "
                f"False-dispatch fee (${settings.FALSE_DISPATCH_FEE_USD:.2f}) applies per account terms. "
                "Referred for hospital-partner / law-enforcement review per Terms of Service."
            )
            ban_triggered = True

    record_audit_event(
        db,
        actor=dispatcher,
        action="dispatch.outcome_recorded",
        target_type="dispatch_request",
        target_id=str(dispatch.id),
        changes={
            "confirmed_real": payload.confirmed_real,
            "notes": payload.notes,
            "ban_triggered": ban_triggered,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
