"""Loudness, tempo, beats, energy, and onset peaks. Fully deterministic.

Input is the full mix as a WAV (see `media.extract.analysis_wav_args`). Without Demucs,
beat tracking runs on the full mix; `music_present` decides whether the result is trusted.
"""

from pathlib import Path

import numpy as np
from pydantic import BaseModel

BEAT_TOLERANCE_S = 0.08  # a cut within ±80ms of a beat is "on the beat"
ANALYSIS_SR = 22050
HOP = 256  # ~11.6ms per frame: fine enough to resolve tempo to about 1 BPM
SILENCE_LUFS = -70.0
# A steady pulse shows up as a strong autocorrelation peak of the onset envelope at the
# beat period. Speech alone stays well under this; music and click tracks sit well above.
# Measured: click track 0.97, steady tone -0.01, speech-only clip 0.01.
PULSE_CLARITY_MUSIC = 0.25
DROP_SIGMA = 2.5  # onset strength this many std devs above the mean is a "drop"
DROP_MIN_GAP_S = 0.5


class AudioResult(BaseModel):
    has_audio: bool
    integrated_lufs: float
    music_present: bool
    pulse_clarity: float
    bpm: float | None
    beats_s: list[float]
    energy_curve: list[float]  # RMS per second, normalized 0-1
    drops_s: list[float]
    onsets_s: list[float]


def silent_result(duration_s: float) -> AudioResult:
    return AudioResult(
        has_audio=False,
        integrated_lufs=SILENCE_LUFS,
        music_present=False,
        pulse_clarity=0.0,
        bpm=None,
        beats_s=[],
        energy_curve=[0.0] * max(1, int(np.ceil(duration_s))),
        drops_s=[],
        onsets_s=[],
    )


def cut_on_beat_fraction(cuts_s: list[float], beats_s: list[float]) -> float | None:
    """Share of cuts within ±80ms of a beat. None when there are no cuts or no beats."""
    if not cuts_s or not beats_s:
        return None
    beats = np.asarray(beats_s)
    hits = sum(1 for cut in cuts_s if float(np.min(np.abs(beats - cut))) <= BEAT_TOLERANCE_S)
    return round(hits / len(cuts_s), 3)


def _integrated_lufs(path: Path) -> float:
    import pyloudnorm
    import soundfile

    data, rate = soundfile.read(str(path))
    if len(data) < rate * 0.4:  # BS.1770 needs at least one 400ms gating block
        return SILENCE_LUFS
    loudness = float(pyloudnorm.Meter(rate).integrated_loudness(data))
    return round(max(loudness, SILENCE_LUFS), 2) if np.isfinite(loudness) else SILENCE_LUFS


def _energy_curve(y: np.ndarray, sr: int) -> list[float]:
    seconds = max(1, int(np.ceil(len(y) / sr)))
    rms = np.array(
        [float(np.sqrt(np.mean(np.square(y[i * sr : (i + 1) * sr])))) for i in range(seconds)]
    )
    peak = float(rms.max())
    return [round(float(v / peak), 3) if peak > 0 else 0.0 for v in rms]


def _pulse_clarity(onset_env: np.ndarray, sr: int, bpm: float) -> float:
    """Normalized autocorrelation of the onset envelope at one beat period (0-1)."""
    if bpm <= 0 or len(onset_env) < 8:
        return 0.0
    env = onset_env - onset_env.mean()
    denom = float(np.dot(env, env))
    lag = round(60.0 / bpm * sr / HOP)
    if denom <= 0 or lag <= 0 or lag >= len(env):
        return 0.0
    return round(max(0.0, float(np.dot(env[:-lag], env[lag:])) / denom), 3)


def _peaks(times: np.ndarray, strength: np.ndarray, min_gap_s: float) -> list[float]:
    """Strongest-first peak picking with a minimum spacing."""
    chosen: list[float] = []
    for i in np.argsort(strength)[::-1]:
        t = float(times[i])
        if all(abs(t - c) >= min_gap_s for c in chosen):
            chosen.append(t)
    return sorted(round(t, 3) for t in chosen)


def analyze_audio(path: Path) -> AudioResult:
    import librosa

    y, sr = librosa.load(str(path), sr=ANALYSIS_SR, mono=True)
    duration = len(y) / sr if sr else 0.0
    if len(y) == 0 or float(np.max(np.abs(y))) < 1e-4:
        result = silent_result(duration)
        return result.model_copy(update={"has_audio": True})

    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr, hop_length=HOP)
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=HOP)
    # The median interval between tracked beats is more precise than the tempogram bin.
    bpm = (
        60.0 / float(np.median(np.diff(beats)))
        if len(beats) > 1
        else float(np.atleast_1d(tempo)[0])
    )
    clarity = _pulse_clarity(onset_env, sr, bpm)
    music = clarity >= PULSE_CLARITY_MUSIC and len(beats) >= 4

    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=HOP)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=HOP)
    threshold = float(onset_env.mean() + DROP_SIGMA * onset_env.std())
    strong = [i for i in onset_frames if onset_env[i] >= threshold]
    drops = _peaks(
        librosa.frames_to_time(np.asarray(strong, dtype=int), sr=sr, hop_length=HOP),
        onset_env[strong],
        DROP_MIN_GAP_S,
    )

    return AudioResult(
        has_audio=True,
        integrated_lufs=_integrated_lufs(path),
        music_present=music,
        pulse_clarity=clarity,
        bpm=round(bpm, 1) if music else None,
        beats_s=[round(float(b), 3) for b in beats] if music else [],
        energy_curve=_energy_curve(y, sr),
        drops_s=drops,
        onsets_s=[round(float(t), 3) for t in onset_times],
    )
