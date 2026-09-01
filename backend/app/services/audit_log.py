from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.user import AuditLog, User


def record_audit_event(
    db: Session,
    *,
    actor: User | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    changes: dict | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """
    Writes one audit-log row. Callers should NOT commit inside this
    function — it's meant to be called as part of the same transaction as
    the state change it's recording, so the audit entry and the change it
    describes are atomic (both happen, or neither does).
    """
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_role=actor.role.value if actor else None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        changes=changes,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(entry)
