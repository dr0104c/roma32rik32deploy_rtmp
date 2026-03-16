import logging

from fastapi import FastAPI

from .mediamtx_hooks import router as mediamtx_router
from .config import get_settings
from .routes.admin import router as admin_router
from .routes.enroll import router as enroll_router
from .routes.health import router as health_router
from .routes.playback import router as playback_router
from .routes.streams import router as streams_router
from .routes.viewer import router as viewer_router


settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


app = FastAPI(title="stream-platform-backend", version="0.3.0")

app.include_router(health_router)
app.include_router(enroll_router)
app.include_router(admin_router)
app.include_router(streams_router)
app.include_router(playback_router)
app.include_router(viewer_router)
app.include_router(mediamtx_router)
