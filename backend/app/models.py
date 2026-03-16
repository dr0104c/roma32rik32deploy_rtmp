from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def new_uuid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('pending','approved','rejected','blocked')", name="ck_users_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    client_code: Mapped[str] = mapped_column(String(9), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")

    status_history: Mapped[list["UserStatusHistory"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    direct_permissions: Mapped[list["StreamPermissionUser"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    group_memberships: Mapped[list["GroupMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserStatusHistory(Base):
    __tablename__ = "user_status_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(16))
    new_status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="status_history")


class OutputStream(Base, TimestampMixin):
    __tablename__ = "output_streams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    playback_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    ingest_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    ingest_sessions: Mapped[list["IngestSession"]] = relationship(back_populates="output_stream", cascade="all, delete-orphan")
    direct_permissions: Mapped[list["StreamPermissionUser"]] = relationship(back_populates="output_stream", cascade="all, delete-orphan")
    group_permissions: Mapped[list["StreamPermissionGroup"]] = relationship(back_populates="output_stream", cascade="all, delete-orphan")


class IngestSession(Base):
    __tablename__ = "ingest_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('created','connecting','live','offline','revoked','error')", name="ck_ingest_sessions_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    output_stream_id: Mapped[str | None] = mapped_column(ForeignKey("output_streams.id", ondelete="SET NULL"))
    ingest_key: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="created", server_default="created")
    publisher_label: Mapped[str | None] = mapped_column(String(255))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_publish_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_publish_stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    output_stream: Mapped[OutputStream | None] = relationship(back_populates="ingest_sessions")


class StreamPermissionUser(Base):
    __tablename__ = "stream_permissions_user"
    __table_args__ = (UniqueConstraint("user_id", "output_stream_id", name="uq_stream_permissions_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    output_stream_id: Mapped[str] = mapped_column(ForeignKey("output_streams.id", ondelete="CASCADE"), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="direct_permissions")
    output_stream: Mapped[OutputStream] = relationship(back_populates="direct_permissions")


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    members: Mapped[list["GroupMember"]] = relationship(back_populates="group", cascade="all, delete-orphan")
    stream_permissions: Mapped[list["StreamPermissionGroup"]] = relationship(back_populates="group", cascade="all, delete-orphan")


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_members"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    group: Mapped[Group] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="group_memberships")


class StreamPermissionGroup(Base):
    __tablename__ = "stream_permissions_group"
    __table_args__ = (UniqueConstraint("group_id", "output_stream_id", name="uq_stream_permissions_group"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    group_id: Mapped[str] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    output_stream_id: Mapped[str] = mapped_column(ForeignKey("output_streams.id", ondelete="CASCADE"), nullable=False)

    group: Mapped[Group] = relationship(back_populates="stream_permissions")
    output_stream: Mapped[OutputStream] = relationship(back_populates="group_permissions")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    actor_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
