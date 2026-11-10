"""projects, shoot_plans

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)


def _base_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "projects",
        *_base_columns(),
        sa.Column("owner_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "style_profile_id", UUID, sa.ForeignKey("style_profiles.id", ondelete="SET NULL")
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("brief", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="planning"),
        sa.Column("share_token", sa.String(64), unique=True),
        sa.CheckConstraint(
            "status IN ('planning', 'shooting', 'editing', 'done')", name="ck_projects_status"
        ),
    )
    op.create_index("ix_projects_owner_created", "projects", ["owner_id", "created_at"])

    op.create_table(
        "shoot_plans",
        *_base_columns(),
        sa.Column(
            "project_id", UUID, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("data", postgresql.JSONB, nullable=False),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.text("true")),
    )
    op.create_index(
        "uq_shoot_plans_project_version", "shoot_plans", ["project_id", "version"], unique=True
    )


def downgrade() -> None:
    op.drop_table("shoot_plans")
    op.drop_table("projects")
