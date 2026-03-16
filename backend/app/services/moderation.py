from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import bad_request, not_found
from ..models import User, UserStatusHistory
from .audit import write_audit_log


VALID_TRANSITIONS = {
    "pending": {"approved", "rejected", "blocked"},
    "approved": {"blocked", "rejected"},
    "rejected": {"approved", "blocked"},
    "blocked": {"approved", "rejected"},
}


def list_users(db: Session, status_filter: str | None = None) -> list[User]:
    query = select(User).order_by(User.created_at.desc())
    if status_filter:
        query = query.where(User.status == status_filter)
    return list(db.scalars(query).all())


def change_user_status(db: Session, user_id: str, new_status: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("user_not_found", "user not found")
    if new_status not in VALID_TRANSITIONS.get(user.status, set()):
        raise bad_request("invalid_status_transition", f"cannot change status from {user.status} to {new_status}")

    previous_status = user.status
    user.status = new_status
    db.add(UserStatusHistory(user_id=user.id, previous_status=previous_status, new_status=new_status))
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action=f"user_{new_status}",
        target_type="user",
        target_id=user.id,
        metadata={"from": previous_status, "to": new_status},
    )
    db.commit()
    db.refresh(user)
    return user
