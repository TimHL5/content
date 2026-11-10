"""Job base class and pipelines.

Every Celery task that does real work uses `base=JobTask`. The task receives a
`JobContext` plus the job's `input` as keyword arguments, and the base class keeps
the `jobs` row and the Redis progress channel in sync:

    @celery_app.task(name="cpu.make_proxy", base=JobTask)
    def make_proxy(ctx: JobContext, asset_id: str) -> dict[str, Any]:
        ctx.progress(0.1, "Transcoding")
        ...
        return {"proxy_key": key}

Start a single job with `enqueue(...)`, or several in sequence with
`start_pipeline(...)`. Never call `task.delay(...)` directly: the row must exist first.

A pipeline is one parent `jobs` row (what the client follows over SSE) plus one child
row per stage. The parent runs no code. Its progress is the weighted sum of its
children, and each stage is sent when the previous one succeeds.
"""

from collections.abc import Sequence
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
STARTING = "Starting"
# Skip progress writes smaller than this (downloaders report thousands of times).
MIN_PROGRESS_DELTA = 0.02


def idempotency_key(subject_id: UUID | str, step: str, step_version: int) -> str:
    return f"{subject_id}:{step}:{step_version}"


def _send(task_name: str, job_id: UUID | str) -> None:
    from stylecut.jobs.celery_app import celery_app

    celery_app.tasks[task_name].apply_async(kwargs={"job_id": str(job_id)})


class JobContext:
    """Handed to the task body. Owns every write to the job's row."""

    def __init__(self, session: Session, job: Job) -> None:
        self.session = session
        self.job = job

    @property
    def job_id(self) -> UUID:
        return self.job.id

    def progress(self, fraction: float, step: str, eta_s: float | None = None) -> None:
        """Record progress (0-1) with a human-readable step name and notify listeners."""
        fraction = min(max(fraction, 0.0), 1.0)
        if step == self.job.step and abs(fraction - self.job.progress) < MIN_PROGRESS_DELTA:
            return
        self.job.progress = fraction
        self.job.step = step
        self._commit_and_publish(eta_s)

    def _start(self) -> None:
        self.job.status = "running"
        self.job.attempts += 1
        self.job.progress = 0.0
        self.job.error = None
        self.job.output = None
        self.job.step = STARTING
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
        self.session.commit()
        publish(event_from_job(self.job, eta_s))
        if self.job.parent_id is not None:
            self._sync_parent(eta_s)

    def _sync_parent(self, eta_s: float | None) -> None:
        """Roll this child's state up into its pipeline parent, and start the next
        group once every job in this one has succeeded.

        The parent row is locked for the update: jobs in a group run in parallel, and
        exactly one of them must be the one that advances the pipeline.
        """
        parent = self.session.scalar(
            select(Job).where(Job.id == self.job.parent_id).with_for_update()
        )
        if parent is None:
            return
        groups: list[list[dict[str, Any]]] = parent.input.get("groups", [])
        me = str(self.job.id)
        group_index = next(
            (i for i, group in enumerate(groups) if any(s["job_id"] == me for s in group)), None
        )
        if group_index is None or parent.status in ("failed", "succeeded"):
            self.session.commit()
            return

        children = {
            str(child.id): child
            for child in self.session.scalars(
                select(Job)
                .where(Job.parent_id == parent.id)
                .execution_options(populate_existing=True)
            )
        }
        stages = [stage for group in groups for stage in group]
        total = sum(float(s["weight"]) for s in stages) or 1.0
        done = sum(
            float(s["weight"]) * children[s["job_id"]].progress
            for s in stages
            if s["job_id"] in children
        )

        def succeeded(group: list[dict[str, Any]]) -> bool:
            return all(
                s["job_id"] in children and children[s["job_id"]].status == "succeeded"
                for s in group
            )

        send_next: list[dict[str, Any]] = []
        parent.progress = max(parent.progress, min(done / total, 1.0))
        if self.job.status == "failed":
            parent.status = "failed"
            parent.error = self.job.error
        elif all(succeeded(group) for group in groups):
            parent.status = "succeeded"
            parent.progress = 1.0
            parent.step = "Done"
            parent.output = self.job.output
        else:
            parent.status = "running"
            # A stage's own "Starting" is noise between two named steps.
            if self.job.status == "running" and self.job.step != STARTING:
                parent.step = self.job.step
            is_current = parent.input.get("current", 0) == group_index
            if is_current and succeeded(groups[group_index]) and group_index + 1 < len(groups):
                parent.input = {**parent.input, "current": group_index + 1}
                send_next = groups[group_index + 1]
        self.session.commit()
        publish(event_from_job(parent, eta_s))
        for stage in send_next:
            _send(stage["task"], stage["job_id"])


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
                # Exceptions meant for the user carry `user_message`; others show their type.
                message = getattr(exc, "user_message", None) or f"{type(exc).__name__}: {exc}"
                ctx._fail(str(message))
                raise
            result: dict[str, Any] = output if isinstance(output, dict) else {}
            ctx._succeed(result)
            return result


