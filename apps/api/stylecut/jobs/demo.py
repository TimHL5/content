"""A no-op job used to exercise queue -> worker -> progress -> SSE end to end."""

import time
from typing import Any

from stylecut.jobs.base import JobContext, JobTask
from stylecut.jobs.celery_app import celery_app


@celery_app.task(name="cpu.demo_sleep", base=JobTask)
def demo_sleep(
    ctx: JobContext, seconds: float = 5.0, steps: int = 10, fail: bool = False
) -> dict[str, Any]:
    steps = max(1, steps)
    per_step = max(0.0, seconds) / steps
    for i in range(steps):
        ctx.progress(i / steps, f"Demo step {i + 1} of {steps}", eta_s=(steps - i) * per_step)
        time.sleep(per_step)
    if fail:
        raise RuntimeError("demo failure requested")
    return {"slept_s": seconds, "steps": steps}
