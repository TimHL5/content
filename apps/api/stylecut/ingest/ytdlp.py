"""YtDlpProvider: YouTube Shorts, Instagram Reels, TikTok.

Only reachable when ENABLE_URL_INGEST is on (see `registry.get_provider`). Platform
downloaders break often and are subject to each platform's terms: the downloaded file
is used for analysis only and expires after 24h.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from stylecut.ingest.base import LocalFile, ProgressFn, SourceMeta
from stylecut.ingest.errors import IngestError, classify_downloader_error
from stylecut.ingest.urls import normalize_url
from stylecut.settings import get_settings

YdlFactory = Callable[[dict[str, Any]], Any]


class _SilentLogger:
    def debug(self, _: str) -> None: ...
    def info(self, _: str) -> None: ...
    def warning(self, _: str) -> None: ...
    def error(self, _: str) -> None: ...


def _default_factory(options: dict[str, Any]) -> Any:
    from yt_dlp import YoutubeDL  # imported lazily: only the io worker needs it

    return YoutubeDL(options)


class YtDlpProvider:
    name = "yt-dlp"

    def __init__(self, factory: YdlFactory = _default_factory) -> None:
        self._factory = factory

    def can_handle(self, source: str) -> bool:
        try:
            normalize_url(source)
        except IngestError:
            return False
        return True

    def fetch(
        self, source: str, dest_dir: Path, on_progress: ProgressFn | None = None
    ) -> tuple[LocalFile, SourceMeta]:
        settings = get_settings()
        target = normalize_url(source)

        def hook(status: dict[str, Any]) -> None:
            if on_progress is None or status.get("status") != "downloading":
                return
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            done = status.get("downloaded_bytes")
            if total and done is not None:
                on_progress(min(float(done) / float(total), 1.0))

        options: dict[str, Any] = {
            "outtmpl": str(dest_dir / "source.%(ext)s"),
            "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
            "merge_output_format": "mp4",
            "max_filesize": settings.max_reference_bytes,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": 20,
            "retries": 2,
            "logger": _SilentLogger(),
            "progress_hooks": [hook],
        }
        try:
            with self._factory(options) as ydl:
                info = ydl.extract_info(target.url, download=False) or {}
                if info.get("is_live"):
                    raise IngestError("INGEST_FAILED", detail="live stream")
                duration = info.get("duration")
                if duration is not None and float(duration) > settings.max_reference_duration_s:
                    raise IngestError("INGEST_TOO_LONG")
                ydl.download([target.url])
        except IngestError:
            raise
        except Exception as exc:
            # yt-dlp raises DownloadError/ExtractorError with a readable message.
            message = str(exc)
            raise IngestError(classify_downloader_error(message), detail=message[:500]) from None

        files = sorted(
            (p for p in dest_dir.glob("source.*") if p.suffix not in (".part", ".ytdl")),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if not files:
            # yt-dlp skips silently when a file exceeds max_filesize.
            raise IngestError("INGEST_TOO_LARGE")
        path = files[0]
        size = path.stat().st_size
        if size > settings.max_reference_bytes:
            raise IngestError("INGEST_TOO_LARGE")
        if on_progress is not None:
            on_progress(1.0)
        return LocalFile(path, size), SourceMeta(platform=target.platform, source_url=target.url)
