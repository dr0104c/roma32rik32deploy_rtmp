import secrets
import string
from collections.abc import Generator
from typing import Any

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from .admin_context import clear_current_admin_actor, set_current_admin_actor
from .config import get_settings
from .errors import unauthorized
from .db import get_db
from .models import User
from .services.admin_auth import AdminAuthContext, validate_admin_access_token


ALPHABET = string.ascii_uppercase + string.digits


def generate_client_code() -> str:
    return f"{_random_code(4)}-{_random_code(4)}"


def generate_ingest_key() -> str:
    return secrets.token_urlsafe(24)


def generate_jti() -> str:
    return secrets.token_hex(16)


def _random_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def require_admin_secret(x_admin_secret: str = Header(alias="X-Admin-Secret")) -> None:
    settings = get_settings()
    if not settings.legacy_admin_secret_enabled:
        raise unauthorized("legacy_admin_secret_disabled", "legacy admin secret auth is disabled")
    if not secrets.compare_digest(x_admin_secret, settings.admin_secret):
        raise unauthorized("admin_secret_invalid", "invalid admin secret")


def decode_jwt(token: str, secret: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise unauthorized("token_invalid", "invalid token") from exc


def get_bearer_token(authorization: str = Header(default="", alias="Authorization")) -> str:
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise unauthorized("bearer_missing", "missing bearer token")
    token = authorization[len(prefix):].strip()
    if not token:
        raise unauthorized("bearer_missing", "missing bearer token")
    return token


def optional_bearer_token(authorization: str = Header(default="", alias="Authorization")) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise unauthorized("bearer_invalid", "invalid bearer token format")
    token = authorization[len(prefix):].strip()
    if not token:
        raise unauthorized("bearer_missing", "missing bearer token")
    return token


def require_admin_bearer(
    token: str | None = Depends(optional_bearer_token),
    db: Session = Depends(get_db),
) -> Generator[AdminAuthContext, None, None]:
    if not token:
        raise unauthorized("admin_bearer_missing", "missing admin bearer token")
    admin_user = validate_admin_access_token(db, token)
    context = AdminAuthContext(
        admin_user_id=admin_user.id,
        username=admin_user.username,
        role=admin_user.role,
        auth_mode="bearer",
    )
    set_current_admin_actor(context.actor_id)
    try:
        yield context
    finally:
        clear_current_admin_actor()


def require_admin_access(
    request: Request,
    token: str | None = Depends(optional_bearer_token),
    x_admin_secret: str = Header(default="", alias="X-Admin-Secret"),
    db: Session = Depends(get_db),
) -> Generator[AdminAuthContext, None, None]:
    settings = get_settings()
    if token:
        admin_user = validate_admin_access_token(db, token)
        context = AdminAuthContext(
            admin_user_id=admin_user.id,
            username=admin_user.username,
            role=admin_user.role,
            auth_mode="bearer",
        )
    else:
        if not settings.legacy_admin_secret_enabled:
            raise unauthorized("admin_auth_required", "missing admin bearer token")
        if not x_admin_secret or not secrets.compare_digest(x_admin_secret, settings.admin_secret):
            raise unauthorized("admin_secret_invalid", "invalid admin secret")
        context = AdminAuthContext(
            admin_user_id=None,
            username="legacy-admin-secret",
            role="legacy-admin",
            auth_mode="legacy_secret",
        )
    request.state.admin_auth = context
    set_current_admin_actor(context.actor_id)
    try:
        yield context
    finally:
        clear_current_admin_actor()


def require_viewer_user(request: Request, token: str = Depends(get_bearer_token), db: Session = Depends(get_db)) -> User:
    settings = get_settings()
    payload = decode_jwt(token, settings.viewer_session_secret)
    if payload.get("scope") != "viewer":
        raise unauthorized("viewer_scope_invalid", "invalid viewer token")
    user = db.get(User, payload.get("sub"))
    if user is None:
        raise unauthorized("viewer_not_found", "viewer not found")
    request.state.viewer_user = user
    return user
