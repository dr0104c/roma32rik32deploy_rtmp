from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy.orm import Session

from ..auth import decode_jwt, generate_jti
from ..config import get_settings
from ..errors import forbidden, not_found, unauthorized
from ..models import OutputStream, User
from .audit import write_audit_log
from .permissions import assert_user_has_stream_access
from .streams import get_stream_by_playback_name


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_viewer_token(user: User) -> tuple[str, int]:
    settings = get_settings()
    expires_in = settings.viewer_session_ttl_seconds
    now = utcnow()
    payload = {
        "sub": user.id,
        "scope": "viewer",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, settings.viewer_session_secret, algorithm="HS256")
    return token, expires_in


def issue_playback_token(db: Session, *, user_id: str, stream_id: str) -> tuple[str, datetime, str]:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("user_not_found", "user not found")
    if user.status != "approved":
        raise forbidden("user_not_approved", "user is not approved")

    stream = db.get(OutputStream, stream_id)
    if stream is None:
        raise not_found("stream_not_found", "stream not found")

    assert_user_has_stream_access(db, user_id, stream_id)

    settings = get_settings()
    now = utcnow()
    expires_at = now + timedelta(seconds=settings.playback_token_ttl_seconds)
    jti = generate_jti()
    payload = {
        "sub": user.id,
        "sid": stream.id,
        "scope": "playback",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.playback_token_secret, algorithm="HS256")
    write_audit_log(
        db,
        actor_type="backend",
        actor_id=user.id,
        action="playback_token_issued",
        target_type="output_stream",
        target_id=stream.id,
        metadata={"jti": jti, "expires_at": expires_at.isoformat()},
    )
    db.commit()
    return token, expires_at, f"{settings.webrtc_public_base_url}/live/{stream.playback_name}/whep?token={token}"


def validate_playback_token_for_path(db: Session, *, token: str, playback_name: str) -> tuple[User, OutputStream]:
    settings = get_settings()
    payload = decode_jwt(token, settings.playback_token_secret)
    if payload.get("scope") != "playback":
        raise unauthorized("playback_scope_invalid", "invalid playback scope")

    user = db.get(User, payload.get("sub"))
    if user is None:
        raise unauthorized("user_not_found", "user not found")
    if user.status != "approved":
        raise forbidden("user_not_approved", "user is not approved")

    stream = db.get(OutputStream, payload.get("sid"))
    if stream is None:
        raise unauthorized("stream_not_found", "stream not found")
    if get_stream_by_playback_name(db, playback_name) is None or stream.playback_name != playback_name:
        raise unauthorized("playback_path_mismatch", "requested stream does not match token")

    assert_user_has_stream_access(db, user.id, stream.id)
    return user, stream
