"""Reference analysis stages: proxy -> measurements -> judgment -> StyleProfile.

Each task is thin: fetch inputs from S3, call one domain function, write its artifact to
a deterministic key under `references/derived/{asset_id}/`. Later stages read earlier
artifacts from S3, so stages can run on different workers and a re-run overwrites cleanly.
"""

import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any, Concatenate
from uuid import UUID, uuid4

from pydantic import BaseModel

from stylecut.analysis import audio as audio_analysis
from stylecut.analysis import color as color_analysis
from stylecut.analysis import scene as scene_analysis
from stylecut.analysis import speech as speech_analysis
from stylecut.analysis import synthesis, visual
from stylecut.analysis.audio import AudioResult
from stylecut.analysis.color import ColorResult
from stylecut.analysis.judgment import VisualBreakdown
from stylecut.analysis.scene import SceneResult
from stylecut.analysis.speech import SpeechStats, Transcript
from stylecut.analysis.visual import VisualResult
from stylecut.db.models import Asset, ReferenceVideo, StyleProfileRow
from stylecut.jobs.base import JobContext, JobTask
from stylecut.jobs.celery_app import celery_app
from stylecut.jobs.ingest import fail_reference, load_reference
from stylecut.llm.client import LlmError
from stylecut.media.extract import analysis_wav_args
from stylecut.media.ffmpeg import run_ffmpeg
from stylecut.schemas.style_profile import SCHEMA_VERSION, SourceInfo
from stylecut.storage import keys, s3

ANALYSIS_FAILED = {
    "code": "ANALYSIS_FAILED",
    "message": "We couldn't analyze that video.",
    "hint": "Try again, or use a different video.",
}

type StageBody = Callable[Concatenate[JobContext, ReferenceVideo, Asset, ...], dict[str, Any]]


class TranscriptArtifact(BaseModel):
    transcript: Transcript
    stats: SpeechStats


def stage(body: StageBody) -> Callable[[JobContext, str, str], dict[str, Any]]:
    """Load the reference and asset, and record a user-facing error if the stage fails."""

    @wraps(body)
    def run(ctx: JobContext, reference_id: str, asset_id: str) -> dict[str, Any]:
        try:
            reference, asset = load_reference(ctx.session, reference_id, asset_id)
            if reference.status != "analyzing":
                reference.status = "analyzing"
                ctx.session.commit()
            return body(ctx, reference, asset)
        except LlmError as exc:
            fail_reference(ctx.session, reference_id, dict(exc.as_dict()))
            raise
        except Exception as exc:
            fail_reference(ctx.session, reference_id, ANALYSIS_FAILED, detail=repr(exc)[:500])
            raise

    return run


def _load[T: BaseModel](asset: Asset, artifact: keys.DerivedArtifact, model: type[T]) -> T:
    return model.model_validate_json(s3.get_bytes(keys.reference_derived(asset.id, artifact)))


def _save(asset: Asset, artifact: keys.DerivedArtifact, value: BaseModel) -> str:
    key = keys.reference_derived(asset.id, artifact)
    s3.put_json(key, value.model_dump_json())
    return key


def _proxy(asset: Asset, tmp: str) -> Path:
    if asset.proxy_key is None:
        raise RuntimeError("asset has no proxy")
    path = Path(tmp) / "proxy.mp4"
    s3.download_file(asset.proxy_key, path)
    return path


def _duration(asset: Asset) -> float:
    return float(asset.duration_s or 0.0)


@celery_app.task(name="cpu.detect_scenes", base=JobTask)
@stage
def detect_scenes(ctx: JobContext, reference: ReferenceVideo, asset: Asset) -> dict[str, Any]:
    ctx.progress(0.1, "Detecting cuts")
    with tempfile.TemporaryDirectory(prefix="scenes-") as tmp:
        # The proxy is constant 30fps, so cut times are exact frame multiples.
        proxy_fps = float(asset.meta.get("proxy", {}).get("fps") or 30.0)
        result = scene_analysis.detect_scenes(_proxy(asset, tmp), _duration(asset), proxy_fps)
    return {"key": _save(asset, "scenes", result), "shots": len(result.shots)}


@celery_app.task(name="cpu.analyze_audio", base=JobTask)
@stage
def analyze_audio(ctx: JobContext, reference: ReferenceVideo, asset: Asset) -> dict[str, Any]:
    ctx.progress(0.1, "Listening to the audio")
    if not asset.has_audio:
        result = audio_analysis.silent_result(_duration(asset))
    else:
        with tempfile.TemporaryDirectory(prefix="audio-") as tmp:
            wav = Path(tmp) / "mix.wav"
            run_ffmpeg(analysis_wav_args(_proxy(asset, tmp), wav))
            result = audio_analysis.analyze_audio(wav)
    return {"key": _save(asset, "audio", result), "bpm": result.bpm}


@celery_app.task(name="gpu.transcribe", base=JobTask)
@stage
def transcribe(ctx: JobContext, reference: ReferenceVideo, asset: Asset) -> dict[str, Any]:
    ctx.progress(0.05, "Transcribing speech")
    speech_key = asset.meta.get("speech_key")
    if not asset.has_audio or not speech_key:
        transcript = Transcript(text="", words=[])
    else:
        with tempfile.TemporaryDirectory(prefix="speech-") as tmp:
            wav = Path(tmp) / "speech.wav"
            s3.download_file(speech_key, wav)
            transcript = speech_analysis.transcribe(wav)
    stats = speech_analysis.speech_stats(transcript.words, _duration(asset))
    artifact = TranscriptArtifact(transcript=transcript, stats=stats)
    return {"key": _save(asset, "transcript", artifact), "words": stats.word_count}


