from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..db import engine
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
