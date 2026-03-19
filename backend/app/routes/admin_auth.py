from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_admin_bearer
from ..db import get_db
from ..schemas import AdminAuthLoginRequest, AdminAuthLoginResponse, AdminMeResponse
from ..services.admin_auth import authenticate_admin, issue_admin_access_token


router = APIRouter(prefix="/api/v1/admin/auth", tags=["admin-auth"])


@router.post("/login", response_model=AdminAuthLoginResponse)
def admin_login(body: AdminAuthLoginRequest, db: Session = Depends(get_db)) -> AdminAuthLoginResponse:
    admin_user = authenticate_admin(db, body.username, body.password)
    token, expires_in = issue_admin_access_token(db, admin_user)
    return AdminAuthLoginResponse(access_token=token, token_type="bearer", expires_in=expires_in)


@router.get("/me", response_model=AdminMeResponse)
def admin_me(auth=Depends(require_admin_bearer)) -> AdminMeResponse:
    return AdminMeResponse(
        id=auth.admin_user_id or "",
        username=auth.username,
        role=auth.role,
        is_active=auth.admin_user_id is not None,
        auth_mode=auth.auth_mode,
    )
