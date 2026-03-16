from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import OutputStream, User
from ..schemas import StreamDetail, StreamSummary
from .streams import get_accessible_stream_query, refresh_stream_lifecycle


def viewer_session_response(user: User) -> tuple[str | None, int | None, str | None]:
    if user.status == "approved":
        return None, None, None
    if user.status == "pending":
        return None, None, "pending approval"
    if user.status == "rejected":
        return None, None, "rejected"
    return None, None, user.blocked_reason or "blocked"


def list_viewer_streams(db: Session, *, user_id: int) -> list[StreamSummary]:
    streams = db.scalars(get_accessible_stream_query(user_id)).all()
    return [stream_to_summary(db, stream) for stream in streams]


def get_viewer_stream(db: Session, *, user_id: int, stream_id: int) -> StreamDetail:
    stream = db.get(OutputStream, stream_id)
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="stream not found")
    accessible_ids = {item.id for item in db.scalars(get_accessible_stream_query(user_id)).all()}
    if stream.id not in accessible_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="stream access is not granted")
    stream = refresh_stream_lifecycle(db, stream)
    db.commit()
    return StreamDetail(
        id=stream.id,
        name=stream.name,
        path_name=stream.path_name,
        status=stream.status,
        is_live=stream.status == "live",
        is_active=stream.is_active,
        last_publish_started_at=stream.last_publish_started_at,
        last_publish_stopped_at=stream.last_publish_stopped_at,
    )


def stream_to_summary(db: Session, stream: OutputStream) -> StreamSummary:
    stream = refresh_stream_lifecycle(db, stream)
    return StreamSummary(
        id=stream.id,
        name=stream.name,
        path_name=stream.path_name,
        status=stream.status,
        is_live=stream.status == "live",
        last_publish_started_at=stream.last_publish_started_at,
        last_publish_stopped_at=stream.last_publish_stopped_at,
    )


def viewer_config() -> dict:
    settings = get_settings()
    return {
        "public_base_url": settings.public_base_url,
        "webrtc_base_url": settings.webrtc_public_base_url,
        "stun_urls": [item for item in settings.stun_urls.split(",") if item],
        "turn_urls": [item for item in settings.turn_urls.split(",") if item],
        "turn_realm": settings.turn_realm,
        "stream_list_poll_interval": settings.stream_list_poll_interval_seconds,
        "playback_token_ttl": settings.playback_token_ttl_seconds,
    }
