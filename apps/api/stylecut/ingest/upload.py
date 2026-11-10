"""UploadProvider: files the user uploaded straight to S3. Always available."""

from pathlib import Path
from urllib.parse import urlsplit

from stylecut.ingest.base import LocalFile, ProgressFn, SourceMeta
from stylecut.ingest.errors import IngestError
from stylecut.settings import get_settings
from stylecut.storage import s3


def upload_source(key: str) -> str:
    return f"s3://{get_settings().s3_bucket}/{key}"


class UploadProvider:
    name = "upload"

    def can_handle(self, source: str) -> bool:
        parts = urlsplit(source)
        return parts.scheme == "s3" and parts.netloc == get_settings().s3_bucket

    def fetch(
        self, source: str, dest_dir: Path, on_progress: ProgressFn | None = None
    ) -> tuple[LocalFile, SourceMeta]:
        key = urlsplit(source).path.lstrip("/")
        dest = dest_dir / f"source{Path(key).suffix or '.mp4'}"
        try:
            s3.download_file(key, dest)
        except s3.ObjectNotFound:
            raise IngestError("INGEST_FAILED", detail=f"missing object {key}") from None
        if on_progress is not None:
            on_progress(1.0)
        return (
            LocalFile(dest, dest.stat().st_size),
            SourceMeta(platform="upload", source_url=None, already_stored=True),
        )
