from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.mfa import role_requires_mfa, start_enrollment, verify_totp
from app.core.rate_limit import rate_limit
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.core.field_encryption import tokenize
from app.db.session import get_db
from app.models.user import User, UserDevice, UserRole
from app.schemas.schemas import OTPRequestIn, OTPVerifyIn, TokenPair
from app.services.captcha_service import CaptchaError, verify_captcha
from app.services.line_type_lookup import LineTypeLookupError, lookup_line_type
from app.services.otp_service import OTPError, OTPInvalidError, OTPRateLimitError, get_otp_service

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

otp_request_rate_limit = rate_limit("otp_request", settings.RATE_LIMIT_OTP_PER_HOUR, 3600)


@router.post(
    "/otp/request",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(otp_request_rate_limit)],
)
async def request_otp(payload: OTPRequestIn, request: Request, db: Session = Depends(get_db)):
    # --- Bot detection (Security Architecture 5) ---
    captcha_token = request.headers.get("x-captcha-token")
    if settings.CAPTCHA_PROVIDER != "none":
        if not captcha_token:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing CAPTCHA token.")
        try:
            client_ip = request.client.host if request.client else None
            if not await verify_captcha(captcha_token, remote_ip=client_ip):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CAPTCHA verification failed.")
        except CaptchaError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))

    # --- VoIP/burner-number flagging (anti-prank spec) ---
    # Flags the account for review; does NOT block OTP delivery outright,
    # since blocking legitimate VoIP users (common for e.g. Google Voice)
    # would itself be a harm. The flag feeds into Dispatch Confidence
    # scoring instead (see app.ml.dispatch_confidence).
    if settings.ENABLE_LINE_TYPE_LOOKUP:
        try:
            line_type, is_voip = await lookup_line_type(payload.phone_number)
            existing = db.query(User).filter(User.phone_number_token == tokenize(payload.phone_number)).one_or_none()
            if existing:
                existing.phone_line_type = line_type
                existing.is_voip_flagged = is_voip
                db.commit()
        except LineTypeLookupError:
            pass  # non-fatal — don't block OTP delivery on a carrier-lookup outage

    otp_service = await get_otp_service()
    try:
        await otp_service.request_otp(payload.phone_number)
    except OTPRateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except OTPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
    return {"detail": "OTP sent."}


@router.post("/otp/verify", response_model=TokenPair)
async def verify_otp(payload: OTPVerifyIn, request: Request, db: Session = Depends(get_db)):
    otp_service = await get_otp_service()
    try:
        await otp_service.verify_otp(payload.phone_number, payload.code)
    except OTPRateLimitError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except OTPInvalidError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    user = db.query(User).filter(User.phone_number_token == tokenize(payload.phone_number)).one_or_none()
    if user is None:
        user = User(
            phone_number=payload.phone_number,
            phone_number_token=tokenize(payload.phone_number),
            phone_verified=True,
            phone_verified_at=datetime.now(timezone.utc),
            role=UserRole.PATIENT,
        )
        db.add(user)
    else:
        user.phone_verified = True
        user.phone_verified_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    # --- Device binding / new-device challenge (Security Architecture 1) ---
    # For privileged roles, a login from a fingerprint never seen for this
    # user requires the MFA step below before a usable token is issued;
    # for patients it's recorded but does not block (patients have no MFA
    # requirement, and blocking a patient mid-emergency on a device check
    # would defeat the platform's purpose).
    device_fingerprint = payload.device_fingerprint
    is_new_device = False
    if device_fingerprint:
        existing_device = (
            db.query(UserDevice)
            .filter(UserDevice.user_id == user.id, UserDevice.device_fingerprint == device_fingerprint)
            .one_or_none()
        )
        is_new_device = existing_device is None
        if existing_device is None:
            db.add(
                UserDevice(
                    user_id=user.id,
                    device_fingerprint=device_fingerprint,
                    last_seen_ip=request.client.host if request.client else None,
                )
            )
        else:
            existing_device.last_seen_at = datetime.now(timezone.utc)
            existing_device.last_seen_ip = request.client.host if request.client else None
        db.commit()

    if role_requires_mfa(user.role.value):
        if not user.mfa_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="MFA enrollment required for this role before login can complete. "
                "Call /auth/mfa/enroll.",
            )
        # Issue a short-lived, MFA-scoped pre-auth token rather than a full
        # access token — the caller must complete /auth/mfa/verify to
        # exchange it for a real session (device-binding new-device
        # challenge folds into this same step: any login for a privileged
        # role always requires the MFA step, new device or not, which is
        # the stricter and simpler policy to reason about and audit).
        pre_auth_token = create_access_token(
            str(user.id), user.role.value, extra_claims={"type": "mfa_pending", "new_device": is_new_device}
        )
        return TokenPair(access_token=pre_auth_token, refresh_token="", token_type="mfa_pending")

    return TokenPair(
        access_token=create_access_token(str(user.id), user.role.value, extra_claims={"hospital_id": str(user.hospital_id) if user.hospital_id else None}),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/mfa/enroll")
def enroll_mfa(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not role_requires_mfa(user.role.value):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not required for this role.")
    enrollment = start_enrollment(user.phone_number)
    user.mfa_secret_encrypted = enrollment.encrypted_secret
    user.mfa_backup_codes_hashed = [hash_password(c) for c in enrollment.backup_codes]
    db.commit()
    return {
        "provisioning_uri": enrollment.provisioning_uri,
        "backup_codes": enrollment.backup_codes,  # shown exactly once — client must display & discard
    }


@router.post("/mfa/activate")
def activate_mfa(code: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.mfa_secret_encrypted:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Call /auth/mfa/enroll first.")
    if not verify_totp(user.mfa_secret_encrypted, code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code.")
    user.mfa_enabled = True
    db.commit()
    return {"detail": "MFA enabled."}


@router.post("/mfa/verify", response_model=TokenPair)
def verify_mfa(pre_auth_token: str, code: str, db: Session = Depends(get_db)):
    try:
        payload = decode_token(pre_auth_token)
        if payload.get("type") != "mfa_pending":
            raise ValueError("wrong token type")
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired pre-auth token.")

    user = db.get(User, payload["sub"])
    if user is None or not user.mfa_enabled or not user.mfa_secret_encrypted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA not configured for this account.")

    valid = verify_totp(user.mfa_secret_encrypted, code)
    if not valid and user.mfa_backup_codes_hashed:
        remaining = []
        for hashed in user.mfa_backup_codes_hashed:
            if not valid and verify_password(code, hashed):
                valid = True  # backup code consumed, not re-added to `remaining`
                continue
            remaining.append(hashed)
        if valid:
            user.mfa_backup_codes_hashed = remaining

    if not valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code.")

    db.commit()
    return TokenPair(
        access_token=create_access_token(str(user.id), user.role.value, extra_claims={"hospital_id": str(user.hospital_id) if user.hospital_id else None}),
        refresh_token=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=TokenPair)
def refresh_token(refresh_token: str, db: Session = Depends(get_db)):
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise ValueError("wrong token type")
    except (jwt.PyJWTError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    return TokenPair(
        access_token=create_access_token(str(user.id), user.role.value, extra_claims={"hospital_id": str(user.hospital_id) if user.hospital_id else None}),
        refresh_token=create_refresh_token(str(user.id)),
    )
