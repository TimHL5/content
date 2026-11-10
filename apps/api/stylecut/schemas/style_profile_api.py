"""Request and response shapes for the style profile endpoints (docs/API.md)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from stylecut.schemas.style_profile import StyleProfile


class StyleProfileSummary(BaseModel):
    id: UUID
    name: str
    summary: str
    platform: str
    duration_s: float
    shot_count: int
    hook_type: str
    created_at: datetime


class StyleProfileOut(BaseModel):
    """`profile` has the user's overrides applied; `overrides` lists them."""

    id: UUID
    name: str
    profile: StyleProfile
    overrides: dict[str, Any]
    sheet_urls: list[str]
    created_at: datetime
    updated_at: datetime


class StyleProfilePatch(BaseModel):
    """`overrides` maps JSON pointers to new values (`{"/captions/fill": "#FFE600"}`);
    a null value removes that override and restores the analyzed value."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    overrides: dict[str, Any] | None = None
