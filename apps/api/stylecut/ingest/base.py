"""The IngestProvider interface.

A provider turns a *source* (a platform URL, or `s3://bucket/key` for a file the user
uploaded) into a local file. Everything downstream is identical for every provider,
so the product never depends on any one downloader working.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from stylecut.ingest.urls import Platform

ProgressFn = Callable[[float], None]  # 0-1


@dataclass(frozen=True)
class LocalFile:
    path: Path
    size_bytes: int


@dataclass(frozen=True)
class SourceMeta:
    platform: Platform
    source_url: str | None  # None for uploads
    # True when the file already lives at its final S3 key and must not be re-uploaded.
    already_stored: bool = False


class IngestProvider(Protocol):
    name: str

    def can_handle(self, source: str) -> bool: ...

    def fetch(
        self, source: str, dest_dir: Path, on_progress: ProgressFn | None = None
    ) -> tuple[LocalFile, SourceMeta]:
        """Download `source` into `dest_dir`. Raises IngestError on any user-facing failure."""
        ...
