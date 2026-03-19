from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    database_url: str = Field(alias="DATABASE_URL")
    admin_secret: str = Field(alias="ADMIN_SECRET")
    admin_jwt_secret: str = Field(alias="ADMIN_JWT_SECRET", default="")
    admin_bootstrap_username: str = Field(alias="ADMIN_BOOTSTRAP_USERNAME", default="admin")
    admin_bootstrap_password: str = Field(alias="ADMIN_BOOTSTRAP_PASSWORD", default="")
    admin_access_token_ttl_seconds: int = Field(alias="ADMIN_ACCESS_TOKEN_TTL_SECONDS", default=3600)
    legacy_admin_secret_enabled: bool = Field(alias="LEGACY_ADMIN_SECRET_ENABLED", default=True)
    internal_api_secret: str = Field(alias="INTERNAL_API_SECRET")
    playback_token_secret: str = Field(alias="PLAYBACK_TOKEN_SECRET")
    viewer_session_secret: str = Field(alias="VIEWER_SESSION_SECRET")
    public_host: str = Field(alias="PUBLIC_HOST")
    public_base_url: str = Field(alias="PUBLIC_BASE_URL")
    webrtc_public_base_url: str = Field(alias="WEBRTC_PUBLIC_BASE_URL")
    turn_shared_secret: str = Field(alias="TURN_SHARED_SECRET")
    turn_realm: str = Field(alias="TURN_REALM")
    stun_urls: str = Field(alias="STUN_URLS")
    turn_urls: str = Field(alias="TURN_URLS")
    log_level: str = Field(alias="LOG_LEVEL", default="INFO")
    access_log_enabled: bool = Field(alias="ACCESS_LOG_ENABLED", default=True)
    stream_list_poll_interval_seconds: int = Field(alias="STREAM_LIST_POLL_INTERVAL_SECONDS", default=5)
    viewer_session_ttl_seconds: int = Field(alias="VIEWER_SESSION_TTL_SECONDS", default=86400)
    playback_token_ttl_seconds: int = Field(alias="PLAYBACK_TOKEN_TTL_SECONDS", default=120)
    ingest_auth_mode: str = Field(alias="INGEST_AUTH_MODE", default="open")
    internal_media_secret_required: bool = Field(alias="INTERNAL_MEDIA_SECRET_REQUIRED", default=True)
    mediamtx_control_api_base_url: str = Field(alias="MEDIAMTX_CONTROL_API_BASE_URL", default="")
    enable_ffmpeg_transcode: bool = Field(alias="ENABLE_FFMPEG_TRANSCODE", default=True)
    stream_stale_after_seconds: int = 10
    stream_end_after_seconds: int = 20


@lru_cache
def get_settings() -> Settings:
    return Settings()
