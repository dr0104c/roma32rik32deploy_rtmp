from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_admin_access
from ..db import get_db
from ..models import AuditLog
from ..schemas import (
    AdminOutputStreamDetailResponse,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AuditLogListResponse,
    AuditLogResponse,
    ChangeUserStatusResponse,
    CreateGroupRequest,
    CreateIngestSessionRequest,
    CreateOutputStreamRequest,
    GrantGroupRequest,
    GrantUserRequest,
    GroupListResponse,
    GroupResponse,
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
from ..services.audit import list_audit_logs
from ..services.ingest import (
    bind_ingest_session_to_output_stream,
    create_ingest_session,
    get_ingest_session,
    list_ingest_sessions,
    revoke_ingest_session,
    rotate_ingest_key,
    serialize_ingest_session,
)
from ..services.moderation import change_user_status, get_user_for_admin, list_users
from ..services.permissions import (
    add_user_to_group,
    create_group,
    get_group,
    grant_group_to_output_stream,
    grant_user_to_output_stream,
    group_member_count,
    list_group_member_ids,
    list_groups,
    list_output_stream_group_ids,
    list_output_stream_user_ids,
    list_user_group_ids,
    list_user_output_stream_ids,
    remove_user_from_group,
    revoke_group_access,
    revoke_user_access,
)
from ..services.streams import build_output_stream_payload, create_output_stream, get_output_stream, list_output_streams, update_output_stream


router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin_access)])


def serialize_user(user) -> UserResponse:
    return UserResponse(user_id=user.id, display_name=user.display_name, client_code=user.client_code, status=user.status)


def serialize_group(db: Session, group) -> GroupResponse:
    return GroupResponse(group_id=group.id, name=group.name, member_count=group_member_count(db, group.id))


def serialize_audit_log(row: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=row.id,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        metadata_json=row.metadata_json or {},
        created_at=row.created_at,
    )


@router.get("/users", response_model=AdminUserListResponse)
def admin_users(
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> AdminUserListResponse:
    users = list_users(db, status_filter=status, search=search, limit=limit, offset=offset)
    return AdminUserListResponse(users=[serialize_user(user) for user in users])


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
def admin_user_detail(user_id: str, db: Session = Depends(get_db)) -> AdminUserDetailResponse:
    user = get_user_for_admin(db, user_id)
    return AdminUserDetailResponse(
        user=serialize_user(user),
        group_ids=list_user_group_ids(db, user.id),
        output_stream_ids=list_user_output_stream_ids(db, user.id),
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


@router.post("/users/{user_id}/unblock", response_model=ChangeUserStatusResponse)
def unblock(user_id: str, db: Session = Depends(get_db)) -> ChangeUserStatusResponse:
    user = change_user_status(db, user_id, "approved")
    return ChangeUserStatusResponse(user_id=user.id, status=user.status)


@router.get("/groups", response_model=GroupListResponse)
def admin_groups(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> GroupListResponse:
    groups = list_groups(db, limit=limit, offset=offset)
    return GroupListResponse(groups=[serialize_group(db, group) for group in groups])


@router.post("/groups", response_model=GroupResponse, status_code=201)
def admin_create_group(body: CreateGroupRequest, db: Session = Depends(get_db)) -> GroupResponse:
    return serialize_group(db, create_group(db, body.name))


@router.post("/users/{user_id}/groups/{group_id}", response_model=GroupResponse)
def admin_add_user_to_group(user_id: str, group_id: str, db: Session = Depends(get_db)) -> GroupResponse:
    add_user_to_group(db, user_id=user_id, group_id=group_id)
    return serialize_group(db, get_group(db, group_id))


@router.delete("/users/{user_id}/groups/{group_id}", response_model=GroupResponse)
def admin_remove_user_from_group(user_id: str, group_id: str, db: Session = Depends(get_db)) -> GroupResponse:
    remove_user_from_group(db, user_id=user_id, group_id=group_id)
    return serialize_group(db, get_group(db, group_id))


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


@router.get("/output-streams/{output_stream_id}", response_model=AdminOutputStreamDetailResponse)
def admin_get_output_stream(output_stream_id: str, db: Session = Depends(get_db)) -> AdminOutputStreamDetailResponse:
    output_stream = get_output_stream(db, output_stream_id)
    return AdminOutputStreamDetailResponse(
        output_stream=OutputStreamResponse(**build_output_stream_payload(output_stream)),
        user_ids=list_output_stream_user_ids(db, output_stream_id),
        group_ids=list_output_stream_group_ids(db, output_stream_id),
    )


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


@router.delete("/output-streams/{output_stream_id}/grant-user/{user_id}", response_model=PermissionMutationResponse)
def admin_revoke_user(output_stream_id: str, user_id: str, db: Session = Depends(get_db)) -> PermissionMutationResponse:
    revoke_user_access(db, output_stream_id, user_id)
    return PermissionMutationResponse(output_stream_id=output_stream_id, subject_id=user_id, subject_type="user", granted=False)


@router.post("/output-streams/{output_stream_id}/grant-group", response_model=PermissionMutationResponse)
def admin_grant_group(output_stream_id: str, body: GrantGroupRequest, db: Session = Depends(get_db)) -> PermissionMutationResponse:
    grant_group_to_output_stream(db, output_stream_id, body.group_id)
    return PermissionMutationResponse(output_stream_id=output_stream_id, subject_id=body.group_id, subject_type="group", granted=True)


@router.delete("/output-streams/{output_stream_id}/grant-group/{group_id}", response_model=PermissionMutationResponse)
def admin_revoke_group(output_stream_id: str, group_id: str, db: Session = Depends(get_db)) -> PermissionMutationResponse:
    revoke_group_access(db, output_stream_id, group_id)
    return PermissionMutationResponse(output_stream_id=output_stream_id, subject_id=group_id, subject_type="group", granted=False)


@router.get("/audit", response_model=AuditLogListResponse)
def admin_audit(
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    rows = list_audit_logs(db, target_type=target_type, target_id=target_id, limit=limit, offset=offset)
    return AuditLogListResponse(audit_logs=[serialize_audit_log(row) for row in rows])
