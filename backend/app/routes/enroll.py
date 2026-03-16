from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from ..auth import generate_client_code
from ..db import get_db
from ..models import User
from ..schemas import EnrollRequest, EnrollResponse
from ..services.streams import audit


router = APIRouter(prefix="/api/v1", tags=["enroll"])


@router.post("/enroll", response_model=EnrollResponse, status_code=201)
def enroll(body: EnrollRequest, db: Session = Depends(get_db)) -> User:
    client_code = generate_client_code()
    while db.scalar(select(User).where(User.client_code == client_code)) is not None:
        client_code = generate_client_code()

    user = User(name=body.name, client_code=client_code, status="pending")
    db.add(user)
    db.flush()
    audit(
        db,
        actor_type="system",
        action="user_enrolled",
        target_type="user",
        target_id=user.id,
        result="ok",
        payload={"name": body.name, "client_code": client_code},
    )
    db.commit()
    db.refresh(user)
    return user
