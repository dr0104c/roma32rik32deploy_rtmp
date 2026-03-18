from __future__ import annotations

import logging
import shlex
from urllib.parse import quote

import httpx

from ..config import get_settings


LOGGER = logging.getLogger(__name__)


def _api_base_url() -> str:
    return get_settings().mediamtx_control_api_base_url.rstrip("/")


def _path_name(path_name: str) -> str:
    return quote(path_name, safe="")


def _live_path(path_name: str) -> str:
    return f"live/{path_name}"


def build_playback_alias_payload(*, playback_path: str, ingest_key: str, transcode_enabled: bool) -> dict[str, object]:
    live_playback_path = _live_path(playback_path)
    ingest_rtmp_url = f"rtmp://127.0.0.1:1935/live/{ingest_key}"

    if not transcode_enabled:
        return {
            "name": live_playback_path,
            "source": ingest_rtmp_url,
            "sourceOnDemand": True,
        }

    publish_rtmp_url = f"rtmp://127.0.0.1:1935/{live_playback_path}"
    ffmpeg_command = " ".join(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "warning",
            "-i",
            shlex.quote(ingest_rtmp_url),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-c:v",
            "copy",
            "-c:a",
            "libopus",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-f",
            "flv",
            shlex.quote(publish_rtmp_url),
        ]
    )
    return {
        "name": live_playback_path,
        "source": "publisher",
        "runOnDemand": ffmpeg_command,
        "runOnDemandRestart": False,
        "runOnDemandStartTimeout": "20s",
        "runOnDemandCloseAfter": "10s",
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
