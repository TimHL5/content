"""References: a video whose style we analyze. Created from a platform URL or an upload."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from stylecut.api.deps import current_user_id
from stylecut.api.errors import ApiError, not_found
from stylecut.api.uploads import owned_asset
from stylecut.db.models import Asset, Job, ReferenceVideo
from stylecut.db.session import get_db
from stylecut.ingest.errors import IngestError
from stylecut.ingest.urls import normalize_url
from stylecut.jobs.ingest import pipeline_key, start_reference_ingest
from stylecut.schemas.jobs import JobAccepted
from stylecut.schemas.media import ReferenceCreateIn, ReferenceOut
from stylecut.settings import get_settings
from stylecut.storage import keys

router = APIRouter(tags=["references"])


def _reference_out(session: Session, reference: ReferenceVideo) -> ReferenceOut:
    job_id = session.scalar(select(Job.id).where(Job.idempotency_key == pipeline_key(reference.id)))
    return ReferenceOut.model_validate(
        {
            "id": reference.id,
            "status": reference.status,
            "platform": reference.platform,
            "source_url": reference.source_url,
            "asset_id": reference.asset_id,
            "job_id": job_id,
            "error": reference.error,
            "created_at": reference.created_at,
        }
    )


def _ingest_api_error(exc: IngestError, status_code: int = 422) -> ApiError:
    return ApiError(status_code, exc.code, exc.message, exc.hint)


@router.post("/references", status_code=202, response_model=JobAccepted)
def create_reference(
    body: ReferenceCreateIn,
    db: Session = Depends(get_db),
    user_id: UUID = Depends(current_user_id),
) -> JobAccepted:
    if body.url is not None:
        if not get_settings().enable_url_ingest:
            raise _ingest_api_error(IngestError("INGEST_DISABLED"), 403)
        try:
            target = normalize_url(body.url)
        except IngestError as exc:
            raise _ingest_api_error(exc) from None
        asset = Asset(id=uuid4(), owner_id=user_id, kind="reference", status="uploading", s3_key="")
        asset.s3_key = keys.reference_raw(asset.id, "mp4")  # final extension set after download
        db.add(asset)
        reference = ReferenceVideo(
            owner_id=user_id, asset_id=asset.id, source_url=target.url, platform=target.platform
        )
    else:
        assert body.asset_id is not None  # guaranteed by ReferenceCreateIn
        asset = owned_asset(db, body.asset_id, user_id)
        if asset.kind != "reference":
            raise ApiError(422, "ASSET_WRONG_KIND", "That file wasn't uploaded as a reference.")
        if asset.status != "ready":
            raise ApiError(
                409, "ASSET_NOT_READY", "That upload hasn't finished.", "Complete the upload first."
            )
        reference = ReferenceVideo(owner_id=user_id, asset_id=asset.id, platform="upload")

    db.add(reference)
    db.commit()
    job = start_reference_ingest(db, reference)
    return JobAccepted(job_id=job.id, resource_id=reference.id)


@router.get("/references", response_model=list[ReferenceOut])
def list_references(
    db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> list[ReferenceOut]:
    rows = db.scalars(
        select(ReferenceVideo)
        .where(ReferenceVideo.owner_id == user_id)
        .order_by(ReferenceVideo.created_at.desc())
        .limit(100)
    ).all()
    return [_reference_out(db, row) for row in rows]


@router.get("/references/{reference_id}", response_model=ReferenceOut)
def get_reference(
    reference_id: UUID, db: Session = Depends(get_db), user_id: UUID = Depends(current_user_id)
) -> ReferenceOut:
    reference = db.get(ReferenceVideo, reference_id)
    if reference is None or reference.owner_id != user_id:
        raise not_found("reference")
    return _reference_out(db, reference)
