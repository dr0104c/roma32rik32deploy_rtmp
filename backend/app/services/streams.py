import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import conflict, not_found
from ..models import IngestSession, OutputStream
from .audit import write_audit_log


SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    cleaned = SLUG_RE.sub("-", value.lower()).strip("-")
    return cleaned or "stream"


def ensure_unique_output_stream_fields(
    db: Session,
    *,
    public_name: str | None = None,
    playback_path: str | None = None,
    exclude_output_stream_id: str | None = None,
) -> None:
    if public_name:
        query = select(OutputStream).where(OutputStream.public_name == public_name)
        if exclude_output_stream_id:
            query = query.where(OutputStream.id != exclude_output_stream_id)
        if db.scalar(query) is not None:
            raise conflict("public_name_exists", "public_name already exists")
    if playback_path:
        query = select(OutputStream).where(OutputStream.playback_path == playback_path)
        if exclude_output_stream_id:
            query = query.where(OutputStream.id != exclude_output_stream_id)
        if db.scalar(query) is not None:
            raise conflict("playback_path_exists", "playback_path already exists")


def build_output_stream_payload(output_stream: OutputStream) -> dict:
    return {
        "output_stream_id": output_stream.id,
        "stream_id": output_stream.id,
        "name": output_stream.name,
        "public_name": output_stream.public_name,
        "title": output_stream.title,
        "description": output_stream.description,
        "visibility": output_stream.visibility,
        "playback_path": output_stream.playback_path,
        "playback_name": output_stream.playback_path,
        "is_active": output_stream.is_active,
        "source_ingest_session_id": output_stream.source_ingest_session_id,
        "metadata_json": output_stream.metadata_json or {},
        "created_at": output_stream.created_at,
        "updated_at": output_stream.updated_at,
    }


def build_viewer_output_stream_payload(output_stream: OutputStream) -> dict:
    return {
        "output_stream_id": output_stream.id,
        "stream_id": output_stream.id,
        "name": output_stream.name,
        "public_name": output_stream.public_name,
        "title": output_stream.title,
        "description": output_stream.description,
        "visibility": output_stream.visibility,
        "playback_path": output_stream.playback_path,
        "playback_name": output_stream.playback_path,
        "is_active": output_stream.is_active,
    }


def create_output_stream(
    db: Session,
    *,
    name: str,
    public_name: str,
    title: str,
    description: str | None = None,
    visibility: str = "private",
    playback_path: str | None = None,
    source_ingest_session_id: str | None = None,
    metadata_json: dict | None = None,
) -> OutputStream:
    public_name_slug = slugify(public_name)
    playback_path_slug = slugify(playback_path or public_name_slug)
    ensure_unique_output_stream_fields(db, public_name=public_name_slug, playback_path=playback_path_slug)
    if source_ingest_session_id is not None and db.get(IngestSession, source_ingest_session_id) is None:
        raise not_found("ingest_session_not_found", "ingest session not found")
    output_stream = OutputStream(
        name=name.strip(),
        public_name=public_name_slug,
        title=title.strip(),
        description=description.strip() if description else None,
        visibility=visibility,
        playback_path=playback_path_slug,
        source_ingest_session_id=source_ingest_session_id,
        metadata_json=metadata_json or {},
        is_active=visibility != "disabled",
    )
    db.add(output_stream)
    db.flush()
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="output_stream_created",
        target_type="output_stream",
        target_id=output_stream.id,
        metadata={"public_name": output_stream.public_name, "playback_path": output_stream.playback_path},
    )
    db.commit()
    db.refresh(output_stream)
    return output_stream


def update_output_stream(
    db: Session,
    *,
    output_stream_id: str,
    name: str | None = None,
    public_name: str | None = None,
    title: str | None = None,
    description: str | None = None,
    visibility: str | None = None,
    playback_path: str | None = None,
    is_active: bool | None = None,
    source_ingest_session_id: str | None = None,
    metadata_json: dict | None = None,
) -> OutputStream:
    output_stream = db.get(OutputStream, output_stream_id)
    if output_stream is None:
        raise not_found("output_stream_not_found", "output stream not found")
    public_name_slug = slugify(public_name) if public_name else None
    playback_path_slug = slugify(playback_path) if playback_path else None
    ensure_unique_output_stream_fields(
        db,
        public_name=public_name_slug,
        playback_path=playback_path_slug,
        exclude_output_stream_id=output_stream.id,
    )
    if source_ingest_session_id is not None and source_ingest_session_id != "" and db.get(IngestSession, source_ingest_session_id) is None:
        raise not_found("ingest_session_not_found", "ingest session not found")
    if name is not None:
        output_stream.name = name.strip()
    if public_name_slug is not None:
        output_stream.public_name = public_name_slug
    if title is not None:
        output_stream.title = title.strip()
    if description is not None:
        output_stream.description = description.strip() or None
    if visibility is not None:
        output_stream.visibility = visibility
        if visibility == "disabled":
            output_stream.is_active = False
    if playback_path_slug is not None:
        output_stream.playback_path = playback_path_slug
    if is_active is not None:
        output_stream.is_active = is_active
    if source_ingest_session_id is not None:
        output_stream.source_ingest_session_id = source_ingest_session_id or None
    if metadata_json is not None:
        output_stream.metadata_json = metadata_json
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="output_stream_updated",
        target_type="output_stream",
        target_id=output_stream.id,
        metadata={"public_name": output_stream.public_name, "playback_path": output_stream.playback_path},
    )
    db.commit()
    db.refresh(output_stream)
    return output_stream


def list_output_streams(db: Session) -> list[OutputStream]:
    return list(db.scalars(select(OutputStream).order_by(OutputStream.created_at.desc())).all())


def get_output_stream(db: Session, output_stream_id: str) -> OutputStream:
    output_stream = db.get(OutputStream, output_stream_id)
    if output_stream is None:
        raise not_found("output_stream_not_found", "output stream not found")
    return output_stream


def get_output_stream_by_playback_path(db: Session, playback_path: str) -> OutputStream | None:
    return db.scalar(select(OutputStream).where(OutputStream.playback_path == playback_path, OutputStream.is_active.is_(True)))


def list_output_streams_for_user(db: Session, user_id: str) -> list[OutputStream]:
    from .permissions import user_has_output_stream_access

    streams = list_output_streams(db)
    return [stream for stream in streams if stream.is_active and user_has_output_stream_access(db, user_id, stream.id)]


def create_stream(db: Session, name: str, playback_name: str) -> OutputStream:
    return create_output_stream(
        db,
        name=name,
        public_name=playback_name,
        title=name,
        playback_path=playback_name,
    )


def list_streams(db: Session) -> list[OutputStream]:
    return list_output_streams(db)


def get_stream_by_playback_name(db: Session, playback_name: str) -> OutputStream | None:
    return get_output_stream_by_playback_path(db, playback_name)
