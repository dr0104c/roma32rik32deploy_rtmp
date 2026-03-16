from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import decode_jwt, generate_jti
from ..config import get_settings
from ..models import OutputStream, PlaybackSession, User, UserStreamGrant
from .streams import audit


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_viewer_token(user: User) -> tuple[str, int]:
    settings = get_settings()
    now = utcnow()
    expires_in = settings.viewer_session_ttl_seconds
    payload = {
        "sub": str(user.id),
        "type": "viewer",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "status_version": user.status_version,
    }
    token = jwt.encode(payload, settings.viewer_session_secret, algorithm="HS256")
    return token, expires_in


def create_playback_session(
    db: Session,
    *,
    user: User,
    stream: OutputStream,
    client_ip: str | None,
    user_agent: str | None,
) -> PlaybackSession:
    settings = get_settings()
    now = utcnow()
    expires_at = now + timedelta(seconds=settings.playback_token_ttl_seconds)
    session = PlaybackSession(
        user_id=user.id,
        output_stream_id=stream.id,
        jti=generate_jti(),
        status="issued",
        client_ip=client_ip,
        user_agent=user_agent,
        issued_at=now,
        expires_at=expires_at,
    )
    db.add(session)
    db.flush()
    audit(
        db,
        actor_type="user",
        actor_id=user.id,
        action="playback_session_issued",
        target_type="output_stream",
        target_id=stream.id,
        result="ok",
        payload={"jti": session.jti, "expires_at": expires_at.isoformat()},
        ip=client_ip,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(session)
    return session


def create_playback_token(*, user: User, stream: OutputStream, session: PlaybackSession, path: str) -> tuple[str, int]:
    settings = get_settings()
    now = utcnow()
    expires_in = settings.playback_token_ttl_seconds
    payload = {
        "sub": str(user.id),
        "stream_id": stream.id,
        "type": "playback",
        "jti": session.jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "path": path,
        "status_version": user.status_version,
    }
    token = jwt.encode(payload, settings.playback_token_secret, algorithm="HS256")
    return token, expires_in


def require_stream_grant(db: Session, *, user_id: int, stream_id: int) -> OutputStream:
    user = db.get(User, user_id)
    stream = db.get(OutputStream, stream_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="stream not found")
    if user.status != "approved":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"user status is {user.status}")

    grant = db.scalar(
        select(UserStreamGrant).where(
            UserStreamGrant.user_id == user_id,
            UserStreamGrant.output_stream_id == stream_id,
        )
    )
    if grant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="stream access is not granted")
    return stream


def validate_playback_token(
    db: Session,
    *,
    token: str,
    expected_path: str,
) -> tuple[User, OutputStream, PlaybackSession, dict[str, Any]]:
    settings = get_settings()
    payload = decode_jwt(token, settings.playback_token_secret)
    if payload.get("type") != "playback":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid playback token type")

    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="viewer not found")
    if user.status != "approved":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"user status is {user.status}")
    if int(payload.get("status_version", 0)) != user.status_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="playback token is stale")

    stream = db.get(OutputStream, int(payload["stream_id"]))
    if stream is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="stream not found")

    if payload.get("path") != expected_path:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="playback path mismatch")

    session = db.scalar(select(PlaybackSession).where(PlaybackSession.jti == payload["jti"]))
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="playback session not found")
    if session.status in {"revoked", "denied", "expired"}:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"playback session is {session.status}")
    if session.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="playback session revoked")
    if session.expires_at <= utcnow():
        session.status = "expired"
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="playback session expired")

    grant = db.scalar(
        select(UserStreamGrant).where(
            UserStreamGrant.user_id == user.id,
            UserStreamGrant.output_stream_id == stream.id,
        )
    )
    if grant is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="stream access is not granted")

    return user, stream, session, payload


def activate_playback_session(
    db: Session,
    *,
    session: PlaybackSession,
    user: User,
    stream: OutputStream,
    ip: str | None,
    user_agent: str | None,
) -> None:
    now = utcnow()
    if session.status != "active":
        session.status = "active"
        session.activated_at = now
    audit(
        db,
        actor_type="mediamtx",
        actor_id=user.id,
        action="playback_started",
        target_type="output_stream",
        target_id=stream.id,
        result="ok",
        payload={"jti": session.jti},
        ip=ip,
        user_agent=user_agent,
    )
    db.commit()


def end_playback_session(
    db: Session,
    *,
    session: PlaybackSession | None,
    stream: OutputStream | None,
    ip: str | None,
    user_agent: str | None,
    result: str = "ok",
    reason: str | None = None,
) -> None:
    now = utcnow()
    if session is not None and session.status not in {"ended", "revoked", "expired"}:
        session.status = "ended"
        session.ended_at = now
    audit(
        db,
        actor_type="mediamtx",
        actor_id=session.user_id if session else None,
        action="playback_stopped",
        target_type="output_stream",
        target_id=stream.id if stream else None,
        result=result,
        reason=reason,
        payload={"jti": session.jti} if session else None,
        ip=ip,
        user_agent=user_agent,
    )
    db.commit()
