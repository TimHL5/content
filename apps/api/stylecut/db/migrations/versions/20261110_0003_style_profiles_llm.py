"""style_profiles, llm_calls, llm_cache

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
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
        "style_profiles",
        *_base_columns(),
        sa.Column("owner_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False),
        sa.Column("data", postgresql.JSONB, nullable=False),
        sa.Column(
            "source_reference_ids",
            postgresql.ARRAY(UUID),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
        sa.Column("is_blend", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_style_profiles_owner_created", "style_profiles", ["owner_id", "created_at"])

    op.create_table(
        "llm_calls",
        *_base_columns(),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("prompt_id", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.Integer, nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float, nullable=False, server_default="0"),
        sa.Column("cache_hit", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index("ix_llm_calls_job_id", "llm_calls", ["job_id"])

    op.create_table(
        "llm_cache",
        *_base_columns(),
        sa.Column("key", sa.String(64), nullable=False, unique=True),
        sa.Column("output", postgresql.JSONB, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("llm_cache")
    op.drop_table("llm_calls")
    op.drop_table("style_profiles")
