import secrets
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .errors import bad_request, unauthorized
from .schemas import MediaAuthRequest
from .services.audit import write_audit_log
from .services.playback import validate_playback_token_for_path
from .services.streams import get_stream_by_ingest_key, get_stream_by_playback_name, mark_ingest_started, mark_ingest_stopped


router = APIRouter(tags=["media"])


def assert_internal_secret(secret: str) -> None:
    settings = get_settings()
    if not secrets.compare_digest(secret, settings.internal_api_secret):
        raise unauthorized("internal_secret_invalid", "invalid internal secret")


def parse_live_path(path: str) -> str:
    value = path.strip("/")
    parts = value.split("/")
    if len(parts) != 2 or parts[0] != "live" or not parts[1]:
        raise bad_request("path_invalid", "invalid path")
    return parts[1]


def handle_media_auth(body: MediaAuthRequest, db: Session) -> dict[str, str]:
    action = body.action.lower()
    protocol = (body.protocol or "").lower()
    segment = parse_live_path(body.path)

    if action == "publish":
        stream = get_stream_by_ingest_key(db, segment)
        if stream is None:
            write_audit_log(db, actor_type="media", action="publish_denied", target_type="output_stream", metadata={"reason": "ingest_key_invalid", "path": body.path})
            db.commit()
            raise unauthorized("ingest_denied", "ingest denied")
        mark_ingest_started(db, segment)
        return {"status": "ok"}

    if action in {"publish_stop", "unpublish"}:
        mark_ingest_stopped(db, segment)
        return {"status": "ok"}

    if action != "read":
        write_audit_log(db, actor_type="media", action="media_auth_denied", target_type="output_stream", metadata={"reason": "unsupported_action", "action": action})
        db.commit()
        raise unauthorized("media_action_invalid", "unsupported media action")

    if protocol == "rtmp":
        write_audit_log(db, actor_type="media", action="rtmp_playback_denied", target_type="output_stream", metadata={"path": body.path})
        db.commit()
        raise unauthorized("rtmp_playback_disabled", "rtmp playback disabled")

    if protocol not in {"webrtc", "whep"}:
        raise unauthorized("media_protocol_invalid", "unsupported playback protocol")

    stream = get_stream_by_playback_name(db, segment)
    if stream is None:
        raise unauthorized("stream_not_found", "stream not found")

    token = parse_qs(body.query or "").get("token", [None])[0]
    if not token:
        raise unauthorized("playback_token_missing", "missing playback token")

    user, validated_stream = validate_playback_token_for_path(db, token=token, playback_name=segment)
    write_audit_log(
        db,
        actor_type="media",
        actor_id=user.id,
        action="playback_authorized",
        target_type="output_stream",
        target_id=validated_stream.id,
        metadata={"path": body.path, "protocol": protocol},
    )
    db.commit()
    return {"status": "ok"}


@router.post("/internal/media/auth")
def media_auth(body: MediaAuthRequest, secret: str = Query(default=""), db: Session = Depends(get_db)):
    assert_internal_secret(secret)
    return handle_media_auth(body, db)


@router.post("/internal/mediamtx/auth")
def mediamtx_auth_compat(body: MediaAuthRequest, secret: str = Query(default=""), db: Session = Depends(get_db)):
    assert_internal_secret(secret)
    return handle_media_auth(body, db)
