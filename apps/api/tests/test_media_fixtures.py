import json
import os
from pathlib import Path

import pytest

from scripts.make_fixtures import make_fixtures
from stylecut.media.ffmpeg import FfmpegError, ffprobe_json, run_ffmpeg
from stylecut.media.fixtures import (
    EXPECTED_DURATION_S,
    FIXTURES,
    FPS,
    HARDCUT_DURATION_S,
    HARDCUT_TIMES_S,
    H,
    W,
    hardcut_segments,
)

SNAPSHOT = Path(__file__).parent / "snapshots" / "fixture_commands.json"


def test_ffmpeg_commands_match_snapshot() -> None:
    """Regenerate with UPDATE_SNAPSHOTS=1 after an intentional change."""
    commands = {name: build(Path("/out") / name) for name, build in FIXTURES.items()}
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(json.dumps(commands, indent=2) + "\n")
    assert commands == json.loads(SNAPSHOT.read_text())


def test_hardcut_segments_cover_the_whole_clip() -> None:
    segments = hardcut_segments()
    assert len(segments) == len(HARDCUT_TIMES_S) + 1
    assert sum(duration for _, duration in segments) == pytest.approx(HARDCUT_DURATION_S)
    colors = [color for color, _ in segments]
    assert all(a != b for a, b in zip(colors, colors[1:], strict=False))
    # Cuts must land exactly on frame boundaries.
    assert all((t * FPS) == int(t * FPS) for t in HARDCUT_TIMES_S)


def test_make_fixtures_writes_every_clip_once(tmp_path: Path) -> None:
    written = make_fixtures(tmp_path)
    assert {p.name for p in written} == set(FIXTURES)
    assert make_fixtures(tmp_path) == []  # second run is a no-op


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_generated_clip_properties(clips: Path, name: str) -> None:
    info = ffprobe_json(clips / name)
    assert float(info["format"]["duration"]) == pytest.approx(EXPECTED_DURATION_S[name], abs=0.1)

    streams = {s["codec_type"]: s for s in info["streams"]}
    if name.endswith(".wav"):
        assert set(streams) == {"audio"}
        assert streams["audio"]["sample_rate"] == "48000"
        return
    video = streams["video"]
    assert (video["width"], video["height"]) == (W, H)
    assert video["r_frame_rate"] == f"{FPS}/1"
    assert video["pix_fmt"] == "yuv420p"
    assert ("audio" in streams) == (name != "broll_5s.mp4")


def test_ffmpeg_errors_are_raised(tmp_path: Path) -> None:
    with pytest.raises(FfmpegError):
        run_ffmpeg(["-i", str(tmp_path / "missing.mp4"), str(tmp_path / "out.mp4")])
