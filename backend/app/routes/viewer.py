from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import require_viewer_user
from ..db import get_db
from ..models import User
from ..schemas import ViewerConfigResponse, ViewerMeResponse, ViewerOutputStreamResponse, ViewerSessionRequest, ViewerSessionResponse, ViewerStreamsResponse, ViewerPlaybackSessionResponse
from ..services.playback import create_viewer_token, issue_playback_token_for_output_stream
from ..services.viewer import get_user, get_user_by_client_code, list_user_stream_payloads, viewer_config


router = APIRouter(prefix="/api/v1/viewer", tags=["viewer"])


def to_user_payload(user: User) -> dict[str, str]:
    return {"user_id": user.id, "display_name": user.display_name, "client_code": user.client_code, "status": user.status}


@router.post("/session", response_model=ViewerSessionResponse)
def viewer_session(body: ViewerSessionRequest, db: Session = Depends(get_db)) -> ViewerSessionResponse:
    user = get_user_by_client_code(db, body.client_code)
    if user is None:
        return ViewerSessionResponse(user={"user_id": "", "display_name": "", "client_code": body.client_code, "status": "missing"}, detail="user not found")
    if user.status != "approved":
        return ViewerSessionResponse(user=to_user_payload(user), detail=f"user status is {user.status}")
    token, expires_in = create_viewer_token(user)
    return ViewerSessionResponse(viewer_token=token, expires_in=expires_in, user=to_user_payload(user))


@router.get("/me", response_model=ViewerMeResponse)
def viewer_me(user: User = Depends(require_viewer_user)) -> ViewerMeResponse:
    return ViewerMeResponse(user=to_user_payload(user))


@router.get("/me/{user_id}", response_model=ViewerMeResponse)
def viewer_me_by_id(user_id: str, db: Session = Depends(get_db)) -> ViewerMeResponse:
    user = get_user(db, user_id)
    return ViewerMeResponse(user=to_user_payload(user))


@router.get("/config", response_model=ViewerConfigResponse)
def config() -> ViewerConfigResponse:
    return ViewerConfigResponse(**viewer_config())


@router.get("/streams", response_model=ViewerStreamsResponse)
def viewer_streams(user: User = Depends(require_viewer_user), db: Session = Depends(get_db)) -> ViewerStreamsResponse:
    return ViewerStreamsResponse(streams=[ViewerOutputStreamResponse(**stream) for stream in list_user_stream_payloads(db, user.id)])


@router.get("/streams/{user_id}", response_model=ViewerStreamsResponse)
def viewer_streams_by_user_id(user_id: str, db: Session = Depends(get_db)) -> ViewerStreamsResponse:
    return ViewerStreamsResponse(streams=[ViewerOutputStreamResponse(**stream) for stream in list_user_stream_payloads(db, user_id)])


@router.post("/streams/{stream_id}/playback-session", response_model=ViewerPlaybackSessionResponse)
def viewer_playback_session(stream_id: str, user: User = Depends(require_viewer_user), db: Session = Depends(get_db)) -> ViewerPlaybackSessionResponse:
    token, expires_at, playback_url, output_stream = issue_playback_token_for_output_stream(db, user_id=user.id, output_stream_id=stream_id)
    return ViewerPlaybackSessionResponse(
        playback_token=token,
        expires_at=expires_at,
        output_stream={"id": output_stream.id, "playback_path": output_stream.playback_path},
        stream={"id": output_stream.id, "playback_path": output_stream.playback_path},
        playback={"webrtc_url": playback_url},
    )
