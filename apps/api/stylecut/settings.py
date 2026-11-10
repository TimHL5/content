"""Runtime configuration. Everything comes from the environment (see .env.example)."""

from functools import lru_cache
from uuid import UUID

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    anthropic_api_key: SecretStr | None = None
    llm_model_smart: str = "claude-sonnet-5-5"
    llm_model_fast: str = "claude-haiku-5-5"

    database_url: str = "postgresql+psycopg://stylecut:stylecut@postgres:5432/stylecut"
    redis_url: str = "redis://redis:6379/0"

    s3_endpoint: str = "http://minio:9000"
    # What the browser can reach; presigned URLs are signed for this host.
    s3_public_endpoint: str | None = None
    s3_bucket: str = "stylecut"
    presign_ttl_s: int = 900
    upload_part_bytes: int = 8 * 1024 * 1024
    max_reference_bytes: int = 200 * 1024 * 1024
    max_library_bytes: int = 50 * 1024 * 1024
    max_reference_duration_s: float = 180.0
    reference_ttl_hours: int = 24
    s3_access_key: SecretStr = SecretStr("")
    s3_secret_key: SecretStr = SecretStr("")

    enable_url_ingest: bool = True
    whisper_model: str = "large-v3"

    # Single-user mode until auth lands in Phase 7.
    dev_user_id: UUID = UUID("00000000-0000-0000-0000-000000000001")
    enable_dev_routes: bool = False
    web_origin: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
