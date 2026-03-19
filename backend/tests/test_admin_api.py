import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ADMIN_SECRET", "test-admin-secret-123456789012")
os.environ.setdefault("ADMIN_JWT_SECRET", "test-admin-jwt-secret-123456789012")
os.environ.setdefault("ADMIN_BOOTSTRAP_USERNAME", "admin")
os.environ.setdefault("ADMIN_BOOTSTRAP_PASSWORD", "test-admin-bootstrap-password-123456")
os.environ.setdefault("ADMIN_ACCESS_TOKEN_TTL_SECONDS", "3600")
os.environ.setdefault("LEGACY_ADMIN_SECRET_ENABLED", "true")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret-1234567890")
os.environ.setdefault("PLAYBACK_TOKEN_SECRET", "test-playback-secret-1234567890")
os.environ.setdefault("VIEWER_SESSION_SECRET", "test-viewer-secret-1234567890")
os.environ.setdefault("PUBLIC_HOST", "127.0.0.1")
os.environ.setdefault("PUBLIC_BASE_URL", "http://127.0.0.1:8080")
os.environ.setdefault("WEBRTC_PUBLIC_BASE_URL", "http://127.0.0.1:8080/webrtc")
os.environ.setdefault("TURN_SHARED_SECRET", "test-turn-secret-1234567890")
os.environ.setdefault("TURN_REALM", "127.0.0.1")
os.environ.setdefault("STUN_URLS", "stun:127.0.0.1:3478")
os.environ.setdefault("TURN_URLS", "turn:127.0.0.1:3478?transport=udp")
os.environ.setdefault("INGEST_AUTH_MODE", "keyed")
os.environ.setdefault("INTERNAL_MEDIA_SECRET_REQUIRED", "true")

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.auth import require_admin_access
from app.config import get_settings
from app.models import Base
from app.routes.admin import (
    admin_add_user_to_group,
    admin_create_group,
    admin_create_output_stream,
    admin_grant_group,
    admin_grant_user,
    admin_revoke_group,
    admin_revoke_user,
    admin_user_detail,
    admin_users,
    approve,
    block,
    reject,
    unblock,
)
from app.routes.enroll import enroll
from app.routes.streams import public_list_streams
from app.schemas import CreateGroupRequest, CreateOutputStreamRequest, EnrollRequest, GrantGroupRequest, GrantUserRequest
from app.services.admin_auth import authenticate_admin, ensure_bootstrap_admin, issue_admin_access_token


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base.metadata.create_all(bind=engine)


def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    get_settings.cache_clear()
    db = SessionLocal()
    ensure_bootstrap_admin(db)
    return db


def make_request() -> Request:
    return Request({"type": "http", "headers": []})


def resolve_admin_context(db=None, *, token: str | None = None, admin_secret: str = "", legacy_enabled: str = "true"):
    os.environ["LEGACY_ADMIN_SECRET_ENABLED"] = legacy_enabled
    get_settings.cache_clear()
    owns_db = db is None
    db = db or fresh_db()
    try:
        generator = require_admin_access(request=make_request(), token=token, x_admin_secret=admin_secret, db=db)
        context = next(generator)
        try:
            return context
        finally:
            try:
                next(generator)
            except StopIteration:
                pass
    finally:
        if owns_db:
            db.close()


def test_admin_login_success_and_failure():
    db = fresh_db()
    admin_user = authenticate_admin(db, "admin", "test-admin-bootstrap-password-123456")
    token, expires_in = issue_admin_access_token(db, admin_user)

    assert token
    assert expires_in == 3600

    try:
        authenticate_admin(db, "admin", "wrong")
        assert False
    except HTTPException as exc:
        assert exc.detail["code"] == "admin_credentials_invalid"
    db.close()


def test_protected_admin_route_with_bearer_token():
    db = fresh_db()
    user = enroll(EnrollRequest(display_name="Protected Route User"), db)
    admin_user = authenticate_admin(db, "admin", "test-admin-bootstrap-password-123456")
    token, _ = issue_admin_access_token(db, admin_user)
    context = resolve_admin_context(db, token=token)

    payload = admin_users(status=None, search=None, limit=100, offset=0, db=db)

    assert context.auth_mode == "bearer"
    assert payload.users[0].user_id == user.user_id
    db.close()


def test_legacy_admin_secret_compatibility_mode():
    context = resolve_admin_context(admin_secret="test-admin-secret-123456789012", legacy_enabled="true")
    assert context.auth_mode == "legacy_secret"

    try:
        resolve_admin_context(admin_secret="test-admin-secret-123456789012", legacy_enabled="false")
        assert False
    except HTTPException as exc:
        assert exc.detail["code"] == "admin_auth_required"


def test_approve_reject_block_unblock_routes():
    db = fresh_db()
    user = enroll(EnrollRequest(display_name="Moderated"), db)

    assert reject(user.user_id, db).status == "rejected"
    assert approve(user.user_id, db).status == "approved"
    assert block(user.user_id, db).status == "blocked"
    assert unblock(user.user_id, db).status == "approved"
    db.close()


def test_create_group_assign_user_and_group_acl():
    db = fresh_db()
    user = enroll(EnrollRequest(display_name="Group Viewer"), db)
    approve(user.user_id, db)
    group = admin_create_group(CreateGroupRequest(name="team-alpha"), db)
    stream = admin_create_output_stream(
        CreateOutputStreamRequest(name="Main", public_name="main", title="Main", playback_path="main"),
        db,
    )

    admin_add_user_to_group(user.user_id, group.group_id, db)
    admin_grant_group(stream.output_stream_id, GrantGroupRequest(group_id=group.group_id), db)
    detail = admin_user_detail(user.user_id, db)
    public_streams = public_list_streams(user_id=user.user_id, db=db)
    revoke_response = admin_revoke_group(stream.output_stream_id, group.group_id, db)

    assert group.group_id in detail.group_ids
    assert public_streams.output_streams[0].output_stream_id == stream.output_stream_id
    assert revoke_response.granted is False
    db.close()


def test_grant_and_revoke_user_access_routes():
    db = fresh_db()
    user = enroll(EnrollRequest(display_name="Direct Viewer"), db)
    approve(user.user_id, db)
    stream = admin_create_output_stream(
        CreateOutputStreamRequest(name="Direct", public_name="direct", title="Direct", playback_path="direct"),
        db,
    )

    grant_response = admin_grant_user(stream.output_stream_id, GrantUserRequest(user_id=user.user_id), db)
    detail = admin_user_detail(user.user_id, db)
    revoke_response = admin_revoke_user(stream.output_stream_id, user.user_id, db)

    assert grant_response.granted is True
    assert stream.output_stream_id in detail.output_stream_ids
    assert revoke_response.granted is False
    db.close()
