from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from ..errors import conflict, forbidden, not_found
from ..models import GroupMember, OutputStream, StreamPermissionGroup, StreamPermissionUser, User
from .audit import write_audit_log


def grant_user_access(db: Session, stream_id: str, user_id: str) -> None:
    user = db.get(User, user_id)
    stream = db.get(OutputStream, stream_id)
    if user is None:
        raise not_found("user_not_found", "user not found")
    if stream is None:
        raise not_found("stream_not_found", "stream not found")
    existing = db.scalar(
        select(StreamPermissionUser).where(
            StreamPermissionUser.user_id == user_id,
            StreamPermissionUser.output_stream_id == stream_id,
        )
    )
    if existing is not None:
        raise conflict("permission_exists", "user permission already exists")
    db.add(StreamPermissionUser(user_id=user_id, output_stream_id=stream_id))
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="grant_user_stream",
        target_type="output_stream",
        target_id=stream_id,
        metadata={"user_id": user_id},
    )
    db.commit()


def revoke_user_access(db: Session, stream_id: str, user_id: str) -> None:
    grant = db.scalar(
        select(StreamPermissionUser).where(
            StreamPermissionUser.user_id == user_id,
            StreamPermissionUser.output_stream_id == stream_id,
        )
    )
    if grant is None:
        raise not_found("permission_not_found", "user permission not found")
    db.delete(grant)
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="revoke_user_stream",
        target_type="output_stream",
        target_id=stream_id,
        metadata={"user_id": user_id},
    )
    db.commit()


def user_has_stream_access(db: Session, user_id: str, stream_id: str) -> bool:
    direct = db.scalar(
        select(exists().where(
            StreamPermissionUser.user_id == user_id,
            StreamPermissionUser.output_stream_id == stream_id,
        ))
    )
    if direct:
        return True

    group_access = db.scalar(
        select(exists().where(
            GroupMember.user_id == user_id,
            GroupMember.group_id == StreamPermissionGroup.group_id,
            StreamPermissionGroup.output_stream_id == stream_id,
        ))
    )
    return bool(group_access)


def assert_user_has_stream_access(db: Session, user_id: str, stream_id: str) -> None:
    if not user_has_stream_access(db, user_id, stream_id):
        raise forbidden("stream_permission_missing", "stream access is not granted")
