from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import PlaybackTokenRequest, PlaybackTokenResponse
from ..services.playback import create_playback_session, create_playback_token, require_stream_grant


router = APIRouter(prefix="/api/v1", tags=["playback"])


@router.post("/playback-token", response_model=PlaybackTokenResponse)
def create_token(
    body: PlaybackTokenRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> PlaybackTokenResponse:
    stream = require_stream_grant(db, user_id=body.user_id, stream_id=body.stream_id)
    user = db.get(User, body.user_id)
    assert user is not None
    media_path = f"live/{stream.stream_key}"
    session = create_playback_session(
        db,
        user=user,
        stream=stream,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    token, expires_in = create_playback_token(user=user, stream=stream, session=session, path=media_path)
    return PlaybackTokenResponse(token=token, expires_in=expires_in)
