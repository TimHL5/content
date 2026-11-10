"""What the LLM is allowed to output for a shoot plan.

Like `analysis/judgment.py`: creative fields only. Budgets, estimated durations, record
lengths, takes, and shoot order have no field here; `generate.finalize` computes them.
"""

from pydantic import BaseModel

from stylecut.schemas.shoot_plan import Priority, Setup
from stylecut.schemas.style_profile import CameraMotion, Framing, ShotKind


class LineDraft(BaseModel):
    id: str
    beat_id: str
    text: str
    emphasis_words: list[str]
    delivery_note: str | None


class ShotDraft(BaseModel):
    id: str
    beat_id: str
    line_ids: list[str]
    kind: ShotKind
    framing: Framing
    camera_motion: CameraMotion
    setup_id: str
    duration_s: float
    priority: Priority
    description: str
    direction: str
    will_be_cut: bool
    reference_shot_idx: int | None
    alternatives: list[str]


class PlanDraft(BaseModel):
    """Output of the `shoot_plan` prompt."""

    title_options: list[str]
    script: list[LineDraft]
    shots: list[ShotDraft]
    setups: list[Setup]
    checklist_notes: list[str]
    music_brief: str | None
    script_changes: str | None  # what was changed when the creator supplied a script


class PartDraft(BaseModel):
    """Output of the `shoot_plan_regen` prompt: a replacement for one part of a plan."""

    script: list[LineDraft]
    shots: list[ShotDraft]
    setups: list[Setup]  # only setups the replacement introduces
