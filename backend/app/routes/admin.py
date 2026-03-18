from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_admin_secret
from ..db import get_db
from ..schemas import (
    AdminUserListResponse,
    ChangeUserStatusResponse,
    CreateIngestSessionRequest,
    CreateOutputStreamRequest,
    GrantGroupRequest,
    GrantUserRequest,
    IngestSessionListResponse,
    IngestSessionResponse,
    OutputStreamListResponse,
    OutputStreamResponse,
    PermissionMutationResponse,
    RevokeIngestSessionResponse,
    RotateIngestKeyResponse,
    UpdateIngestSessionBindingRequest,
    UpdateOutputStreamRequest,
    UserResponse,
)
from ..services.ingest import bind_ingest_session_to_output_stream, create_ingest_session, get_ingest_session, list_ingest_sessions, revoke_ingest_session, rotate_ingest_key, serialize_ingest_session
from ..services.moderation import change_user_status, list_users
from ..services.permissions import grant_group_to_output_stream, grant_user_to_output_stream
from ..services.streams import build_output_stream_payload, create_output_stream, get_output_stream, list_output_streams, update_output_stream


router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin_secret)])


@router.get("/users", response_model=AdminUserListResponse)
def admin_users(status: str | None = Query(default=None), db: Session = Depends(get_db)) -> AdminUserListResponse:
    users = list_users(db, status_filter=status)
    return AdminUserListResponse(users=[UserResponse(user_id=u.id, display_name=u.display_name, client_code=u.client_code, status=u.status) for u in users])


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
    session = create_ingest_session(
        db,
        current_output_stream_id=body.current_output_stream_id or body.output_stream_id,
        source_label=body.source_label or body.publisher_label,
        ingest_key=body.ingest_key,
        metadata_json=body.metadata_json,
    )
    return IngestSessionResponse(**serialize_ingest_session(session))


@router.get("/ingest-sessions", response_model=IngestSessionListResponse)
def admin_ingest_sessions(current_output_stream_id: str | None = Query(default=None), db: Session = Depends(get_db)) -> IngestSessionListResponse:
    sessions = list_ingest_sessions(db, current_output_stream_id=current_output_stream_id)
    return IngestSessionListResponse(ingest_sessions=[IngestSessionResponse(**serialize_ingest_session(session)) for session in sessions])


@router.get("/ingest-sessions/{ingest_session_id}", response_model=IngestSessionResponse)
def admin_ingest_session(ingest_session_id: str, db: Session = Depends(get_db)) -> IngestSessionResponse:
    return IngestSessionResponse(**serialize_ingest_session(get_ingest_session(db, ingest_session_id)))


@router.patch("/ingest-sessions/{ingest_session_id}", response_model=IngestSessionResponse)
def admin_bind_ingest_session(ingest_session_id: str, body: UpdateIngestSessionBindingRequest, db: Session = Depends(get_db)) -> IngestSessionResponse:
    session = bind_ingest_session_to_output_stream(db, ingest_session_id=ingest_session_id, output_stream_id=body.current_output_stream_id)
    return IngestSessionResponse(**serialize_ingest_session(session))


@router.post("/ingest-sessions/{ingest_session_id}/rotate-key", response_model=RotateIngestKeyResponse)
def admin_rotate_ingest_key(ingest_session_id: str, db: Session = Depends(get_db)) -> RotateIngestKeyResponse:
    session = rotate_ingest_key(db, ingest_session_id)
    return RotateIngestKeyResponse(ingest_session_id=session.id, ingest_key=session.ingest_key, status=session.status)


@router.post("/ingest-sessions/{ingest_session_id}/revoke", response_model=RevokeIngestSessionResponse)
def admin_revoke_ingest(ingest_session_id: str, db: Session = Depends(get_db)) -> RevokeIngestSessionResponse:
    session = revoke_ingest_session(db, ingest_session_id)
    return RevokeIngestSessionResponse(ingest_session_id=session.id, status=session.status)


@router.post("/output-streams", response_model=OutputStreamResponse, status_code=201)
def admin_create_output_stream(body: CreateOutputStreamRequest, db: Session = Depends(get_db)) -> OutputStreamResponse:
    output_stream = create_output_stream(
        db,
        name=body.name,
        public_name=body.public_name or body.playback_name or body.name,
        title=body.title or body.name,
        description=body.description,
        visibility=body.visibility,
        playback_path=body.playback_path or body.playback_name,
        source_ingest_session_id=body.source_ingest_session_id,
        metadata_json=body.metadata_json,
    )
    return OutputStreamResponse(**build_output_stream_payload(output_stream))


@router.get("/output-streams", response_model=OutputStreamListResponse)
def admin_list_output_streams(db: Session = Depends(get_db)) -> OutputStreamListResponse:
    payload = [OutputStreamResponse(**build_output_stream_payload(stream)) for stream in list_output_streams(db)]
    return OutputStreamListResponse(output_streams=payload, streams=payload)


@router.get("/output-streams/{output_stream_id}", response_model=OutputStreamResponse)
def admin_get_output_stream(output_stream_id: str, db: Session = Depends(get_db)) -> OutputStreamResponse:
    return OutputStreamResponse(**build_output_stream_payload(get_output_stream(db, output_stream_id)))


@router.patch("/output-streams/{output_stream_id}", response_model=OutputStreamResponse)
def admin_update_output_stream(output_stream_id: str, body: UpdateOutputStreamRequest, db: Session = Depends(get_db)) -> OutputStreamResponse:
    output_stream = update_output_stream(
        db,
        output_stream_id=output_stream_id,
        name=body.name,
        public_name=body.public_name,
        title=body.title,
        description=body.description,
        visibility=body.visibility,
        playback_path=body.playback_path,
        is_active=body.is_active,
        source_ingest_session_id=body.source_ingest_session_id,
        metadata_json=body.metadata_json,
    )
    return OutputStreamResponse(**build_output_stream_payload(output_stream))


@router.post("/output-streams/{output_stream_id}/grant-user", response_model=PermissionMutationResponse)
def admin_grant_user(output_stream_id: str, body: GrantUserRequest, db: Session = Depends(get_db)) -> PermissionMutationResponse:
    grant_user_to_output_stream(db, output_stream_id, body.user_id)
    return PermissionMutationResponse(output_stream_id=output_stream_id, subject_id=body.user_id, subject_type="user", granted=True)


@router.post("/output-streams/{output_stream_id}/grant-group", response_model=PermissionMutationResponse)
def admin_grant_group(output_stream_id: str, body: GrantGroupRequest, db: Session = Depends(get_db)) -> PermissionMutationResponse:
    grant_group_to_output_stream(db, output_stream_id, body.group_id)
    return PermissionMutationResponse(output_stream_id=output_stream_id, subject_id=body.group_id, subject_type="group", granted=True)
