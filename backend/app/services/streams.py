import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import generate_ingest_key
from ..errors import conflict, not_found
from ..models import IngestSession, OutputStream
from .audit import write_audit_log


SLUG_RE = re.compile(r"[^a-z0-9]+")


def utcnow() -> datetime:
    return datetime.now(UTC)


def slugify(value: str) -> str:
    cleaned = SLUG_RE.sub("-", value.lower()).strip("-")
    return cleaned or "stream"


def unique_playback_name(db: Session, playback_name: str) -> str:
    candidate = slugify(playback_name)
    if db.scalar(select(OutputStream).where(OutputStream.playback_name == candidate)) is not None:
        raise conflict("playback_name_exists", "playback_name already exists")
    return candidate


def create_stream(db: Session, name: str, playback_name: str) -> OutputStream:
    candidate = unique_playback_name(db, playback_name)
    ingest_key = generate_ingest_key()
    while db.scalar(select(OutputStream).where(OutputStream.ingest_key == ingest_key)) is not None:
        ingest_key = generate_ingest_key()
    stream = OutputStream(name=name.strip(), playback_name=candidate, ingest_key=ingest_key, is_active=True)
    db.add(stream)
    db.flush()
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="stream_created",
        target_type="output_stream",
        target_id=stream.id,
        metadata={"name": stream.name, "playback_name": stream.playback_name},
    )
    db.commit()
    db.refresh(stream)
    return stream


def list_streams(db: Session) -> list[OutputStream]:
    return list(db.scalars(select(OutputStream).order_by(OutputStream.created_at.desc())).all())


def get_stream_by_ingest_key(db: Session, ingest_key: str) -> OutputStream | None:
    return db.scalar(select(OutputStream).where(OutputStream.ingest_key == ingest_key, OutputStream.is_active.is_(True)))


def get_stream_by_playback_name(db: Session, playback_name: str) -> OutputStream | None:
    return db.scalar(select(OutputStream).where(OutputStream.playback_name == playback_name, OutputStream.is_active.is_(True)))


def mark_ingest_started(db: Session, ingest_key: str) -> OutputStream:
    stream = get_stream_by_ingest_key(db, ingest_key)
    if stream is None:
        raise not_found("stream_not_found", "stream not found")
    now = utcnow()
    session = IngestSession(output_stream_id=stream.id, ingest_key=ingest_key, status="live", last_seen_at=now)
    db.add(session)
    write_audit_log(
        db,
        actor_type="media",
        action="ingest_started",
        target_type="output_stream",
        target_id=stream.id,
        metadata={"ingest_key": ingest_key},
    )
    db.commit()
    db.refresh(stream)
    return stream


def mark_ingest_stopped(db: Session, ingest_key: str) -> None:
    session = db.scalar(
        select(IngestSession).where(IngestSession.ingest_key == ingest_key).order_by(IngestSession.updated_at.desc())
    )
    if session is not None:
        session.status = "offline"
        session.last_seen_at = utcnow()
        write_audit_log(
            db,
            actor_type="media",
            action="ingest_stopped",
            target_type="output_stream",
            target_id=session.output_stream_id,
            metadata={"ingest_key": ingest_key},
        )
        db.commit()


def list_streams_for_user(db: Session, user_id: str) -> list[OutputStream]:
    from .permissions import user_has_stream_access

    streams = list_streams(db)
    return [stream for stream in streams if user_has_stream_access(db, user_id, stream.id)]
