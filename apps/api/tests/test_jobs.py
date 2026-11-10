import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from stylecut.db.models import Job
from stylecut.jobs import base
from stylecut.jobs.base import enqueue, idempotency_key
from stylecut.jobs.celery_app import QUEUES, celery_app, route_task
from stylecut.jobs.demo import demo_sleep
from stylecut.jobs.events import channel
from stylecut.redis_client import get_redis


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Capture apply_async calls instead of hitting the broker."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(demo_sleep, "apply_async", lambda *a, **kw: calls.append(kw), raising=False)
    return calls


def _make_job(db: Session, user_id: UUID, **input: Any) -> Job:
    job = Job(owner_id=user_id, type=demo_sleep.name, input=input)
    db.add(job)
    db.commit()
    return job


def _run_and_collect(job: Job) -> tuple[Any, list[dict[str, Any]]]:
    pubsub = get_redis().pubsub()
    pubsub.subscribe(channel(job.id))
    pubsub.get_message(timeout=1)  # subscribe confirmation
    result = demo_sleep.apply(kwargs={"job_id": str(job.id)})
    events = []
    while (message := pubsub.get_message(timeout=0.2)) is not None:
        if message["type"] == "message":
            events.append(json.loads(message["data"]))
    pubsub.close()
    return result, events


def test_queues_and_routing() -> None:
    assert QUEUES == ("io", "cpu", "gpu", "llm")
    assert {q.name for q in celery_app.conf.task_queues} == set(QUEUES)
    assert route_task("io.ingest_reference") == {"queue": "io"}
    assert route_task("gpu.transcribe") == {"queue": "gpu"}
    assert route_task("llm.synthesize_profile") == {"queue": "llm"}
    assert route_task("cpu.demo_sleep") == {"queue": "cpu"}
    assert route_task("unprefixed") == {"queue": "cpu"}


def test_job_success_updates_row_and_publishes_progress(db: Session, user_id: UUID) -> None:
    job = _make_job(db, user_id, seconds=0, steps=3)
    result, events = _run_and_collect(job)

    assert result.successful()
    db.refresh(job)
    assert (job.status, job.progress, job.attempts) == ("succeeded", 1.0, 1)
    assert job.output == {"slept_s": 0, "steps": 3}
    assert job.error is None

    assert [e["status"] for e in events] == ["running"] * 4 + ["succeeded"]
    assert [e["step"] for e in events][1:4] == [f"Demo step {i} of 3" for i in (1, 2, 3)]
    progress = [e["progress"] for e in events]
    assert progress == sorted(progress) and progress[-1] == 1.0
    assert all(e["job_id"] == str(job.id) for e in events)


def test_job_failure_is_recorded_and_published(db: Session, user_id: UUID) -> None:
    job = _make_job(db, user_id, seconds=0, steps=1, fail=True)
    result, events = _run_and_collect(job)

    assert result.failed()
    db.refresh(job)
    assert job.status == "failed"
    assert job.error == "RuntimeError: demo failure requested"
    assert events[-1]["status"] == "failed"
    assert events[-1]["error"] == job.error


def test_succeeded_job_is_not_rerun_on_duplicate_delivery(db: Session, user_id: UUID) -> None:
    job = _make_job(db, user_id, seconds=0, steps=1)
    demo_sleep.apply(kwargs={"job_id": str(job.id)})
    _, events = _run_and_collect(job)
    db.refresh(job)
    assert job.attempts == 1
    assert events == []


def test_enqueue_creates_row_then_sends(
    db: Session, user_id: UUID, sent: list[dict[str, Any]]
) -> None:
    job = enqueue(db, demo_sleep, owner_id=user_id, input={"seconds": 1})
    assert (job.status, job.type, job.input) == ("queued", "cpu.demo_sleep", {"seconds": 1})
    assert sent == [{"kwargs": {"job_id": str(job.id)}}]


def test_enqueue_is_idempotent_on_key(
    db: Session, user_id: UUID, sent: list[dict[str, Any]]
) -> None:
    key = idempotency_key(uuid4(), "demo", 1)
    first = enqueue(db, demo_sleep, owner_id=user_id, key=key)
    second = enqueue(db, demo_sleep, owner_id=user_id, key=key)
    assert second.id == first.id
    assert len(sent) == 1  # cache hit: no second send

    first.status = "failed"
    first.error = "boom"
    db.commit()
    retried = enqueue(db, demo_sleep, owner_id=user_id, key=key)
    assert retried.id == first.id
    assert (retried.status, retried.error) == ("queued", None)
    assert len(sent) == 2


def test_idempotency_key_format() -> None:
    assert base.idempotency_key("abc", "make_proxy", 2) == "abc:make_proxy:2"


def test_get_job_endpoint(client: TestClient, db: Session, user_id: UUID) -> None:
    job = _make_job(db, user_id, seconds=0)
    res = client.get(f"/api/v1/jobs/{job.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == str(job.id)
    assert (body["status"], body["progress"], body["type"]) == ("queued", 0.0, "cpu.demo_sleep")

    missing = client.get(f"/api/v1/jobs/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_demo_job_route_enqueues(client: TestClient, sent: list[dict[str, Any]]) -> None:
    res = client.post("/api/v1/dev/demo-job", json={"seconds": 1, "steps": 2})
    assert res.status_code == 202
    assert sent == [{"kwargs": {"job_id": res.json()["job_id"]}}]


def test_enqueue_through_real_apply_async(db: Session, user_id: UUID) -> None:
    """No stubbing: Celery's own argument checks and the task base class both run."""
    celery_app.conf.task_always_eager = True
    try:
        job = enqueue(db, demo_sleep, owner_id=user_id, input={"seconds": 0, "steps": 2})
    finally:
        celery_app.conf.task_always_eager = False
    db.refresh(job)
    assert (job.status, job.attempts) == ("succeeded", 1)
    assert job.output == {"slept_s": 0, "steps": 2}


def test_unhandled_error_returns_envelope_with_cors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("secret detail")

    monkeypatch.setattr(demo_sleep, "apply_async", boom, raising=False)
    res = client.post("/api/v1/dev/demo-job", headers={"Origin": "http://localhost:3000"})
    assert res.status_code == 500
    assert res.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "secret detail" not in res.text
    assert res.headers["access-control-allow-origin"] == "http://localhost:3000"
