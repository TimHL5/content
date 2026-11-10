import json
import os
from pathlib import Path

import pytest

from stylecut.media.ffmpeg import ffprobe_json, run_ffmpeg
from stylecut.media.probe import parse_probe, probe
from stylecut.media.proxy import proxy_args, speech_wav_args

SNAPSHOT = Path(__file__).parent / "snapshots" / "proxy_commands.json"


def _video_stream(**overrides: object) -> dict[str, object]:
    return {
        "codec_type": "video",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "avg_frame_rate": "30000/1001",
        "r_frame_rate": "30/1",
        **overrides,
    }


def test_parse_probe_applies_rotation_to_dimensions() -> None:
    info = parse_probe(
        {
            "format": {"duration": "12.5", "size": "1000"},
            "streams": [
                _video_stream(side_data_list=[{"rotation": -90}]),
                {"codec_type": "audio", "codec_name": "aac", "sample_rate": "44100", "channels": 2},
            ],
        }
    )
    assert (info.width, info.height, info.rotation) == (1080, 1920, 270)
    assert info.fps == pytest.approx(29.97, abs=0.001)
    assert (info.duration_s, info.size_bytes) == (12.5, 1000)
    assert info.has_video and info.has_audio
    assert info.audio_streams[0].model_dump() == {
        "codec": "aac",
        "sample_rate": 44100,
        "channels": 2,
    }


def test_parse_probe_legacy_rotate_tag_and_no_audio() -> None:
    info = parse_probe(
        {"format": {"duration": "3"}, "streams": [_video_stream(tags={"rotate": "90"})]}
    )
    assert (info.width, info.height, info.rotation) == (1080, 1920, 90)
    assert info.has_audio is False and info.audio_streams == []


def test_parse_probe_audio_file_with_cover_art_is_not_video() -> None:
    info = parse_probe(
        {
            "format": {"duration": "200.0"},
            "streams": [
                {"codec_type": "audio", "codec_name": "mp3", "sample_rate": "44100"},
                _video_stream(codec_name="mjpeg", disposition={"attached_pic": 1}),
            ],
        }
    )
    assert info.has_video is False and info.has_audio is True
    assert (info.width, info.height, info.fps) == (None, None, None)


def test_parse_probe_falls_back_to_stream_duration_and_bad_fps() -> None:
    info = parse_probe({"streams": [_video_stream(duration="4.2", avg_frame_rate="0/0")]})
    assert info.duration_s == 4.2
    assert info.fps == 30.0  # r_frame_rate
    assert parse_probe({}).duration_s == 0.0


def test_proxy_commands_match_snapshot() -> None:
    commands = {
        "proxy_with_audio": proxy_args(Path("/in/a.mov"), Path("/out/proxy.mp4"), has_audio=True),
        "proxy_silent": proxy_args(Path("/in/a.mov"), Path("/out/proxy.mp4"), has_audio=False),
        "speech_wav": speech_wav_args(Path("/in/a.mov"), Path("/out/speech.wav")),
    }
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(json.dumps(commands, indent=2) + "\n")
    assert commands == json.loads(SNAPSHOT.read_text())


def test_probe_real_clips(clips: Path) -> None:
    head = probe(clips / "talking_head_10s.mp4")
    assert (head.width, head.height, head.fps) == (540, 960, 30.0)
    assert head.duration_s == pytest.approx(10.0, abs=0.1)
    assert head.has_video and head.has_audio

    broll = probe(clips / "broll_5s.mp4")
    assert broll.has_video and not broll.has_audio

    music = probe(clips / "music_120bpm_20s.wav")
    assert not music.has_video and music.has_audio
    assert music.audio_streams[0].sample_rate == 48000


def test_proxy_of_landscape_25fps_source(tmp_path: Path) -> None:
    """A 1280x720 25fps source becomes 960x540 at a constant 30fps with 48k stereo AAC."""
    src = tmp_path / "landscape.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=25:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=330:sample_rate=44100:duration=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(src),
        ]  # fmt: skip
    )
    out = tmp_path / "proxy.mp4"
    run_ffmpeg(proxy_args(src, out, has_audio=True))

    info = probe(out)
    assert (info.width, info.height, info.fps) == (960, 540, 30.0)
    assert info.duration_s == pytest.approx(2.0, abs=0.15)
    assert info.video_codec == "h264"
    assert info.audio_streams[0].model_dump() == {
        "codec": "aac",
        "sample_rate": 48000,
        "channels": 2,
    }

    wav = tmp_path / "speech.wav"
    run_ffmpeg(speech_wav_args(src, wav))
    audio = ffprobe_json(wav)["streams"][0]
    assert (audio["codec_name"], audio["sample_rate"], audio["channels"]) == (
        "pcm_s16le",
        "16000",
        1,
    )


def test_proxy_never_upscales_and_handles_silent_and_odd_sizes(tmp_path: Path) -> None:
    src = tmp_path / "small.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=270x482:rate=30:duration=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv444p",
            str(src),
        ]  # fmt: skip
    )
    out = tmp_path / "proxy.mp4"
    run_ffmpeg(proxy_args(src, out, has_audio=False))
    info = probe(out)
    assert (info.width, info.height) == (270, 482)
    assert not info.has_audio
