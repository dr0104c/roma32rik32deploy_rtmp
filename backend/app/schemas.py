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


class AdminUserDetailResponse(BaseModel):
    user: UserResponse
    group_ids: list[str]
    output_stream_ids: list[str]


class ChangeUserStatusResponse(BaseModel):
    user_id: str
    status: str


class AdminAuthLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=512)


class AdminAuthLoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class AdminMeResponse(BaseModel):
    id: str
    username: str
    role: str
    is_active: bool
    auth_mode: str


class CreateOutputStreamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    public_name: str | None = Field(default=None, min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    visibility: str = Field(default="private", pattern="^(private|public|unlisted|disabled)$")
    playback_path: str | None = Field(default=None, min_length=1, max_length=128)
    source_ingest_session_id: str | None = None
    metadata_json: dict[str, Any] | None = None
    playback_name: str | None = None


class UpdateOutputStreamRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    public_name: str | None = Field(default=None, min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    visibility: str | None = Field(default=None, pattern="^(private|public|unlisted|disabled)$")
    playback_path: str | None = Field(default=None, min_length=1, max_length=128)
    is_active: bool | None = None
    source_ingest_session_id: str | None = None
    metadata_json: dict[str, Any] | None = None


class OutputStreamResponse(BaseModel):
    output_stream_id: str
    stream_id: str | None = None
    name: str
    public_name: str
    title: str
    description: str | None
    visibility: str
    playback_path: str
    playback_name: str | None = None
    is_active: bool
    source_ingest_session_id: str | None
    metadata_json: dict[str, Any]
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OutputStreamListResponse(BaseModel):
    output_streams: list[OutputStreamResponse]
    streams: list[OutputStreamResponse] | None = None


class ViewerOutputStreamResponse(BaseModel):
    output_stream_id: str
    stream_id: str | None = None
    name: str
    public_name: str
    title: str
    description: str | None
    visibility: str
    playback_path: str
    playback_name: str | None = None
    is_active: bool


class ViewerOutputStreamListResponse(BaseModel):
    output_streams: list[ViewerOutputStreamResponse]
    streams: list[ViewerOutputStreamResponse] | None = None


class GrantUserRequest(BaseModel):
    user_id: str


class GrantGroupRequest(BaseModel):
    group_id: str


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class GroupResponse(BaseModel):
    group_id: str
    name: str
    member_count: int = 0


class GroupListResponse(BaseModel):
    groups: list[GroupResponse]


class PermissionMutationResponse(BaseModel):
    output_stream_id: str
    subject_id: str
    subject_type: str
    granted: bool


class AdminOutputStreamDetailResponse(BaseModel):
    output_stream: OutputStreamResponse
    user_ids: list[str]
    group_ids: list[str]


class AuditLogResponse(BaseModel):
    id: str
    actor_type: str
    actor_id: str | None
    action: str
    target_type: str
    target_id: str | None
    metadata_json: dict[str, Any]
    created_at: datetime


class AuditLogListResponse(BaseModel):
    audit_logs: list[AuditLogResponse]


class CreateIngestSessionRequest(BaseModel):
    current_output_stream_id: str | None = None
    output_stream_id: str | None = None
    source_label: str | None = Field(default=None, max_length=255)
    publisher_label: str | None = Field(default=None, max_length=255)
    ingest_key: str | None = Field(default=None, min_length=1, max_length=128)
    metadata_json: dict[str, Any] | None = None


class UpdateIngestSessionBindingRequest(BaseModel):
    current_output_stream_id: str | None = None


class RotateIngestKeyResponse(BaseModel):
    ingest_session_id: str
    ingest_key: str
    status: str


class RevokeIngestSessionResponse(BaseModel):
    ingest_session_id: str
    status: str


class IngestSessionResponse(BaseModel):
    ingest_session_id: str
    source_label: str | None
    status: str
    created_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    revoked_at: datetime | None
    last_seen_at: datetime | None
    current_output_stream_id: str | None
    metadata_json: dict[str, Any]
    ingest_key: str | None = None


class IngestSessionListResponse(BaseModel):
    ingest_sessions: list[IngestSessionResponse]


class PlaybackTokenRequest(BaseModel):
    user_id: str
    output_stream_id: str | None = None
    stream_id: str | None = None
    playback_path: str | None = None


class PlaybackTokenResponse(BaseModel):
    token: str
    expires_at: datetime
    playback_url: str
    output_stream_id: str
    playback_path: str


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
    client_code: str = Field(min_length=3, max_length=9)


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
    ingest_transport: str
    ingest_container: str
    playback_transport: str
    rtmp_playback_enabled: bool
    output_stream_acl_scope: str
    playback_token_lookup_fields: list[str]
    viewer_must_not_use_fields: list[str]
    browser_rendering_verified: bool
    real_android_ice_verified: bool
    transcoding_enabled: bool
    transcoding_verified: bool
    expected_ingest_video_codec: str
    expected_ingest_audio_codec: str
    expected_ingest_notes: str


class ViewerStreamsResponse(BaseModel):
    streams: list[ViewerOutputStreamResponse]


class ViewerPlaybackSessionResponse(BaseModel):
    playback_token: str
    expires_at: datetime
    output_stream: dict[str, Any] | None = None
    stream: dict[str, Any] | None = None
    playback: dict[str, Any]


class LegacyViewerSessionPayload(BaseModel):
    client_code: str


class LegacyUserSummary(BaseModel):
    id: str
    name: str
    client_code: str
    status: str

    model_config = ConfigDict(from_attributes=True)
