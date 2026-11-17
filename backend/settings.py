"""Application settings from environment variables (prefix ``COLDKEEPER_``) or ``.env``.

Only composition roots (API, worker, CLI) read settings; use cases receive plain values.
"""

from __future__ import annotations

import enum
from pathlib import Path
from typing import Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(enum.StrEnum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class Settings(BaseSettings):
    """All runtime configuration; secrets are never logged."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="COLDKEEPER_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment = Environment.DEVELOPMENT
    database_url: SecretStr = SecretStr("postgresql+asyncpg://coldkeeper:coldkeeper@localhost:5433/coldkeeper")
    log_level: str = "INFO"

    # Browser origin(s) allowed to send state-changing requests (CSRF Origin check).
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:8080"])
    # Public URL shown in instructions (ingest URL for devices).
    public_url: str = "http://localhost:8080"

    session_idle_days: int = Field(default=7, ge=1, le=90)
    session_absolute_days: int = Field(default=30, ge=1, le=365)
    login_max_failures: int = Field(default=5, ge=1, le=100)
    login_lockout_minutes: int = Field(default=15, ge=1, le=1440)

    telegram_bot_token: SecretStr | None = None
    telegram_bot_username: str | None = None

    worker_connectivity_seconds: float = Field(default=15.0, gt=0)
    worker_delivery_seconds: float = Field(default=5.0, gt=0)

    demo_dir: Path = Path(".demo")

    @field_validator("telegram_bot_token", "telegram_bot_username", mode="before")
    @classmethod
    def _empty_is_none(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @property
    def secure_cookies(self) -> bool:
        """``Secure`` cookies outside local development (HTTPS is required in production)."""
        return self.env is Environment.PRODUCTION

    @property
    def bot_configured(self) -> bool:
        """A real Telegram bot is configured; otherwise delivery runs as dry-run."""
        return self.telegram_bot_token is not None and self.telegram_bot_username is not None
