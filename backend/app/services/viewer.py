from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import forbidden, not_found
from ..models import User
from .streams import build_viewer_output_stream_payload, list_output_streams_for_user


def get_user_by_client_code(db: Session, client_code: str) -> User | None:
    return db.scalar(select(User).where(User.client_code == client_code.strip().upper()))


def get_user(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("user_not_found", "user not found")
    return user


def list_user_stream_payloads(db: Session, user_id: str) -> list[dict]:
    user = get_user(db, user_id)
    if user.status != "approved":
        raise forbidden("user_not_approved", "user is not approved")
    return [build_viewer_output_stream_payload(stream) for stream in list_output_streams_for_user(db, user_id)]


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
