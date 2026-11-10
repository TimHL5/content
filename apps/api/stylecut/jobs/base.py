"""Job base class.

Every Celery task that does real work uses `base=JobTask`. The task receives a
`JobContext` plus the job's `input` as keyword arguments, and the base class keeps
the `jobs` row and the Redis progress channel in sync:

    @celery_app.task(name="cpu.make_proxy", base=JobTask)
    def make_proxy(ctx: JobContext, asset_id: str) -> dict[str, Any]:
        ctx.progress(0.1, "Transcoding")
        ...
        return {"proxy_key": key}

Start jobs with `enqueue(...)`, never `task.delay(...)`, so the row exists first.
"""

from typing import Any
from uuid import UUID

from celery import Task
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stylecut.db.models import Job
from stylecut.db.session import get_sessionmaker
from stylecut.jobs.events import event_from_job, publish

MAX_ERROR_CHARS = 2000


def idempotency_key(subject_id: UUID | str, step: str, step_version: int) -> str:
    return f"{subject_id}:{step}:{step_version}"


class JobContext:
    """Handed to the task body. Owns every write to the job's row."""

    def __init__(self, session: Session, job: Job) -> None:
        self._session = session
        self.job = job

    @property
    def job_id(self) -> UUID:
        return self.job.id

    def progress(self, fraction: float, step: str, eta_s: float | None = None) -> None:
        """Record progress (0-1) with a human-readable step name and notify listeners."""
        self.job.progress = min(max(fraction, 0.0), 1.0)
        self.job.step = step
        self._commit_and_publish(eta_s)

    def _start(self) -> None:
        self.job.status = "running"
        self.job.attempts += 1
        self.job.progress = 0.0
        self.job.error = None
        self.job.output = None
        self.job.step = "Starting"
        self._commit_and_publish()

    def _succeed(self, output: dict[str, Any]) -> None:
        self.job.status = "succeeded"
        self.job.progress = 1.0
        self.job.step = "Done"
        self.job.output = output
        self._commit_and_publish()

    def _fail(self, error: str) -> None:
        self.job.status = "failed"
        self.job.error = error[:MAX_ERROR_CHARS]
        self._commit_and_publish()

    def _commit_and_publish(self, eta_s: float | None = None) -> None:
        self._session.commit()
        publish(event_from_job(self.job, eta_s))


class JobTask(Task):
    abstract = True
    # Callers pass only `job_id`; the task body's arguments come from the job's input,
    # so Celery must not check call arguments against the body's signature.
    typing = False

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        job_id = UUID(str(kwargs.pop("job_id")))
        with get_sessionmaker()() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise LookupError(f"job {job_id} does not exist")
            if job.status == "succeeded":
                # Duplicate delivery (acks_late): the work is already done.
                return job.output
            ctx = JobContext(session, job)
            ctx._start()
            try:
                output = self.run(ctx, *args, **job.input)
            except Exception as exc:
                session.rollback()
                ctx._fail(f"{type(exc).__name__}: {exc}")
                raise
            result: dict[str, Any] = output if isinstance(output, dict) else {}
            ctx._succeed(result)
            return result


def enqueue(
    session: Session,
    task: Task,
    *,
    owner_id: UUID,
    input: dict[str, Any] | None = None,
    key: str | None = None,
    parent_id: UUID | None = None,
) -> Job:
    """Create the `jobs` row, then send the task.

    With `key` (see `idempotency_key`): a queued, running, or succeeded job with the
    same key is returned as-is and nothing is sent; a failed one is reset and re-sent.
    """
    job: Job | None = None
    if key is not None:
        job = session.scalar(select(Job).where(Job.idempotency_key == key))
        if job is not None and job.status != "failed":
            return job

    if job is None:
        job = Job(
            owner_id=owner_id,
            type=task.name,
            status="queued",
            progress=0.0,
            attempts=0,
            input=input or {},
            idempotency_key=key,
            parent_id=parent_id,
        )
        session.add(job)
        try:
            session.commit()
        except IntegrityError:
            # Lost a race on the unique key: the other request's job wins.
            session.rollback()
            existing = session.scalar(select(Job).where(Job.idempotency_key == key))
            if existing is None:
                raise
            return existing
    else:
        job.status = "queued"
        job.progress = 0.0
        job.step = None
        job.error = None
        job.input = input or {}
        session.commit()

    task.apply_async(kwargs={"job_id": str(job.id)})
    return job
