"""Probe schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from whatisup.models.probe import NetworkType
from whatisup.models.result import CheckStatus


class ProbeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    location_name: str = Field(min_length=1, max_length=255)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    network_type: NetworkType = NetworkType.external


class ProbeUpdate(BaseModel):
    location_name: str | None = Field(default=None, min_length=1, max_length=255)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    is_active: bool | None = None
    network_type: NetworkType | None = None


class ProbeOut(BaseModel):
    id: uuid.UUID
    name: str
    location_name: str
    latitude: float | None
    longitude: float | None
    is_active: bool
    last_seen_at: datetime | None
    network_type: NetworkType = NetworkType.external

    model_config = {"from_attributes": True}


class ProbeRegistered(ProbeOut):
    """Returned once at probe creation — includes the plaintext API key."""

    api_key: str


class ProbeCheckResultIn(BaseModel):
    """Payload pushed by a probe to report a check result."""

    monitor_id: uuid.UUID
    checked_at: datetime
    status: CheckStatus
    http_status: int | None = Field(default=None, ge=100, le=599)
    response_time_ms: float | None = Field(default=None, ge=0)
    redirect_count: int = Field(default=0, ge=0, le=50)
    final_url: str | None = Field(default=None, max_length=2048)
    ssl_valid: bool | None = None
    ssl_expires_at: datetime | None = None
    ssl_days_remaining: int | None = None
    error_message: str | None = Field(default=None, max_length=1000)
    scenario_result: dict | None = None
    dns_resolved_values: list[str] | None = None
    # HTTP waterfall timing
    dns_resolve_ms: int | None = Field(default=None, ge=0)
    ttfb_ms: int | None = Field(default=None, ge=0)
    download_ms: int | None = Field(default=None, ge=0)
    # API schema fingerprint
    schema_fingerprint: str | None = Field(default=None, max_length=64)


class ProbeHealthPayload(BaseModel):
    """System health metrics reported by the probe at each heartbeat."""

    cpu_percent: float | None = Field(default=None, ge=0, le=100)
    ram_percent: float | None = Field(default=None, ge=0, le=100)
    disk_percent: float | None = Field(default=None, ge=0, le=100)
    load_avg_1m: float | None = Field(default=None, ge=0)
    monitors_active: int | None = Field(default=None, ge=0)
    checks_running: int | None = Field(default=None, ge=0)


class ProbeHeartbeatRequest(BaseModel):
    """Body sent by the probe at each heartbeat."""

    health: ProbeHealthPayload | None = None


class ProbeHeartbeatResponse(BaseModel):
    """Response to probe heartbeat — includes monitor configs to check."""

    monitors: list[ProbeMonitorConfig]


class ProbeMonitorConfig(BaseModel):
    id: uuid.UUID
    url: str
    interval_seconds: int
    timeout_seconds: int
    follow_redirects: bool
    expected_status_codes: list[int]
    ssl_check_enabled: bool
    ssl_expiry_warn_days: int
    check_type: str = "http"
    tcp_port: int | None = None
    dns_record_type: str | None = None
    dns_expected_value: str | None = None
    dns_nameservers: list[str] | None = None
    keyword: str | None = None
    keyword_negate: bool = False
    expected_json_path: str | None = None
    expected_json_value: str | None = None
    scenario_steps: list | None = None
    scenario_variables: list | None = None
    trigger_now: bool = False
    # Advanced HTTP assertions
    body_regex: str | None = None
    expected_headers: dict[str, str] | None = None
    json_schema: dict | None = None
    # Schema drift detection
    schema_drift_enabled: bool = False
    # SMTP checks
    smtp_port: int | None = None
    smtp_starttls: bool = False
    # UDP checks
    udp_port: int | None = None
    # Domain expiry checks
    domain_expiry_warn_days: int = 30
    # Auto-pause after N consecutive failures (informational — enforced server-side)
    auto_pause_after: int | None = None


class ProbeMonitorStatus(BaseModel):
    """Status of a probe for a given monitor (last check result)."""

    probe_id: uuid.UUID
    name: str
    location_name: str
    latitude: float | None
    longitude: float | None
    is_active: bool
    last_seen_at: datetime | None
    last_status: CheckStatus | None
    last_checked_at: datetime | None
    response_time_ms: float | None


class ProbeStatsOut(BaseModel):
    """Probe with 24h availability stats and live health — used for dashboard map."""

    id: uuid.UUID
    name: str
    location_name: str
    latitude: float | None
    longitude: float | None
    is_active: bool
    last_seen_at: datetime | None
    network_type: NetworkType
    uptime_24h: float | None
    check_count_24h: int
    health: ProbeHealthPayload | None = None

    model_config = {"from_attributes": True}
