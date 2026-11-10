from typing import Literal

from pydantic import BaseModel


class CheckResult(BaseModel):
    ok: bool
    latency_ms: float | None = None
    error: str | None = None


class HealthChecks(BaseModel):
    db: CheckResult
    redis: CheckResult
    s3: CheckResult


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    checks: HealthChecks
