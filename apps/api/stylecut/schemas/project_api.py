"""Request and response shapes for projects and Plan Mode (docs/API.md)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from stylecut.schemas.shoot_plan import Priority, ProjectBrief, RegenerateScope, ShootPlan
from stylecut.schemas.style_profile import BeatFunction

ProjectStatus = Literal["planning", "shooting", "editing", "done"]


class ProjectCreateIn(BaseModel):
    style_profile_id: UUID
    title: str = Field(min_length=1, max_length=200)
    brief: ProjectBrief


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    brief: ProjectBrief | None = None


class ProjectOut(BaseModel):
    id: UUID
    title: str
    status: ProjectStatus
    style_profile_id: UUID | None
    style_name: str | None
    brief: ProjectBrief
    has_plan: bool
    plan_job_id: UUID | None = None  # the most recent plan job, to follow or report failure
    created_at: datetime
    updated_at: datetime


class PlanBeat(BaseModel):
    id: str
    function: BeatFunction
    must_have: bool


class PlanStyle(BaseModel):
    """The few style facts the plan screens need, so they don't load the whole profile."""

    name: str
    wpm: float
    max_shot_s: float
    beats: list[PlanBeat]


class ShootPlanOut(BaseModel):
    project_id: UUID
    title: str
    version: int
    plan: ShootPlan
    word_count: int
    style: PlanStyle
    updated_at: datetime


class LineEdit(BaseModel):
    id: str
    text: str = Field(min_length=1, max_length=2000)


class ShotEdit(BaseModel):
    id: str
    description: str | None = Field(default=None, max_length=1000)
    direction: str | None = Field(default=None, max_length=2000)
    duration_s: float | None = Field(default=None, gt=0, le=180)
    priority: Priority | None = None


class ShootPlanPatch(BaseModel):
    """Manual edits. Each is optional; the plan is re-derived and re-validated afterwards."""

    lines: list[LineEdit] | None = None
    shots: list[ShotEdit] | None = None
    shot_order: list[str] | None = None  # every shot id, in the new EDIT order


class RegenerateIn(BaseModel):
    scope: RegenerateScope
    target_id: str | None = None
    instruction: str | None = Field(default=None, max_length=500)


class ShareOut(BaseModel):
    token: str
    path: str  # relative web path of the read-only page
