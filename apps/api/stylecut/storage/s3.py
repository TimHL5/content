"""S3 access (MinIO locally). Never log presigned URLs or credentials."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from stylecut.settings import get_settings


class ObjectNotFound(Exception):
    pass


def _client(endpoint: str) -> Any:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=2,
            read_timeout=30,
            retries={"max_attempts": 2},
        ),
    )


@lru_cache
def get_s3_client() -> Any:
    """For server-side calls."""
    return _client(get_settings().s3_endpoint)


@lru_cache
def get_presign_client() -> Any:
    """For URLs handed to the browser: the signature covers the host, so they must be
    signed for the endpoint the browser will actually call."""
    settings = get_settings()
    return _client(settings.s3_public_endpoint or settings.s3_endpoint)


def _bucket() -> str:
    return get_settings().s3_bucket


def _is_missing(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound")


def object_size(key: str) -> int:
    try:
        head = get_s3_client().head_object(Bucket=_bucket(), Key=key)
    except ClientError as exc:
        if _is_missing(exc):
            raise ObjectNotFound(key) from None
        raise
    return int(head["ContentLength"])


def download_file(key: str, dest: Path) -> None:
    try:
        get_s3_client().download_file(_bucket(), key, str(dest))
    except ClientError as exc:
        if _is_missing(exc):
            raise ObjectNotFound(key) from None
        raise


def upload_file(path: Path, key: str, content_type: str) -> None:
    get_s3_client().upload_file(str(path), _bucket(), key, ExtraArgs={"ContentType": content_type})


def presign_get(key: str) -> str:
    url: str = get_presign_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=get_settings().presign_ttl_s,
    )
    return url


def create_multipart_upload(key: str, content_type: str) -> str:
    res = get_s3_client().create_multipart_upload(
        Bucket=_bucket(), Key=key, ContentType=content_type
    )
    upload_id: str = res["UploadId"]
    return upload_id


def presign_upload_part(key: str, upload_id: str, part_number: int) -> str:
    url: str = get_presign_client().generate_presigned_url(
        "upload_part",
        Params={"Bucket": _bucket(), "Key": key, "UploadId": upload_id, "PartNumber": part_number},
        ExpiresIn=get_settings().presign_ttl_s,
    )
    return url


def complete_multipart_upload(key: str, upload_id: str, parts: list[tuple[int, str]]) -> None:
    """`parts` is (part_number, etag). Raises ClientError if S3 rejects them."""
    get_s3_client().complete_multipart_upload(
        Bucket=_bucket(),
        Key=key,
        UploadId=upload_id,
        MultipartUpload={"Parts": [{"PartNumber": n, "ETag": etag} for n, etag in sorted(parts)]},
    )


def abort_multipart_upload(key: str, upload_id: str) -> None:
    get_s3_client().abort_multipart_upload(Bucket=_bucket(), Key=key, UploadId=upload_id)
