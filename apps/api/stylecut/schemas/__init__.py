"""Pydantic models: the source of truth for every JSON contract.

Models listed in `EXPORTED_MODELS` are turned into TypeScript by `make types`.
"""

from pydantic import BaseModel

from stylecut.schemas.errors import ErrorBody, ErrorEnvelope
from stylecut.schemas.health import CheckResult, HealthChecks, HealthOut
from stylecut.schemas.jobs import JobAccepted, JobEvent, JobOut, JobStatus
from stylecut.schemas.media import (
    AssetOut,
    AssetWithUrls,
    ReferenceCreateIn,
    ReferenceOut,
    UploadCompleteIn,
    UploadCompleteOut,
    UploadCreateIn,
    UploadCreateOut,
)

EXPORTED_MODELS: list[type[BaseModel]] = [
    AssetWithUrls,
    ErrorEnvelope,
    HealthOut,
    JobAccepted,
    JobEvent,
    JobOut,
    ReferenceCreateIn,
    ReferenceOut,
    UploadCompleteIn,
    UploadCompleteOut,
    UploadCreateIn,
    UploadCreateOut,
]

__all__ = [
    "EXPORTED_MODELS",
    "AssetOut",
    "AssetWithUrls",
    "ReferenceCreateIn",
    "ReferenceOut",
    "UploadCompleteIn",
    "UploadCompleteOut",
    "UploadCreateIn",
    "UploadCreateOut",
    "CheckResult",
    "ErrorBody",
    "ErrorEnvelope",
    "HealthChecks",
    "HealthOut",
    "JobAccepted",
    "JobEvent",
    "JobOut",
    "JobStatus",
]
