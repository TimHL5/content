import asyncio
import json
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from stylecut.db.models import Job
from stylecut.jobs.events import channel
from stylecut.jobs.stream import stream_job_events
from stylecut.redis_client import new_async_redis
from stylecut.schemas.jobs import JobEvent


def _event(job_id: UUID, status: str, progress: float, step: str | None = None) -> JobEvent:
    return JobEvent.model_validate(
        {"job_id": job_id, "status": status, "progress": progress, "step": step}
    )


def test_stream_sends_snapshot_then_live_events_and_closes_on_done() -> None:
    job_id = uuid4()

    async def scenario() -> list[dict[str, str]]:
        redis = new_async_redis()
        publisher = new_async_redis()

        async def snapshot() -> JobEvent:
            return _event(job_id, "queued", 0.0)

        async def publish_later() -> None:
            await asyncio.sleep(0.2)
            for event in (
                _event(job_id, "running", 0.5, "Detecting cuts"),
                _event(job_id, "succeeded", 1.0, "Done"),
                _event(job_id, "running", 0.9, "must never be delivered"),
            ):
                await publisher.publish(channel(job_id), event.model_dump_json())

        task = asyncio.create_task(publish_later())
        received = [item async for item in stream_job_events(job_id, snapshot, redis)]
        await task
        await redis.aclose()
        await publisher.aclose()
        return received

    received = asyncio.run(asyncio.wait_for(scenario(), timeout=10))
    assert [item["event"] for item in received] == ["progress", "progress", "done"]
    assert json.loads(received[1]["data"])["step"] == "Detecting cuts"
    assert json.loads(received[2]["data"])["progress"] == 1.0


def test_stream_notices_terminal_state_without_a_published_event() -> None:
    """A worker that died silently: the periodic re-read of the row ends the stream."""
    job_id = uuid4()
    states = iter([_event(job_id, "running", 0.3), _event(job_id, "failed", 0.3)])

    async def scenario() -> list[dict[str, str]]:
        redis = new_async_redis()

        async def snapshot() -> JobEvent:
            return next(states)

        received = [
            item async for item in stream_job_events(job_id, snapshot, redis, recheck_seconds=0.1)
        ]
        await redis.aclose()
        return received

    received = asyncio.run(asyncio.wait_for(scenario(), timeout=10))
    assert [item["event"] for item in received] == ["progress", "error"]


def test_sse_endpoint_for_finished_job(client: TestClient, db: Session, user_id: UUID) -> None:
    job = Job(owner_id=user_id, type="cpu.demo_sleep", status="succeeded", progress=1.0)
    db.add(job)
    db.commit()

    with client.stream("GET", f"/api/v1/jobs/{job.id}/events") as res:
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/event-stream")
        body = "".join(res.iter_text())

    assert "event: done" in body
    data_line = next(line for line in body.splitlines() if line.startswith("data: "))
    assert json.loads(data_line.removeprefix("data: "))["job_id"] == str(job.id)


def test_sse_endpoint_404_for_unknown_job(client: TestClient) -> None:
    res = client.get(f"/api/v1/jobs/{uuid4()}/events")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "JOB_NOT_FOUND"
