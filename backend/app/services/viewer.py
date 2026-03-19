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
    expected_ingest_notes = (
        "Synthetic verification publishes H.264 video + AAC audio over RTMP; ffmpeg transcode is enabled for WebRTC/WHEP playback, "
        "but browser/device rendering and ICE on real Android are not verified automatically."
        if settings.enable_ffmpeg_transcode
        else "Synthetic verification publishes H.264 video + AAC audio over RTMP; transcoding is disabled, so Android playback "
        "compatibility depends on source codecs and is not proven by automated checks."
    )
    return {
        "public_base_url": settings.public_base_url,
        "webrtc_base_url": settings.webrtc_public_base_url,
        "stun_urls": [item for item in settings.stun_urls.split(",") if item],
        "turn_urls": [item for item in settings.turn_urls.split(",") if item],
        "turn_realm": settings.turn_realm,
        "stream_list_poll_interval": settings.stream_list_poll_interval_seconds,
        "playback_token_ttl": settings.playback_token_ttl_seconds,
        "ingest_transport": "RTMP",
        "ingest_container": "FLV",
        "playback_transport": "WebRTC/WHEP",
        "rtmp_playback_enabled": False,
        "output_stream_acl_scope": "output_stream",
        "playback_token_lookup_fields": ["output_stream_id", "playback_path"],
        "viewer_must_not_use_fields": ["ingest_key"],
        "browser_rendering_verified": False,
        "real_android_ice_verified": False,
        "transcoding_enabled": settings.enable_ffmpeg_transcode,
        "transcoding_verified": False,
        "expected_ingest_video_codec": "H264",
        "expected_ingest_audio_codec": "AAC",
        "expected_ingest_notes": expected_ingest_notes,
    }
