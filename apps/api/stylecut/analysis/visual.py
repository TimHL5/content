"""Contact sheets for the vision model, plus two deterministic per-shot measurements:
optical-flow motion score and punch-in detection.

Contact sheets (docs/STYLE_PROFILE_SPEC.md): 2 frames per shot at 25% and 75% of the shot,
at most 48 frames, up to 3x4 tiles per sheet, each tile 360px tall with `#shot_idx t=12.4s`
burned in. They are low-resolution and kept only for the Style Card and as LLM input;
they never go into a user's output.
"""

from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from stylecut.analysis.scene import ShotSpan
from stylecut.media.extract import FrameReader

MAX_FRAMES = 48
GRID_COLS, GRID_ROWS = 4, 3
TILES_PER_SHEET = GRID_COLS * GRID_ROWS
TILE_HEIGHT = 360
JPEG_QUALITY = 80

FLOW_WIDTH = 320  # motion scores are in pixels/frame at this width
FLOW_PAIRS_PER_SHOT = 4

PUNCH_IN_SCALE_RANGE = (1.05, 1.6)
PUNCH_IN_MIN_INLIERS = 15
PUNCH_IN_MIN_INLIER_RATIO = 0.3
DEFAULT_PUNCH_IN_SCALE = 1.15


class SheetFrame(BaseModel):
    shot_idx: int
    t: float


class ShotMeasure(BaseModel):
    idx: int
    motion_score: float
    punch_in: bool
    punch_in_scale: float | None = None


class VisualResult(BaseModel):
    frames: list[SheetFrame]  # in sheet order
    sheet_count: int
    shots: list[ShotMeasure]


def pick_frames(shots: list[ShotSpan], max_frames: int = MAX_FRAMES) -> list[SheetFrame]:
    """Two frames per shot when they fit, else one per shot, else an even sample of shots."""
    if not shots:
        return []
    if len(shots) * 2 <= max_frames:
        positions: tuple[float, ...] = (0.25, 0.75)
        chosen = shots
    else:
        positions = (0.5,)
        if len(shots) <= max_frames:
            chosen = shots
        else:
            picks = np.linspace(0, len(shots) - 1, max_frames).round().astype(int)
            chosen = [shots[i] for i in sorted(set(picks.tolist()))]
    return [
        SheetFrame(shot_idx=s.idx, t=round(s.start_s + (s.end_s - s.start_s) * p, 3))
        for s in chosen
        for p in positions
    ]


def _label(tile: Any, text: str) -> None:
    import cv2

    font, scale, thickness = cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
    (width, height), baseline = cv2.getTextSize(text, font, scale, thickness)
    cv2.rectangle(tile, (0, 0), (width + 10, height + baseline + 10), (0, 0, 0), -1)
    cv2.putText(tile, text, (5, height + 5), font, scale, (255, 255, 255), thickness, cv2.LINE_AA)


