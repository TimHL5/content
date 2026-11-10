from pathlib import Path
from typing import Any

import pytest

from stylecut.ingest.errors import IngestError, classify_downloader_error
from stylecut.ingest.registry import get_provider
from stylecut.ingest.upload import UploadProvider, upload_source
from stylecut.ingest.urls import normalize_url
from stylecut.ingest.ytdlp import YtDlpProvider
from stylecut.settings import get_settings


@pytest.mark.parametrize(
    ("raw", "platform", "canonical"),
    [
        ("https://www.youtube.com/shorts/abc_DEF-123?feature=share", "youtube", "https://www.youtube.com/shorts/abc_DEF-123"),
        ("youtu.be/abc123?si=tracking", "youtube", "https://www.youtube.com/shorts/abc123"),
        ("https://m.youtube.com/watch?v=abc123&t=4s", "youtube", "https://www.youtube.com/shorts/abc123"),
        ("http://instagram.com/reel/CxYz_12-a/?igsh=zzz", "instagram", "https://www.instagram.com/reel/CxYz_12-a/"),
        ("https://www.instagram.com/some.user/reels/CxYz12a", "instagram", "https://www.instagram.com/reel/CxYz12a/"),
        ("https://www.instagram.com/p/CxYz12a/", "instagram", "https://www.instagram.com/reel/CxYz12a/"),
        ("https://www.tiktok.com/@some.user/video/7312345678901234567?is_from_webapp=1", "tiktok", "https://www.tiktok.com/@some.user/video/7312345678901234567"),
        ("  https://vm.tiktok.com/ZMabc123/  ", "tiktok", "https://vm.tiktok.com/ZMabc123/"),
        ("https://www.tiktok.com/t/ZTabc123", "tiktok", "https://www.tiktok.com/t/ZTabc123/"),
    ],
)  # fmt: skip
def test_normalize_url(raw: str, platform: str, canonical: str) -> None:
    result = normalize_url(raw)
    assert (result.platform, result.url) == (platform, canonical)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not a url",
        "ftp://youtube.com/shorts/abc",
        "file:///etc/passwd",
        "http://localhost:9000/stylecut/secret",
        "http://169.254.169.254/latest/meta-data",
        "https://youtube.com.evil.example/shorts/abc",
        "https://evil.example/?next=https://youtube.com/shorts/abc",
        "https://user@evil.example/shorts/abc",
        "https://www.youtube.com/",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/@channel",
        "https://www.instagram.com/some.user/",
        "https://www.tiktok.com/@some.user",
        "https://vimeo.com/12345",
        "https://www.youtube.com/shorts/abc\n@evil.example",
        "https://www.youtube.com/shorts/" + "a" * 3000,
    ],
)
def test_normalize_url_rejects_everything_else(raw: str) -> None:
    with pytest.raises(IngestError) as excinfo:
        normalize_url(raw)
    assert excinfo.value.code == "INGEST_UNSUPPORTED_URL"


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("ERROR: [youtube] abc: Private video. Sign in if you've been granted access", "INGEST_PRIVATE_VIDEO"),
        ("ERROR: [Instagram] xyz: Requested content is not available, rate-limit reached or login required", "INGEST_LOGIN_REQUIRED"),
        ("ERROR: [TikTok] 123: This video is not available in your country", "INGEST_REGION_LOCKED"),
        ("ERROR: [youtube] abc: Video unavailable. This video has been removed by the uploader", "INGEST_REMOVED"),
        ("ERROR: Unable to download webpage: HTTP Error 404: Not Found", "INGEST_REMOVED"),
        ("File is larger than max-filesize (300MiB > 200MiB). Aborting.", "INGEST_TOO_LARGE"),
        ("ERROR: Unsupported URL: https://example.com", "INGEST_UNSUPPORTED_URL"),
        ("ERROR: something nobody predicted", "INGEST_FAILED"),
    ],
)  # fmt: skip
def test_classify_downloader_error(message: str, code: str) -> None:
    assert classify_downloader_error(message) == code


def test_every_ingest_error_has_a_message_and_a_hint() -> None:
    for code in IngestError.__init__.__annotations__["code"].__args__:
        error = IngestError(code)
        assert error.message and error.hint and error.as_dict()["code"] == code


