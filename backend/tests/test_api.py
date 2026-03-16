import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ADMIN_SECRET", "test-admin-secret-123456789012")
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

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.mediamtx_hooks import handle_media_auth
from app.models import AuditLog, Base
from app.schemas import MediaAuthRequest
from app.services.enrollment import enroll_user
from app.services.moderation import change_user_status
from app.services.permissions import grant_user_access
from app.services.playback import issue_playback_token
from app.services.streams import create_stream


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base.metadata.create_all(bind=engine)


def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_enroll_creates_pending_user_and_client_code():
    db = fresh_db()
    user = enroll_user(db, "Ivan")
    assert user.status == "pending"
    assert len(user.client_code) == 9
    db.close()


def test_approve_changes_status():
    db = fresh_db()
    user = enroll_user(db, "Maria")
    approved = change_user_status(db, user.id, "approved")
    assert approved.status == "approved"
    db.close()


def test_blocked_user_cannot_get_playback_token():
    db = fresh_db()
    user = enroll_user(db, "Blocked")
    change_user_status(db, user.id, "approved")
    change_user_status(db, user.id, "blocked")
    stream = create_stream(db, "Main", "main")
    grant_user_access(db, stream.id, user.id)
    try:
        issue_playback_token(db, user_id=user.id, stream_id=stream.id)
        assert False
    except Exception as exc:  # noqa: BLE001
        assert "approved" in str(exc.detail)
    db.close()


def test_user_without_permission_cannot_get_playback_token():
    db = fresh_db()
    user = enroll_user(db, "NoPerm")
    change_user_status(db, user.id, "approved")
    stream = create_stream(db, "Restricted", "restricted")
    try:
        issue_playback_token(db, user_id=user.id, stream_id=stream.id)
        assert False
    except Exception as exc:  # noqa: BLE001
        assert "access is not granted" in str(exc.detail)
    db.close()


def test_approved_user_with_permission_gets_playback_token():
    db = fresh_db()
    user = enroll_user(db, "Allowed")
    change_user_status(db, user.id, "approved")
    stream = create_stream(db, "Viewer", "viewer")
    grant_user_access(db, stream.id, user.id)
    token, expires_at, playback_url = issue_playback_token(db, user_id=user.id, stream_id=stream.id)
    assert token
    assert expires_at
    assert stream.playback_name in playback_url
    db.close()


def test_direct_rtmp_playback_auth_denied():
    db = fresh_db()
    user = enroll_user(db, "Allowed")
    change_user_status(db, user.id, "approved")
    stream = create_stream(db, "Viewer", "viewer")
    grant_user_access(db, stream.id, user.id)
    token, _, _ = issue_playback_token(db, user_id=user.id, stream_id=stream.id)
    try:
        handle_media_auth(MediaAuthRequest(action="read", path=f"live/{stream.playback_name}", protocol="rtmp", query=f"token={token}"), db)
        assert False
    except Exception as exc:  # noqa: BLE001
        assert "rtmp playback disabled" in str(exc.detail)
    db.close()


def test_playback_auth_with_invalid_token_denied_and_valid_allowed():
    db = fresh_db()
    user = enroll_user(db, "Allowed")
    change_user_status(db, user.id, "approved")
    stream = create_stream(db, "Viewer", "viewer")
    grant_user_access(db, stream.id, user.id)
    token, _, _ = issue_playback_token(db, user_id=user.id, stream_id=stream.id)

    try:
        handle_media_auth(MediaAuthRequest(action="read", path=f"live/{stream.playback_name}", protocol="whep", query="token=invalid"), db)
        assert False
    except Exception as exc:  # noqa: BLE001
        assert "invalid token" in str(exc.detail)

    assert handle_media_auth(
        MediaAuthRequest(action="read", path=f"live/{stream.playback_name}", protocol="whep", query=f"token={token}"),
        db,
    ) == {"status": "ok"}
    db.close()


def test_audit_records_created_for_critical_actions():
    db = fresh_db()
    user = enroll_user(db, "Audit")
    change_user_status(db, user.id, "approved")
    stream = create_stream(db, "AuditStream", "audit-stream")
    grant_user_access(db, stream.id, user.id)
    issue_playback_token(db, user_id=user.id, stream_id=stream.id)
    actions = {row.action for row in db.scalars(select(AuditLog)).all()}
    assert "user_enrolled" in actions
    assert "user_approved" in actions
    assert "stream_created" in actions
    assert "grant_user_stream" in actions
    assert "playback_token_issued" in actions
    db.close()
