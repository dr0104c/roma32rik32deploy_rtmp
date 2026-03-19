import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import SessionLocal
from .mediamtx_hooks import router as media_router
from .routes.admin_auth import router as admin_auth_router
from .routes.admin import router as admin_router
from .routes.enroll import router as enroll_router
from .routes.health import router as health_router
from .routes.playback import router as playback_router
from .routes.streams import router as streams_router
from .routes.viewer import router as viewer_router
from .services.admin_auth import ensure_bootstrap_admin
from .services.ingest import reconcile_live_ingests


settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="stream-platform-backend", version="0.4.0")


@app.on_event("startup")
def restore_live_ingests() -> None:
    db = SessionLocal()
    try:
        ensure_bootstrap_admin(db)
        reconcile_live_ingests(db)
    finally:
        db.close()


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and {"code", "message"} <= set(exc.detail):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": "http_error", "message": str(exc.detail)}})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"error": {"code": "validation_error", "message": str(exc.errors())}})


app.include_router(health_router)
app.include_router(enroll_router)
app.include_router(admin_auth_router)
app.include_router(admin_router)
app.include_router(streams_router)
app.include_router(playback_router)
app.include_router(viewer_router)
app.include_router(media_router)
