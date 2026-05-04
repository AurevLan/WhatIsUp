"""CheckResult and stats schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from whatisup.models.result import CheckStatus


class CheckResultOut(BaseModel):
    id: uuid.UUID
    monitor_id: uuid.UUID
    probe_id: uuid.UUID
    checked_at: datetime
    status: CheckStatus
    http_status: int | None
    response_time_ms: float | None
    redirect_count: int
    final_url: str | None
    ssl_valid: bool | None
    ssl_expires_at: datetime | None
    ssl_days_remaining: int | None
    error_message: str | None
    scenario_result: dict | None = None
    dns_resolved_values: list[str] | None = None
    tls_audit: dict | None = None
    dns_consistency: dict | None = None

    model_config = {"from_attributes": True}


class UptimeStats(BaseModel):
    monitor_id: uuid.UUID
    period_hours: int
    total_checks: int
    up_checks: int
    # Multi-probe consensus: a time window is "up" if at least one probe in
    # the same network view saw the service up. The global uptime_percent is
    # the worst of the per-view percentages so a regional outage still shows.
    uptime_percent: float
    internal_uptime_percent: float | None = None
    external_uptime_percent: float | None = None
    avg_response_time_ms: float | None
    p95_response_time_ms: float | None


class ProbeStatus(BaseModel):
    probe_id: uuid.UUID
    probe_name: str
    location_name: str
    last_status: CheckStatus | None
    last_checked_at: datetime | None
    response_time_ms: float | None
