from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..auth import generate_ingest_key
from ..errors import conflict, not_found
from ..models import IngestSession, OutputStream
from .audit import write_audit_log, write_ingest_event
from .mediamtx import delete_playback_alias, sync_playback_alias
from .transcoding import start_transcoder, stop_transcoder


def utcnow() -> datetime:
    return datetime.now(UTC)


def generate_unique_ingest_key(db: Session) -> str:
    ingest_key = generate_ingest_key()
    while db.scalar(select(IngestSession).where(IngestSession.ingest_key == ingest_key)) is not None:
        ingest_key = generate_ingest_key()
    return ingest_key


def serialize_ingest_session(session: IngestSession, *, include_secret: bool = True) -> dict:
    return {
        "ingest_session_id": session.id,
        "source_label": session.source_label,
        "status": session.status,
        "created_at": session.created_at,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "revoked_at": session.revoked_at,
        "last_seen_at": session.last_seen_at,
        "current_output_stream_id": session.current_output_stream_id,
        "metadata_json": session.metadata_json or {},
        "ingest_key": session.ingest_key if include_secret else None,
    }


def create_ingest_session(
    db: Session,
    *,
    current_output_stream_id: str | None = None,
    source_label: str | None = None,
    ingest_key: str | None = None,
    metadata_json: dict | None = None,
) -> IngestSession:
    if current_output_stream_id is not None and db.get(OutputStream, current_output_stream_id) is None:
        raise not_found("output_stream_not_found", "output stream not found")
    if ingest_key is not None and db.scalar(select(IngestSession).where(IngestSession.ingest_key == ingest_key)) is not None:
        raise conflict("ingest_key_exists", "ingest key already exists")
    session = IngestSession(
        ingest_key=ingest_key or generate_unique_ingest_key(db),
        source_label=source_label,
        status="created",
        current_output_stream_id=current_output_stream_id,
        metadata_json=metadata_json or {},
    )
    db.add(session)
    db.flush()
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="ingest_session_created",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"current_output_stream_id": current_output_stream_id, "source_label": source_label},
    )
    write_ingest_event(db, ingest_session_id=session.id, event_type="created", payload={"current_output_stream_id": current_output_stream_id})
    db.commit()
    db.refresh(session)
    return session


def get_ingest_session(db: Session, ingest_session_id: str) -> IngestSession:
    session = db.get(IngestSession, ingest_session_id)
    if session is None:
        raise not_found("ingest_session_not_found", "ingest session not found")
    return session


def list_ingest_sessions(db: Session, *, current_output_stream_id: str | None = None) -> list[IngestSession]:
    query = select(IngestSession).order_by(IngestSession.created_at.desc())
    if current_output_stream_id:
        query = query.where(IngestSession.current_output_stream_id == current_output_stream_id)
    return list(db.scalars(query).all())


def list_live_ingest_sessions(db: Session) -> list[IngestSession]:
    query = select(IngestSession).where(IngestSession.status == "live").order_by(IngestSession.created_at.desc())
    return list(db.scalars(query).all())


def get_ingest_session_by_key(db: Session, ingest_key: str) -> IngestSession | None:
    return db.scalar(select(IngestSession).where(IngestSession.ingest_key == ingest_key).order_by(IngestSession.created_at.desc()))


def bind_ingest_session_to_output_stream(db: Session, *, ingest_session_id: str, output_stream_id: str | None) -> IngestSession:
    session = get_ingest_session(db, ingest_session_id)
    if output_stream_id is not None and db.get(OutputStream, output_stream_id) is None:
        raise not_found("output_stream_not_found", "output stream not found")
    session.current_output_stream_id = output_stream_id
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="ingest_session_bound",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"current_output_stream_id": output_stream_id},
    )
    db.commit()
    db.refresh(session)
    return session


def rotate_ingest_key(db: Session, ingest_session_id: str) -> IngestSession:
    session = get_ingest_session(db, ingest_session_id)
    if session.status == "revoked":
        raise conflict("ingest_session_revoked", "ingest session is revoked")
    session.ingest_key = generate_unique_ingest_key(db)
    session.status = "created"
    session.started_at = None
    session.ended_at = None
    session.last_seen_at = None
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="ingest_key_rotated",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"current_output_stream_id": session.current_output_stream_id},
    )
    write_ingest_event(db, ingest_session_id=session.id, event_type="key_rotated")
    db.commit()
    db.refresh(session)
    return session


def revoke_ingest_session(db: Session, ingest_session_id: str) -> IngestSession:
    session = get_ingest_session(db, ingest_session_id)
    session.status = "revoked"
    session.revoked_at = utcnow()
    session.ended_at = session.ended_at or session.revoked_at
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="ingest_session_revoked",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"current_output_stream_id": session.current_output_stream_id},
    )
    write_ingest_event(db, ingest_session_id=session.id, event_type="revoked")
    db.commit()
    db.refresh(session)
    return session


