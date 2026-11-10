"""Progress events: Redis pub/sub channel `job:{id}` (docs/ARCHITECTURE.md)."""

from uuid import UUID

from stylecut.db.models import Job
from stylecut.redis_client import get_redis
from stylecut.schemas.jobs import JobEvent, JobStatus


def channel(job_id: UUID) -> str:
    return f"job:{job_id}"


def event_from_job(job: Job, eta_s: float | None = None) -> JobEvent:
    status: JobStatus = job.status  # type: ignore[assignment]  # constrained by ck_jobs_status
    return JobEvent(
        job_id=job.id,
        status=status,
        progress=job.progress,
        step=job.step,
        eta_s=eta_s,
        error=job.error,
    )


def publish(event: JobEvent) -> None:
    get_redis().publish(channel(event.job_id), event.model_dump_json())
