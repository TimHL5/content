"""Celery app. One queue per weight class; a task's queue is the prefix of its name.

io.*   downloads, uploads
cpu.*  ffmpeg, scene detect
gpu.*  whisper, optional demucs
llm.*  Anthropic API calls
"""

from typing import Any

from celery import Celery
from kombu import Queue

from stylecut.settings import get_settings

QUEUES: tuple[str, ...] = ("io", "cpu", "gpu", "llm")
DEFAULT_QUEUE = "cpu"


def route_task(name: str, *_: Any, **__: Any) -> dict[str, str]:
    prefix = name.split(".", 1)[0]
    return {"queue": prefix if prefix in QUEUES else DEFAULT_QUEUE}


def create_celery() -> Celery:
    settings = get_settings()
    app = Celery(
        "stylecut",
        broker=settings.redis_url,
        backend=settings.redis_url,  # needed for chords/groups in the analysis DAG
        include=[
            "stylecut.jobs.demo",
            "stylecut.jobs.ingest",
            "stylecut.jobs.analysis",
            "stylecut.jobs.planning",
        ],
    )
    app.conf.update(
        task_queues=[Queue(name) for name in QUEUES],
        task_default_queue=DEFAULT_QUEUE,
        task_routes=(route_task,),
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        result_expires=3600,
        broker_connection_retry_on_startup=True,
        timezone="UTC",
    )
    return app


celery_app = create_celery()
