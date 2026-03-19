from __future__ import annotations

import atexit
import logging
import subprocess
import threading
import time

from ..config import get_settings
from .mediamtx import transcode_path


LOGGER = logging.getLogger(__name__)

_LOCK = threading.Lock()
_TRANSCODERS: dict[str, "_TranscoderHandle"] = {}


class _TranscoderHandle:
    def __init__(self, *, playback_path: str, ingest_key: str):
        self.playback_path = playback_path
        self.ingest_key = ingest_key
        self.stop_event = threading.Event()
        self.process: subprocess.Popen[bytes] | None = None
        self.thread = threading.Thread(target=self._run, name=f"ffmpeg-transcoder-{playback_path}", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.thread.join(timeout=1)

    def _run(self) -> None:
        command = _build_ffmpeg_command(playback_path=self.playback_path, ingest_key=self.ingest_key)
        while not self.stop_event.is_set():
            try:
                self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                exit_code = self.process.wait()
            except OSError:
                LOGGER.exception("failed to start ffmpeg transcoder", extra={"playback_path": self.playback_path})
                return
            finally:
                self.process = None

            if self.stop_event.is_set():
                return

            LOGGER.warning(
                "ffmpeg transcoder exited; restarting",
                extra={"playback_path": self.playback_path, "exit_code": exit_code},
            )
            time.sleep(1)


def _build_ffmpeg_command(*, playback_path: str, ingest_key: str) -> list[str]:
    internal_secret = get_settings().internal_api_secret
    mediamtx_rtmp_base_url = "rtmp://mediamtx:1935/live"
    mediamtx_rtsp_base_url = "rtsp://mediamtx:8554/live"
    return [
        "ffmpeg",
        "-nostdin",
        "-loglevel",
        "warning",
        "-i",
        f"{mediamtx_rtmp_base_url}/{ingest_key}?internal_secret={internal_secret}",
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "baseline",
        "-level:v",
        "4.0",
        "-g",
        "60",
        "-keyint_min",
        "60",
        "-sc_threshold",
        "0",
        "-c:a",
        "libopus",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        f"{mediamtx_rtsp_base_url}/{transcode_path(playback_path)}?internal_secret={internal_secret}",
    ]


def start_transcoder(*, playback_path: str, ingest_key: str) -> None:
    with _LOCK:
        handle = _TRANSCODERS.get(playback_path)
        if handle is not None:
            return

        handle = _TranscoderHandle(playback_path=playback_path, ingest_key=ingest_key)
        _TRANSCODERS[playback_path] = handle
        handle.start()


def stop_transcoder(playback_path: str | None) -> None:
    if not playback_path:
        return

    with _LOCK:
        handle = _TRANSCODERS.pop(playback_path, None)

    if handle is not None:
        handle.stop()


@atexit.register
def _shutdown_transcoders() -> None:
    with _LOCK:
        handles = list(_TRANSCODERS.values())
        _TRANSCODERS.clear()

    for handle in handles:
        handle.stop()
