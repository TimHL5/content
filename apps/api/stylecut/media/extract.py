"""Audio extraction and frame reading for analysis. Works on proxies."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

ANALYSIS_SAMPLE_RATE = 48000


def analysis_wav_args(src: Path, out: Path) -> list[str]:
    """Full mix as 48 kHz stereo PCM: the input for loudness and beat analysis."""
    return [
        "-i", str(src),
        "-vn", "-map", "0:a:0",
        "-ac", "2", "-ar", str(ANALYSIS_SAMPLE_RATE), "-c:a", "pcm_s16le",
        "-map_metadata", "-1", str(out),
    ]  # fmt: skip


class FrameReader:
    """Random-access frame reads from a video file (BGR uint8 arrays).

    Decoding goes through OpenCV's bundled ffmpeg libraries; no subprocess is involved.
    """

    def __init__(self, path: Path) -> None:
        import cv2

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(str(path))
        if not self._cap.isOpened():
            raise OSError(f"cannot open video: {path.name}")
        self.fps: float = float(self._cap.get(cv2.CAP_PROP_FPS) or 30.0)
        self.frame_count: int = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

    def __enter__(self) -> "FrameReader":
        return self

    def __exit__(self, *_: object) -> None:
        self._cap.release()

    def frame_index(self, t: float) -> int:
        last = max(self.frame_count - 1, 0)
        return min(max(round(t * self.fps), 0), last)

    def at_index(self, index: int) -> Any | None:
        self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self._cap.read()
        return frame if ok else None

    def at(self, t: float) -> Any | None:
        return self.at_index(self.frame_index(t))

    def pair_at(self, t: float) -> tuple[Any, Any] | None:
        """Two consecutive frames starting at time t (for optical flow)."""
        first = self.at(t)
        if first is None:
            return None
        ok, second = self._cap.read()
        return (first, second) if ok else None

    def sample(self, times: list[float]) -> Iterator[tuple[float, Any]]:
        for t in times:
            frame = self.at(t)
            if frame is not None:
                yield t, frame
