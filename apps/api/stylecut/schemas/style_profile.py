"""StyleProfile v1 (docs/STYLE_PROFILE_SPEC.md): a reference video's style in a form
the planner and editor can act on.

[D] = deterministic: computed by code, never produced or changed by the LLM.
[J] = judgment: produced by the LLM from evidence.

Units: every `*_pct` and `*_ratio` field is a fraction in 0-1. Times are seconds
unless the name ends in `_ms`.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

Fraction = Annotated[float, Field(ge=0, le=1)]

Platform = Literal["tiktok", "instagram", "youtube", "upload"]
Aspect = Literal["9:16", "1:1", "4:5", "16:9"]
Acceleration = Literal["steady", "speeds_up", "slows_down", "bursty"]
ShotKind = Literal["a_roll", "b_roll", "screen", "text_card", "reaction", "product", "pov", "other"]
Framing = Literal["ecu", "cu", "mcu", "ms", "ws", "overhead", "pov", "screen"]
CameraMotion = Literal["static", "handheld", "push_in", "pull_out", "pan", "whip", "tracking"]
CaptionCase = Literal["upper", "lower", "sentence", "title"]
CaptionHighlight = Literal["none", "color", "box", "scale"]
EmojiLevel = Literal["none", "sparse", "frequent"]
CaptionAnimation = Literal["none", "pop", "fade", "typewriter", "bounce"]
OverlayKind = Literal["title", "label", "arrow", "emoji", "progress_bar", "sticker", "other"]
OverlayPosition = Literal["top", "center", "bottom", "follow"]
Delivery = Literal["energetic", "conversational", "calm", "deadpan", "whisper"]
VoiceType = Literal["on_camera", "voiceover", "mixed", "none"]
SfxDensity = Literal["none", "low", "medium", "high"]
SfxType = Literal["whoosh", "pop", "ding", "riser", "bass_hit", "click", "record_scratch"]
BeatFunction = Literal[
    "hook", "context", "tension", "value", "proof", "twist", "payoff", "cta", "loop"
]
HookType = Literal[
    "bold_claim", "question", "pov", "list_tease", "result_first",
    "controversy", "visual_shock", "story_open", "challenge",
]  # fmt: skip
ZoomTrigger = Literal["emphasis_word", "new_point", "joke", "number"]
TransitionStyle = Literal["hard_cut", "whip", "zoom", "fade", "glitch"]
TextCardUsage = Literal["none", "intro", "sections", "frequent"]

# Bundled caption presets and OFL fonts. The font files ship with the renderer (Phase 4);
# analysis only ever maps what it sees to the nearest of these and never claims an exact font.
CAPTION_PRESETS: tuple[str, ...] = ("bold_pop", "clean_subtle", "boxed", "karaoke", "minimal_lower")
BUNDLED_FONTS: tuple[str, ...] = (
    "Montserrat ExtraBold",
    "Inter Bold",
    "Anton",
    "Poppins SemiBold",
    "Bebas Neue",
)


class Stats(BaseModel):
    mean: float
    median: float
    p10: float
    p90: float
    min: float
    max: float


class SourceInfo(BaseModel):
    platform: Platform
    url: str | None = None
    duration_s: float  # [D]
    aspect: Aspect  # [D] nearest of the supported aspects
    fps: float  # [D] of the original, not the proxy


class Pacing(BaseModel):  # all [D]
    shot_count: int
    shot_len_s: Stats
    cuts_per_5s: list[float]  # pacing curve
    acceleration: Acceleration
    max_shot_s: float  # rule used by the pacing pass (= p90, clamped 1.5-6s)
    cut_on_beat_pct: Fraction | None = None  # None when there is no music


class Shot(BaseModel):
    idx: int
    start_s: float  # [D]
    end_s: float  # [D]
    kind: ShotKind  # [J]
    framing: Framing  # [J]
    camera_motion: CameraMotion  # [J], informed by motion_score
    punch_in: bool  # [D] detected scale jump vs the previous shot
    motion_score: float  # [D]
    description: str  # [J] short, content-agnostic
    beat_id: str | None = None  # [D] the beat whose time range contains the shot's midpoint


class CaptionStyle(BaseModel):  # [J] from vision, mapped to our presets
    present: bool
    preset: str
    font_family: str
    case: CaptionCase
    words_per_chunk: tuple[int, int]
    lines: Literal[1, 2]
    position_y_pct: Fraction  # 0 = top, 1 = bottom (center of the caption block)
    fill: str
    stroke: str | None = None
    stroke_px: int
    shadow: bool
    highlight: CaptionHighlight
    highlight_color: str | None = None
    emoji: EmojiLevel
    animation: CaptionAnimation


class Overlay(BaseModel):  # [J]
    kind: OverlayKind
    start_s: float
    end_s: float
    position: OverlayPosition
    text_example: str | None = None  # paraphrased pattern, never the reference's words


class Speech(BaseModel):  # [D] unless noted
    present: bool
    coverage_pct: Fraction
    wpm: float
    pause_ms_p50: float
    pause_ms_p90: float
    filler_rate: float  # fillers per 100 words
    delivery: Delivery | None = None  # [J]
    voice_type: VoiceType  # [J]


class Audio(BaseModel):  # [D] unless noted
    integrated_lufs: float
    music_present: bool
    bpm: float | None = None
    energy_curve: list[float]  # RMS per second, normalized 0-1
    drops_s: list[float]  # large onset peaks
    sfx_density: SfxDensity  # [J]
    sfx_types: list[SfxType]  # [J]
    music_mood: str | None = None  # [J] a mood description, never the track name


class Color(BaseModel):  # [D] unless noted
    luma_mean: float
    contrast: float
    saturation: float
    warmth: float
    eq: dict[str, float]  # ffmpeg eq params: brightness, contrast, saturation, gamma
    look: str  # [J]


class Beat(BaseModel):  # [J]; time ranges are snapped to shot boundaries by code
    id: str
    function: BeatFunction
    start_s: float
    end_s: float
    technique: str
    must_have: bool


class Hook(BaseModel):  # [J]
    type: HookType
    duration_s: float  # [D] length of the hook beat
    template: str  # content-agnostic fill-in-the-blank pattern
    visual: str


class EditingRules(BaseModel):
    punch_in_every_s: float | None = None  # [D] average interval between punch-ins
    punch_in_scale: float  # [D] median detected scale, default 1.15
    zoom_on: list[ZoomTrigger]  # [J]
    broll_ratio: Fraction  # [D] share of runtime that is b_roll/screen/product
    jump_cut_silences: bool  # [J]
    transitions: list[TransitionStyle]  # [J]
    loop_ending: bool  # [J]
    text_card_usage: TextCardUsage  # [J]


class StyleProfile(BaseModel):
    schema_version: Literal[1] = 1
    id: UUID
    name: str
    source: SourceInfo
    summary: str  # [J]
    pacing: Pacing
    shots: list[Shot]
    captions: CaptionStyle
    overlays: list[Overlay]
    speech: Speech
    audio: Audio
    color: Color
    hook: Hook
    beats: list[Beat]
    rules: EditingRules
    confidence: dict[str, Fraction]  # per [J] block: {"captions": 0.9, "beats": 0.7, ...}
    user_overrides: dict[str, Any] = {}  # JSON pointer -> value; applied on read


def migrate_style_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Bring stored profile JSON up to SCHEMA_VERSION. Add a step here on every bump."""
    version = data.get("schema_version", 1)
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported StyleProfile schema_version {version}")
    return data


