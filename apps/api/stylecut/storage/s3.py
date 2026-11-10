"""S3 client (MinIO locally). Never log presigned URLs or credentials."""

from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config

from stylecut.settings import get_settings


@lru_cache
def get_s3_client() -> Any:
    settings = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="us-east-1",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=2,
            read_timeout=10,
            retries={"max_attempts": 2},
        ),
    )
