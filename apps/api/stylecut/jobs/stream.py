"""Relay a job's progress events as Server-Sent Events.

SSE event names: `progress` while queued/running, then exactly one `done` or `error`.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

import redis.asyncio as aioredis

from stylecut.jobs.events import channel
from stylecut.schemas.jobs import TERMINAL_STATUSES, JobEvent

Snapshot = Callable[[], Awaitable[JobEvent | None]]

# If no event arrives for this long, re-read the row. Covers a worker that died
# without publishing and an event lost between subscribe and snapshot.
RECHECK_SECONDS = 10.0


def sse_name(event: JobEvent) -> str:
    if event.status == "succeeded":
        return "done"
    if event.status == "failed":
        return "error"
    return "progress"


def to_sse(event: JobEvent) -> dict[str, str]:
    return {"event": sse_name(event), "data": event.model_dump_json()}


async def stream_job_events(
    job_id: UUID,
    snapshot: Snapshot,
    redis: aioredis.Redis,
    recheck_seconds: float = RECHECK_SECONDS,
) -> AsyncIterator[dict[str, str]]:
    pubsub = redis.pubsub()
    # Subscribe before reading the row so nothing published in between is missed.
    await pubsub.subscribe(channel(job_id))
    try:
        current = await snapshot()
        if current is None:
            return
        yield to_sse(current)
        if current.status in TERMINAL_STATUSES:
            return

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=recheck_seconds
            )
            if message is None:
                current = await snapshot()
                if current is None:
                    return
                if current.status in TERMINAL_STATUSES:
                    yield to_sse(current)
                    return
                continue
            event = JobEvent.model_validate_json(message["data"])
            yield to_sse(event)
            if event.status in TERMINAL_STATUSES:
                return
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()  # type: ignore[no-untyped-call]
