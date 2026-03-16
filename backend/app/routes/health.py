from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import engine, get_db
from ..models import AuditLog, IngestSession, OutputStream, User
from ..schemas import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/health/ready")
def health_ready():
    settings = get_settings()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "ready": False, "reason": f"database: {exc.__class__.__name__}"},
        )

    missing = []
    for key in ("database_url", "admin_secret", "internal_api_secret", "playback_token_secret", "viewer_session_secret"):
        if not getattr(settings, key, ""):
            missing.append(key)
    if missing:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "degraded", "ready": False, "reason": f"missing config: {','.join(missing)}"},
        )

    return {"status": "ok", "ready": True}


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    return {
        "users_total": len(list(db.scalars(select(User)).all())),
        "streams_total": len(list(db.scalars(select(OutputStream)).all())),
        "ingest_live_total": len(list(db.scalars(select(IngestSession).where(IngestSession.status == "live")).all())),
        "media_auth_failures_total": len(
            list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.actor_type == "media",
                        AuditLog.action.in_(["publish_denied", "media_auth_denied", "rtmp_playback_denied"]),
                    )
                ).all()
            )
        ),
    }
