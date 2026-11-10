"""Word budget and beat scaffold. Fully deterministic (docs/PLAN_MODE_SPEC.md, steps 1-2)."""

import re

from pydantic import BaseModel

from stylecut.schemas.shoot_plan import ProjectBrief
from stylecut.schemas.style_profile import BeatFunction, StyleProfile

HOOK_CLAMP_S = (1.5, 4.0)
MIN_TARGET_S, MAX_TARGET_S = 5.0, 180.0
FALLBACK_WPM = 150.0  # used only when a plan needs speech but the reference had none

_WORD = re.compile(r"[A-Za-z0-9]+(?:['’.,-][A-Za-z0-9]+)*")


class ScaffoldBeat(BaseModel):
    id: str
    function: BeatFunction
    start_s: float
    end_s: float
    technique: str
    must_have: bool


def count_words(text: str) -> int:
    """Spoken words: "$1,200" and "don't" are one word each."""
    return len(_WORD.findall(text))


def target_duration(brief: ProjectBrief, profile: StyleProfile) -> float:
    """The brief's target, or the reference's own length."""
    wanted = brief.target_duration_s or profile.source.duration_s
    return round(min(max(wanted, MIN_TARGET_S), MAX_TARGET_S), 1)


def speaking_wpm(profile: StyleProfile) -> float:
    return profile.speech.wpm if profile.speech.present and profile.speech.wpm > 0 else FALLBACK_WPM


def word_budget(target_s: float, profile: StyleProfile) -> int:
    """speech_time = target x coverage; budget = speech_time x wpm / 60.

    A reference with no speech gives a budget of 0: the plan is shots and on-screen text.
    """
    if not profile.speech.present:
        return 0
    speech_time = target_s * profile.speech.coverage_pct
    return round(speech_time * profile.speech.wpm / 60.0)


def estimate_line_seconds(text: str, wpm: float) -> float:
    return round(count_words(text) / (wpm / 60.0), 2) if wpm > 0 else 0.0


def scale_beats(profile: StyleProfile, target_s: float) -> list[ScaffoldBeat]:
    """Scale the reference's beats to the target length.

    The hook keeps its absolute length (clamped to 1.5-4s) because a hook that scales
    with the video stops being a hook; the remaining beats share what is left in
    proportion to their original lengths.
    """
    beats = sorted(profile.beats, key=lambda b: b.start_s)
    if not beats:
        return []
    hook = next((b for b in beats if b.function == "hook"), None)
    hook_len = 0.0
    if hook is not None:
        low, high = HOOK_CLAMP_S
        hook_len = min(max(hook.end_s - hook.start_s, low), high, target_s)

    others = [b for b in beats if b is not hook]
    others_total = sum(b.end_s - b.start_s for b in others)
    remaining = max(target_s - hook_len, 0.0)

    result: list[ScaffoldBeat] = []
    cursor = 0.0
    for beat in beats:
        if beat is hook:
            length = hook_len
        elif others_total > 0:
            length = remaining * (beat.end_s - beat.start_s) / others_total
        else:
            length = 0.0
        end = cursor + length
        result.append(
            ScaffoldBeat(
                id=beat.id,
                function=beat.function,
                start_s=round(cursor, 2),
                end_s=round(end, 2),
                technique=beat.technique,
                must_have=beat.must_have,
            )  # fmt: skip
        )
        cursor = end
    if result:
        result[-1].end_s = round(target_s, 2)  # absorb rounding
    return [b for b in result if b.end_s > b.start_s]
