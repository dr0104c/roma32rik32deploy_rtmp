from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import PlaybackTokenRequest, PlaybackTokenResponse
from ..services.playback import issue_playback_token


router = APIRouter(prefix="/api/v1", tags=["playback"])


@router.post("/playback-token", response_model=PlaybackTokenResponse)
def playback_token(body: PlaybackTokenRequest, db: Session = Depends(get_db)) -> PlaybackTokenResponse:
    token, expires_at, playback_url = issue_playback_token(db, user_id=body.user_id, stream_id=body.stream_id)
    return PlaybackTokenResponse(token=token, expires_at=expires_at, playback_url=playback_url)
