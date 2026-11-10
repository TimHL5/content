"""Color statistics and an approximate ffmpeg `eq` filter. Fully deterministic.

One frame per second is sampled. Stats are normalized so they do not depend on resolution:
    luma_mean   0-1   mean lightness (LAB L)
    contrast    0-~0.5 std dev of lightness
    saturation  0-1   mean HSV saturation
    warmth      -1..1 mean LAB b* (positive = yellow/warm, negative = blue/cool)
"""

from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from stylecut.media.extract import FrameReader

SAMPLE_EVERY_S = 1.0

# Neutral baseline: a typical well-exposed phone clip. `eq` expresses how far the reference
# sits from it, scaled down so applying it nudges footage toward the look without clipping.
NEUTRAL_LUMA = 0.50
NEUTRAL_CONTRAST = 0.22
NEUTRAL_SATURATION = 0.35
EQ_BRIGHTNESS_GAIN, EQ_BRIGHTNESS_RANGE = 0.4, (-0.15, 0.15)
EQ_CONTRAST_GAIN, EQ_CONTRAST_RANGE = 1.5, (0.8, 1.3)
EQ_SATURATION_GAIN, EQ_SATURATION_RANGE = 1.2, (0.7, 1.5)


class ColorResult(BaseModel):
    luma_mean: float
    contrast: float
    saturation: float
    warmth: float
    eq: dict[str, float]
    frames_sampled: int


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    return round(min(max(value, bounds[0]), bounds[1]), 3)


def eq_params(luma: float, contrast: float, saturation: float) -> dict[str, float]:
    return {
        "brightness": _clamp((luma - NEUTRAL_LUMA) * EQ_BRIGHTNESS_GAIN, EQ_BRIGHTNESS_RANGE),
        "contrast": _clamp(1 + (contrast - NEUTRAL_CONTRAST) * EQ_CONTRAST_GAIN, EQ_CONTRAST_RANGE),
        "saturation": _clamp(
            1 + (saturation - NEUTRAL_SATURATION) * EQ_SATURATION_GAIN, EQ_SATURATION_RANGE
        ),
        "gamma": 1.0,
    }


def frame_stats(frame: Any) -> tuple[float, float, float, float]:
    """(luma, contrast, saturation, warmth) of one BGR frame."""
    import cv2

    small = cv2.resize(frame, (160, max(1, round(160 * frame.shape[0] / frame.shape[1]))))
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV).astype(np.float32)
    lightness = lab[:, :, 0] / 255.0
    return (
        float(lightness.mean()),
        float(lightness.std()),
        float(hsv[:, :, 1].mean() / 255.0),
        float((lab[:, :, 2].mean() - 128.0) / 127.0),
    )


def summarize(samples: list[tuple[float, float, float, float]]) -> ColorResult:
    if not samples:
        return ColorResult(
            luma_mean=NEUTRAL_LUMA,
            contrast=NEUTRAL_CONTRAST,
            saturation=NEUTRAL_SATURATION,
            warmth=0.0,
            eq=eq_params(NEUTRAL_LUMA, NEUTRAL_CONTRAST, NEUTRAL_SATURATION),
            frames_sampled=0,
        )
    luma, contrast, saturation, warmth = (float(np.mean(col)) for col in zip(*samples, strict=True))
    return ColorResult(
        luma_mean=round(luma, 3),
        contrast=round(contrast, 3),
        saturation=round(saturation, 3),
        warmth=round(warmth, 3),
        eq=eq_params(luma, contrast, saturation),
        frames_sampled=len(samples),
    )


def analyze_color(path: Path, duration_s: float) -> ColorResult:
    times = [t + SAMPLE_EVERY_S / 2 for t in np.arange(0.0, max(duration_s - 0.05, 0.0), 1.0)]
    with FrameReader(path) as reader:
        return summarize([frame_stats(frame) for _, frame in reader.sample(times or [0.0])])
