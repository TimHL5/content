from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

JobStatus = Literal["queued", "running", "succeeded", "failed"]

TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed"})


class JobEvent(BaseModel):
    """Progress event published on Redis channel `job:{id}` and relayed over SSE."""

    job_id: UUID
    status: JobStatus
    progress: float = Field(ge=0, le=1)
    step: str | None = None
    eta_s: float | None = None
    error: str | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: str
    status: JobStatus
    progress: float = Field(ge=0, le=1)
    step: str | None = None
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    error: str | None = None
    attempts: int
    parent_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class JobAccepted(BaseModel):
    """Body of every `202` response for a long-running operation."""

    job_id: UUID
    resource_id: UUID | None = None
