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
os.environ.setdefault("INGEST_AUTH_MODE", "keyed")
os.environ.setdefault("INTERNAL_MEDIA_SECRET_REQUIRED", "true")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.mediamtx_hooks import handle_media_auth
from app.models import AuditLog, Base
from app.schemas import MediaAuthRequest
from app.services.enrollment import enroll_user
from app.services.ingest import create_ingest_session, mark_ingest_started, mark_ingest_stopped, revoke_ingest_session, rotate_ingest_key
from app.services.mediamtx import build_playback_alias_payload
from app.services.moderation import change_user_status
from app.services.permissions import grant_group_to_output_stream, grant_user_to_output_stream
from app.services.playback import issue_playback_token_for_output_stream
from app.services.streams import create_output_stream


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


def test_approved_user_with_output_stream_permission_gets_playback_token():
    db = fresh_db()
    user = enroll_user(db, "Allowed")
    change_user_status(db, user.id, "approved")
    output_stream = create_output_stream(db, name="Viewer", public_name="viewer", title="Viewer", playback_path="viewer-main")
    grant_user_to_output_stream(db, output_stream.id, user.id)
    token, expires_at, playback_url, issued_stream = issue_playback_token_for_output_stream(db, user_id=user.id, output_stream_id=output_stream.id)
    assert token
    assert expires_at
    assert issued_stream.id == output_stream.id
    assert output_stream.playback_path in playback_url
    db.close()


def test_playback_token_cannot_be_issued_without_acl():
    db = fresh_db()
    user = enroll_user(db, "NoPerm")
    change_user_status(db, user.id, "approved")
    output_stream = create_output_stream(db, name="Restricted", public_name="restricted", title="Restricted")
    try:
        issue_playback_token_for_output_stream(db, user_id=user.id, output_stream_id=output_stream.id)
        assert False
    except Exception as exc:  # noqa: BLE001
        assert "access is not granted" in str(exc.detail)
    db.close()


def test_playback_auth_uses_output_stream_path_and_blocks_rtmp():
    db = fresh_db()
    user = enroll_user(db, "Viewer")
    change_user_status(db, user.id, "approved")
    output_stream = create_output_stream(db, name="Viewer", public_name="viewer", title="Viewer", playback_path="viewer-main")
    grant_user_to_output_stream(db, output_stream.id, user.id)
    token, _, _, _ = issue_playback_token_for_output_stream(db, user_id=user.id, output_stream_id=output_stream.id)

    assert handle_media_auth(
        MediaAuthRequest(action="read", path=f"live/{output_stream.playback_path}", protocol="whep", query=f"token={token}"),
        db,
    ) == {"status": "ok"}

    try:
        handle_media_auth(MediaAuthRequest(action="read", path=f"live/{output_stream.playback_path}", protocol="rtmp", query=f"token={token}"), db)
        assert False
    except Exception as exc:  # noqa: BLE001
        assert "rtmp playback disabled" in str(exc.detail)
    db.close()


def test_internal_rtmp_alias_pull_is_allowed_for_loopback_ingest_key():
    db = fresh_db()
    output_stream = create_output_stream(db, name="Viewer", public_name="viewer", title="Viewer", playback_path="viewer-main")
    ingest_session = create_ingest_session(db, current_output_stream_id=output_stream.id, source_label="cam-1")
    mark_ingest_started(db, ingest_key=ingest_session.ingest_key, source_label="publisher-a")

    assert handle_media_auth(
        MediaAuthRequest(
            action="read",
            path=f"live/{ingest_session.ingest_key}",
            protocol="rtmp",
            ip="127.0.0.1",
        ),
        db,
    ) == {"status": "ok"}
    db.close()


def test_internal_transcode_publish_is_allowed_for_loopback_playback_path():
    db = fresh_db()
    output_stream = create_output_stream(db, name="Viewer", public_name="viewer", title="Viewer", playback_path="viewer-main")

    assert handle_media_auth(
        MediaAuthRequest(
            action="publish",
            path=f"live/{output_stream.playback_path}",
            protocol="rtmp",
            ip="127.0.0.1",
        ),
        db,
    ) == {"status": "ok"}
    db.close()


def test_playback_alias_payload_uses_opus_transcode_when_enabled():
    payload = build_playback_alias_payload(playback_path="viewer-main", ingest_key="ingest-key", transcode_enabled=True)

    assert payload["name"] == "live/viewer-main"
    assert payload["source"] == "publisher"
    assert "runOnDemand" in payload
    assert "libopus" in payload["runOnDemand"]
    assert "rtmp://127.0.0.1:1935/live/ingest-key" in payload["runOnDemand"]
    assert "rtmp://127.0.0.1:1935/live/viewer-main" in payload["runOnDemand"]


def test_ingest_publish_flow_uses_ingest_key_and_binds_output_stream():
    db = fresh_db()
    output_stream = create_output_stream(db, name="Cam", public_name="cam", title="Camera", playback_path="cam-live")
    ingest_session = create_ingest_session(db, current_output_stream_id=output_stream.id, source_label="cam-1")
    started_session, resolved_output_stream = mark_ingest_started(db, ingest_key=ingest_session.ingest_key, source_label="publisher-a")
    assert started_session.status == "live"
    assert resolved_output_stream.id == output_stream.id
    assert resolved_output_stream.source_ingest_session_id == ingest_session.id
    stopped_session = mark_ingest_stopped(db, ingest_key=ingest_session.ingest_key)
    assert stopped_session is not None
    assert stopped_session.status == "ended"
    db.close()


def test_revoked_ingest_session_cannot_publish():
    db = fresh_db()
    ingest_session = create_ingest_session(db, source_label="cam-1")
    revoke_ingest_session(db, ingest_session.id)
    try:
        handle_media_auth(MediaAuthRequest(action="publish", path=f"live/{ingest_session.ingest_key}", protocol="rtmp"), db)
        assert False
    except Exception as exc:  # noqa: BLE001
        assert "ingest denied" in str(exc.detail)
    db.close()


def test_rotate_and_revoke_ingest_session():
    db = fresh_db()
    ingest_session = create_ingest_session(db, source_label="cam")
    original_key = ingest_session.ingest_key
    rotated = rotate_ingest_key(db, ingest_session.id)
    assert rotated.ingest_key != original_key
    revoked = revoke_ingest_session(db, ingest_session.id)
    assert revoked.status == "revoked"
    db.close()


def test_group_grant_api_service_exists_for_output_stream_acl():
    db = fresh_db()
    output_stream = create_output_stream(db, name="Cam", public_name="cam", title="Cam")
    try:
        grant_group_to_output_stream(db, output_stream.id, "missing-group")
        assert False
    except Exception as exc:  # noqa: BLE001
        assert "group not found" in str(exc.detail)
    db.close()


def test_audit_records_created_for_product_flow():
    db = fresh_db()
    user = enroll_user(db, "Audit")
    change_user_status(db, user.id, "approved")
    output_stream = create_output_stream(db, name="Audit", public_name="audit", title="Audit")
    ingest_session = create_ingest_session(db, current_output_stream_id=output_stream.id)
    grant_user_to_output_stream(db, output_stream.id, user.id)
    issue_playback_token_for_output_stream(db, user_id=user.id, output_stream_id=output_stream.id)
    mark_ingest_started(db, ingest_key=ingest_session.ingest_key)
    actions = {row.action for row in db.scalars(select(AuditLog)).all()}
    assert "output_stream_created" in actions
    assert "ingest_session_created" in actions
    assert "grant_user_output_stream" in actions
    assert "playback_token_issued" in actions
    assert "ingest_started" in actions
    db.close()