class JsonPointerError(ValueError):
    pass


def _tokens(pointer: str) -> list[str]:
    if not pointer.startswith("/") or pointer == "/":
        raise JsonPointerError(f"not a JSON pointer: {pointer!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]


def apply_overrides(data: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of `data` with each `{"/captions/fill": "#FFF"}` override applied.

    Only existing paths can be overridden: an override never adds a key or list item.
    """
    import copy

    result = copy.deepcopy(data)
    for pointer, value in overrides.items():
        tokens = _tokens(pointer)
        node: Any = result
        for depth, token in enumerate(tokens):
            last = depth == len(tokens) - 1
            if isinstance(node, dict):
                if token not in node:
                    raise JsonPointerError(f"no such field: {pointer}")
                if last:
                    node[token] = value
                else:
                    node = node[token]
            elif isinstance(node, list):
                if not token.isdigit() or int(token) >= len(node):
                    raise JsonPointerError(f"no such item: {pointer}")
                if last:
                    node[int(token)] = value
                else:
                    node = node[int(token)]
            else:
                raise JsonPointerError(f"no such field: {pointer}")
    return result


# Identity and bookkeeping are not style and cannot be overridden.
PROTECTED_POINTER_PREFIXES: tuple[str, ...] = (
    "/id", "/schema_version", "/user_overrides", "/source",
)  # fmt: skip
