"""Tests run against real Postgres, Redis, and MinIO (docker compose or CI services).

They use a separate database (`<name>_test`, recreated per session) and Redis db 15,
so running them never touches dev data.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

_dev_url = make_url(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://stylecut:stylecut@postgres:5432/stylecut")
)
_test_url = _dev_url.set(database=f"{_dev_url.database}_test")
_redis_base = os.environ.get("REDIS_URL", "redis://redis:6379/0").rsplit("/", 1)[0]

# Must be set before anything imports stylecut.settings.
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
os.environ["REDIS_URL"] = f"{_redis_base}/15"
os.environ["ENABLE_DEV_ROUTES"] = "true"
# Presigned URLs must be reachable from inside the test process.
os.environ["S3_PUBLIC_ENDPOINT"] = os.environ.get("S3_ENDPOINT", "http://minio:9000")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from scripts.bootstrap_storage import ensure_bucket, ensure_lifecycle  # noqa: E402
from scripts.make_fixtures import make_fixtures  # noqa: E402
from stylecut.db.session import get_sessionmaker  # noqa: E402
from stylecut.settings import get_settings  # noqa: E402


def alembic_config() -> Config:
    return Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))


@pytest.fixture(scope="session", autouse=True)
def _infrastructure() -> Iterator[None]:
    admin = create_engine(_dev_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{_test_url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{_test_url.database}"'))
    admin.dispose()
    command.upgrade(alembic_config(), "head")

    ensure_bucket()
    ensure_lifecycle()
    yield


@pytest.fixture
def db() -> Iterator[Session]:
    with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def client() -> Iterator[TestClient]:
    from stylecut.api.app import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def user_id() -> UUID:
    return get_settings().dev_user_id


@pytest.fixture(scope="session")
def clips(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The synthetic fixture clips (`make fixtures`), generated once per test run."""
    out = tmp_path_factory.mktemp("fixtures")
    make_fixtures(out)
    return out


@pytest.fixture
def eager() -> Iterator[None]:
    """Run Celery tasks inline, through the real apply_async and task base class."""
    from stylecut.jobs.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    try:
        yield
    finally:
        celery_app.conf.task_always_eager = False
