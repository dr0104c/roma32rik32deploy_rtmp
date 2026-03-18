from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import PlaybackTokenRequest, PlaybackTokenResponse
from ..services.playback import issue_playback_token_for_output_stream


router = APIRouter(prefix="/api/v1", tags=["playback"])


@router.post("/playback-token", response_model=PlaybackTokenResponse)
def playback_token(body: PlaybackTokenRequest, db: Session = Depends(get_db)) -> PlaybackTokenResponse:
    token, expires_at, playback_url, output_stream = issue_playback_token_for_output_stream(
        db,
        user_id=body.user_id,
        output_stream_id=body.output_stream_id or body.stream_id,
        playback_path=body.playback_path,
    )
    return PlaybackTokenResponse(
        token=token,
        expires_at=expires_at,
        playback_url=playback_url,
        output_stream_id=output_stream.id,
        playback_path=output_stream.playback_path,
    )
