from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_admin_secret
from ..db import get_db
from ..schemas import AdminUserListResponse, ChangeUserStatusResponse, UserResponse
from ..services.moderation import change_user_status, list_users


router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin_secret)])


@router.get("/users", response_model=AdminUserListResponse)
def admin_users(status: str | None = Query(default=None), db: Session = Depends(get_db)) -> AdminUserListResponse:
    users = list_users(db, status_filter=status)
    return AdminUserListResponse(
        users=[UserResponse(user_id=u.id, display_name=u.display_name, client_code=u.client_code, status=u.status) for u in users]
    )


@router.post("/users/{user_id}/approve", response_model=ChangeUserStatusResponse)
def approve(user_id: str, db: Session = Depends(get_db)) -> ChangeUserStatusResponse:
    user = change_user_status(db, user_id, "approved")
    return ChangeUserStatusResponse(user_id=user.id, status=user.status)


@router.post("/users/{user_id}/reject", response_model=ChangeUserStatusResponse)
def reject(user_id: str, db: Session = Depends(get_db)) -> ChangeUserStatusResponse:
    user = change_user_status(db, user_id, "rejected")
    return ChangeUserStatusResponse(user_id=user.id, status=user.status)


@router.post("/users/{user_id}/block", response_model=ChangeUserStatusResponse)
def block(user_id: str, db: Session = Depends(get_db)) -> ChangeUserStatusResponse:
    user = change_user_status(db, user_id, "blocked")
    return ChangeUserStatusResponse(user_id=user.id, status=user.status)
