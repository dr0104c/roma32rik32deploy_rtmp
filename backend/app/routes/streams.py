from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_admin_access
from ..db import get_db
from ..schemas import CreateOutputStreamRequest, GrantUserRequest, OutputStreamListResponse, OutputStreamResponse, PermissionMutationResponse, ViewerOutputStreamListResponse, ViewerOutputStreamResponse
from ..services.permissions import grant_user_to_output_stream, revoke_user_access
from ..services.streams import build_output_stream_payload, create_output_stream, list_output_streams
from ..services.viewer import list_user_stream_payloads


router = APIRouter(tags=["streams"])


@router.post("/api/v1/admin/streams", response_model=OutputStreamResponse, dependencies=[Depends(require_admin_access)], status_code=201)
def compatibility_create_stream(body: CreateOutputStreamRequest, db: Session = Depends(get_db)) -> OutputStreamResponse:
    output_stream = create_output_stream(
        db,
        name=body.name,
        public_name=body.public_name or body.playback_name or body.name,
        title=body.title or body.name,
        description=body.description,
        visibility=body.visibility,
        playback_path=body.playback_path or body.playback_name or body.public_name,
        source_ingest_session_id=body.source_ingest_session_id,
        metadata_json=body.metadata_json,
    )
    return OutputStreamResponse(**build_output_stream_payload(output_stream))


@router.get("/api/v1/admin/streams", response_model=OutputStreamListResponse, dependencies=[Depends(require_admin_access)])
def compatibility_list_streams(db: Session = Depends(get_db)) -> OutputStreamListResponse:
    payload = [OutputStreamResponse(**build_output_stream_payload(stream)) for stream in list_output_streams(db)]
    return OutputStreamListResponse(output_streams=payload, streams=payload)


@router.post("/api/v1/admin/streams/{stream_id}/grant-user", response_model=PermissionMutationResponse, dependencies=[Depends(require_admin_access)])
def compatibility_grant_user(stream_id: str, body: GrantUserRequest, db: Session = Depends(get_db)) -> PermissionMutationResponse:
    grant_user_to_output_stream(db, stream_id, body.user_id)
    return PermissionMutationResponse(output_stream_id=stream_id, subject_id=body.user_id, subject_type="user", granted=True)


@router.post("/api/v1/admin/streams/{stream_id}/revoke-user", response_model=PermissionMutationResponse, dependencies=[Depends(require_admin_access)])
def compatibility_revoke_user(stream_id: str, body: GrantUserRequest, db: Session = Depends(get_db)) -> PermissionMutationResponse:
    revoke_user_access(db, stream_id, body.user_id)
    return PermissionMutationResponse(output_stream_id=stream_id, subject_id=body.user_id, subject_type="user", granted=False)


@router.get("/api/v1/streams", response_model=ViewerOutputStreamListResponse)
def public_list_streams(user_id: str = Query(...), db: Session = Depends(get_db)) -> ViewerOutputStreamListResponse:
    streams = list_user_stream_payloads(db, user_id)
    payload = [ViewerOutputStreamResponse(**stream) for stream in streams]
    return ViewerOutputStreamListResponse(output_streams=payload, streams=payload)
