"""The only place that runs ffmpeg/ffprobe.

Commands are argument lists, never shell strings. Builders elsewhere return the
arguments *after* the binary name so they can be snapshot-tested.
"""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# Prepended to every ffmpeg call: quiet, non-interactive, overwrite outputs.
GLOBAL_ARGS: tuple[str, ...] = ("-hide_banner", "-loglevel", "error", "-nostdin", "-y")


class FfmpegError(RuntimeError):
    def __init__(self, binary: str, returncode: int, stderr: str) -> None:
        super().__init__(f"{binary} exited with {returncode}: {stderr.strip()[-2000:]}")
        self.returncode = returncode
        self.stderr = stderr


def _run(binary: str, args: Sequence[str], timeout_s: float | None) -> str:
    proc = subprocess.run(  # noqa: S603  (argument list, no shell)
        [binary, *args], capture_output=True, text=True, timeout=timeout_s, check=False
    )
    if proc.returncode != 0:
        raise FfmpegError(binary, proc.returncode, proc.stderr)
    return proc.stdout


def run_ffmpeg(args: Sequence[str], timeout_s: float | None = 600) -> None:
    _run(FFMPEG, [*GLOBAL_ARGS, *args], timeout_s)


def ffprobe_json(path: Path, timeout_s: float | None = 60) -> dict[str, Any]:
    """Raw ffprobe output (format + streams). `media.probe()` in Phase 1 builds on this."""
    out = _run(
        FFPROBE,
        ["-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        timeout_s,
    )
    data: dict[str, Any] = json.loads(out)
    return data
