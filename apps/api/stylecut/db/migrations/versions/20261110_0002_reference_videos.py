"""reference_videos

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reference_videos",
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
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column(
            "derived", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("error", postgresql.JSONB),
        sa.CheckConstraint(
            "platform IN ('tiktok', 'instagram', 'youtube', 'upload')",
            name="ck_reference_videos_platform",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'ingesting', 'ingested', 'analyzing', 'ready', 'failed')",
            name="ck_reference_videos_status",
        ),
    )
    op.create_index(
        "ix_reference_videos_owner_created", "reference_videos", ["owner_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("reference_videos")
