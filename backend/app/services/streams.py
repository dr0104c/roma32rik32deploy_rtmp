import re
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, desc, select
from sqlalchemy.orm import Session

from ..auth import generate_stream_key
from ..config import get_settings
from ..models import AuditLog, IngestSession, OutputStream, User, UserStreamGrant


SLUG_RE = re.compile(r"[^a-z0-9]+")
logger = logging.getLogger("stream_platform.audit")


def utcnow() -> datetime:
    return datetime.now(UTC)


def audit(
    db: Session,
    *,
    actor_type: str,
    action: str,
    target_type: str,
    actor_id: int | None = None,
    target_id: int | None = None,
    result: str | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    event = {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "result": result,
        "reason": reason,
        "ip": ip,
        "user_agent": user_agent,
    }
    if payload is not None:
        event["payload"] = payload
    logger.info(json.dumps(event, default=str, sort_keys=True))
    db.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            reason=reason,
            payload_json=payload,
            ip=ip,
            user_agent=user_agent,
        )
    )


def slugify_stream_name(name: str) -> str:
    value = SLUG_RE.sub("-", name.lower()).strip("-")
    return value or "stream"


def unique_path_name(db: Session, name: str) -> str:
    base = slugify_stream_name(name)
    candidate = base
    index = 2
    while db.scalar(select(OutputStream).where(OutputStream.path_name == candidate)) is not None:
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def create_output_stream(db: Session, name: str) -> OutputStream:
    stream_key = generate_stream_key()
    while db.scalar(select(OutputStream).where(OutputStream.stream_key == stream_key)) is not None:
        stream_key = generate_stream_key()

    stream = OutputStream(
        name=name,
        stream_key=stream_key,
        path_name=unique_path_name(db, name),
        is_active=True,
        status="offline",
    )
    db.add(stream)
    db.flush()
    audit(
        db,
        actor_type="admin",
        action="stream_created",
        target_type="output_stream",
        target_id=stream.id,
        result="ok",
        payload={"name": name, "path_name": stream.path_name},
    )
    db.commit()
    db.refresh(stream)
    return stream


def grant_user_stream(db: Session, stream_id: int, user_id: int) -> None:
    stream = db.get(OutputStream, stream_id)
    user = db.get(User, user_id)
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="stream not found")
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    grant = db.scalar(
        select(UserStreamGrant).where(
            UserStreamGrant.user_id == user_id,
            UserStreamGrant.output_stream_id == stream_id,
        )
    )
    if grant is None:
        db.add(UserStreamGrant(user_id=user_id, output_stream_id=stream_id))
        audit(
            db,
            actor_type="admin",
            action="stream_granted",
            target_type="output_stream",
            target_id=stream_id,
            result="ok",
            payload={"user_id": user_id},
        )
        db.commit()


def get_stream_for_publish(db: Session, stream_key: str) -> OutputStream | None:
    return db.scalar(select(OutputStream).where(OutputStream.stream_key == stream_key))


def get_stream_for_playback(db: Session, path_segment: str) -> OutputStream | None:
    return db.scalar(
        select(OutputStream).where(
            (OutputStream.path_name == path_segment) | (OutputStream.stream_key == path_segment)
        )
    )


def get_accessible_stream_query(user_id: int) -> Select[tuple[OutputStream]]:
    return (
        select(OutputStream)
        .join(UserStreamGrant, UserStreamGrant.output_stream_id == OutputStream.id)
        .where(UserStreamGrant.user_id == user_id, OutputStream.is_active.is_(True))
        .order_by(OutputStream.name.asc())
    )


def refresh_stream_lifecycle(db: Session, stream: OutputStream) -> OutputStream:
    settings = get_settings()
    current_time = utcnow()

    latest_ingest = db.scalar(
        select(IngestSession)
        .where(IngestSession.output_stream_id == stream.id)
        .order_by(desc(IngestSession.created_at))
    )

    if latest_ingest and latest_ingest.status == "publishing":
        heartbeat = latest_ingest.last_heartbeat_at or latest_ingest.started_at or latest_ingest.created_at
        if heartbeat and current_time - heartbeat <= timedelta(seconds=settings.stream_stale_after_seconds):
            stream.status = "live"
            stream.last_seen_at = heartbeat
        elif heartbeat and current_time - heartbeat <= timedelta(seconds=settings.stream_end_after_seconds):
            stream.status = "stalled"
            stream.last_seen_at = heartbeat
        else:
            latest_ingest.status = "ended"
            latest_ingest.ended_at = current_time
            stream.status = "ended"
            stream.last_publish_stopped_at = current_time
    elif stream.last_publish_stopped_at is not None:
        if current_time - stream.last_publish_stopped_at > timedelta(seconds=settings.stream_end_after_seconds):
            stream.status = "offline"
        else:
            stream.status = "ended"
    else:
        stream.status = "offline"

    db.flush()
    return stream


def record_publish_started(
    db: Session,
    stream: OutputStream,
    *,
    source_name: str | None,
    ip: str | None,
    user_agent: str | None,
) -> IngestSession:
    current_time = utcnow()
    session = IngestSession(
        output_stream_id=stream.id,
        ingest_key=stream.stream_key,
        source_name=source_name,
        status="publishing",
        started_at=current_time,
        last_heartbeat_at=current_time,
    )
    stream.status = "live"
    stream.last_publish_started_at = current_time
    stream.last_seen_at = current_time
    db.add(session)
    audit(
        db,
        actor_type="mediamtx",
        action="publish_started",
        target_type="output_stream",
        target_id=stream.id,
        result="ok",
        payload={"source_name": source_name},
        ip=ip,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(session)
    return session


def record_publish_stopped(
    db: Session,
    stream: OutputStream,
    *,
    ip: str | None,
    user_agent: str | None,
) -> None:
    current_time = utcnow()
    ingest = db.scalar(
        select(IngestSession)
        .where(IngestSession.output_stream_id == stream.id, IngestSession.status == "publishing")
        .order_by(desc(IngestSession.created_at))
    )
    if ingest is not None:
        ingest.status = "ended"
        ingest.ended_at = current_time
        ingest.last_heartbeat_at = current_time
    stream.status = "ended"
    stream.last_publish_stopped_at = current_time
    stream.last_seen_at = current_time
    audit(
        db,
        actor_type="mediamtx",
        action="publish_stopped",
        target_type="output_stream",
        target_id=stream.id,
        result="ok",
        ip=ip,
        user_agent=user_agent,
    )
    db.commit()
