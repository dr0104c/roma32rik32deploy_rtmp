from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import forbidden, not_found, unauthorized
from ..models import AdminUser
from .audit import write_audit_log


SALT_BYTES = 16
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class AdminAuthContext:
    admin_user_id: str | None
    username: str
    role: str
    auth_mode: str

    @property
    def actor_id(self) -> str:
        return self.admin_user_id or "legacy-admin-secret"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(derived)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, n_value, r_value, p_value, salt_b64, derived_b64 = password_hash.split("$", 5)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hashlib.scrypt(
        password.encode("utf-8"),
        salt=_unb64(salt_b64),
        n=int(n_value),
        r=int(r_value),
        p=int(p_value),
        dklen=len(_unb64(derived_b64)),
    )
    return hmac.compare_digest(candidate, _unb64(derived_b64))


def get_admin_user(db: Session, admin_user_id: str) -> AdminUser:
    admin_user = db.get(AdminUser, admin_user_id)
    if admin_user is None:
        raise not_found("admin_user_not_found", "admin user not found")
    return admin_user


def ensure_bootstrap_admin(db: Session) -> AdminUser | None:
    existing = db.scalar(select(AdminUser).limit(1))
    if existing is not None:
        return existing

    settings = get_settings()
    if not settings.admin_bootstrap_username or not settings.admin_bootstrap_password:
        return None

    admin_user = AdminUser(
        username=settings.admin_bootstrap_username.strip().lower(),
        password_hash=hash_password(settings.admin_bootstrap_password),
        role="owner",
        is_active=True,
    )
    db.add(admin_user)
    db.flush()
    write_audit_log(
        db,
        actor_type="system",
        actor_id="bootstrap",
        action="admin_bootstrap_created",
        target_type="admin_user",
        target_id=admin_user.id,
        metadata={"username": admin_user.username, "role": admin_user.role},
    )
    db.commit()
    db.refresh(admin_user)
    return admin_user


def authenticate_admin(db: Session, username: str, password: str) -> AdminUser:
    ensure_bootstrap_admin(db)
    admin_user = db.scalar(select(AdminUser).where(AdminUser.username == username.strip().lower()))
    if admin_user is None or not verify_password(password, admin_user.password_hash):
        raise unauthorized("admin_credentials_invalid", "invalid admin credentials")
    if not admin_user.is_active:
        raise forbidden("admin_user_inactive", "admin user is inactive")
    return admin_user


def issue_admin_access_token(db: Session, admin_user: AdminUser) -> tuple[str, int]:
    settings = get_settings()
    now = utcnow()
    expires_in = settings.admin_access_token_ttl_seconds
    payload = {
        "sub": admin_user.id,
        "username": admin_user.username,
        "role": admin_user.role,
        "scope": "admin",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
    }
    token = jwt.encode(payload, settings.admin_jwt_secret or settings.admin_secret, algorithm="HS256")
    write_audit_log(
        db,
        actor_type="admin",
        actor_id=admin_user.id,
        action="admin_login_success",
        target_type="admin_user",
        target_id=admin_user.id,
        metadata={"username": admin_user.username, "auth_mode": "bearer"},
    )
    db.commit()
    return token, expires_in


def validate_admin_access_token(db: Session, token: str) -> AdminUser:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.admin_jwt_secret or settings.admin_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise unauthorized("admin_token_invalid", "invalid admin token") from exc
    if payload.get("scope") != "admin":
        raise unauthorized("admin_scope_invalid", "invalid admin token scope")
    admin_user = get_admin_user(db, payload.get("sub", ""))
    if not admin_user.is_active:
        raise forbidden("admin_user_inactive", "admin user is inactive")
    return admin_user
