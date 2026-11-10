"""Synthetic test clips built with ffmpeg lavfi sources (`make fixtures`).

Each builder returns ffmpeg arguments; nothing here touches the filesystem.
The known timestamps below are ground truth for the Phase 2 analysis tests.
"""

from collections.abc import Callable
from pathlib import Path

W, H, FPS = 540, 960, 30
SAMPLE_RATE = 48000

# vertical_hardcuts_15s.mp4: hard cuts at these times (seconds, frame-aligned at 30fps).
HARDCUT_TIMES_S: tuple[float, ...] = (1.0, 2.5, 3.5, 5.0, 7.0, 8.0, 9.5, 11.0, 12.0, 14.0)
HARDCUT_DURATION_S = 15.0
# Adjacent cards differ strongly in hue and brightness so content detectors fire on every cut.
HARDCUT_COLORS: tuple[str, ...] = (
    "red", "blue", "yellow", "green", "magenta", "white",
    "navy", "orange", "cyan", "black", "purple",
)  # fmt: skip

# music_120bpm_20s.wav: one click every 0.5s starting at t=0.
CLICK_BPM = 120.0
CLICK_DURATION_S = 20.0

_VIDEO_OUT = ("-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p")
_AUDIO_OUT = ("-c:a", "aac", "-b:a", "96k", "-ar", str(SAMPLE_RATE))
_STABLE = ("-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact")


def talking_head_10s(out: Path) -> list[str]:
    """Moving test pattern + 220Hz tone, 10s. Stands in for an a-roll clip with audio."""
    return [
        "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:duration=10",
        "-f", "lavfi", "-i", f"sine=frequency=220:sample_rate={SAMPLE_RATE}:duration=10",
        *_VIDEO_OUT, *_AUDIO_OUT, "-shortest", *_STABLE, str(out),
    ]  # fmt: skip


def broll_5s(out: Path) -> list[str]:
    """SMPTE bars, 5s, no audio stream. Stands in for silent b-roll."""
    return [
        "-f", "lavfi", "-i", f"smptebars=size={W}x{H}:rate={FPS}:duration=5",
        *_VIDEO_OUT, "-an", *_STABLE, str(out),
    ]  # fmt: skip


def music_120bpm_20s(out: Path) -> list[str]:
    """Click track: a 30ms 1kHz burst on every beat at 120 BPM."""
    beat_s = 60.0 / CLICK_BPM
    expr = f"0.8*sin(2*PI*1000*t)*lt(mod(t\\,{beat_s:g})\\,0.03)"
    source = f"aevalsrc={expr}"
    return [
        "-f", "lavfi", "-i", f"{source}:sample_rate={SAMPLE_RATE}:duration={CLICK_DURATION_S:g}",
        "-c:a", "pcm_s16le", "-ac", "1", "-map_metadata", "-1", "-fflags", "+bitexact", str(out),
    ]  # fmt: skip


def hardcut_segments() -> list[tuple[str, float]]:
    """(color, duration_s) per card, derived from HARDCUT_TIMES_S."""
    bounds = (0.0, *HARDCUT_TIMES_S, HARDCUT_DURATION_S)
    durations = [end - start for start, end in zip(bounds, bounds[1:], strict=False)]
    return list(zip(HARDCUT_COLORS, durations, strict=True))


def vertical_hardcuts_15s(out: Path) -> list[str]:
    """Solid color cards with hard cuts at HARDCUT_TIMES_S, plus a 440Hz tone."""
    segments = hardcut_segments()
    args: list[str] = []
    for color, duration in segments:
        args += [
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:size={W}x{H}:rate={FPS}:duration={duration:g}",
        ]
    audio_idx = len(segments)
    args += [
        "-f", "lavfi", "-i",
        f"sine=frequency=440:sample_rate={SAMPLE_RATE}:duration={HARDCUT_DURATION_S:g}",
    ]  # fmt: skip
    pads = "".join(f"[{i}:v]" for i in range(len(segments)))
    args += [
        "-filter_complex", f"{pads}concat=n={len(segments)}:v=1:a=0[v]",
        "-map", "[v]", "-map", f"{audio_idx}:a",
        *_VIDEO_OUT, *_AUDIO_OUT, "-shortest", *_STABLE, str(out),
    ]  # fmt: skip
    return args


FIXTURES: dict[str, Callable[[Path], list[str]]] = {
    "talking_head_10s.mp4": talking_head_10s,
    "broll_5s.mp4": broll_5s,
    "music_120bpm_20s.wav": music_120bpm_20s,
    "vertical_hardcuts_15s.mp4": vertical_hardcuts_15s,
}

EXPECTED_DURATION_S: dict[str, float] = {
    "talking_head_10s.mp4": 10.0,
    "broll_5s.mp4": 5.0,
    "music_120bpm_20s.wav": CLICK_DURATION_S,
    "vertical_hardcuts_15s.mp4": HARDCUT_DURATION_S,
}
