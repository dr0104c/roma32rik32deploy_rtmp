from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_admin_secret
from ..db import get_db
from ..schemas import (
    AdminUserListResponse,
    ChangeUserStatusResponse,
    CreateIngestSessionRequest,
    IngestSessionListResponse,
    IngestSessionResponse,
    RevokeIngestSessionResponse,
    RotateIngestKeyResponse,
    UserResponse,
)
from ..services.ingest import create_ingest_session, list_ingest_sessions, revoke_ingest_session, rotate_ingest_key
from ..services.moderation import change_user_status, list_users


router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin_secret)])


@router.get("/users", response_model=AdminUserListResponse)
def admin_users(status: str | None = Query(default=None), db: Session = Depends(get_db)) -> AdminUserListResponse:
    users = list_users(db, status_filter=status)
    return AdminUserListResponse(
        users=[UserResponse(user_id=u.id, display_name=u.display_name, client_code=u.client_code, status=u.status) for u in users]
    )


@router.post("/users/{user_id}/approve", response_model=ChangeUserStatusResponse)
def approve(user_id: str, db: Session = Depends(get_db)) -> ChangeUserStatusResponse:
    user = change_user_status(db, user_id, "approved")
    return ChangeUserStatusResponse(user_id=user.id, status=user.status)


@router.post("/users/{user_id}/reject", response_model=ChangeUserStatusResponse)
def reject(user_id: str, db: Session = Depends(get_db)) -> ChangeUserStatusResponse:
    user = change_user_status(db, user_id, "rejected")
    return ChangeUserStatusResponse(user_id=user.id, status=user.status)


@router.post("/users/{user_id}/block", response_model=ChangeUserStatusResponse)
def block(user_id: str, db: Session = Depends(get_db)) -> ChangeUserStatusResponse:
    user = change_user_status(db, user_id, "blocked")
    return ChangeUserStatusResponse(user_id=user.id, status=user.status)


@router.post("/ingest-sessions", response_model=IngestSessionResponse, status_code=201)
def create_ingest(body: CreateIngestSessionRequest, db: Session = Depends(get_db)) -> IngestSessionResponse:
    session = create_ingest_session(db, output_stream_id=body.output_stream_id, publisher_label=body.publisher_label)
    return IngestSessionResponse(
        ingest_session_id=session.id,
        output_stream_id=session.output_stream_id,
        ingest_key=session.ingest_key,
        status=session.status,
        publisher_label=session.publisher_label,
        last_seen_at=session.last_seen_at,
        last_publish_started_at=session.last_publish_started_at,
        last_publish_stopped_at=session.last_publish_stopped_at,
        last_error=session.last_error,
    )


@router.get("/ingest-sessions", response_model=IngestSessionListResponse)
def admin_ingest_sessions(output_stream_id: str | None = Query(default=None), db: Session = Depends(get_db)) -> IngestSessionListResponse:
    sessions = list_ingest_sessions(db, output_stream_id=output_stream_id)
    return IngestSessionListResponse(
        ingest_sessions=[
            IngestSessionResponse(
                ingest_session_id=session.id,
                output_stream_id=session.output_stream_id,
                ingest_key=session.ingest_key,
                status=session.status,
                publisher_label=session.publisher_label,
                last_seen_at=session.last_seen_at,
                last_publish_started_at=session.last_publish_started_at,
                last_publish_stopped_at=session.last_publish_stopped_at,
                last_error=session.last_error,
            )
            for session in sessions
        ]
    )


@router.post("/ingest-sessions/{ingest_session_id}/rotate-key", response_model=RotateIngestKeyResponse)
def admin_rotate_ingest_key(ingest_session_id: str, db: Session = Depends(get_db)) -> RotateIngestKeyResponse:
    session = rotate_ingest_key(db, ingest_session_id)
    return RotateIngestKeyResponse(ingest_session_id=session.id, ingest_key=session.ingest_key, status=session.status)


@router.post("/ingest-sessions/{ingest_session_id}/revoke", response_model=RevokeIngestSessionResponse)
def admin_revoke_ingest(ingest_session_id: str, db: Session = Depends(get_db)) -> RevokeIngestSessionResponse:
    session = revoke_ingest_session(db, ingest_session_id)
    return RevokeIngestSessionResponse(ingest_session_id=session.id, status=session.status)
