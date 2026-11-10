"""Wait for S3 to accept connections, create the bucket, and apply lifecycle rules.

Runs as the one-shot `storage-init` compose service. Idempotent.
"""

import sys
import time
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from stylecut.settings import get_settings
from stylecut.storage.keys import EXPIRING_PREFIXES
from stylecut.storage.s3 import get_s3_client

WAIT_SECONDS = 60.0


def ensure_bucket(wait_seconds: float = WAIT_SECONDS) -> bool:
    """Returns True if the bucket was created, False if it already existed."""
    s3 = get_s3_client()
    bucket = get_settings().s3_bucket
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
            break
        except (BotoCoreError, ClientError) as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"S3 not reachable after {wait_seconds:.0f}s ({type(exc).__name__})"
                ) from None
            time.sleep(1.0)
    if bucket in existing:
        return False
    s3.create_bucket(Bucket=bucket)
    return True


def lifecycle_rules() -> list[dict[str, Any]]:
    """Reference media is temporary (CLAUDE.md guardrail): raw files and proxies are
    deleted after the configured TTL. Derived data (stats, contact sheets) is kept."""
    days = max(1, round(get_settings().reference_ttl_hours / 24))
    return [
        {
            "ID": f"expire-{prefix.strip('/').replace('/', '-')}",
            "Status": "Enabled",
            "Filter": {"Prefix": prefix},
            "Expiration": {"Days": days},
            # Also drop reference uploads that were started and never completed.
            # (MinIO rejects a rule that has only this action, so it rides along here.)
            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": days},
        }
        for prefix in EXPIRING_PREFIXES
    ]


def ensure_lifecycle() -> None:
    get_s3_client().put_bucket_lifecycle_configuration(
        Bucket=get_settings().s3_bucket,
        LifecycleConfiguration={"Rules": lifecycle_rules()},
    )


def main() -> None:
    try:
        created = ensure_bucket()
    except TimeoutError as exc:
        sys.exit(str(exc))
    ensure_lifecycle()
    print(f"bucket {'created' if created else 'already exists'}; lifecycle rules applied")


if __name__ == "__main__":
    main()
