"""Probe schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from whatisup.models.result import CheckStatus


class ProbeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    location_name: str = Field(min_length=1, max_length=255)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)


class ProbeUpdate(BaseModel):
    location_name: str | None = Field(default=None, min_length=1, max_length=255)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)


class ProbeOut(BaseModel):
    id: uuid.UUID
    name: str
    location_name: str
    latitude: float | None
    longitude: float | None
    is_active: bool
    last_seen_at: datetime | None

    model_config = {"from_attributes": True}


class ProbeRegistered(ProbeOut):
    """Returned once at probe creation — includes the plaintext API key."""
    api_key: str


class ProbeCheckResultIn(BaseModel):
    """Payload pushed by a probe to report a check result."""
    monitor_id: uuid.UUID
    checked_at: datetime
    status: CheckStatus
    http_status: int | None = None
    response_time_ms: float | None = None
    redirect_count: int = 0
    final_url: str | None = None
    ssl_valid: bool | None = None
    ssl_expires_at: datetime | None = None
    ssl_days_remaining: int | None = None
    error_message: str | None = Field(default=None, max_length=1000)


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
