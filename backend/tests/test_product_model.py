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

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.mediamtx_hooks import handle_media_auth
from app.models import Base, User
from app.routes.admin import admin_create_output_stream, admin_grant_user, approve, create_ingest
from app.routes.enroll import enroll
from app.routes.playback import playback_token
from app.routes.streams import public_list_streams
from app.routes.viewer import viewer_playback_session, viewer_session, viewer_streams
from app.schemas import (
    CreateIngestSessionRequest,
    CreateOutputStreamRequest,
    EnrollRequest,
    GrantUserRequest,
    MediaAuthRequest,
    PlaybackTokenRequest,
    ViewerSessionRequest,
)


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base.metadata.create_all(bind=engine)


def fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_product_model_separates_ingest_key_from_playback_path():
    db = fresh_db()

    user_response = enroll(EnrollRequest(display_name="Product Model Viewer"), db)
    user_id = user_response.user_id
    client_code = user_response.client_code

    approve(user_id, db)

    output_stream_response = admin_create_output_stream(
        CreateOutputStreamRequest(
            name="Main Stage",
            public_name="main-stage",
            title="Main Stage",
            playback_path="main-stage-watch",
        ),
        db,
    )
    output_stream_id = output_stream_response.output_stream_id
    playback_path = output_stream_response.playback_path

    ingest_session_response = create_ingest(
        CreateIngestSessionRequest(current_output_stream_id=output_stream_id, source_label="encoder-a"),
        db,
    )
    ingest_key = ingest_session_response.ingest_key

    admin_grant_user(output_stream_id, GrantUserRequest(user_id=user_id), db)

    assert playback_path != ingest_key

    public_streams_response = public_list_streams(user_id=user_id, db=db)
    public_streams_dump = public_streams_response.model_dump()
    assert public_streams_dump["output_streams"][0]["output_stream_id"] == output_stream_id
    assert public_streams_dump["output_streams"][0]["playback_path"] == playback_path
    assert "ingest_key" not in str(public_streams_dump)
    assert "source_ingest_session_id" not in str(public_streams_dump)

    viewer_session_response = viewer_session(ViewerSessionRequest(client_code=client_code), db)
    viewer_token = viewer_session_response.viewer_token
    assert viewer_token

    user = db.get(User, user_id)
    viewer_streams_response = viewer_streams(user=user, db=db)
    viewer_streams_dump = viewer_streams_response.model_dump()
    assert viewer_streams_dump["streams"][0]["output_stream_id"] == output_stream_id
    assert "ingest_key" not in str(viewer_streams_dump)
    assert "source_ingest_session_id" not in str(viewer_streams_dump)

    token_by_id_response = playback_token(PlaybackTokenRequest(user_id=user_id, output_stream_id=output_stream_id), db)
    token_by_id_dump = token_by_id_response.model_dump()
    assert token_by_id_dump["output_stream_id"] == output_stream_id
    assert f"/live/{playback_path}/whep?token=" in token_by_id_dump["playback_url"]
    assert ingest_key not in token_by_id_dump["playback_url"]

    token_by_path_response = playback_token(PlaybackTokenRequest(user_id=user_id, playback_path=playback_path), db)
    assert token_by_path_response.playback_path == playback_path

    try:
        playback_token(PlaybackTokenRequest(user_id=user_id, playback_path=ingest_key), db)
        assert False
    except Exception as exc:  # noqa: BLE001
        assert exc.detail["code"] == "ingest_key_not_playback_identifier"

    assert handle_media_auth(
        MediaAuthRequest(action="publish", path=f"live/{ingest_key}", protocol="rtmp"),
        db,
    ) == {"status": "ok"}

    try:
        handle_media_auth(
            MediaAuthRequest(action="read", path=f"live/{ingest_key}", protocol="rtmp"),
            db,
        )
        assert False
    except Exception as exc:  # noqa: BLE001
        assert exc.detail["code"] == "rtmp_playback_disabled"

    try:
        handle_media_auth(
            MediaAuthRequest(action="read", path=f"live/{playback_path}", protocol="rtmp"),
            db,
        )
        assert False
    except Exception as exc:  # noqa: BLE001
        assert exc.detail["code"] == "rtmp_playback_disabled"

    viewer_playback_response = viewer_playback_session(output_stream_id, user=user, db=db)
    viewer_playback_dump = viewer_playback_response.model_dump()
    assert viewer_playback_dump["output_stream"]["playback_path"] == playback_path
    assert f"/live/{playback_path}/whep?token=" in viewer_playback_dump["playback"]["webrtc_url"]
    assert ingest_key not in viewer_playback_dump["playback"]["webrtc_url"]

    assert handle_media_auth(
        MediaAuthRequest(
            action="read",
            path=f"live/{playback_path}",
            protocol="whep",
            query=f"token={token_by_id_response.token}",
        ),
        db,
    ) == {"status": "ok"}

    db.close()
