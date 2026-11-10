"""`GET /health`: checks DB, Redis, and S3. 200 when all pass, 503 otherwise."""

import time
from collections.abc import Callable

from fastapi import APIRouter, Response
from sqlalchemy import text

from stylecut.db.session import get_engine
from stylecut.redis_client import get_redis
from stylecut.schemas.health import CheckResult, HealthChecks, HealthOut
from stylecut.settings import get_settings
from stylecut.storage.s3 import get_s3_client

router = APIRouter(tags=["health"])


def check_db() -> None:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))


def check_redis() -> None:
    get_redis().ping()


def check_s3() -> None:
    get_s3_client().head_bucket(Bucket=get_settings().s3_bucket)


# Looked up by name at request time so tests can swap a check out.
CHECKS: dict[str, Callable[[], None]] = {"db": check_db, "redis": check_redis, "s3": check_s3}


def _run(check: Callable[[], None]) -> CheckResult:
    started = time.perf_counter()
    try:
        check()
    except Exception as exc:
        # Class name only: exception messages can contain hosts, URLs, or credentials.
        return CheckResult(ok=False, error=type(exc).__name__)
    return CheckResult(ok=True, latency_ms=round((time.perf_counter() - started) * 1000, 1))


@router.get("/health", response_model=HealthOut)
def health(response: Response) -> HealthOut:
    checks = HealthChecks(db=_run(CHECKS["db"]), redis=_run(CHECKS["redis"]), s3=_run(CHECKS["s3"]))
    healthy = checks.db.ok and checks.redis.ok and checks.s3.ok
    if not healthy:
        response.status_code = 503
    return HealthOut(status="ok" if healthy else "degraded", checks=checks)
