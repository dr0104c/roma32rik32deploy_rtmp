import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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

from app.db import get_db
from app.main import app
from app.models import Base


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def fresh_client() -> TestClient:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_product_model_separates_ingest_key_from_playback_path():
    client = fresh_client()
    admin_headers = {"X-Admin-Secret": os.environ["ADMIN_SECRET"]}
    internal_headers = {"X-Internal-Secret": os.environ["INTERNAL_API_SECRET"]}

    enroll = client.post("/api/v1/enroll", json={"display_name": "Product Model Viewer"})
    assert enroll.status_code == 201
    user = enroll.json()
    user_id = user["user_id"]
    client_code = user["client_code"]

    approve = client.post(f"/api/v1/admin/users/{user_id}/approve", headers=admin_headers)
    assert approve.status_code == 200

    output_stream = client.post(
        "/api/v1/admin/output-streams",
        json={
            "name": "Main Stage",
            "public_name": "main-stage",
            "title": "Main Stage",
            "playback_path": "main-stage-watch",
        },
        headers=admin_headers,
    )
    assert output_stream.status_code == 201
    output_stream_body = output_stream.json()
    output_stream_id = output_stream_body["output_stream_id"]
    playback_path = output_stream_body["playback_path"]

    ingest_session = client.post(
        "/api/v1/admin/ingest-sessions",
        json={"current_output_stream_id": output_stream_id, "source_label": "encoder-a"},
        headers=admin_headers,
    )
    assert ingest_session.status_code == 201
    ingest_session_body = ingest_session.json()
    ingest_key = ingest_session_body["ingest_key"]

    grant = client.post(
        f"/api/v1/admin/output-streams/{output_stream_id}/grant-user",
        json={"user_id": user_id},
        headers=admin_headers,
    )
    assert grant.status_code == 200

    assert playback_path != ingest_key

    public_streams = client.get("/api/v1/streams", params={"user_id": user_id})
    assert public_streams.status_code == 200
    public_streams_body = public_streams.json()
    assert public_streams_body["output_streams"][0]["output_stream_id"] == output_stream_id
    assert public_streams_body["output_streams"][0]["playback_path"] == playback_path
    assert "ingest_key" not in public_streams.text
    assert "source_ingest_session_id" not in public_streams.text

    viewer_session = client.post("/api/v1/viewer/session", json={"client_code": client_code})
    assert viewer_session.status_code == 200
    viewer_token = viewer_session.json()["viewer_token"]

    viewer_streams = client.get("/api/v1/viewer/streams", headers={"Authorization": f"Bearer {viewer_token}"})
    assert viewer_streams.status_code == 200
    assert viewer_streams.json()["streams"][0]["output_stream_id"] == output_stream_id
    assert "ingest_key" not in viewer_streams.text
    assert "source_ingest_session_id" not in viewer_streams.text

    token_by_id = client.post("/api/v1/playback-token", json={"user_id": user_id, "output_stream_id": output_stream_id})
    assert token_by_id.status_code == 200
    token_by_id_body = token_by_id.json()
    assert token_by_id_body["output_stream_id"] == output_stream_id
    assert f"/live/{playback_path}/whep?token=" in token_by_id_body["playback_url"]
    assert ingest_key not in token_by_id_body["playback_url"]

    token_by_path = client.post("/api/v1/playback-token", json={"user_id": user_id, "playback_path": playback_path})
    assert token_by_path.status_code == 200
    assert token_by_path.json()["playback_path"] == playback_path

    token_with_ingest_key = client.post("/api/v1/playback-token", json={"user_id": user_id, "playback_path": ingest_key})
    assert token_with_ingest_key.status_code == 400
    assert token_with_ingest_key.json()["error"]["code"] == "ingest_key_not_playback_identifier"

    publish = client.post(
        "/internal/media/auth",
        json={"action": "publish", "path": f"live/{ingest_key}", "protocol": "rtmp"},
        headers=internal_headers,
    )
    assert publish.status_code == 200

    rtmp_read_ingest = client.post(
        "/internal/media/auth",
        json={"action": "read", "path": f"live/{ingest_key}", "protocol": "rtmp"},
        headers=internal_headers,
    )
    assert rtmp_read_ingest.status_code == 401
    assert rtmp_read_ingest.json()["error"]["code"] == "rtmp_playback_disabled"

    rtmp_read_output = client.post(
        "/internal/media/auth",
        json={"action": "read", "path": f"live/{playback_path}", "protocol": "rtmp"},
        headers=internal_headers,
    )
    assert rtmp_read_output.status_code == 401
    assert rtmp_read_output.json()["error"]["code"] == "rtmp_playback_disabled"

    viewer_playback = client.post(
        f"/api/v1/viewer/streams/{output_stream_id}/playback-session",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert viewer_playback.status_code == 200
    viewer_playback_body = viewer_playback.json()
    assert viewer_playback_body["output_stream"]["playback_path"] == playback_path
    assert f"/live/{playback_path}/whep?token=" in viewer_playback_body["playback"]["webrtc_url"]
    assert ingest_key not in viewer_playback_body["playback"]["webrtc_url"]

    whep_auth = client.post(
        "/internal/media/auth",
        json={
            "action": "read",
            "path": f"live/{playback_path}",
            "protocol": "whep",
            "query": f"token={token_by_id_body['token']}",
        },
        headers=internal_headers,
    )
    assert whep_auth.status_code == 200

    app.dependency_overrides.clear()
