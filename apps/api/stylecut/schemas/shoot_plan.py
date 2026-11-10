"""ProjectBrief and ShootPlan v1 (docs/PLAN_MODE_SPEC.md).

Plan Mode tells the creator exactly what to film so the auto-editor has everything the
style needs. The LLM writes the script and designs the shots; code computes budgets,
durations, takes, and shoot order, and checks the plan against the style's rules.
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from stylecut.schemas.style_profile import CameraMotion, Framing, ShotKind

SCHEMA_VERSION = 1

Crew = Literal["solo", "two_person"]
Gear = Literal["phone", "tripod", "gimbal", "lav_mic", "ring_light", "camera"]
Priority = Literal["must", "nice"]
RegenerateScope = Literal["hook", "beat", "shot", "all"]


class Constraints(BaseModel):
    crew: Crew = "solo"
    gear: list[Gear] = ["phone"]
    locations: list[str] = []  # "home office", "kitchen", "street"
    can_show_face: bool = True
    has_screen_content: bool = False  # app demos / screen recordings available
    max_setups: int | None = Field(default=None, ge=1, le=20)


class ProjectBrief(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    key_points: list[str] = []
    script: str | None = None  # if provided, it is fitted to the style, not replaced
    target_duration_s: float | None = Field(default=None, ge=5, le=180)
    audience: str | None = None
    tone: str | None = None  # overrides the profile's delivery
    constraints: Constraints = Constraints()


class ScriptLine(BaseModel):
    id: str  # "L1"
    beat_id: str  # links to StyleProfile.beats
    text: str
    est_duration_s: float  # [D] words / (profile.speech.wpm / 60)
    emphasis_words: list[str] = []  # will drive punch-ins and caption highlights
    delivery_note: str | None = None  # "pause before the number"


class PlannedShot(BaseModel):
    id: str  # "S1"
    beat_id: str
    line_ids: list[str] = []  # empty for pure b-roll
    kind: ShotKind
    framing: Framing
    camera_motion: CameraMotion
    setup_id: str  # shots sharing location + framing + lighting
    duration_s: float  # target on-screen duration
    record_s: float  # [D] how long to record (duration x 2, at least 3s for non-speech)
    takes: int  # [D] hook 3, must a_roll 2, everything else 1
    priority: Priority
    description: str  # "Close-up of hands signing lease, slow push-in"
    direction: str  # filming instructions in plain language
    # True for a long a_roll the editor will break up with jump cuts and punch-ins, which
    # is what allows it to run past the style's max shot length.
    will_be_cut: bool = False
    reference_shot_idx: int | None = None  # which reference shot this mirrors
    alternatives: list[str] = []  # fallback if they can't get it


class Setup(BaseModel):
    id: str
    location: str
    framing_summary: str
    lighting: str  # "face a window, no overhead light"
    audio: str  # "lav mic or phone within 1m"
    orientation: Literal["vertical"] = "vertical"
    props: list[str] = []


class ShootPlan(BaseModel):
    schema_version: Literal[1] = 1
    project_id: UUID
    style_profile_id: UUID
    target_duration_s: float
    word_budget: int  # [D]
    title_options: list[str]  # on-screen hook text options
    script: list[ScriptLine]
    shots: list[PlannedShot]  # in EDIT order
    setups: list[Setup]
    shoot_order: list[str]  # [D] shot ids in SHOOT order
    checklist_notes: list[str] = []  # "Film the hook last when you're warmed up"
    music_brief: str | None = None  # mood + BPM range to pick from the library
    # Rules the plan still breaks after one repair attempt. Shown to the creator, not fatal.
    warnings: list[str] = []


def migrate_shoot_plan(data: dict[str, Any]) -> dict[str, Any]:
    """Bring stored plan JSON up to SCHEMA_VERSION. Add a step here on every bump."""
    version = data.get("schema_version", 1)
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported ShootPlan schema_version {version}")
    return data
