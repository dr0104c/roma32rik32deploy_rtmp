from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import generate_client_code
from ..models import User, UserStatusHistory
from .audit import write_audit_log


def enroll_user(db: Session, display_name: str) -> User:
    client_code = generate_client_code()
    while db.scalar(select(User).where(User.client_code == client_code)) is not None:
        client_code = generate_client_code()

    user = User(display_name=display_name.strip(), client_code=client_code, status="pending")
    db.add(user)
    db.flush()
    db.add(UserStatusHistory(user_id=user.id, previous_status=None, new_status="pending"))
    write_audit_log(
        db,
        actor_type="viewer",
        action="user_enrolled",
        target_type="user",
        target_id=user.id,
        metadata={"display_name": user.display_name, "client_code": client_code},
    )
    db.commit()
    db.refresh(user)
    return user
