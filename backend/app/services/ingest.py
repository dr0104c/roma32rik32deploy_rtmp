from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import generate_ingest_key
from ..errors import bad_request, conflict, not_found
from ..models import IngestSession, OutputStream
from .audit import write_audit_log


VALID_INGEST_TRANSITIONS = {
    "created": {"connecting", "live", "revoked", "error", "offline"},
    "connecting": {"live", "offline", "revoked", "error"},
    "live": {"offline", "revoked", "error"},
    "offline": {"connecting", "live", "revoked", "error"},
    "error": {"connecting", "live", "offline", "revoked"},
    "revoked": set(),
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def generate_unique_ingest_key(db: Session) -> str:
    ingest_key = generate_ingest_key()
    while db.scalar(select(IngestSession).where(IngestSession.ingest_key == ingest_key)) is not None:
        ingest_key = generate_ingest_key()
    return ingest_key


def create_ingest_session(
    db: Session,
    *,
    output_stream_id: str,
    publisher_label: str | None = None,
    ingest_key: str | None = None,
) -> IngestSession:
    stream = db.get(OutputStream, output_stream_id)
    if stream is None:
        raise not_found("stream_not_found", "stream not found")
    if ingest_key is not None and db.scalar(select(IngestSession).where(IngestSession.ingest_key == ingest_key)) is not None:
        raise conflict("ingest_key_exists", "ingest key already exists")
    session = IngestSession(
        output_stream_id=stream.id,
        ingest_key=ingest_key or generate_unique_ingest_key(db),
        status="created",
        publisher_label=publisher_label,
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
        metadata={"output_stream_id": output_stream_id, "publisher_label": publisher_label, "ingest_key_override": ingest_key is not None},
    )
    db.commit()
    db.refresh(session)
    return session


def list_ingest_sessions(db: Session, *, output_stream_id: str | None = None) -> list[IngestSession]:
    query = select(IngestSession).order_by(IngestSession.created_at.desc())
    if output_stream_id:
        query = query.where(IngestSession.output_stream_id == output_stream_id)
    return list(db.scalars(query).all())


def get_ingest_session_by_key(db: Session, ingest_key: str) -> IngestSession | None:
    return db.scalar(select(IngestSession).where(IngestSession.ingest_key == ingest_key).order_by(IngestSession.created_at.desc()))


def require_valid_transition(current_status: str, next_status: str) -> None:
    if next_status not in VALID_INGEST_TRANSITIONS.get(current_status, set()):
        raise bad_request("ingest_transition_invalid", f"cannot transition ingest session from {current_status} to {next_status}")


def transition_ingest_session(
    db: Session,
    *,
    session: IngestSession,
    next_status: str,
    publisher_label: str | None = None,
    error_message: str | None = None,
) -> IngestSession:
    if session.status != next_status:
        require_valid_transition(session.status, next_status)
    now = utcnow()
    if publisher_label is not None:
        session.publisher_label = publisher_label
    if next_status in {"connecting", "live"}:
        session.last_seen_at = now
    if next_status == "live" and session.last_publish_started_at is None:
        session.last_publish_started_at = now
    if next_status in {"offline", "revoked"}:
        session.last_publish_stopped_at = now
    if next_status == "error":
        session.last_error = error_message or "unknown error"
    session.status = next_status
    db.flush()
    return session


def rotate_ingest_key(db: Session, ingest_session_id: str) -> IngestSession:
    session = db.get(IngestSession, ingest_session_id)
    if session is None:
        raise not_found("ingest_session_not_found", "ingest session not found")
    if session.status == "revoked":
        raise conflict("ingest_session_revoked", "ingest session is revoked")
    session.ingest_key = generate_unique_ingest_key(db)
    session.status = "created"
    session.last_error = None
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="ingest_key_rotated",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"output_stream_id": session.output_stream_id},
    )
    db.commit()
    db.refresh(session)
    return session


def revoke_ingest_session(db: Session, ingest_session_id: str) -> IngestSession:
    session = db.get(IngestSession, ingest_session_id)
    if session is None:
        raise not_found("ingest_session_not_found", "ingest session not found")
    if session.status != "revoked":
        transition_ingest_session(db, session=session, next_status="revoked")
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="ingest_session_revoked",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"output_stream_id": session.output_stream_id},
    )
    db.commit()
    db.refresh(session)
    return session


def resolve_publish_target(
    db: Session,
    *,
    ingest_key: str,
    ingest_auth_mode: str,
) -> tuple[OutputStream | None, IngestSession | None]:
    if ingest_auth_mode == "keyed":
        session = get_ingest_session_by_key(db, ingest_key)
        if session is None or session.status == "revoked":
            return None, session
        stream = db.get(OutputStream, session.output_stream_id) if session.output_stream_id else None
        return stream, session

    stream = db.scalar(select(OutputStream).where(OutputStream.ingest_key == ingest_key, OutputStream.is_active.is_(True)))
    if stream is not None:
        return stream, None
    session = get_ingest_session_by_key(db, ingest_key)
    if session is None or session.status == "revoked":
        return None, session
    stream = db.get(OutputStream, session.output_stream_id) if session.output_stream_id else None
    return stream, session


def handle_publish_start(
    db: Session,
    *,
    ingest_key: str,
    publisher_label: str | None = None,
) -> tuple[OutputStream | None, IngestSession | None]:
    from ..config import get_settings

    stream, session = resolve_publish_target(db, ingest_key=ingest_key, ingest_auth_mode=get_settings().ingest_auth_mode)
    if stream is None:
        return None, session
    if session is None:
        session = db.scalar(
            select(IngestSession)
            .where(IngestSession.output_stream_id == stream.id, IngestSession.ingest_key == ingest_key)
            .order_by(IngestSession.created_at.desc())
        )
        if session is None:
            session = IngestSession(
                output_stream_id=stream.id,
                ingest_key=ingest_key,
                status="created",
                publisher_label=publisher_label,
            )
            db.add(session)
            db.flush()

    if session.status == "live":
        session.last_seen_at = utcnow()
    else:
        if session.status == "created":
            transition_ingest_session(db, session=session, next_status="connecting", publisher_label=publisher_label)
        transition_ingest_session(db, session=session, next_status="live", publisher_label=publisher_label)
    write_audit_log(
        db,
        actor_type="media",
        action="ingest_started",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"output_stream_id": stream.id, "publisher_label": publisher_label},
    )
    db.commit()
    db.refresh(session)
    return stream, session


def handle_publish_stop(db: Session, *, ingest_key: str) -> IngestSession | None:
    session = get_ingest_session_by_key(db, ingest_key)
    if session is None:
        return None
    if session.status == "offline":
        session.last_publish_stopped_at = session.last_publish_stopped_at or utcnow()
    elif session.status != "revoked":
        transition_ingest_session(db, session=session, next_status="offline")
    write_audit_log(
        db,
        actor_type="media",
        action="ingest_stopped",
        target_type="ingest_session",
        target_id=session.id,
        metadata={"output_stream_id": session.output_stream_id},
    )
    db.commit()
    db.refresh(session)
    return session


def get_latest_ingest_event_time(db: Session) -> datetime | None:
    session = db.scalar(select(IngestSession).order_by(IngestSession.updated_at.desc()))
    return session.updated_at if session else None


def count_live_ingest_sessions(db: Session) -> int:
    return len(list(db.scalars(select(IngestSession).where(IngestSession.status == "live")).all()))
