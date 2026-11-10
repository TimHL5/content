from uuid import UUID

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stylecut.db import models  # noqa: F401
from stylecut.db.base import Base
from stylecut.db.models import Asset, Job, User
from stylecut.db.session import get_engine
from tests.conftest import alembic_config


def test_migration_matches_models() -> None:
    """The hand-written migration and the SQLAlchemy models must not drift apart."""
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_tables_indexes_and_seed_user(db: Session, user_id: UUID) -> None:
    inspector = inspect(get_engine())
    assert {"users", "assets", "jobs"} <= set(inspector.get_table_names())
    assert {i["name"] for i in inspector.get_indexes("assets")} >= {
        "ix_assets_owner_kind",
        "ix_assets_expires_ready",
    }
    assert "ix_jobs_parent_id" in {i["name"] for i in inspector.get_indexes("jobs")}

    user = db.get(User, user_id)
    assert user is not None and user.email == "dev@stylecut.local"


def test_defaults_and_constraints(db: Session, user_id: UUID) -> None:
    asset = Asset(owner_id=user_id, kind="footage", s3_key="footage/p/a/original.mp4")
    job = Job(owner_id=user_id, type="cpu.demo_sleep")
    db.add_all([asset, job])
    db.commit()
    db.refresh(asset)
    db.refresh(job)
    assert asset.id is not None and asset.status == "uploading" and asset.meta == {}
    assert (job.status, job.progress, job.attempts, job.input) == ("queued", 0.0, 0, {})
    assert job.created_at is not None and job.updated_at is not None

    db.add(Asset(owner_id=user_id, kind="not-a-kind", s3_key="x"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add_all(
        [
            Job(owner_id=user_id, type="t", idempotency_key="dup:step:1"),
            Job(owner_id=user_id, type="t", idempotency_key="dup:step:1"),
        ]
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_migration_downgrade_and_upgrade_roundtrip() -> None:
    # Runs last in this module: it drops every table and rebuilds them.
    get_engine().dispose()
    command.downgrade(alembic_config(), "base")
    with get_engine().connect() as conn:
        remaining = conn.execute(
            text("SELECT count(*) FROM pg_tables WHERE tablename IN ('users', 'assets', 'jobs')")
        ).scalar_one()
    assert remaining == 0
    get_engine().dispose()
    command.upgrade(alembic_config(), "head")
    assert {"users", "assets", "jobs"} <= set(inspect(get_engine()).get_table_names())
