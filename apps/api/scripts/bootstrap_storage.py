"""Wait for S3 to accept connections, then create the bucket if it is missing.

Runs as the one-shot `storage-init` compose service. Idempotent.
"""

import sys
import time

from botocore.exceptions import BotoCoreError, ClientError

from stylecut.settings import get_settings
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


def main() -> None:
    try:
        created = ensure_bucket()
    except TimeoutError as exc:
        sys.exit(str(exc))
    print(f"bucket {'created' if created else 'already exists'}")


if __name__ == "__main__":
    main()
