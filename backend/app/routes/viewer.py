from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_viewer_user
from ..db import get_db
from ..models import User
from ..schemas import (
    PlaybackSessionTokenResponse,
    UserSummary,
    ViewerConfigResponse,
    ViewerMeResponse,
    ViewerSessionRequest,
    ViewerSessionResponse,
    ViewerStreamsResponse,
)
from ..services.playback import create_playback_session, create_playback_token, create_viewer_token, require_stream_grant
from ..services.streams import audit
from ..services.viewer import get_viewer_stream, list_viewer_streams, viewer_config


router = APIRouter(prefix="/api/v1/viewer", tags=["viewer"])


@router.post("/session", response_model=ViewerSessionResponse)
def create_viewer_session(body: ViewerSessionRequest, request: Request, db: Session = Depends(get_db)) -> ViewerSessionResponse:
    user = db.scalar(select(User).where(User.client_code == body.client_code.strip().upper()))
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if user.status != "approved":
        audit(
            db,
            actor_type="viewer",
            actor_id=user.id,
            action="viewer_session_denied",
            target_type="user",
            target_id=user.id,
            result="deny",
            reason=user.status,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.commit()
        return ViewerSessionResponse(
            user=UserSummary.model_validate(user),
            detail=user.blocked_reason or f"user status is {user.status}",
        )

    viewer_token, expires_in = create_viewer_token(user)
    audit(
        db,
        actor_type="viewer",
        actor_id=user.id,
        action="viewer_session_issued",
        target_type="user",
        target_id=user.id,
        result="ok",
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.commit()
    return ViewerSessionResponse(
        viewer_token=viewer_token,
        expires_in=expires_in,
        user=UserSummary.model_validate(user),
    )


@router.get("/me", response_model=ViewerMeResponse)
def viewer_me(user: User = Depends(require_viewer_user)) -> ViewerMeResponse:
    return ViewerMeResponse(user=UserSummary.model_validate(user))


@router.get("/config", response_model=ViewerConfigResponse)
def config(_: User = Depends(require_viewer_user)) -> ViewerConfigResponse:
    return ViewerConfigResponse(**viewer_config())


@router.get("/streams", response_model=ViewerStreamsResponse)
def streams(user: User = Depends(require_viewer_user), db: Session = Depends(get_db)) -> ViewerStreamsResponse:
    items = list_viewer_streams(db, user_id=user.id)
    db.commit()
    return ViewerStreamsResponse(streams=items)


@router.get("/streams/{stream_id}")
def stream_detail(stream_id: int, user: User = Depends(require_viewer_user), db: Session = Depends(get_db)):
    detail = get_viewer_stream(db, user_id=user.id, stream_id=stream_id)
    return detail


@router.post("/streams/{stream_id}/playback-session", response_model=PlaybackSessionTokenResponse)
def playback_session(
    stream_id: int,
    request: Request,
    user: User = Depends(require_viewer_user),
    db: Session = Depends(get_db),
) -> PlaybackSessionTokenResponse:
    stream = require_stream_grant(db, user_id=user.id, stream_id=stream_id)
    media_path = f"live/{stream.stream_key}"
    session = create_playback_session(
        db,
        user=user,
        stream=stream,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    token, expires_in = create_playback_token(user=user, stream=stream, session=session, path=media_path)
    return PlaybackSessionTokenResponse(
        playback_token=token,
        expires_in=expires_in,
        stream={"id": stream.id, "name": stream.name, "path_name": stream.path_name},
        playback={"webrtc_url": f"{viewer_config()['webrtc_base_url']}/{media_path}/whep?token={token}"},
    )
