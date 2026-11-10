"""users, assets, jobs

Revision ID: 0001
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Single-user mode until auth lands (Phase 7). Matches the DEV_USER_ID default.
DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


def _base_columns() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    users = op.create_table(
        "users",
        *_base_columns(),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("name", sa.String(200)),
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
    )
    op.bulk_insert(users, [{"id": DEV_USER_ID, "email": "dev@stylecut.local", "name": "Dev User"}])

    op.create_table(
        "assets",
        *_base_columns(),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("s3_key", sa.Text, nullable=False),
        sa.Column("proxy_key", sa.Text),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("duration_s", sa.Float),
        sa.Column("width", sa.Integer),
        sa.Column("height", sa.Integer),
        sa.Column("fps", sa.Float),
        sa.Column("has_audio", sa.Boolean),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploading"),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("meta", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.CheckConstraint(
            "kind IN ('reference', 'footage', 'music', 'sfx', 'render', 'image')",
            name="ck_assets_kind",
        ),
        sa.CheckConstraint(
            "status IN ('uploading', 'ready', 'failed', 'expired')", name="ck_assets_status"
        ),
    )
    op.create_index("ix_assets_owner_kind", "assets", ["owner_id", "kind"])
    op.create_index(
        "ix_assets_expires_ready",
        "assets",
        ["expires_at"],
        postgresql_where=sa.text("status = 'ready'"),
    )

    op.create_table(
        "jobs",
        *_base_columns(),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float, nullable=False, server_default="0"),
        sa.Column("step", sa.Text),
        sa.Column("input", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.Text, unique=True),
        sa.Column(
            "parent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_jobs_status"
        ),
        sa.CheckConstraint("progress >= 0 AND progress <= 1", name="ck_jobs_progress"),
    )
    op.create_index("ix_jobs_parent_id", "jobs", ["parent_id"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("assets")
    op.drop_table("users")