class FakeYdl:
    """Stands in for yt_dlp.YoutubeDL."""

    def __init__(
        self,
        options: dict[str, Any],
        info: dict[str, Any] | None = None,
        error: Exception | None = None,
        payload: bytes | None = b"x" * 1000,
    ) -> None:
        self.options, self.info, self.error, self.payload = options, info or {}, error, payload
        self.downloaded: list[str] = []

    def __enter__(self) -> "FakeYdl":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict[str, Any]:
        assert download is False
        if self.error is not None:
            raise self.error
        return self.info

    def download(self, urls: list[str]) -> None:
        self.downloaded += urls
        if self.payload is None:
            return
        dest = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
        for hook in self.options["progress_hooks"]:
            hook({"status": "downloading", "downloaded_bytes": 500, "total_bytes": 1000})
        dest.write_bytes(self.payload)
        (dest.parent / "source.mp4.part").write_bytes(b"leftover")


def _provider(**kwargs: Any) -> tuple[YtDlpProvider, list[FakeYdl]]:
    made: list[FakeYdl] = []

    def factory(options: dict[str, Any]) -> FakeYdl:
        made.append(FakeYdl(options, **kwargs))
        return made[-1]

    return YtDlpProvider(factory), made


def test_ytdlp_provider_downloads_the_canonical_url(tmp_path: Path) -> None:
    provider, made = _provider(info={"duration": 31})
    progress: list[float] = []
    local, meta = provider.fetch("youtu.be/abc123?si=x", tmp_path, progress.append)

    assert made[0].downloaded == ["https://www.youtube.com/shorts/abc123"]
    assert (local.path.name, local.size_bytes) == ("source.mp4", 1000)
    assert (meta.platform, meta.source_url, meta.already_stored) == (
        "youtube",
        "https://www.youtube.com/shorts/abc123",
        False,
    )
    assert progress == [0.5, 1.0]
    options = made[0].options
    assert options["max_filesize"] == get_settings().max_reference_bytes
    assert options["noplaylist"] is True and options["merge_output_format"] == "mp4"


def test_ytdlp_provider_rejects_long_and_live_videos_before_downloading(tmp_path: Path) -> None:
    provider, made = _provider(info={"duration": 181})
    with pytest.raises(IngestError) as excinfo:
        provider.fetch("https://www.youtube.com/shorts/abc", tmp_path)
    assert excinfo.value.code == "INGEST_TOO_LONG"
    assert made[0].downloaded == []

    provider, made = _provider(info={"is_live": True})
    with pytest.raises(IngestError):
        provider.fetch("https://www.youtube.com/shorts/abc", tmp_path)
    assert made[0].downloaded == []


def test_ytdlp_provider_maps_downloader_errors(tmp_path: Path) -> None:
    provider, _ = _provider(error=RuntimeError("ERROR: [TikTok] 1: Private video"))
    with pytest.raises(IngestError) as excinfo:
        provider.fetch("https://www.tiktok.com/@u/video/123", tmp_path)
    assert excinfo.value.code == "INGEST_PRIVATE_VIDEO"
    assert excinfo.value.user_message == "That video is private."
    assert "TikTok" in (excinfo.value.detail or "")


def test_ytdlp_provider_reports_too_large_when_nothing_was_written(tmp_path: Path) -> None:
    provider, _ = _provider(payload=None)
    with pytest.raises(IngestError) as excinfo:
        provider.fetch("https://www.youtube.com/shorts/abc", tmp_path)
    assert excinfo.value.code == "INGEST_TOO_LARGE"


def test_registry_respects_the_feature_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://www.youtube.com/shorts/abc"
    assert isinstance(get_provider(url), YtDlpProvider)
    assert isinstance(get_provider(upload_source("references/raw/x.mp4")), UploadProvider)

    with pytest.raises(IngestError) as excinfo:
        get_provider("https://vimeo.com/1")
    assert excinfo.value.code == "INGEST_UNSUPPORTED_URL"
    with pytest.raises(IngestError):
        get_provider("s3://someone-elses-bucket/key.mp4")

    monkeypatch.setattr(get_settings(), "enable_url_ingest", False)
    with pytest.raises(IngestError) as excinfo:
        get_provider(url)
    assert excinfo.value.code == "INGEST_DISABLED"
    # Uploads keep working with URL ingest off.
    assert isinstance(get_provider(upload_source("references/raw/x.mp4")), UploadProvider)