def _reset(job: Job, input: dict[str, Any]) -> None:
    job.status = "queued"
    job.progress = 0.0
    job.step = None
    job.error = None
    job.output = None
    job.input = input


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
        _reset(job, input or {})
        session.commit()

    _send(task.name, job.id)
    return job


Stage = tuple[Task, float]


def start_pipeline(
    session: Session,
    *,
    type: str,
    owner_id: UUID,
    stages: Sequence[Stage | Sequence[Stage]],
    args: dict[str, Any],
    key: str | None = None,
) -> Job:
    """Run `stages` under one parent job. Each entry is a `(task, weight)` stage, or a
    list of them to run in parallel; the next entry starts when all of the previous
    one's jobs have succeeded.

    Every stage receives `args` as keyword arguments. Returns the parent, whose id is
    what clients follow. Idempotent on `key` exactly like `enqueue`; a failed pipeline
    restarts from its first stage (stages overwrite their own artifacts).
    """
    groups: list[list[Stage]] = []
    for entry in stages:
        if isinstance(entry[0], Task):
            groups.append([(entry[0], float(entry[1]))])  # type: ignore[arg-type]
        else:
            groups.append([(task, float(weight)) for task, weight in entry])  # type: ignore[misc]
    if not groups or any(not group for group in groups):
        raise ValueError("a pipeline needs at least one stage per group")

    parent: Job | None = None
    if key is not None:
        parent = session.scalar(select(Job).where(Job.idempotency_key == key))
        if parent is not None and parent.status != "failed":
            return parent

    if parent is not None:
        # Simplest correct restart: drop the old children and build the plan again.
        for child in session.scalars(select(Job).where(Job.parent_id == parent.id)):
            session.delete(child)
        _reset(parent, {})
        session.flush()
    else:
        parent = Job(
            owner_id=owner_id, type=type, status="queued", progress=0.0, attempts=0,
            input={}, idempotency_key=key,
        )  # fmt: skip
        session.add(parent)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(select(Job).where(Job.idempotency_key == key))
            if existing is None:
                raise
            return existing

    plan: list[list[dict[str, Any]]] = []
    for group in groups:
        children = [
            Job(
                owner_id=owner_id,
                type=task.name,
                status="queued",
                progress=0.0,
                attempts=0,
                input=args,
                parent_id=parent.id,
            )  # fmt: skip
            for task, _ in group
        ]
        session.add_all(children)
        session.flush()
        plan.append(
            [
                {"job_id": str(child.id), "task": task.name, "weight": weight}
                for child, (task, weight) in zip(children, group, strict=True)
            ]
        )

    parent.input = {"args": args, "groups": plan, "current": 0}
    session.commit()
    for stage in plan[0]:
        _send(stage["task"], stage["job_id"])
    return parent
