from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import require_admin_secret
from ..db import get_db
from ..models import User
from ..schemas import ApproveUserResponse, BlockUserRequest
from ..services.streams import audit


router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin_secret)])


@router.post("/users/{user_id}/approve", response_model=ApproveUserResponse)
def approve_user(user_id: int, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    user.status = "approved"
    user.approved_at = datetime.now(UTC)
    user.blocked_reason = None
    user.status_version += 1
    audit(
        db,
        actor_type="admin",
        action="user_approved",
        target_type="user",
        target_id=user.id,
        result="ok",
        payload={"status": "approved", "status_version": user.status_version},
    )
    db.commit()
    db.refresh(user)
    return user


@router.post("/users/{user_id}/block", response_model=ApproveUserResponse)
def block_user(user_id: int, body: BlockUserRequest, db: Session = Depends(get_db)) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    user.status = "blocked"
    user.blocked_reason = body.reason
    user.status_version += 1
    audit(
        db,
        actor_type="admin",
        action="user_blocked",
        target_type="user",
        target_id=user.id,
        result="ok",
        reason=body.reason,
        payload={"status_version": user.status_version},
    )
    db.commit()
    db.refresh(user)
    return user
