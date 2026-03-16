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
os.environ.setdefault("INGEST_AUTH_MODE", "open")
os.environ.setdefault("INTERNAL_MEDIA_SECRET_REQUIRED", "true")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.mediamtx_hooks import handle_media_auth
from app.models import AuditLog, Base
from app.schemas import MediaAuthRequest
from app.services.enrollment import enroll_user
from app.services.ingest import create_ingest_session, handle_publish_start, handle_publish_stop, revoke_ingest_session, rotate_ingest_key, transition_ingest_session
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


def test_valid_ingest_lifecycle_transitions():
    db = fresh_db()
    stream = create_stream(db, "Cam", "cam")
    session = create_ingest_session(db, output_stream_id=stream.id, publisher_label="cam-1")
    session = transition_ingest_session(db, session=session, next_status="connecting")
    session = transition_ingest_session(db, session=session, next_status="live")
    session = transition_ingest_session(db, session=session, next_status="offline")
    assert session.status == "offline"
    db.close()


def test_invalid_ingest_transition_rejected():
    db = fresh_db()
    stream = create_stream(db, "Cam", "cam")
    session = create_ingest_session(db, output_stream_id=stream.id)
    try:
        transition_ingest_session(db, session=session, next_status="revoked")
        transition_ingest_session(db, session=session, next_status="live")
        assert False
    except Exception as exc:  # noqa: BLE001
        assert "cannot transition" in str(exc.detail)
    db.close()


def test_publish_start_callback_marks_live_and_stop_marks_offline_idempotently():
    db = fresh_db()
    stream = create_stream(db, "Cam", "cam")
    ingest = create_ingest_session(db, output_stream_id=stream.id, publisher_label="cam-1")
    _, live_session = handle_publish_start(db, ingest_key=ingest.ingest_key, publisher_label="publisher-a")
    assert live_session is not None
    assert live_session.status == "live"
    _, live_session_second = handle_publish_start(db, ingest_key=ingest.ingest_key, publisher_label="publisher-a")
    assert live_session_second is not None
    assert live_session_second.status == "live"
    stopped = handle_publish_stop(db, ingest_key=ingest.ingest_key)
    assert stopped is not None
    assert stopped.status == "offline"
    stopped_again = handle_publish_stop(db, ingest_key=ingest.ingest_key)
    assert stopped_again is not None
    assert stopped_again.status == "offline"
    db.close()


def test_keyed_ingest_auth_denies_invalid_publish_key():
    db = fresh_db()
    previous_mode = os.environ.get("INGEST_AUTH_MODE", "open")
    os.environ["INGEST_AUTH_MODE"] = "keyed"
    get_settings.cache_clear()
    try:
        stream = create_stream(db, "Cam", "cam")
        create_ingest_session(db, output_stream_id=stream.id)
        try:
            handle_media_auth(MediaAuthRequest(action="publish", path="live/not-a-real-key", protocol="rtmp"), db)
            assert False
        except Exception as exc:  # noqa: BLE001
            assert "ingest denied" in str(exc.detail)
    finally:
        os.environ["INGEST_AUTH_MODE"] = previous_mode
        get_settings.cache_clear()
        db.close()


def test_internal_media_auth_requires_secret_when_enabled():
    from app.mediamtx_hooks import assert_internal_secret

    previous_required = os.environ.get("INTERNAL_MEDIA_SECRET_REQUIRED", "true")
    os.environ["INTERNAL_MEDIA_SECRET_REQUIRED"] = "true"
    get_settings.cache_clear()
    try:
        try:
            assert_internal_secret("")
            assert False
        except Exception as exc:  # noqa: BLE001
            assert "invalid internal secret" in str(exc.detail)
        assert_internal_secret(os.environ["INTERNAL_API_SECRET"])
    finally:
        os.environ["INTERNAL_MEDIA_SECRET_REQUIRED"] = previous_required
        get_settings.cache_clear()


def test_rotate_and_revoke_ingest_session():
    db = fresh_db()
    stream = create_stream(db, "Cam", "cam")
    session = create_ingest_session(db, output_stream_id=stream.id)
    original_key = session.ingest_key
    rotated = rotate_ingest_key(db, session.id)
    assert rotated.ingest_key != original_key
    revoked = revoke_ingest_session(db, session.id)
    assert revoked.status == "revoked"
    db.close()
