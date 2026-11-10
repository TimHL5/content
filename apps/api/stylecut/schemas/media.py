"""Uploads, assets, and references (docs/API.md)."""

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from stylecut.schemas.errors import ErrorBody

AssetKind = Literal["reference", "footage", "music", "sfx", "render", "image"]
AssetStatus = Literal["uploading", "ready", "failed", "expired"]
UploadKind = Literal["reference", "music", "sfx"]
Platform = Literal["tiktok", "instagram", "youtube", "upload"]
ReferenceStatus = Literal["queued", "ingesting", "ingested", "analyzing", "ready", "failed"]


class AssetOut(BaseModel):
    id: UUID
    kind: AssetKind
    status: AssetStatus
    duration_s: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool | None = None
    has_proxy: bool
    expires_at: datetime | None = None
    created_at: datetime


class AssetWithUrls(BaseModel):
    """`GET /assets/{id}`. URLs are presigned, short-lived, and null once the asset expired."""

    asset: AssetOut
    url: str | None = None
    proxy_url: str | None = None


class UploadCreateIn(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    content_type: str = Field(default="", max_length=127)
    kind: UploadKind


class UploadPartUrl(BaseModel):
    part_number: int
    url: str


class UploadCreateOut(BaseModel):
    asset_id: UUID
    upload_id: str
    part_size: int
    parts: list[UploadPartUrl]


class UploadedPart(BaseModel):
    part_number: int = Field(ge=1, le=10000)
    etag: str = Field(min_length=1, max_length=200)


class UploadCompleteIn(BaseModel):
    upload_id: str
    parts: list[UploadedPart] = Field(min_length=1)


class UploadCompleteOut(BaseModel):
    asset: AssetOut


class ReferenceCreateIn(BaseModel):
    """Exactly one of `url` (platform link) or `asset_id` (an uploaded reference file)."""

    url: str | None = Field(default=None, max_length=2000)
    asset_id: UUID | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.url is None) == (self.asset_id is None):
            raise ValueError("provide exactly one of url or asset_id")
        return self


class ReferenceOut(BaseModel):
    id: UUID
    status: ReferenceStatus
    platform: Platform
    source_url: str | None = None
    asset_id: UUID
    job_id: UUID | None = None
    error: ErrorBody | None = None
    created_at: datetime
