from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_admin_secret
from ..db import get_db
from ..schemas import CreateStreamRequest, CreateStreamResponse, GrantResponse
from ..services.streams import create_output_stream, grant_user_stream


router = APIRouter(prefix="/api/v1", tags=["streams"], dependencies=[Depends(require_admin_secret)])


@router.post("/streams", response_model=CreateStreamResponse, status_code=201)
def create_stream(body: CreateStreamRequest, db: Session = Depends(get_db)) -> CreateStreamResponse:
    stream = create_output_stream(db, body.name)
    return CreateStreamResponse.model_validate(stream)


@router.post("/streams/{stream_id}/grant-user/{user_id}", response_model=GrantResponse)
def grant_user(stream_id: int, user_id: int, db: Session = Depends(get_db)) -> GrantResponse:
    grant_user_stream(db, stream_id, user_id)
    return GrantResponse(user_id=user_id, stream_id=stream_id, granted=True)
