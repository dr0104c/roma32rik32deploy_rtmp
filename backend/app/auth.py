import secrets
import string
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User


ALPHABET = string.ascii_uppercase + string.digits


def generate_client_code() -> str:
    return f"{_random_code(4)}-{_random_code(4)}"


def generate_stream_key() -> str:
    return secrets.token_urlsafe(24)


def generate_jti() -> str:
    return secrets.token_hex(16)


def _random_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def require_admin_secret(x_admin_secret: str = Header(alias="X-Admin-Secret")) -> None:
    settings = get_settings()
    if not secrets.compare_digest(x_admin_secret, settings.admin_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid admin secret")


def decode_jwt(token: str, secret: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from exc


def get_bearer_token(authorization: str = Header(default="", alias="Authorization")) -> str:
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = authorization[len(prefix):].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    return token


def require_viewer_user(
    request: Request,
    token: str = Depends(get_bearer_token),
    db: Session = Depends(get_db),
) -> User:
    settings = get_settings()
    payload = decode_jwt(token, settings.viewer_session_secret)
    if payload.get("type") != "viewer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid viewer token")

    user_id = int(payload["sub"])
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="viewer not found")
    if user.status != "approved":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"user status is {user.status}")
    if int(payload.get("status_version", 0)) != user.status_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="viewer token is stale")

    request.state.viewer_token_payload = payload
    request.state.viewer_user = user
    return user
