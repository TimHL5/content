from urllib.parse import urlsplit

from stylecut.ingest.base import IngestProvider
from stylecut.ingest.errors import IngestError
from stylecut.ingest.upload import UploadProvider
from stylecut.ingest.ytdlp import YtDlpProvider
from stylecut.settings import get_settings


def get_provider(source: str) -> IngestProvider:
    """Pick the provider for a source. Uploads always work; URLs need ENABLE_URL_INGEST."""
    upload = UploadProvider()
    if upload.can_handle(source):
        return upload
    if urlsplit(source).scheme in ("http", "https"):
        if not get_settings().enable_url_ingest:
            raise IngestError("INGEST_DISABLED")
        downloader = YtDlpProvider()
        if downloader.can_handle(source):
            return downloader
    raise IngestError("INGEST_UNSUPPORTED_URL")
