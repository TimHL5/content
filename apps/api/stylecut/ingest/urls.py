"""URL normalization and platform detection.

Only an allow-list of hosts and path shapes is accepted, so the downloader can never
be pointed at an arbitrary address (SSRF) and the same video always maps to one URL.
"""

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from stylecut.ingest.errors import IngestError

Platform = Literal["tiktok", "instagram", "youtube", "upload"]

MAX_URL_CHARS = 2000
_ID = r"[A-Za-z0-9_-]+"


@dataclass(frozen=True)
class NormalizedUrl:
    platform: Platform
    url: str  # canonical: https, no tracking parameters


def _host(netloc: str) -> str:
    host = netloc.lower().split("@")[-1].split(":")[0]
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host


def _youtube(host: str, path: str, query: dict[str, list[str]]) -> str | None:
    video_id: str | None = None
    if host == "youtu.be":
        match = re.fullmatch(rf"/({_ID})/?", path)
        video_id = match.group(1) if match else None
    elif host in ("youtube.com", "music.youtube.com"):
        match = re.fullmatch(rf"/shorts/({_ID})/?", path)
        if match:
            video_id = match.group(1)
        elif path.rstrip("/") == "/watch" and query.get("v"):
            candidate = query["v"][0]
            video_id = candidate if re.fullmatch(_ID, candidate) else None
    return f"https://www.youtube.com/shorts/{video_id}" if video_id else None


def _instagram(host: str, path: str) -> str | None:
    if host != "instagram.com":
        return None
    # Optional leading /{username}/ segment, then reel|reels|p|tv/{code}
    match = re.fullmatch(rf"(?:/[A-Za-z0-9_.]+)?/(?:reel|reels|p|tv)/({_ID})/?", path)
    return f"https://www.instagram.com/reel/{match.group(1)}/" if match else None


def _tiktok(host: str, path: str) -> str | None:
    if host == "tiktok.com":
        match = re.fullmatch(r"/(@[A-Za-z0-9_.]+)/video/(\d+)/?", path)
        if match:
            return f"https://www.tiktok.com/{match.group(1)}/video/{match.group(2)}"
        match = re.fullmatch(rf"/t/({_ID})/?", path)
        if match:
            return f"https://www.tiktok.com/t/{match.group(1)}/"
    elif host in ("vm.tiktok.com", "vt.tiktok.com"):
        match = re.fullmatch(rf"/({_ID})/?", path)
        if match:
            return f"https://{host}/{match.group(1)}/"
    return None


def normalize_url(raw: str) -> NormalizedUrl:
    """Raises IngestError("INGEST_UNSUPPORTED_URL") for anything not on the allow-list."""
    text = raw.strip()
    if not text or len(text) > MAX_URL_CHARS or any(c.isspace() for c in text):
        raise IngestError("INGEST_UNSUPPORTED_URL")
    if "://" not in text:
        text = f"https://{text}"
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise IngestError("INGEST_UNSUPPORTED_URL")

    host = _host(parts.netloc)
    path = parts.path or "/"
    if (url := _youtube(host, path, parse_qs(parts.query))) is not None:
        return NormalizedUrl("youtube", url)
    if (url := _instagram(host, path)) is not None:
        return NormalizedUrl("instagram", url)
    if (url := _tiktok(host, path)) is not None:
        return NormalizedUrl("tiktok", url)
    raise IngestError("INGEST_UNSUPPORTED_URL")
