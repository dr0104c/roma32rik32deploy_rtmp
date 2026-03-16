import secrets
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import PlaybackSession
from .schemas import MediaMTXAuthRequest, MediaMTXEventRequest
from .services.playback import activate_playback_session, end_playback_session, validate_playback_token
from .services.streams import (
    audit,
    get_stream_for_playback,
    get_stream_for_publish,
    record_publish_started,
    record_publish_stopped,
)


router = APIRouter(prefix="/internal/mediamtx", tags=["mediamtx"])


def _extract_path_segment(path: str) -> str:
    normalized = path.strip("/")
    parts = normalized.split("/")
    if len(parts) != 2 or parts[0] != "live" or not parts[1]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid path")
    return parts[1]


def _safe_payload(body: MediaMTXAuthRequest | MediaMTXEventRequest) -> dict:
    payload = body.model_dump()
    if payload.get("query"):
        payload["query"] = "redacted"
    if payload.get("password"):
        payload["password"] = "redacted"
    return payload


def _assert_secret(secret: str) -> None:
    from .config import get_settings

    settings = get_settings()
    if not secrets.compare_digest(secret, settings.internal_api_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal secret")


@router.post("/auth")
def mediamtx_auth(body: MediaMTXAuthRequest, secret: str = Query(default=""), db: Session = Depends(get_db)):
    _assert_secret(secret)
    action = body.action.lower()
    protocol = (body.protocol or "").lower()
    ip = body.ip
    user_agent = body.userAgent

    if action == "publish":
        segment = _extract_path_segment(body.path)
        stream = get_stream_for_publish(db, segment)
        if stream is None or not stream.is_active:
            audit(
                db,
                actor_type="mediamtx",
                action="publish_denied",
                target_type="output_stream",
                result="deny",
                reason="stream_not_found",
                payload=_safe_payload(body),
                ip=ip,
                user_agent=user_agent,
            )
            db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="stream not found")

        record_publish_started(db, stream, source_name=protocol or None, ip=ip, user_agent=user_agent)
        return {"status": "ok"}

    if action not in {"read", "playback"}:
        audit(
            db,
            actor_type="mediamtx",
            action="auth_denied",
            target_type="output_stream",
            result="deny",
            reason="unsupported_action",
            payload=_safe_payload(body),
            ip=ip,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unsupported action")

    if protocol == "rtmp":
        audit(
            db,
            actor_type="mediamtx",
            action="playback_denied",
            target_type="output_stream",
            result="deny",
            reason="rtmp_playback_disabled",
            payload=_safe_payload(body),
            ip=ip,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="rtmp playback disabled")

    if protocol not in {"webrtc", "whep"}:
        audit(
            db,
            actor_type="mediamtx",
            action="playback_denied",
            target_type="output_stream",
            result="deny",
            reason="unsupported_protocol",
            payload=_safe_payload(body),
            ip=ip,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unsupported playback protocol")

    segment = _extract_path_segment(body.path)
    stream = get_stream_for_playback(db, segment)
    if stream is None or not stream.is_active:
        audit(
            db,
            actor_type="mediamtx",
            action="playback_denied",
            target_type="output_stream",
            result="deny",
            reason="stream_not_found",
            payload=_safe_payload(body),
            ip=ip,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="stream not found")

    query = parse_qs(body.query or "", keep_blank_values=False)
    token = query.get("token", [None])[0]
    if not token:
        audit(
            db,
            actor_type="mediamtx",
            action="playback_denied",
            target_type="output_stream",
            target_id=stream.id,
            result="deny",
            reason="missing_playback_token",
            payload=_safe_payload(body),
            ip=ip,
            user_agent=user_agent,
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing playback token")

    expected_path = f"live/{stream.stream_key}"
    try:
        user, validated_stream, session, _ = validate_playback_token(db, token=token, expected_path=expected_path)
    except HTTPException as exc:
        session = db.scalar(select(PlaybackSession).where(PlaybackSession.jti == parse_qs(body.query or "").get("jti", [""])[0]))
        if session is not None:
            end_playback_session(db, session=session, stream=stream, ip=ip, user_agent=user_agent, result="deny", reason=exc.detail)
        else:
            audit(
                db,
                actor_type="mediamtx",
                action="playback_denied",
                target_type="output_stream",
                target_id=stream.id,
                result="deny",
                reason=str(exc.detail),
                ip=ip,
                user_agent=user_agent,
            )
            db.commit()
        raise

    activate_playback_session(db, session=session, user=user, stream=validated_stream, ip=ip, user_agent=user_agent)
    return {"status": "ok"}


@router.post("/publish-stop")
def mediamtx_publish_stop(body: MediaMTXEventRequest, secret: str = Query(default=""), db: Session = Depends(get_db)):
    _assert_secret(secret)
    segment = _extract_path_segment(body.path)
    stream = get_stream_for_publish(db, segment)
    if stream is not None:
        record_publish_stopped(db, stream, ip=body.ip, user_agent=body.userAgent)
    return {"status": "ok"}


@router.post("/read-stop")
def mediamtx_read_stop(body: MediaMTXEventRequest, secret: str = Query(default=""), db: Session = Depends(get_db)):
    _assert_secret(secret)
    segment = _extract_path_segment(body.path)
    stream = get_stream_for_playback(db, segment)
    session = db.scalar(select(PlaybackSession).order_by(desc(PlaybackSession.issued_at)))
    end_playback_session(db, session=session, stream=stream, ip=body.ip, user_agent=body.userAgent)
    return {"status": "ok"}
