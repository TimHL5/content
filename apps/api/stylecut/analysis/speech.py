"""Transcript and delivery statistics.

faster-whisper produces word timestamps (the only model call here); every number derived
from them (WPM, pauses, fillers, coverage) is computed by `speech_stats`, which is pure.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel

from stylecut.settings import get_settings

WHISPER_SAMPLE_RATE = 16000
MIN_WORDS_FOR_SPEECH = 3
# A gap up to this long is a pause *inside* speech; anything longer is non-speech time.
MAX_INTRA_SPEECH_GAP_S = 0.7
MIN_PAUSE_S = 0.05  # shorter gaps are timestamp jitter, not pauses
FILLER_PAUSE_S = 0.15

ALWAYS_FILLERS = frozenset({"um", "uh", "umm", "uhh", "erm", "er", "hmm", "mm", "basically"})
FILLER_BIGRAMS = frozenset({("you", "know")})
# "like" and "so" are fillers only in filler position (set off by a comma or a pause).
CONTEXT_FILLERS = frozenset({"like", "so"})


class Word(BaseModel):
    text: str  # as transcribed, including attached punctuation
    start: float
    end: float
    probability: float | None = None


class Transcript(BaseModel):
    language: str | None = None
    text: str
    words: list[Word]


class SpeechStats(BaseModel):
    present: bool
    word_count: int
    coverage_pct: float
    wpm: float
    pause_ms_p50: float
    pause_ms_p90: float
    filler_count: int
    filler_rate: float  # per 100 words


def _norm(text: str) -> str:
    return re.sub(r"[^a-z']", "", text.lower())


def _is_filler(words: list[Word], normalized: list[str], i: int) -> bool:
    token = normalized[i]
    if token in ALWAYS_FILLERS:
        return True
    if i + 1 < len(words) and (token, normalized[i + 1]) in FILLER_BIGRAMS:
        return True
    if token not in CONTEXT_FILLERS:
        return False
    word = words[i]
    own_comma = word.text.rstrip().endswith(",")
    prev_comma = i > 0 and words[i - 1].text.rstrip().endswith(",")
    pause_before = i > 0 and word.start - words[i - 1].end >= FILLER_PAUSE_S
    pause_after = i + 1 < len(words) and words[i + 1].start - word.end >= FILLER_PAUSE_S
    if token == "like":
        return (own_comma or prev_comma) and (pause_after or pause_before)
    return own_comma and (i == 0 or pause_before)  # sentence-opening "So,"


def count_fillers(words: list[Word]) -> int:
    normalized = [_norm(w.text) for w in words]
    return sum(1 for i in range(len(words)) if _is_filler(words, normalized, i))


def speech_stats(words: list[Word], duration_s: float) -> SpeechStats:
    """Pure. WPM is measured over speech time only, so pauses for b-roll don't lower it."""
    if len(words) < MIN_WORDS_FOR_SPEECH or duration_s <= 0:
        return SpeechStats(
            present=False, word_count=len(words), coverage_pct=0.0, wpm=0.0,
            pause_ms_p50=0.0, pause_ms_p90=0.0, filler_count=0, filler_rate=0.0,
        )  # fmt: skip

    ordered = sorted(words, key=lambda w: w.start)
    gaps = [max(0.0, nxt.start - cur.end) for cur, nxt in zip(ordered, ordered[1:], strict=False)]
    speech_time = sum(max(0.0, w.end - w.start) for w in ordered)
    speech_time += sum(g for g in gaps if g <= MAX_INTRA_SPEECH_GAP_S)
    speech_time = min(max(speech_time, 1e-6), duration_s)

    pauses_ms = [g * 1000 for g in gaps if g >= MIN_PAUSE_S]
    fillers = count_fillers(ordered)
    return SpeechStats(
        present=True,
        word_count=len(ordered),
        coverage_pct=round(speech_time / duration_s, 3),
        wpm=round(len(ordered) / (speech_time / 60.0), 1),
        pause_ms_p50=round(float(np.percentile(pauses_ms, 50)), 1) if pauses_ms else 0.0,
        pause_ms_p90=round(float(np.percentile(pauses_ms, 90)), 1) if pauses_ms else 0.0,
        filler_count=fillers,
        filler_rate=round(fillers * 100.0 / len(ordered), 2),
    )


@lru_cache(maxsize=1)
def _model() -> Any:
    from faster_whisper import WhisperModel

    # device="auto" uses CUDA when present; int8 keeps CPU-only machines usable.
    return WhisperModel(get_settings().whisper_model, device="auto", compute_type="auto")


def transcribe(wav_path: Path) -> Transcript:
    """16 kHz mono WAV -> words with timestamps (VAD on)."""
    import soundfile

    # Hand Whisper the samples directly. Its own file decoder (PyAV) breaks across PyAV
    # releases, and the WAV is already in the format it wants.
    samples, rate = soundfile.read(str(wav_path), dtype="float32", always_2d=False)
    if rate != WHISPER_SAMPLE_RATE:
        raise ValueError(f"expected {WHISPER_SAMPLE_RATE} Hz audio, got {rate}")
    if samples.ndim > 1:
        samples = samples.mean(axis=1)
    segments, info = _model().transcribe(samples, word_timestamps=True, vad_filter=True)
    words: list[Word] = []
    texts: list[str] = []
    for segment in segments:
        texts.append(segment.text.strip())
        for w in segment.words or []:
            words.append(
                Word(
                    text=w.word.strip(),
                    start=round(float(w.start), 3),
                    end=round(float(w.end), 3),
                    probability=round(float(w.probability), 3),
                )
            )
    return Transcript(language=getattr(info, "language", None), text=" ".join(texts), words=words)