def resolve_output_stream_for_ingest(db: Session, *, session: IngestSession) -> OutputStream:
    if session.current_output_stream_id:
        output_stream = db.get(OutputStream, session.current_output_stream_id)
        if output_stream is not None:
            return output_stream

    output_stream = db.scalar(select(OutputStream).where(OutputStream.source_ingest_session_id == session.id).order_by(OutputStream.created_at.asc()))
    if output_stream is not None:
        session.current_output_stream_id = output_stream.id
        return output_stream

    auto_name = session.source_label or f"ingest-{session.id[:8]}"
    playback_path = f"out-{session.id[:12]}"
    output_stream = OutputStream(
        name=auto_name,
        public_name=playback_path,
        title=auto_name,
        description="Auto-created from ingest session",
        visibility="private",
        playback_path=playback_path,
        source_ingest_session_id=session.id,
        metadata_json={"auto_created_from_ingest": True},
        is_active=True,
    )
    db.add(output_stream)
    db.flush()
    session.current_output_stream_id = output_stream.id
    write_audit_log(
        db,
        actor_type="media",
        action="output_stream_auto_created",
        target_type="output_stream",
        target_id=output_stream.id,
        metadata={"ingest_session_id": session.id, "playback_path": output_stream.playback_path},
    )
    return output_stream


def mark_ingest_started(db: Session, *, ingest_key: str, source_label: str | None = None) -> tuple[IngestSession, OutputStream]:
    session = get_ingest_session_by_key(db, ingest_key)
    if session is None:
        raise not_found("ingest_session_not_found", "ingest session not found")
    if session.status == "revoked":
        raise conflict("ingest_session_revoked", "ingest session is revoked")
    now = utcnow()
    session.source_label = source_label or session.source_label
    session.status = "live"
    session.started_at = session.started_at or now
    session.ended_at = None
    session.last_seen_at = now
    output_stream = resolve_output_stream_for_ingest(db, session=session)
    output_stream.source_ingest_session_id = session.id
    output_stream.is_active = output_stream.visibility != "disabled"
    write_audit_log(
        db,
        actor_type="media",
        action="ingest_started",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"output_stream_id": output_stream.id, "playback_path": output_stream.playback_path},
    )
    write_ingest_event(
        db,
        ingest_session_id=session.id,
        event_type="started",
        payload={"output_stream_id": output_stream.id, "playback_path": output_stream.playback_path},
    )
    db.commit()
    db.refresh(session)
    db.refresh(output_stream)
    return session, output_stream


def mark_ingest_stopped(db: Session, *, ingest_key: str) -> IngestSession | None:
    session = get_ingest_session_by_key(db, ingest_key)
    if session is None:
        return None
    if session.status != "revoked":
        session.status = "ended"
    session.ended_at = utcnow()
    write_audit_log(
        db,
        actor_type="media",
        action="ingest_stopped",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"current_output_stream_id": session.current_output_stream_id},
    )
    write_ingest_event(
        db,
        ingest_session_id=session.id,
        event_type="stopped",
        payload={"current_output_stream_id": session.current_output_stream_id},
    )
    db.commit()
    db.refresh(session)
    return session


def handle_publish_start(db: Session, *, ingest_key: str, publisher_label: str | None = None) -> tuple[OutputStream | None, IngestSession | None]:
    session, output_stream = mark_ingest_started(db, ingest_key=ingest_key, source_label=publisher_label)
    if output_stream is not None:
        if get_settings().enable_ffmpeg_transcode:
            start_transcoder(playback_path=output_stream.playback_path, ingest_key=ingest_key)
        sync_playback_alias(playback_path=output_stream.playback_path, ingest_key=ingest_key)
    return output_stream, session


def handle_publish_stop(db: Session, *, ingest_key: str) -> IngestSession | None:
    session = get_ingest_session_by_key(db, ingest_key)
    playback_path = None
    if session is not None:
        output_stream = resolve_output_stream_for_ingest(db, session=session)
        playback_path = output_stream.playback_path

    stopped = mark_ingest_stopped(db, ingest_key=ingest_key)
    stop_transcoder(playback_path)
    delete_playback_alias(playback_path)
    return stopped


def reconcile_live_ingests(db: Session) -> None:
    settings = get_settings()
    for session in list_live_ingest_sessions(db):
        output_stream = resolve_output_stream_for_ingest(db, session=session)
        if settings.enable_ffmpeg_transcode:
            start_transcoder(playback_path=output_stream.playback_path, ingest_key=session.ingest_key)
        sync_playback_alias(playback_path=output_stream.playback_path, ingest_key=session.ingest_key)
