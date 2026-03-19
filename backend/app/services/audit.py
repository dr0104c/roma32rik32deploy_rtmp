import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_context import current_admin_actor_id
from ..models import AuditLog, IngestEventLog


logger = logging.getLogger("stream_platform.audit")


def write_audit_log(
    db: Session,
    *,
    actor_type: str,
    action: str,
    target_type: str,
    actor_id: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if actor_type == "admin" and (actor_id is None or actor_id == "bootstrap-admin"):
        actor_id = current_admin_actor_id() or "bootstrap-admin"
    event = {
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "metadata": metadata or {},
    }
    logger.info(json.dumps(event, sort_keys=True, default=str))
    db.add(
        AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata or {},
        )
    )


def write_ingest_event(
    db: Session,
    *,
    ingest_session_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> None:
    event = {
        "ingest_session_id": ingest_session_id,
        "event_type": event_type,
        "payload": payload or {},
    }
    logger.info(json.dumps(event, sort_keys=True, default=str))
    db.add(
        IngestEventLog(
            ingest_session_id=ingest_session_id,
            event_type=event_type,
            payload_json=payload or {},
        )
    )


def list_audit_logs(
    db: Session,
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc())
    if target_type:
        query = query.where(AuditLog.target_type == target_type)
    if target_id:
        query = query.where(AuditLog.target_id == target_id)
    query = query.limit(limit).offset(offset)
    return list(db.scalars(query).all())
