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
        if not v:
            raise ValueError("PROBE_API_KEY is required. Set it in the environment or .env file.")
        if not v.startswith("wiu_"):
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

    # Disk spill buffer for results when the central API is unreachable
    # (default path: <tempdir>/whatisup_probe_spill.jsonl)
    result_spill_path: str | None = None
    result_spill_max_entries: int = 5000

    # Liveness file touched at every sync cycle — used by the Docker HEALTHCHECK
    liveness_file: str = "/tmp/whatisup_probe_alive"

    # Max HTTP response body size read into memory (bytes) — protects the
    # probe from OOM on a monitored endpoint returning a huge payload
    http_max_body_bytes: int = 10 * 1024 * 1024

    # Logging
    log_level: str = "INFO"

    # plan D, D-1 — discovery engine
    # Unix socket the `docker` source reads (read-only inventory: containers +
    # published ports). Absent by default from the compose file — the source
    # only becomes usable once an operator opts in and mounts it `:ro`.
    discovery_docker_socket: str = "/var/run/docker.sock"
    # How often each enabled discovery source re-runs and pushes a fresh
    # snapshot. Independent from heartbeat_interval: discovery is inventory,
    # not a liveness signal, and doesn't need to be nearly as frequent.
    discovery_interval_seconds: int = 900


_settings: ProbeSettings | None = None


def get_settings() -> ProbeSettings:
    global _settings
    if _settings is None:
        _settings = ProbeSettings()
    return _settings
