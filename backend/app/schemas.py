from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str


class EnrollRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)


class UserResponse(BaseModel):
    user_id: str
    display_name: str
    client_code: str
    status: str


class AdminUserListResponse(BaseModel):
    users: list[UserResponse]


class ChangeUserStatusResponse(BaseModel):
    user_id: str
    status: str


class CreateStreamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    playback_name: str = Field(min_length=1, max_length=128)


class StreamResponse(BaseModel):
    stream_id: str
    name: str
    playback_name: str
    is_active: bool
    ingest_key: str | None = None


class StreamListResponse(BaseModel):
    streams: list[StreamResponse]


class GrantUserRequest(BaseModel):
    user_id: str


class PermissionMutationResponse(BaseModel):
    stream_id: str
    user_id: str
    granted: bool


class CreateIngestSessionRequest(BaseModel):
    output_stream_id: str
    publisher_label: str | None = Field(default=None, max_length=255)


class RotateIngestKeyResponse(BaseModel):
    ingest_session_id: str
    ingest_key: str
    status: str


class RevokeIngestSessionResponse(BaseModel):
    ingest_session_id: str
    status: str


class IngestSessionResponse(BaseModel):
    ingest_session_id: str
    output_stream_id: str | None
    ingest_key: str
    status: str
    publisher_label: str | None
    last_seen_at: datetime | None
    last_publish_started_at: datetime | None
    last_publish_stopped_at: datetime | None
    last_error: str | None


class IngestSessionListResponse(BaseModel):
    ingest_sessions: list[IngestSessionResponse]


class PlaybackTokenRequest(BaseModel):
    user_id: str
    stream_id: str


class PlaybackTokenResponse(BaseModel):
    token: str
    expires_at: datetime
    playback_url: str


class MediaAuthRequest(BaseModel):
    action: str
    path: str
    protocol: str | None = None
    query: str | None = None
    ip: str | None = None
    id: str | None = None
    userAgent: str | None = None


class MediaEventRequest(BaseModel):
    path: str
    protocol: str | None = None
    ip: str | None = None
    id: str | None = None
    userAgent: str | None = None


class ViewerSessionRequest(BaseModel):
    client_code: str = Field(min_length=9, max_length=9)


class ViewerSessionResponse(BaseModel):
    viewer_token: str | None = None
    expires_in: int | None = None
    user: UserResponse
    detail: str | None = None


class ViewerMeResponse(BaseModel):
    user: UserResponse


class ViewerConfigResponse(BaseModel):
    public_base_url: str
    webrtc_base_url: str
    stun_urls: list[str]
    turn_urls: list[str]
    turn_realm: str
    stream_list_poll_interval: int
    playback_token_ttl: int


class ViewerStreamsResponse(BaseModel):
    streams: list[dict[str, Any]]


class ViewerPlaybackSessionResponse(BaseModel):
    playback_token: str
    expires_at: datetime
    stream: dict[str, Any]
    playback: dict[str, Any]


class LegacyViewerSessionPayload(BaseModel):
    client_code: str


class LegacyUserSummary(BaseModel):
    id: str
    name: str
    client_code: str
    status: str

    model_config = ConfigDict(from_attributes=True)
