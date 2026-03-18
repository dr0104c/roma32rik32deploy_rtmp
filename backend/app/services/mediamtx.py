from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from ..config import get_settings


LOGGER = logging.getLogger(__name__)
TRANSCODE_PATH_PREFIX = "_transcode_"


def _api_base_url() -> str:
    return get_settings().mediamtx_control_api_base_url.rstrip("/")


def _path_name(path_name: str) -> str:
    return quote(path_name, safe="")


def _live_path(path_name: str) -> str:
    return f"live/{path_name}"


def transcode_path(playback_path: str) -> str:
    return f"{TRANSCODE_PATH_PREFIX}{playback_path}"


def _internal_rtmp_url(path_name: str, internal_api_secret: str) -> str:
    return f"rtmp://127.0.0.1:1935/live/{path_name}?internal_secret={internal_api_secret}"


def _internal_rtsp_url(path_name: str, internal_api_secret: str) -> str:
    return f"rtsp://127.0.0.1:8554/live/{path_name}?internal_secret={internal_api_secret}"


def build_playback_alias_payload(
    *,
    playback_path: str,
    ingest_key: str,
    transcode_enabled: bool,
    internal_api_secret: str,
) -> dict[str, object]:
    live_playback_path = _live_path(playback_path)
    source_url = _internal_rtmp_url(ingest_key, internal_api_secret)
    if transcode_enabled:
        source_url = _internal_rtsp_url(transcode_path(playback_path), internal_api_secret)

    return {
        "name": live_playback_path,
        "source": source_url,
        "sourceOnDemand": True,
    }


def _request(method: str, path: str, *, json: dict | None = None, allow_404: bool = False) -> None:
    base_url = _api_base_url()
    if not base_url:
        return

    url = f"{base_url}{path}"
    with httpx.Client(timeout=5.0) as client:
        response = client.request(method, url, json=json)

    if allow_404 and response.status_code == 404:
        return
    response.raise_for_status()


def sync_playback_alias(*, playback_path: str, ingest_key: str) -> None:
    settings = get_settings()
    if not settings.mediamtx_control_api_base_url:
        return

    live_playback_path = _live_path(playback_path)
    payload = build_playback_alias_payload(
        playback_path=playback_path,
        ingest_key=ingest_key,
        transcode_enabled=settings.enable_ffmpeg_transcode,
        internal_api_secret=settings.internal_api_secret,
    )

    try:
        _request("DELETE", f"/config/paths/delete/{_path_name(live_playback_path)}", allow_404=True)
        _request("POST", f"/config/paths/add/{_path_name(live_playback_path)}", json=payload)
    except httpx.HTTPError:
        LOGGER.exception("failed to sync MediaMTX playback alias", extra={"playback_path": playback_path})
        raise


def delete_playback_alias(playback_path: str | None) -> None:
    if not playback_path or not _api_base_url():
        return

    try:
        _request("DELETE", f"/config/paths/delete/{_path_name(_live_path(playback_path))}", allow_404=True)
    except httpx.HTTPError:
        LOGGER.exception("failed to delete MediaMTX playback alias", extra={"playback_path": playback_path})
        raise
