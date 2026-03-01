"""Application configuration via environment variables."""

from __future__ import annotations

import logging
from typing import Annotated

from pydantic import AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_SECRET = "CHANGE_ME_IN_PRODUCTION"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "WhatIsUp"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "production"

    # Security
    secret_key: str = _DEFAULT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # CORS
    cors_allowed_origins: list[str] = Field(default=["http://localhost:5173"])

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # Database
    database_url: str = "postgresql+asyncpg://whatisup:whatisup@localhost:5432/whatisup"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Email (SMTP)
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@example.com"
    smtp_tls: bool = True

    # Probe
    probe_result_rate_limit: str = "30/minute"
    probe_heartbeat_interval_seconds: int = 30

    # Feature flags
    registration_open: bool = True  # False = invite-only after first user

    @model_validator(mode="after")
    def warn_default_secrets(self) -> "Settings":
        if self.environment == "production" and self.secret_key == _DEFAULT_SECRET:
            logger.warning(
                "SECRET_KEY is set to the default value — "
                "this is insecure for production. Set SECRET_KEY env var."
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
