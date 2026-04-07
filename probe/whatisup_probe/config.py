"""Probe configuration."""

from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProbeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Central server
    central_api_url: str = "http://localhost:8000"
    probe_api_key: str = ""

    @field_validator("probe_api_key")
    @classmethod
    def _validate_api_key(cls, v: str) -> str:
        if v and not v.startswith("wiu_"):
            raise ValueError("Invalid probe API key format (expected wiu_ prefix)")
        return v

    # Probe identity
    probe_name: str = "default-probe"
    probe_location: str = "Unknown"

    # Heartbeat interval (seconds) — how often to refresh monitor list
    heartbeat_interval: int = 30

    # Max concurrent checks
    max_concurrent_checks: int = 10
    # Max concurrent Playwright/Chromium instances (subset of max_concurrent_checks)
    max_concurrent_scenarios: int = 2

    # Logging
    log_level: str = "INFO"


_settings: ProbeSettings | None = None


def get_settings() -> ProbeSettings:
    global _settings
    if _settings is None:
        _settings = ProbeSettings()
    return _settings
