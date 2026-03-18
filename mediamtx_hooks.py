from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .errors import bad_request, unauthorized
from .schemas import MediaAuthRequest, MediaEventRequest
from .services.audit import write_audit_log
from .services.ingest import handle_publish_start, handle_publish_stop
from .services.ingest import get_ingest_session_by_key
from .services.playback import validate_playback_token_for_path
from .services.streams import get_output_stream_by_playback_path


router = APIRouter(tags=["media"])


def assert_internal_secret(secret: str | None) -> None:
    settings = get_settings()
    if not settings.internal_media_secret_required:
        return
    from secrets import compare_digest

    if not secret or not compare_digest(secret, settings.internal_api_secret):
        raise unauthorized("internal_secret_invalid", "invalid internal secret")


def resolve_internal_secret(query_secret: str, header_secret: str) -> str:
    return header_secret or query_secret


def parse_live_path(path: str) -> str:
    value = path.strip("/")
    parts = value.split("/")
    if len(parts) != 2 or parts[0] != "live" or not parts[1]:
        raise bad_request("path_invalid", "invalid path")
    return parts[1]


def is_internal_rtmp_alias_pull(body: MediaAuthRequest, db: Session, segment: str) -> bool:
    if body.action.lower() != "read" or (body.protocol or "").lower() != "rtmp":
        return False
    if body.ip not in {"127.0.0.1", "::1"}:
        return False

    session = get_ingest_session_by_key(db, segment)
    return session is not None and session.current_output_stream_id is not None


def is_internal_transcode_publish(body: MediaAuthRequest, db: Session, segment: str) -> bool:
    if body.action.lower() != "publish" or (body.protocol or "").lower() != "rtmp":
        return False
    if body.ip not in {"127.0.0.1", "::1"}:
        return False

    return get_output_stream_by_playback_path(db, segment) is not None


def handle_media_auth(body: MediaAuthRequest, db: Session) -> dict[str, str]:
    action = body.action.lower()
    protocol = (body.protocol or "").lower()
    segment = parse_live_path(body.path)

    if is_internal_transcode_publish(body, db, segment):
        return {"status": "ok"}

    if action == "publish":
        try:
            output_stream, session = handle_publish_start(db, ingest_key=segment, publisher_label=body.userAgent)
        except HTTPException:
            write_audit_log(
                db,
                actor_type="media",
                action="publish_denied",
                target_type="ingest_session",
                target_id=None,
                metadata={"reason": "ingest_key_invalid_or_revoked", "path": body.path, "protocol": protocol},
            )
            db.commit()
            raise unauthorized("ingest_denied", "ingest denied")
        return {"status": "ok"}

    if action in {"publish_stop", "unpublish"}:
        handle_publish_stop(db, ingest_key=segment)
        return {"status": "ok"}

    if action != "read":
        write_audit_log(db, actor_type="media", action="media_auth_denied", target_type="output_stream", metadata={"reason": "unsupported_action", "action": action})
        db.commit()
        raise unauthorized("media_action_invalid", "unsupported media action")

    if protocol == "rtmp" and is_internal_rtmp_alias_pull(body, db, segment):
        return {"status": "ok"}

    if protocol == "rtmp":
        write_audit_log(db, actor_type="media", action="rtmp_playback_denied", target_type="output_stream", metadata={"path": body.path})
        db.commit()
        raise unauthorized("rtmp_playback_disabled", "rtmp playback disabled")

    if protocol not in {"webrtc", "whep"}:
        raise unauthorized("media_protocol_invalid", "unsupported playback protocol")

    output_stream = get_output_stream_by_playback_path(db, segment)
    if output_stream is None:
        raise unauthorized("output_stream_not_found", "output stream not found")

    token = parse_qs(body.query or "").get("token", [None])[0]
    if not token:
        raise unauthorized("playback_token_missing", "missing playback token")

    user, validated_stream = validate_playback_token_for_path(db, token=token, playback_path=segment)
    write_audit_log(
        db,
        actor_type="media",
        actor_id=user.id,
        action="playback_authorized",
        target_type="output_stream",
        target_id=validated_stream.id,
        metadata={"path": body.path, "protocol": protocol, "playback_path": validated_stream.playback_path},
    )
    db.commit()
    return {"status": "ok"}


@router.post("/internal/media/auth")
def media_auth(
    body: MediaAuthRequest,
    secret: str = Query(default=""),
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
    db: Session = Depends(get_db),
):
    assert_internal_secret(resolve_internal_secret(secret, x_internal_secret))
    return handle_media_auth(body, db)


@router.post("/internal/mediamtx/auth")
def mediamtx_auth_compat(
    body: MediaAuthRequest,
    secret: str = Query(default=""),
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
    db: Session = Depends(get_db),
):
    assert_internal_secret(resolve_internal_secret(secret, x_internal_secret))
    return handle_media_auth(body, db)


@router.post("/internal/media/publish-stop")
def media_publish_stop(
    body: MediaEventRequest,
    secret: str = Query(default=""),
    x_internal_secret: str = Header(default="", alias="X-Internal-Secret"),
    db: Session = Depends(get_db),
):
    assert_internal_secret(resolve_internal_secret(secret, x_internal_secret))
    segment = parse_live_path(body.path)
    session = handle_publish_stop(db, ingest_key=segment)
    if session is None:
        write_audit_log(db, actor_type="media", action="publish_stop_ignored", target_type="ingest_session", metadata={"path": body.path})
        db.commit()
    return {"status": "ok"}
