"""Proxy transcodes. Analysis and preview renders work on these, never on originals.

Builders return ffmpeg argument lists (snapshot-tested); `media.ffmpeg.run_ffmpeg` runs them.
"""

from pathlib import Path

PROXY_SHORT_SIDE = 540
PROXY_FPS = 30
SPEECH_SAMPLE_RATE = 16000

# Short side becomes 540 (never upscaled); the long side follows, rounded to an even number.
_SCALE = (
    f"scale=w='if(lt(iw,ih),min({PROXY_SHORT_SIDE},iw),-2)'"
    f":h='if(lt(iw,ih),-2,min({PROXY_SHORT_SIDE},ih))'"
)
# x264 needs even dimensions; this only trims a pixel when a source has an odd short side.
_EVEN = "crop=trunc(iw/2)*2:trunc(ih/2)*2"


def proxy_args(src: Path, out: Path, has_audio: bool) -> list[str]:
    """540p H.264, constant 30fps, AAC 48k stereo. Rotation metadata is baked in by ffmpeg."""
    args = [
        "-i", str(src),
        "-map", "0:v:0",
        "-vf", f"{_SCALE},{_EVEN},fps={PROXY_FPS},format=yuv420p,setsar=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-g", str(PROXY_FPS),  # a keyframe every second: cheap, accurate seeking for analysis
        "-fps_mode", "cfr",
    ]  # fmt: skip
    if has_audio:
        args += ["-map", "0:a:0", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k"]
    else:
        args += ["-an"]
    args += ["-map_metadata", "-1", "-movflags", "+faststart", str(out)]
    return args


def speech_wav_args(src: Path, out: Path) -> list[str]:
    """16 kHz mono PCM for speech-to-text."""
    return [
        "-i", str(src),
        "-vn", "-map", "0:a:0",
        "-ac", "1", "-ar", str(SPEECH_SAMPLE_RATE), "-c:a", "pcm_s16le",
        "-map_metadata", "-1", str(out),
    ]  # fmt: skip
