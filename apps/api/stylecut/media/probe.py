"""`probe()`: ffprobe -> the handful of facts the rest of the system needs."""

from fractions import Fraction
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from stylecut.media.ffmpeg import ffprobe_json


class AudioStreamInfo(BaseModel):
    codec: str
    sample_rate: int | None = None
    channels: int | None = None


class MediaInfo(BaseModel):
    duration_s: float
    size_bytes: int | None = None
    has_video: bool
    has_audio: bool
    # Display dimensions: rotation is already applied (a phone clip stored 1920x1080
    # with rotation 90 reports 1080x1920).
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    rotation: int = 0
    video_codec: str | None = None
    audio_streams: list[AudioStreamInfo] = []


def _fraction(value: Any) -> float | None:
    try:
        result = float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return None
    return result if result > 0 else None


def _rotation(stream: dict[str, Any]) -> int:
    raw: Any = None
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            raw = side_data["rotation"]
            break
    if raw is None:
        raw = stream.get("tags", {}).get("rotate")
    try:
        return int(round(float(raw))) % 360
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_probe(data: dict[str, Any]) -> MediaInfo:
    """Pure: ffprobe's `-show_format -show_streams` JSON -> MediaInfo."""
    streams: list[dict[str, Any]] = data.get("streams", [])
    fmt: dict[str, Any] = data.get("format", {})
    # Cover art in audio files shows up as a video stream; it is not video.
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    audio = [s for s in streams if s.get("codec_type") == "audio"]

    duration = _float(fmt.get("duration"))
    if duration is None:
        candidates = [d for s in streams if (d := _float(s.get("duration"))) is not None]
        duration = max(candidates, default=0.0)

    width = height = None
    fps = None
    rotation = 0
    if video is not None:
        rotation = _rotation(video)
        width, height = video.get("width"), video.get("height")
        if rotation in (90, 270) and width and height:
            width, height = height, width
        fps = _fraction(video.get("avg_frame_rate")) or _fraction(video.get("r_frame_rate"))

    size = fmt.get("size")
    return MediaInfo(
        duration_s=duration,
        size_bytes=int(size) if size is not None and str(size).isdigit() else None,
        has_video=video is not None,
        has_audio=bool(audio),
        width=width,
        height=height,
        fps=round(fps, 3) if fps else None,
        rotation=rotation,
        video_codec=video.get("codec_name") if video else None,
        audio_streams=[
            AudioStreamInfo(
                codec=str(s.get("codec_name", "unknown")),
                sample_rate=int(s["sample_rate"])
                if str(s.get("sample_rate", "")).isdigit()
                else None,
                channels=s.get("channels"),
            )
            for s in audio
        ],
    )


def probe(path: Path) -> MediaInfo:
    return parse_probe(ffprobe_json(path))