def build_sheets(frames: list[tuple[SheetFrame, Any]]) -> list[bytes]:
    """Lay labeled tiles out on 3x4 sheets and return them as JPEG bytes."""
    import cv2

    sheets: list[bytes] = []
    if not frames:
        return sheets
    first = frames[0][1]
    tile_w = max(2, round(TILE_HEIGHT * first.shape[1] / first.shape[0]))
    for start in range(0, len(frames), TILES_PER_SHEET):
        batch = frames[start : start + TILES_PER_SHEET]
        # Size the sheet to the tiles it holds, so a short video is not mostly black.
        cols = min(len(batch), GRID_COLS)
        rows = -(-len(batch) // GRID_COLS)
        sheet = np.zeros((rows * TILE_HEIGHT, cols * tile_w, 3), dtype=np.uint8)
        for n, (meta, frame) in enumerate(batch):
            tile = cv2.resize(frame, (tile_w, TILE_HEIGHT), interpolation=cv2.INTER_AREA)
            _label(tile, f"#{meta.shot_idx} t={meta.t:.1f}s")
            row, col = divmod(n, GRID_COLS)
            sheet[
                row * TILE_HEIGHT : (row + 1) * TILE_HEIGHT, col * tile_w : (col + 1) * tile_w
            ] = tile
        ok, encoded = cv2.imencode(".jpg", sheet, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise RuntimeError("could not encode contact sheet")
        sheets.append(encoded.tobytes())
    return sheets


def _gray(frame: Any, width: int) -> Any:
    import cv2

    height = max(2, round(width * frame.shape[0] / frame.shape[1]))
    return cv2.cvtColor(cv2.resize(frame, (width, height)), cv2.COLOR_BGR2GRAY)


def flow_magnitude(first: Any, second: Any) -> float:
    """Mean Farneback optical-flow magnitude between two frames (px/frame at FLOW_WIDTH)."""
    import cv2

    flow = cv2.calcOpticalFlowFarneback(
        _gray(first, FLOW_WIDTH),
        _gray(second, FLOW_WIDTH),
        None,
        0.5,
        3,
        15,
        3,
        5,
        1.2,
        0,  # type: ignore[call-overload]
    )
    return float(np.linalg.norm(flow, axis=2).mean())


def estimate_punch_in(before: Any, after: Any) -> float | None:
    """Scale of `after` relative to `before` if it is the same scene zoomed in, else None.

    ORB features are matched across the cut and fitted to a similarity transform with
    RANSAC. A scale of 1.05-1.6 backed by enough inliers counts as a punch-in.
    """
    import cv2

    orb = cv2.ORB.create(nfeatures=800)
    kp_a, des_a = orb.detectAndCompute(_gray(before, 480), None)
    kp_b, des_b = orb.detectAndCompute(_gray(after, 480), None)
    if des_a is None or des_b is None or len(kp_a) < 20 or len(kp_b) < 20:
        return None
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(des_a, des_b)
    if len(matches) < PUNCH_IN_MIN_INLIERS:
        return None
    src = np.array([kp_a[m.queryIdx].pt for m in matches], dtype=np.float32)
    dst = np.array([kp_b[m.trainIdx].pt for m in matches], dtype=np.float32)
    matrix, inliers = cv2.estimateAffinePartial2D(
        src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0
    )
    if matrix is None or inliers is None:
        return None
    count = int(inliers.sum())
    if count < PUNCH_IN_MIN_INLIERS or count / len(matches) < PUNCH_IN_MIN_INLIER_RATIO:
        return None
    scale = float(np.hypot(matrix[0, 0], matrix[0, 1]))
    low, high = PUNCH_IN_SCALE_RANGE
    return round(scale, 3) if low <= scale <= high else None


def measure_shots(reader: FrameReader, shots: list[ShotSpan]) -> list[ShotMeasure]:
    frame_s = 1.0 / reader.fps
    measures: list[ShotMeasure] = []
    for i, shot in enumerate(shots):
        length = shot.end_s - shot.start_s
        magnitudes: list[float] = []
        for k in range(FLOW_PAIRS_PER_SHOT):
            t = shot.start_s + length * (k + 0.5) / FLOW_PAIRS_PER_SHOT
            # Both frames must lie inside the shot, or the cut itself reads as motion.
            if t + frame_s >= shot.end_s - frame_s:
                continue
            pair = reader.pair_at(t)
            if pair is not None:
                magnitudes.append(flow_magnitude(*pair))

        scale: float | None = None
        if i > 0:
            cut_index = reader.frame_index(shot.start_s)
            before, after = reader.at_index(cut_index - 1), reader.at_index(cut_index)
            if before is not None and after is not None:
                scale = estimate_punch_in(before, after)
        measures.append(
            ShotMeasure(
                idx=shot.idx,
                motion_score=round(float(np.mean(magnitudes)), 3) if magnitudes else 0.0,
                punch_in=scale is not None,
                punch_in_scale=scale,
            )
        )
    return measures


def analyze_visual(path: Path, shots: list[ShotSpan]) -> tuple[VisualResult, list[bytes]]:
    """Returns the measurements and the contact sheets (JPEG bytes, in order)."""
    picks = pick_frames(shots)
    with FrameReader(path) as reader:
        frames = [(pick, frame) for pick in picks if (frame := reader.at(pick.t)) is not None]
        measures = measure_shots(reader, shots)
    sheets = build_sheets(frames)
    return (
        VisualResult(frames=[meta for meta, _ in frames], sheet_count=len(sheets), shots=measures),
        sheets,
    )


def punch_in_summary(measures: list[ShotMeasure], duration_s: float) -> tuple[float | None, float]:
    """(average seconds between punch-ins or None, median punch-in scale or the default)."""
    scales = [m.punch_in_scale for m in measures if m.punch_in_scale is not None]
    if not scales or duration_s <= 0:
        return None, DEFAULT_PUNCH_IN_SCALE
    return round(duration_s / len(scales), 2), round(float(np.median(scales)), 3)
