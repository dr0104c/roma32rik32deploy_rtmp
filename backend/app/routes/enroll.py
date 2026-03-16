from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import EnrollRequest, UserResponse
from ..services.enrollment import enroll_user
from ..services.viewer import get_user


router = APIRouter(prefix="/api/v1", tags=["enroll"])


@router.post("/enroll", response_model=UserResponse, status_code=201)
def enroll(body: EnrollRequest, db: Session = Depends(get_db)) -> UserResponse:
    user = enroll_user(db, body.display_name)
    return UserResponse(user_id=user.id, display_name=user.display_name, client_code=user.client_code, status=user.status)


@router.get("/me/{user_id}", response_model=UserResponse)
def me(user_id: str, db: Session = Depends(get_db)) -> UserResponse:
    user = get_user(db, user_id)
    return UserResponse(user_id=user.id, display_name=user.display_name, client_code=user.client_code, status=user.status)