@celery_app.task(name="cpu.analyze_color", base=JobTask)
@stage
def analyze_color(ctx: JobContext, reference: ReferenceVideo, asset: Asset) -> dict[str, Any]:
    ctx.progress(0.1, "Reading colors")
    with tempfile.TemporaryDirectory(prefix="color-") as tmp:
        result = color_analysis.analyze_color(_proxy(asset, tmp), _duration(asset))
    return {"key": _save(asset, "color", result)}


@celery_app.task(name="cpu.build_contact_sheets", base=JobTask)
@stage
def build_contact_sheets(
    ctx: JobContext, reference: ReferenceVideo, asset: Asset
) -> dict[str, Any]:
    ctx.progress(0.1, "Picking frames")
    scenes = _load(asset, "scenes", SceneResult)
    with tempfile.TemporaryDirectory(prefix="visual-") as tmp:
        result, sheets = visual.analyze_visual(_proxy(asset, tmp), scenes.shots)
    for n, sheet in enumerate(sheets):
        s3.put_bytes(keys.reference_sheet(asset.id, n), sheet, "image/jpeg")
    return {"key": _save(asset, "visual", result), "sheets": len(sheets)}


def _source(reference: ReferenceVideo, asset: Asset) -> SourceInfo:
    return SourceInfo.model_validate(
        {
            "platform": reference.platform,
            "url": reference.source_url,
            "duration_s": _duration(asset),
            "aspect": synthesis.nearest_aspect(asset.width, asset.height),
            "fps": float(asset.fps or 30.0),
        }
    )


@celery_app.task(name="llm.vision_breakdown", base=JobTask)
@stage
def vision_breakdown(ctx: JobContext, reference: ReferenceVideo, asset: Asset) -> dict[str, Any]:
    ctx.progress(0.1, "Reading captions and shots")
    scenes = _load(asset, "scenes", SceneResult)
    measured = _load(asset, "visual", VisualResult)
    sheets = [s3.get_bytes(keys.reference_sheet(asset.id, n)) for n in range(measured.sheet_count)]
    breakdown = synthesis.run_visual_breakdown(
        scene=scenes,
        visual=measured,
        sheets=sheets,
        aspect=synthesis.nearest_aspect(asset.width, asset.height),
        session=ctx.session,
        job_id=ctx.job_id,
    )
    return {"key": _save(asset, "vision", breakdown)}


def default_profile_name(reference: ReferenceVideo) -> str:
    source = {"tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube"}.get(
        reference.platform, "Uploaded"
    )
    return f"{source} style · {datetime.now(UTC):%b %-d}"


@celery_app.task(name="llm.synthesize_profile", base=JobTask)
@stage
def synthesize_profile(ctx: JobContext, reference: ReferenceVideo, asset: Asset) -> dict[str, Any]:
    ctx.progress(0.1, "Building the style")
    scenes = _load(asset, "scenes", SceneResult)
    audio = _load(asset, "audio", AudioResult)
    speech = _load(asset, "transcript", TranscriptArtifact)
    color = _load(asset, "color", ColorResult)
    measured = _load(asset, "visual", VisualResult)
    breakdown = _load(asset, "vision", VisualBreakdown)
    source = _source(reference, asset)

    judgment = synthesis.run_style_synthesis(
        source=source, scene=scenes, audio=audio, speech=speech.stats,
        transcript=speech.transcript, color=color, visual=measured, breakdown=breakdown,
        session=ctx.session, job_id=ctx.job_id,
    )  # fmt: skip
    ctx.progress(0.9, "Building the style")
    profile_id = uuid4()
    name = default_profile_name(reference)
    profile = synthesis.assemble_profile(
        profile_id=profile_id, name=name, source=source, scene=scenes, audio=audio,
        speech=speech.stats, color=color, visual=measured, breakdown=breakdown,
        synthesis=judgment,
    )  # fmt: skip

    ctx.session.add(
        StyleProfileRow(
            id=profile_id,
            owner_id=reference.owner_id,
            name=name,
            schema_version=SCHEMA_VERSION,
            data=profile.model_dump(mode="json"),
            source_reference_ids=[reference.id],
        )
    )
    artifacts: tuple[keys.DerivedArtifact, ...] = (
        "scenes", "audio", "transcript", "color", "visual", "vision",
    )  # fmt: skip
    reference.derived = {
        **{name_: keys.reference_derived(asset.id, name_) for name_ in artifacts},
        "sheets": [keys.reference_sheet(asset.id, n) for n in range(measured.sheet_count)],
    }
    reference.status = "ready"
    ctx.session.commit()
    return {"style_profile_id": str(profile_id)}


@celery_app.task(name="io.cleanup_reference_media", base=JobTask)
def cleanup_reference_media(ctx: JobContext, reference_id: str, asset_id: str) -> dict[str, Any]:
    """Reference media is temporary: once the style exists, delete the video and audio now
    rather than waiting for the 24h lifecycle rule. Derived data and contact sheets stay.

    A failure here must not fail the reference: the lifecycle rule is the backstop.
    """
    ctx.progress(0.2, "Cleaning up")
    asset = ctx.session.get(Asset, UUID(asset_id))
    if asset is None or asset.kind != "reference":
        return {"deleted": 0}
    doomed = [
        k
        for k in (asset.s3_key, asset.proxy_key, asset.meta.get("speech_key"))
        if isinstance(k, str) and k.startswith(keys.EXPIRING_PREFIXES)
    ]
    s3.delete_objects(doomed)
    asset.status = "expired"
    asset.proxy_key = None
    asset.expires_at = datetime.now(UTC)
    ctx.session.commit()
    return {"deleted": len(doomed)}
