from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_platform_admin
from app.db.session import get_db
from app.models.user import AuditLog, User
from app.services.audit_log import record_audit_event
from app.services.kill_switch import activate_kill_switch, deactivate_kill_switch, is_dispatch_kill_switch_active

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/kill-switch")
async def kill_switch_status(admin: User = Depends(require_platform_admin)):
    return {"active": await is_dispatch_kill_switch_active()}


@router.post("/kill-switch/activate")
async def activate(
    reason: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_platform_admin),
):
    await activate_kill_switch(reason)
    record_audit_event(
        db,
        actor=admin,
        action="admin.kill_switch.activate",
        changes={"reason": reason},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return {"detail": "Dispatch kill switch activated. All requests now route to human-mediated review."}


@router.post("/kill-switch/deactivate")
async def deactivate(
    request: Request, db: Session = Depends(get_db), admin: User = Depends(require_platform_admin)
):
    await deactivate_kill_switch()
    record_audit_event(
        db,
        actor=admin,
        action="admin.kill_switch.deactivate",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return {"detail": "Dispatch kill switch deactivated."}


@router.get("/audit-log")
def list_audit_log(
    limit: int = Query(100, le=500),
    action_prefix: str | None = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_platform_admin),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action_prefix:
        stmt = stmt.where(AuditLog.action.like(f"{action_prefix}%"))
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": str(r.id),
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "actor_role": r.actor_role,
            "action": r.action,
            "target_type": r.target_type,
            "target_id": r.target_id,
            "changes": r.changes,
            "ip_address": r.ip_address,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


user_router = APIRouter(prefix="/users", tags=["users"])


@user_router.patch("/me/accept-dispatch-terms")
def accept_dispatch_terms(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """
    Financial & legal deterrence gate (anti-prank spec): explicit,
    recorded acceptance of the false-dispatch fee policy, required before
    Silent Override dispatch can be used.
    """
    user.dispatch_terms_accepted_at = datetime.now(timezone.utc)
    db.commit()
    return {"accepted_at": user.dispatch_terms_accepted_at.isoformat()}
