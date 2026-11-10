"""What the LLM is allowed to output.

These models contain judgment fields only. Measured values (cut times, shot lengths,
BPM, loudness, WPM, color stats, punch-ins, ratios) have no field here, so the model
cannot change or invent them: `synthesis.assemble_profile` copies them from code.

Kept free of numeric/length constraints because structured outputs do not enforce
them; `assemble_profile` clamps and normalizes instead.
"""

import re
from typing import Literal

from pydantic import BaseModel

from stylecut.schemas.style_profile import (
    BUNDLED_FONTS,
    CAPTION_PRESETS,
    BeatFunction,
    CameraMotion,
    CaptionAnimation,
    CaptionCase,
    CaptionHighlight,
    CaptionStyle,
    Delivery,
    EmojiLevel,
    Framing,
    HookType,
    Overlay,
    SfxDensity,
    SfxType,
    ShotKind,
    TextCardUsage,
    TransitionStyle,
    VoiceType,
    ZoomTrigger,
)

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _hex(value: str | None, default: str | None) -> str | None:
    return value.upper() if value is not None and _HEX.match(value) else default


def _unit(value: float) -> float:
    return round(min(max(float(value), 0.0), 1.0), 3)


class ShotJudgment(BaseModel):
    idx: int
    kind: ShotKind
    framing: Framing
    camera_motion: CameraMotion
    description: str


class CaptionJudgment(BaseModel):
    present: bool
    preset: str
    font_family: str
    case: CaptionCase
    words_per_chunk_min: int
    words_per_chunk_max: int
    lines: Literal[1, 2]
    position_y_pct: float
    fill: str
    stroke: str | None
    stroke_px: int
    shadow: bool
    highlight: CaptionHighlight
    highlight_color: str | None
    emoji: EmojiLevel
    animation: CaptionAnimation

    def to_caption_style(self) -> CaptionStyle:
        """Map onto bundled presets/fonts and valid ranges. Never trust free-form values."""
        low = min(max(self.words_per_chunk_min, 1), 8)
        high = min(max(self.words_per_chunk_max, low), 8)
        highlight_color = _hex(self.highlight_color, None)
        highlight = self.highlight
        if highlight == "color" and highlight_color is None:
            highlight = "none"
        return CaptionStyle(
            present=self.present,
            preset=self.preset if self.preset in CAPTION_PRESETS else CAPTION_PRESETS[0],
            font_family=self.font_family if self.font_family in BUNDLED_FONTS else BUNDLED_FONTS[0],
            case=self.case,
            words_per_chunk=(low, high),
            lines=self.lines,
            position_y_pct=_unit(self.position_y_pct),
            fill=_hex(self.fill, "#FFFFFF") or "#FFFFFF",
            stroke=_hex(self.stroke, None),
            stroke_px=min(max(self.stroke_px, 0), 16),
            shadow=self.shadow,
            highlight=highlight,
            highlight_color=highlight_color if highlight != "none" else None,
            emoji=self.emoji,
            animation=self.animation,
        )


class VisualConfidence(BaseModel):
    shots: float
    captions: float
    overlays: float


class VisualBreakdown(BaseModel):
    """Output of the `visual_breakdown` prompt."""

    shots: list[ShotJudgment]
    captions: CaptionJudgment
    overlays: list[Overlay]
    setting_notes: str
    confidence: VisualConfidence


class BeatJudgment(BaseModel):
    id: str
    function: BeatFunction
    start_s: float
    end_s: float
    technique: str
    must_have: bool


class HookJudgment(BaseModel):
    type: HookType
    template: str
    visual: str


class RulesJudgment(BaseModel):
    zoom_on: list[ZoomTrigger]
    jump_cut_silences: bool
    transitions: list[TransitionStyle]
    loop_ending: bool
    text_card_usage: TextCardUsage


class AudioJudgment(BaseModel):
    sfx_density: SfxDensity
    sfx_types: list[SfxType]
    music_mood: str | None


class SpeechJudgment(BaseModel):
    delivery: Delivery | None
    voice_type: VoiceType


class SynthesisConfidence(BaseModel):
    hook: float
    beats: float
    rules: float
    audio: float
    speech: float
    color: float


class SynthesisOut(BaseModel):
    """Output of the `style_synthesis` prompt."""

    summary: str
    hook: HookJudgment
    beats: list[BeatJudgment]
    rules: RulesJudgment
    audio_judgment: AudioJudgment
    speech_judgment: SpeechJudgment
    color_look: str
    confidence: SynthesisConfidence
