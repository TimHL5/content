"""Cuts, shot lengths, and the pacing curve. Fully deterministic.

Method (docs/STYLE_PROFILE_SPEC.md): PySceneDetect ContentDetector(threshold=27); if that
finds fewer than 2 cuts in a video longer than 10s, retry with AdaptiveDetector. Cuts
closer than 0.15s are merged.
"""

from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel

from stylecut.schemas.style_profile import Acceleration, Stats

CONTENT_THRESHOLD = 27.0
MIN_CUT_GAP_S = 0.15
ADAPTIVE_RETRY_MIN_DURATION_S = 10.0
PACING_WINDOW_S = 5.0
MIN_PARTIAL_WINDOW_S = 2.0  # a shorter trailing window is too noisy to extrapolate
ACCELERATION_SLOPE = 0.15  # cuts per 5s, per window
BURSTY_CV = 0.6
MAX_SHOT_CLAMP_S = (1.5, 6.0)

Detector = Literal["content", "adaptive"]


class ShotSpan(BaseModel):
    idx: int
    start_s: float
    end_s: float


class SceneResult(BaseModel):
    duration_s: float
    fps: float
    detector: Detector
    cuts_s: list[float]
    shots: list[ShotSpan]
    shot_len_s: Stats
    cuts_per_5s: list[float]
    acceleration: Acceleration
    max_shot_s: float


def merge_close_cuts(cuts: list[float], duration_s: float) -> list[float]:
    """Sorted cut times with near-duplicates and cuts at the very start/end removed."""
    merged: list[float] = []
    for cut in sorted(cuts):
        if cut < MIN_CUT_GAP_S or cut > duration_s - MIN_CUT_GAP_S:
            continue
        if merged and cut - merged[-1] < MIN_CUT_GAP_S:
            continue
        merged.append(round(cut, 3))
    return merged


def stats(values: list[float]) -> Stats:
    arr = np.asarray(values, dtype=float)
    return Stats(
        mean=round(float(arr.mean()), 3),
        median=round(float(np.median(arr)), 3),
        p10=round(float(np.percentile(arr, 10)), 3),
        p90=round(float(np.percentile(arr, 90)), 3),
        min=round(float(arr.min()), 3),
        max=round(float(arr.max()), 3),
    )


def pacing_curve(cuts: list[float], duration_s: float) -> list[float]:
    """Cuts per 5-second window. A trailing partial window is scaled to a 5s rate."""
    curve: list[float] = []
    start = 0.0
    while start < duration_s:
        end = min(start + PACING_WINDOW_S, duration_s)
        length = end - start
        count = sum(1 for c in cuts if start <= c < end)
        if length >= PACING_WINDOW_S - 1e-6:
            curve.append(float(count))
        elif length >= MIN_PARTIAL_WINDOW_S or not curve:
            curve.append(round(count * PACING_WINDOW_S / length, 2))
        start += PACING_WINDOW_S
    return curve


def classify_acceleration(curve: list[float]) -> Acceleration:
    """Trend first (slope of a linear fit), then burstiness (coefficient of variation)."""
    if len(curve) < 2:
        return "steady"
    arr = np.asarray(curve, dtype=float)
    slope = float(np.polyfit(np.arange(len(arr)), arr, 1)[0])
    if slope > ACCELERATION_SLOPE:
        return "speeds_up"
    if slope < -ACCELERATION_SLOPE:
        return "slows_down"
    mean = float(arr.mean())
    if mean > 0 and float(arr.std()) / mean > BURSTY_CV:
        return "bursty"
    return "steady"


def build_scene_result(
    cuts: list[float], duration_s: float, fps: float, detector: Detector = "content"
) -> SceneResult:
    """Pure: everything derived from the cut list."""
    cuts = merge_close_cuts(cuts, duration_s)
    bounds = [0.0, *cuts, round(duration_s, 3)]
    shots = [
        ShotSpan(idx=i, start_s=start, end_s=end)
        for i, (start, end) in enumerate(zip(bounds, bounds[1:], strict=False))
    ]
    lengths = stats([s.end_s - s.start_s for s in shots])
    curve = pacing_curve(cuts, duration_s)
    low, high = MAX_SHOT_CLAMP_S
    return SceneResult(
        duration_s=round(duration_s, 3),
        fps=fps,
        detector=detector,
        cuts_s=cuts,
        shots=shots,
        shot_len_s=lengths,
        cuts_per_5s=curve,
        acceleration=classify_acceleration(curve),
        max_shot_s=round(min(max(lengths.p90, low), high), 3),
    )


def _detect(path: Path, detector: Detector, fps: float) -> list[float]:
    from scenedetect import AdaptiveDetector, ContentDetector, detect

    min_scene_len = max(2, round(MIN_CUT_GAP_S * fps))
    instance = (
        ContentDetector(threshold=CONTENT_THRESHOLD, min_scene_len=min_scene_len)
        if detector == "content"
        else AdaptiveDetector(min_scene_len=min_scene_len)
    )
    scenes = detect(str(path), instance)
    # Each scene is (start, end); every start except the first is a cut.
    return [float(start.seconds) for start, _ in scenes[1:]]


def detect_scenes(path: Path, duration_s: float, fps: float) -> SceneResult:
    cuts = _detect(path, "content", fps)
    detector: Detector = "content"
    if len(cuts) < 2 and duration_s > ADAPTIVE_RETRY_MIN_DURATION_S:
        adaptive = _detect(path, "adaptive", fps)
        if len(adaptive) > len(cuts):
            cuts, detector = adaptive, "adaptive"
    return build_scene_result(cuts, duration_s, fps, detector)
