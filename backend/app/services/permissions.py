from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from ..errors import conflict, forbidden, not_found
from ..models import Group, GroupMember, OutputStream, StreamPermissionGroup, StreamPermissionUser, User
from .audit import write_audit_log


def grant_user_to_output_stream(db: Session, output_stream_id: str, user_id: str) -> None:
    user = db.get(User, user_id)
    output_stream = db.get(OutputStream, output_stream_id)
    if user is None:
        raise not_found("user_not_found", "user not found")
    if output_stream is None:
        raise not_found("output_stream_not_found", "output stream not found")
    existing = db.scalar(select(StreamPermissionUser).where(StreamPermissionUser.user_id == user_id, StreamPermissionUser.output_stream_id == output_stream_id))
    if existing is not None:
        raise conflict("permission_exists", "user permission already exists")
    db.add(StreamPermissionUser(user_id=user_id, output_stream_id=output_stream_id))
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="grant_user_output_stream",
        target_type="output_stream",
        target_id=output_stream_id,
        metadata={"user_id": user_id},
    )
    db.commit()


def revoke_user_access(db: Session, output_stream_id: str, user_id: str) -> None:
    grant = db.scalar(select(StreamPermissionUser).where(StreamPermissionUser.user_id == user_id, StreamPermissionUser.output_stream_id == output_stream_id))
    if grant is None:
        raise not_found("permission_not_found", "user permission not found")
    db.delete(grant)
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="revoke_user_output_stream",
        target_type="output_stream",
        target_id=output_stream_id,
        metadata={"user_id": user_id},
    )
    db.commit()


def grant_group_to_output_stream(db: Session, output_stream_id: str, group_id: str) -> None:
    group = db.get(Group, group_id)
    output_stream = db.get(OutputStream, output_stream_id)
    if group is None:
        raise not_found("group_not_found", "group not found")
    if output_stream is None:
        raise not_found("output_stream_not_found", "output stream not found")
    existing = db.scalar(select(StreamPermissionGroup).where(StreamPermissionGroup.group_id == group_id, StreamPermissionGroup.output_stream_id == output_stream_id))
    if existing is not None:
        raise conflict("permission_exists", "group permission already exists")
    db.add(StreamPermissionGroup(group_id=group_id, output_stream_id=output_stream_id))
    write_audit_log(
        db,
        actor_type="admin",
        actor_id="bootstrap-admin",
        action="grant_group_output_stream",
        target_type="output_stream",
        target_id=output_stream_id,
        metadata={"group_id": group_id},
    )
    db.commit()


def user_has_output_stream_access(db: Session, user_id: str, output_stream_id: str) -> bool:
    direct = db.scalar(select(exists().where(StreamPermissionUser.user_id == user_id, StreamPermissionUser.output_stream_id == output_stream_id)))
    if direct:
        return True
    group_access = db.scalar(
        select(exists().where(
            GroupMember.user_id == user_id,
            GroupMember.group_id == StreamPermissionGroup.group_id,
            StreamPermissionGroup.output_stream_id == output_stream_id,
        ))
    )
    return bool(group_access)


def assert_user_has_stream_access(db: Session, user_id: str, stream_id: str) -> None:
    if not user_has_output_stream_access(db, user_id, stream_id):
        raise forbidden("stream_permission_missing", "output stream access is not granted")


def grant_user_access(db: Session, stream_id: str, user_id: str) -> None:
    grant_user_to_output_stream(db, stream_id, user_id)
