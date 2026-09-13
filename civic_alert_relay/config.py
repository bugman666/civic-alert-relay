"""Process configuration.

Values come from environment variables with the ``CAR_`` prefix, optionally
loaded from a ``.env`` file. See ``configs/config.example.env``.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the relay process."""

    model_config = SettingsConfigDict(
        env_prefix="CAR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"

    # Reserved for #3 (Redis Pub/Sub fan-out). The process does not connect yet.
    redis_url: str = "redis://127.0.0.1:6379/0"

    # Reserved for later subscription / event-history storage. Unused for now.
    database_url: str = "postgresql://civic:civic@127.0.0.1:5432/civic_alert"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""

    return Settings()
