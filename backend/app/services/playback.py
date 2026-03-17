from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import decode_jwt, generate_jti
from ..config import get_settings
from ..errors import bad_request, forbidden, not_found, unauthorized
from ..models import IngestSession, OutputStream, User
from .audit import write_audit_log
from .permissions import assert_user_has_stream_access
from .streams import get_output_stream_by_playback_path


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


def resolve_output_stream_for_playback_request(
    db: Session,
    *,
    output_stream_id: str | None = None,
    playback_path: str | None = None,
) -> OutputStream:
    if output_stream_id:
        output_stream = db.get(OutputStream, output_stream_id)
        if output_stream is None:
            raise not_found("output_stream_not_found", "output stream not found")
        return output_stream
    if playback_path:
        ingest_session = db.scalar(select(IngestSession).where(IngestSession.ingest_key == playback_path))
        if ingest_session is not None:
            raise bad_request(
                "ingest_key_not_playback_identifier",
                "ingest key cannot be used as output stream identifier",
            )
        output_stream = get_output_stream_by_playback_path(db, playback_path)
        if output_stream is None:
            raise not_found("output_stream_not_found", "output stream not found")
        return output_stream
    raise bad_request("output_stream_missing", "output_stream_id or playback_path is required")


def issue_playback_token_for_output_stream(
    db: Session,
    *,
    user_id: str,
    output_stream_id: str | None = None,
    playback_path: str | None = None,
) -> tuple[str, datetime, str, OutputStream]:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("user_not_found", "user not found")
    if user.status != "approved":
        raise forbidden("user_not_approved", "user is not approved")

    output_stream = resolve_output_stream_for_playback_request(db, output_stream_id=output_stream_id, playback_path=playback_path)
    assert_user_has_stream_access(db, user_id, output_stream.id)

    settings = get_settings()
    now = utcnow()
    expires_at = now + timedelta(seconds=settings.playback_token_ttl_seconds)
    jti = generate_jti()
    payload = {
        "sub": user.id,
        "sid": output_stream.id,
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
        target_id=output_stream.id,
        metadata={"jti": jti, "expires_at": expires_at.isoformat(), "playback_path": output_stream.playback_path},
    )
    db.commit()
    return token, expires_at, f"{settings.webrtc_public_base_url}/live/{output_stream.playback_path}/whep?token={token}", output_stream


def validate_playback_token_for_path(db: Session, *, token: str, playback_path: str) -> tuple[User, OutputStream]:
    settings = get_settings()
    payload = decode_jwt(token, settings.playback_token_secret)
    if payload.get("scope") != "playback":
        raise unauthorized("playback_scope_invalid", "invalid playback scope")
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise unauthorized("user_not_found", "user not found")
    if user.status != "approved":
        raise forbidden("user_not_approved", "user is not approved")

    output_stream = db.get(OutputStream, payload.get("sid"))
    if output_stream is None:
        raise unauthorized("output_stream_not_found", "output stream not found")
    if output_stream.playback_path != playback_path:
        raise unauthorized("playback_path_mismatch", "requested output stream does not match token")

    assert_user_has_stream_access(db, user.id, output_stream.id)
    return user, output_stream
