from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    status: str


class EnrollRequest(BaseModel):
    name: str


class UserSummary(BaseModel):
    id: int
    name: str
    client_code: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class EnrollResponse(UserSummary):
    pass


class ApproveUserResponse(BaseModel):
    id: int
    status: str
    approved_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class BlockUserRequest(BaseModel):
    reason: str


class CreateStreamRequest(BaseModel):
    name: str


class StreamSummary(BaseModel):
    id: int
    name: str
    path_name: str
    status: str
    is_live: bool
    last_publish_started_at: datetime | None
    last_publish_stopped_at: datetime | None


class StreamDetail(StreamSummary):
    is_active: bool


class CreateStreamResponse(BaseModel):
    id: int
    name: str
    stream_key: str
    path_name: str

    model_config = ConfigDict(from_attributes=True)


class GrantResponse(BaseModel):
    user_id: int
    stream_id: int
    granted: bool


class PlaybackTokenRequest(BaseModel):
    user_id: int
    stream_id: int


class PlaybackTokenResponse(BaseModel):
    token: str
    expires_in: int


class ViewerSessionRequest(BaseModel):
    client_code: str


class ViewerSessionResponse(BaseModel):
    viewer_token: str | None = None
    expires_in: int | None = None
    user: UserSummary
    detail: str | None = None


class ViewerMeResponse(BaseModel):
    user: UserSummary


class ViewerConfigResponse(BaseModel):
    public_base_url: str
    webrtc_base_url: str
    stun_urls: list[str]
    turn_urls: list[str]
    turn_realm: str
    stream_list_poll_interval: int
    playback_token_ttl: int


class ViewerStreamsResponse(BaseModel):
    streams: list[StreamSummary]


class PlaybackSessionTokenResponse(BaseModel):
    playback_token: str
    expires_in: int
    stream: dict
    playback: dict


class MediaMTXAuthRequest(BaseModel):
    action: str
    path: str
    protocol: str | None = None
    query: str | None = None
    user: str | None = None
    password: str | None = None
    ip: str | None = None
    id: str | None = None
    userAgent: str | None = None


class MediaMTXEventRequest(BaseModel):
    path: str
    query: str | None = None
    protocol: str | None = None
    id: str | None = None
    ip: str | None = None
    userAgent: str | None = None
