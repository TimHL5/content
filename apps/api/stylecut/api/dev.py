"""Local-dev helpers. Mounted only when ENABLE_DEV_ROUTES=true."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stylecut.api.deps import current_user_id
from stylecut.db.session import get_db
from stylecut.jobs.base import enqueue
from stylecut.jobs.demo import demo_sleep
from stylecut.schemas.jobs import JobAccepted

router = APIRouter(prefix="/dev", tags=["dev"])


class DemoJobIn(BaseModel):
    seconds: float = Field(default=5.0, ge=0, le=60)
    steps: int = Field(default=10, ge=1, le=100)
    fail: bool = False


@router.post("/demo-job", status_code=202, response_model=JobAccepted)
def start_demo_job(
    body: DemoJobIn | None = None,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(current_user_id),
) -> JobAccepted:
    params = body or DemoJobIn()
    job = enqueue(db, demo_sleep, owner_id=user_id, input=params.model_dump())
    return JobAccepted(job_id=job.id)
