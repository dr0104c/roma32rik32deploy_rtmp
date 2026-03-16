from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import require_admin_secret
from ..db import get_db
from ..schemas import CreateStreamRequest, PermissionMutationResponse, GrantUserRequest, StreamListResponse, StreamResponse
from ..services.permissions import grant_user_access, revoke_user_access
from ..services.streams import create_stream, list_streams
from ..services.viewer import list_user_stream_payloads


router = APIRouter(tags=["streams"])


@router.post("/api/v1/admin/streams", response_model=StreamResponse, dependencies=[Depends(require_admin_secret)], status_code=201)
def admin_create_stream(body: CreateStreamRequest, db: Session = Depends(get_db)) -> StreamResponse:
    stream = create_stream(db, body.name, body.playback_name)
    return StreamResponse(stream_id=stream.id, name=stream.name, playback_name=stream.playback_name, is_active=stream.is_active, ingest_key=stream.ingest_key)


@router.get("/api/v1/admin/streams", response_model=StreamListResponse, dependencies=[Depends(require_admin_secret)])
def admin_list_streams(db: Session = Depends(get_db)) -> StreamListResponse:
    streams = list_streams(db)
    return StreamListResponse(
        streams=[StreamResponse(stream_id=s.id, name=s.name, playback_name=s.playback_name, is_active=s.is_active, ingest_key=s.ingest_key) for s in streams]
    )


@router.get("/api/v1/streams", response_model=StreamListResponse)
def public_list_streams(user_id: str = Query(...), db: Session = Depends(get_db)) -> StreamListResponse:
    streams = list_user_stream_payloads(db, user_id)
    return StreamListResponse(
        streams=[StreamResponse(stream_id=s["stream_id"], name=s["name"], playback_name=s["playback_name"], is_active=s["is_active"]) for s in streams]
    )


@router.post("/api/v1/admin/streams/{stream_id}/grant-user", response_model=PermissionMutationResponse, dependencies=[Depends(require_admin_secret)])
def grant_user(stream_id: str, body: GrantUserRequest, db: Session = Depends(get_db)) -> PermissionMutationResponse:
    grant_user_access(db, stream_id, body.user_id)
    return PermissionMutationResponse(stream_id=stream_id, user_id=body.user_id, granted=True)


@router.post("/api/v1/admin/streams/{stream_id}/revoke-user", response_model=PermissionMutationResponse, dependencies=[Depends(require_admin_secret)])
def revoke_user(stream_id: str, body: GrantUserRequest, db: Session = Depends(get_db)) -> PermissionMutationResponse:
    revoke_user_access(db, stream_id, body.user_id)
    return PermissionMutationResponse(stream_id=stream_id, user_id=body.user_id, granted=False)
