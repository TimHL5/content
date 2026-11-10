"""Presigned multipart uploads: the browser sends file bytes straight to S3.

POST /uploads                      -> asset_id + one presigned PUT URL per part
PUT  <part url>  (browser -> S3)   -> ETag header
POST /uploads/{asset_id}/complete  -> asset is ready
"""

import math
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from stylecut.api.deps import current_user_id
from stylecut.api.errors import ApiError, not_found
from stylecut.db.models import Asset
from stylecut.db.session import get_db
from stylecut.schemas.media import (
    AssetOut,
    AssetWithUrls,
    UploadCompleteIn,
    UploadCompleteOut,
    UploadCreateIn,
    UploadCreateOut,
    UploadPartUrl,
)
from stylecut.settings import get_settings
from stylecut.storage import keys, s3

router = APIRouter(tags=["uploads"])

_VIDEO = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".webm": "video/webm",
}
_AUDIO = {
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
    ".aac": "audio/aac", ".ogg": "audio/ogg", ".flac": "audio/flac",
}  # fmt: skip
ALLOWED_TYPES: dict[str, dict[str, str]] = {"reference": _VIDEO, "music": _AUDIO, "sfx": _AUDIO}
MAX_PARTS = 10_000


def asset_out(asset: Asset) -> AssetOut:
    """Expiry is applied on read: a reference past its TTL reports `expired`."""
    expired = asset.expires_at is not None and asset.expires_at <= datetime.now(UTC)
    return AssetOut.model_validate(
        {
            "id": asset.id,
            "kind": asset.kind,
            "status": "expired" if expired and asset.status == "ready" else asset.status,
            "duration_s": asset.duration_s,
            "width": asset.width,
            "height": asset.height,
            "fps": asset.fps,
            "has_audio": asset.has_audio,
            "has_proxy": asset.proxy_key is not None and not expired,
            "expires_at": asset.expires_at,
            "created_at": asset.created_at,
        }
    )


def owned_asset(session: Session, asset_id: UUID, user_id: UUID) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None or asset.owner_id != user_id:
        raise not_found("asset")
    return asset


def _key_for(kind: str, user_id: UUID, asset_id: UUID, ext: str) -> str:
    if kind == "reference":
        return keys.reference_raw(asset_id, ext)
    if kind == "music":
        return keys.library_asset(user_id, "music", asset_id, ext)
    return keys.library_asset(user_id, "sfx", asset_id, ext)


@router.post("/uploads", response_model=UploadCreateOut, status_code=201)
def create_upload(
    body: UploadCreateIn,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(current_user_id),
) -> UploadCreateOut:
    settings = get_settings()
    ext = PurePosixPath(body.filename).suffix.lower()
    content_type = ALLOWED_TYPES[body.kind].get(ext)
    if content_type is None:
        allowed = ", ".join(sorted(e.lstrip(".").upper() for e in ALLOWED_TYPES[body.kind]))
        raise ApiError(
            422, "UPLOAD_UNSUPPORTED_TYPE", "That file type isn't supported.", f"Use {allowed}."
        )
    limit = settings.max_reference_bytes if body.kind == "reference" else settings.max_library_bytes
    if body.size > limit:
        raise ApiError(
            413,
            "UPLOAD_TOO_LARGE",
            f"That file is larger than {limit // (1024 * 1024)} MB.",
            "Export a smaller copy and try again.",
        )

    part_size = settings.upload_part_bytes
    part_count = math.ceil(body.size / part_size)
    if part_count > MAX_PARTS:
        raise ApiError(413, "UPLOAD_TOO_LARGE", "That file is too large to upload.")

    asset_id = uuid4()
    key = _key_for(body.kind, user_id, asset_id, ext)
    upload_id = s3.create_multipart_upload(key, content_type)
    db.add(
        Asset(
            id=asset_id,
            owner_id=user_id,
            kind=body.kind,
            s3_key=key,
            status="uploading",
            meta={
                "upload_id": upload_id,
                "filename": body.filename,
                "size": body.size,
                "part_size": part_size,
            },
        )
    )
    db.commit()
    return UploadCreateOut(
        asset_id=asset_id,
        upload_id=upload_id,
        part_size=part_size,
        parts=[
            UploadPartUrl(part_number=n, url=s3.presign_upload_part(key, upload_id, n))
            for n in range(1, part_count + 1)
        ],
    )


@router.post("/uploads/{asset_id}/complete", response_model=UploadCompleteOut)
def complete_upload(
    asset_id: UUID,
    body: UploadCompleteIn,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(current_user_id),
) -> UploadCompleteOut:
    asset = owned_asset(db, asset_id, user_id)
    if asset.status == "ready":
        return UploadCompleteOut(asset=asset_out(asset))  # safe to retry
    if asset.status != "uploading" or asset.meta.get("upload_id") != body.upload_id:
        raise ApiError(409, "UPLOAD_NOT_PENDING", "That upload is no longer in progress.")

    try:
        s3.complete_multipart_upload(
            asset.s3_key, body.upload_id, [(p.part_number, p.etag) for p in body.parts]
        )
        size = s3.object_size(asset.s3_key)
    except (ClientError, s3.ObjectNotFound):
        raise ApiError(
            422, "UPLOAD_INCOMPLETE", "The upload didn't finish.", "Try uploading the file again."
        ) from None

    if size != asset.meta.get("size"):
        asset.status = "failed"
        db.commit()
        raise ApiError(
            422,
            "UPLOAD_SIZE_MISMATCH",
            "The upload was cut short.",
            "Try uploading the file again.",
        )

    asset.status = "ready"
    if asset.kind == "reference":
        asset.expires_at = datetime.now(UTC) + timedelta(hours=get_settings().reference_ttl_hours)
    db.commit()
    return UploadCompleteOut(asset=asset_out(asset))


@router.get("/assets/{asset_id}", response_model=AssetWithUrls)
def get_asset(
    asset_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> AssetWithUrls:
    asset = owned_asset(db, asset_id, user_id)
    out = asset_out(asset)
    if out.status != "ready":
        return AssetWithUrls(asset=out)
    return AssetWithUrls(
        asset=out,
        url=s3.presign_get(asset.s3_key),
        proxy_url=s3.presign_get(asset.proxy_key) if asset.proxy_key else None,
    )
