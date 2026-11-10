"""Reference ingest: source -> stored original -> 540p proxy + speech WAV.

Pipeline (see `start_reference_ingest`):

    io.ingest_reference  ->  cpu.make_proxy
"""

import hashlib
import logging
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from stylecut.db.models import Asset, Job, ReferenceVideo
from stylecut.ingest.errors import IngestError
from stylecut.ingest.registry import get_provider
from stylecut.ingest.upload import upload_source
from stylecut.jobs.base import JobContext, JobTask, idempotency_key, start_pipeline
from stylecut.jobs.celery_app import celery_app
from stylecut.media.ffmpeg import FfmpegError, run_ffmpeg
from stylecut.media.probe import probe
from stylecut.media.proxy import proxy_args, speech_wav_args
from stylecut.settings import get_settings
from stylecut.storage import keys, s3

logger = logging.getLogger(__name__)

PIPELINE_TYPE = "reference.ingest"
PIPELINE_STEP = "reference_ingest"
PIPELINE_VERSION = 1

_CONTENT_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}


def pipeline_key(reference_id: UUID) -> str:
    return idempotency_key(reference_id, PIPELINE_STEP, PIPELINE_VERSION)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(session: Session, reference_id: str, asset_id: str) -> tuple[ReferenceVideo, Asset]:
    reference = session.get(ReferenceVideo, UUID(reference_id))
    asset = session.get(Asset, UUID(asset_id))
    if reference is None or asset is None:
        raise LookupError("reference or asset no longer exists")
    return reference, asset


def _mark_failed(session: Session, reference_id: str, error: IngestError) -> None:
    session.rollback()
    reference = session.get(ReferenceVideo, UUID(reference_id))
    if reference is not None:
        reference.status = "failed"
        reference.error = error.as_dict()
        session.commit()
    if error.detail:
        logger.warning("ingest failed for reference %s: %s", reference_id, error.detail)


@celery_app.task(name="io.ingest_reference", base=JobTask)
def ingest_reference(ctx: JobContext, reference_id: str, asset_id: str) -> dict[str, Any]:
    """Fetch the source, check it is a short video, and store the original."""
    settings = get_settings()
    session = ctx.session
    try:
        reference, asset = _load(session, reference_id, asset_id)
        reference.status = "ingesting"
        reference.error = None
        session.commit()

        source = reference.source_url or upload_source(asset.s3_key)
        provider = get_provider(source)
        ctx.progress(0.02, "Downloading")
        with tempfile.TemporaryDirectory(prefix="ingest-") as tmp:
            local, meta = provider.fetch(
                source, Path(tmp), lambda f: ctx.progress(0.02 + 0.73 * f, "Downloading")
            )
            ctx.progress(0.78, "Checking the video")
            try:
                info = probe(local.path)
            except FfmpegError:
                raise IngestError("INGEST_NOT_A_VIDEO") from None
            if not info.has_video or info.duration_s <= 0:
                raise IngestError("INGEST_NOT_A_VIDEO")
            if info.duration_s > settings.max_reference_duration_s:
                raise IngestError("INGEST_TOO_LONG")
            if local.size_bytes > settings.max_reference_bytes:
                raise IngestError("INGEST_TOO_LARGE")

            content_hash = _sha256(local.path)
            if not meta.already_stored:
                ctx.progress(0.88, "Saving")
                suffix = local.path.suffix.lower() or ".mp4"
                key = keys.reference_raw(asset.id, suffix)
                s3.upload_file(local.path, key, _CONTENT_TYPES.get(suffix, "video/mp4"))
                asset.s3_key = key
    except IngestError as exc:
        _mark_failed(session, reference_id, exc)
        raise
    except Exception as exc:
        _mark_failed(session, reference_id, IngestError("INGEST_FAILED", detail=repr(exc)[:500]))
        raise

    asset.status = "ready"
    asset.content_hash = content_hash
    asset.duration_s = info.duration_s
    asset.width = info.width
    asset.height = info.height
    asset.fps = info.fps
    asset.has_audio = info.has_audio
    asset.expires_at = datetime.now(UTC) + timedelta(hours=settings.reference_ttl_hours)
    asset.meta = {**asset.meta, "probe": info.model_dump(), "provider": provider.name}
    session.commit()
    return {"asset_id": asset_id, "duration_s": info.duration_s}


@celery_app.task(name="cpu.make_proxy", base=JobTask)
def make_proxy(ctx: JobContext, reference_id: str, asset_id: str) -> dict[str, Any]:
    """540p H.264 CFR 30fps AAC 48k proxy, plus a 16k mono WAV when there is audio."""
    session = ctx.session
    try:
        reference, asset = _load(session, reference_id, asset_id)
        proxy_key = keys.reference_proxy(asset.id)
        speech_key = keys.reference_speech(asset.id)
        ctx.progress(0.05, "Preparing")
        with tempfile.TemporaryDirectory(prefix="proxy-") as tmp:
            src = Path(tmp) / f"source{Path(asset.s3_key).suffix or '.mp4'}"
            s3.download_file(asset.s3_key, src)
            has_audio = bool(asset.has_audio)

            ctx.progress(0.15, "Making a preview copy")
            proxy_path = Path(tmp) / "proxy.mp4"
            run_ffmpeg(proxy_args(src, proxy_path, has_audio))
            proxy_info = probe(proxy_path)
            s3.upload_file(proxy_path, proxy_key, "video/mp4")

            if has_audio:
                ctx.progress(0.8, "Extracting audio")
                speech_path = Path(tmp) / "speech.wav"
                run_ffmpeg(speech_wav_args(src, speech_path))
                s3.upload_file(speech_path, speech_key, "audio/wav")
            ctx.progress(0.95, "Finishing")
    except Exception as exc:
        _mark_failed(session, reference_id, IngestError("INGEST_FAILED", detail=repr(exc)[:500]))
        raise

    asset.proxy_key = proxy_key
    asset.meta = {
        **asset.meta,
        "speech_key": speech_key if has_audio else None,
        "proxy": {"width": proxy_info.width, "height": proxy_info.height, "fps": proxy_info.fps},
    }
    reference.status = "ingested"
    session.commit()
    return {"asset_id": asset_id, "proxy_key": proxy_key}


def start_reference_ingest(session: Session, reference: ReferenceVideo) -> Job:
    return start_pipeline(
        session,
        type=PIPELINE_TYPE,
        owner_id=reference.owner_id,
        stages=[(ingest_reference, 0.5), (make_proxy, 0.5)],
        args={"reference_id": str(reference.id), "asset_id": str(reference.asset_id)},
        key=pipeline_key(reference.id),
    )
