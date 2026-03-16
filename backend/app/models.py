from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_code: Mapped[str] = mapped_column(String(9), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    status_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    blocked_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    grants: Mapped[list["UserStreamGrant"]] = relationship(back_populates="user")
    playback_sessions: Mapped[list["PlaybackSession"]] = relationship(back_populates="user")


class OutputStream(Base):
    __tablename__ = "output_streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stream_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    path_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="offline", server_default="offline")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_publish_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_publish_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    grants: Mapped[list["UserStreamGrant"]] = relationship(back_populates="stream")
    ingest_sessions: Mapped[list["IngestSession"]] = relationship(back_populates="stream")
    playback_sessions: Mapped[list["PlaybackSession"]] = relationship(back_populates="stream")


class UserStreamGrant(Base):
    __tablename__ = "user_stream_grants"
    __table_args__ = (UniqueConstraint("user_id", "output_stream_id", name="uq_user_stream_grants"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    output_stream_id: Mapped[int] = mapped_column(ForeignKey("output_streams.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user: Mapped[User] = relationship(back_populates="grants")
    stream: Mapped[OutputStream] = relationship(back_populates="grants")


class IngestSession(Base):
    __tablename__ = "ingest_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    output_stream_id: Mapped[int | None] = mapped_column(ForeignKey("output_streams.id", ondelete="SET NULL"))
    ingest_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="created", server_default="created")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    stream: Mapped[OutputStream | None] = relationship(back_populates="ingest_sessions")


class PlaybackSession(Base):
    __tablename__ = "playback_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    output_stream_id: Mapped[int] = mapped_column(ForeignKey("output_streams.id", ondelete="CASCADE"), nullable=False)
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="issued", server_default="issued")
    client_ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="playback_sessions")
    stream: Mapped[OutputStream] = relationship(back_populates="playback_sessions")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str | None] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(255))
    payload_json: Mapped[dict | None] = mapped_column(JSON)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
