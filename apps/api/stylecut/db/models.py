"""SQLAlchemy models (docs/DATA_MODEL.md). Phase 0: users, assets, jobs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from stylecut.db.base import Base

ASSET_KINDS = ("reference", "footage", "music", "sfx", "render", "image")
ASSET_STATUSES = ("uploading", "ready", "failed", "expired")
JOB_STATUSES = ("queued", "running", "succeeded", "failed")
PLATFORMS = ("tiktok", "instagram", "youtube", "upload")
REFERENCE_STATUSES = ("queued", "ingesting", "ingested", "analyzing", "ready", "failed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(200))
    plan: Mapped[str] = mapped_column(String(32), nullable=False, server_default="free")


class Asset(Base):
    """Every media file."""

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(_in("kind", ASSET_KINDS), name="ck_assets_kind"),
        CheckConstraint(_in("status", ASSET_STATUSES), name="ck_assets_status"),
        Index("ix_assets_owner_kind", "owner_id", "kind"),
        Index("ix_assets_expires_ready", "expires_at", postgresql_where=text("status = 'ready'")),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False)
    proxy_key: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    duration_s: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    fps: Mapped[float | None] = mapped_column(Float)
    has_audio: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="uploading")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUSES), name="ck_jobs_status"),
        CheckConstraint("progress >= 0 AND progress <= 1", name="ck_jobs_progress"),
        Index("ix_jobs_parent_id", "parent_id"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    progress: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    step: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # `{subject_id}:{step}:{step_version}`; NULL for jobs that must always run.
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    parent_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE")
    )


class ReferenceVideo(Base):
    """One per analyzed reference. (`references` is a reserved word in Postgres.)"""

    __tablename__ = "reference_videos"
    __table_args__ = (
        CheckConstraint(_in("platform", PLATFORMS), name="ck_reference_videos_platform"),
        CheckConstraint(_in("status", REFERENCE_STATUSES), name="ck_reference_videos_status"),
        Index("ix_reference_videos_owner_created", "owner_id", "created_at"),
    )

    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    # S3 keys of scenes/audio/transcript/color/sheets, filled in by the analysis DAG.
    derived: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # {code, message, hint} when status is "failed".
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class StyleProfileRow(Base):
    """An editable style. `data` holds a validated `schemas.style_profile.StyleProfile`."""

    __tablename__ = "style_profiles"
    __table_args__ = (Index("ix_style_profiles_owner_created", "owner_id", "created_at"),)

    owner_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source_reference_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    is_blend: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class LlmCall(Base):
    """One row per LLM call (including cache hits) for cost tracking."""

    __tablename__ = "llm_calls"
    __table_args__ = (Index("ix_llm_calls_job_id", "job_id"),)

    job_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("jobs.id", ondelete="SET NULL")
    )
    prompt_id: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class LlmCache(Base):
    """key = sha256(prompt_id, version, model, inputs, images)."""

    __tablename__ = "llm_cache"

    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
