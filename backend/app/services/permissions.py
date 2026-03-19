from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from ..errors import conflict, forbidden, not_found
from ..models import Group, GroupMember, OutputStream, StreamPermissionGroup, StreamPermissionUser, User
from .audit import write_audit_log


def list_groups(db: Session, *, limit: int = 100, offset: int = 0) -> list[Group]:
    query = select(Group).order_by(Group.name.asc()).limit(limit).offset(offset)
    return list(db.scalars(query).all())


def get_group(db: Session, group_id: str) -> Group:
    group = db.get(Group, group_id)
    if group is None:
        raise not_found("group_not_found", "group not found")
    return group


def create_group(db: Session, name: str) -> Group:
    normalized_name = name.strip()
    existing = db.scalar(select(Group).where(Group.name == normalized_name))
    if existing is not None:
        raise conflict("group_exists", "group already exists")
    group = Group(name=normalized_name)
    db.add(group)
    db.flush()
    write_audit_log(
        db,
        actor_type="admin",
        action="group_created",
        target_type="group",
        target_id=group.id,
        metadata={"name": group.name},
    )
    db.commit()
    db.refresh(group)
    return group


def add_user_to_group(db: Session, *, user_id: str, group_id: str) -> None:
    user = db.get(User, user_id)
    group = db.get(Group, group_id)
    if user is None:
        raise not_found("user_not_found", "user not found")
    if group is None:
        raise not_found("group_not_found", "group not found")
    existing = db.scalar(select(GroupMember).where(GroupMember.user_id == user_id, GroupMember.group_id == group_id))
    if existing is not None:
        raise conflict("group_membership_exists", "group membership already exists")
    db.add(GroupMember(user_id=user_id, group_id=group_id))
    write_audit_log(
        db,
        actor_type="admin",
        action="group_member_added",
        target_type="group",
        target_id=group_id,
        metadata={"user_id": user_id},
    )
    db.commit()


def remove_user_from_group(db: Session, *, user_id: str, group_id: str) -> None:
    membership = db.scalar(select(GroupMember).where(GroupMember.user_id == user_id, GroupMember.group_id == group_id))
    if membership is None:
        raise not_found("group_membership_not_found", "group membership not found")
    db.delete(membership)
    write_audit_log(
        db,
        actor_type="admin",
        action="group_member_removed",
        target_type="group",
        target_id=group_id,
        metadata={"user_id": user_id},
    )
    db.commit()


def list_group_member_ids(db: Session, group_id: str) -> list[str]:
    return list(db.scalars(select(GroupMember.user_id).where(GroupMember.group_id == group_id).order_by(GroupMember.user_id.asc())).all())


def list_user_group_ids(db: Session, user_id: str) -> list[str]:
    return list(db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == user_id).order_by(GroupMember.group_id.asc())).all())


def group_member_count(db: Session, group_id: str) -> int:
    return int(db.scalar(select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group_id)) or 0)


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


def revoke_group_access(db: Session, output_stream_id: str, group_id: str) -> None:
    grant = db.scalar(select(StreamPermissionGroup).where(StreamPermissionGroup.group_id == group_id, StreamPermissionGroup.output_stream_id == output_stream_id))
    if grant is None:
        raise not_found("permission_not_found", "group permission not found")
    db.delete(grant)
    write_audit_log(
        db,
        actor_type="admin",
        action="revoke_group_output_stream",
        target_type="output_stream",
        target_id=output_stream_id,
        metadata={"group_id": group_id},
    )
    db.commit()


def list_output_stream_user_ids(db: Session, output_stream_id: str) -> list[str]:
    return list(
        db.scalars(
            select(StreamPermissionUser.user_id)
            .where(StreamPermissionUser.output_stream_id == output_stream_id)
            .order_by(StreamPermissionUser.user_id.asc())
        ).all()
    )


def list_output_stream_group_ids(db: Session, output_stream_id: str) -> list[str]:
    return list(
        db.scalars(
            select(StreamPermissionGroup.group_id)
            .where(StreamPermissionGroup.output_stream_id == output_stream_id)
            .order_by(StreamPermissionGroup.group_id.asc())
        ).all()
    )


def list_user_output_stream_ids(db: Session, user_id: str) -> list[str]:
    return list(
        db.scalars(
            select(StreamPermissionUser.output_stream_id)
            .where(StreamPermissionUser.user_id == user_id)
            .order_by(StreamPermissionUser.output_stream_id.asc())
        ).all()
    )


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
