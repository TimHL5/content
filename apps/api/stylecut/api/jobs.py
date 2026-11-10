from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from stylecut.api.deps import current_user_id
from stylecut.api.errors import not_found
from stylecut.db.models import Job
from stylecut.db.session import get_db, get_sessionmaker
from stylecut.jobs.events import event_from_job
from stylecut.jobs.stream import stream_job_events
from stylecut.redis_client import new_async_redis
from stylecut.schemas.jobs import JobEvent, JobOut

router = APIRouter(tags=["jobs"])


def _owned_job(session: Session, job_id: UUID, user_id: UUID) -> Job:
    job = session.get(Job, job_id)
    if job is None or job.owner_id != user_id:
        raise not_found("job")
    return job


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> Job:
    return _owned_job(db, job_id, user_id)


@router.get("/jobs/{job_id}/events")
def job_events(
    job_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> EventSourceResponse:
    _owned_job(db, job_id, user_id)  # 404 before the stream starts

    def load() -> JobEvent | None:
        with get_sessionmaker()() as session:
            job = session.get(Job, job_id)
            return event_from_job(job) if job is not None else None

    async def snapshot() -> JobEvent | None:
        return await run_in_threadpool(load)

    async def events() -> AsyncIterator[dict[str, str]]:
        redis = new_async_redis()
        try:
            async for item in stream_job_events(job_id, snapshot, redis):
                yield item
        finally:
            await redis.aclose()

    return EventSourceResponse(events(), ping=15, headers={"X-Accel-Buffering": "no"})
