"""Alert schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from whatisup.models.alert import AlertChannelType, AlertCondition, AlertEventStatus

# ── Per-type channel config validators ────────────────────────────────────────


class EmailChannelConfig(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)

    @field_validator("to")
    @classmethod
    def validate_emails(cls, v: list[str]) -> list[str]:
        pattern = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
        for addr in v:
            if not pattern.match(addr):
                raise ValueError(f"Invalid email address: {addr!r}")
        return v


class WebhookChannelConfig(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    secret: str | None = Field(default=None, max_length=512)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Webhook URL must start with http:// or https://")
        return v


class TelegramChannelConfig(BaseModel):
    bot_token: str = Field(min_length=1, max_length=256)
    chat_id: str = Field(min_length=1, max_length=64)

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        # Telegram bot tokens format: {digits}:{alphanumeric_string}
        if not re.match(r"^\d+:[A-Za-z0-9_-]{10,}$", v):
            raise ValueError("Invalid Telegram bot token format")
        return v


class SlackChannelConfig(BaseModel):
    webhook_url: str = Field(min_length=8, max_length=2048)

    @field_validator("webhook_url")
    @classmethod
    def validate_slack_url(cls, v: str) -> str:
        if not v.startswith("https://hooks.slack.com/"):
            raise ValueError("Slack webhook URL must start with https://hooks.slack.com/")
        return v


class PagerDutyChannelConfig(BaseModel):
    integration_key: str = Field(..., min_length=32, max_length=36)
    severity: Literal["critical", "error", "warning", "info"] = "critical"


class OpsgenieChannelConfig(BaseModel):
    api_key: str = Field(..., min_length=32, max_length=64)
    region: Literal["us", "eu"] = "us"
    priority: Literal["P1", "P2", "P3", "P4", "P5"] = "P1"


_CONFIG_VALIDATORS: dict[AlertChannelType, type[BaseModel]] = {
    AlertChannelType.email: EmailChannelConfig,
    AlertChannelType.webhook: WebhookChannelConfig,
    AlertChannelType.telegram: TelegramChannelConfig,
    AlertChannelType.slack: SlackChannelConfig,
    AlertChannelType.pagerduty: PagerDutyChannelConfig,
    AlertChannelType.opsgenie: OpsgenieChannelConfig,
}


# ── Public schemas ─────────────────────────────────────────────────────────────


class AlertChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: AlertChannelType
    config: dict

    @field_validator("config")
    @classmethod
    def validate_config(cls, v: dict, info) -> dict:
        channel_type = info.data.get("type")
        validator = _CONFIG_VALIDATORS.get(channel_type)
        if validator is None:
            raise ValueError(f"Unsupported channel type: {channel_type!r}")
        # Validate via the per-type model (raises ValidationError on invalid input)
        validated = validator.model_validate(v)
        return validated.model_dump(exclude_none=True)


class AlertChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    type: AlertChannelType
    # config intentionally excluded — contains secrets

    model_config = {"from_attributes": True}


class AlertChannelTestOut(BaseModel):
    success: bool
    detail: str


class TelegramResolveIn(BaseModel):
    bot_token: str


class TelegramResolveOut(BaseModel):
    chat_id: str
    chat_name: str


class AlertRuleCreate(BaseModel):
    monitor_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    condition: AlertCondition
    min_duration_seconds: int = Field(default=0, ge=0)
    channel_ids: list[uuid.UUID] = Field(min_length=1)
    renotify_after_minutes: int | None = Field(default=None, ge=1, le=10080)
    threshold_value: float | None = Field(default=None, ge=0)
    digest_minutes: int = Field(default=0, ge=0, le=1440)
    # Storm protection
    storm_window_seconds: int | None = Field(default=None, ge=10, le=3600)
    storm_max_alerts: int | None = Field(default=None, ge=1, le=1000)
    # Baseline
    baseline_factor: float | None = Field(default=None, ge=1.1, le=100.0)
    # Anomaly detection
    anomaly_zscore_threshold: float | None = Field(default=None, ge=1.0, le=10.0)
    # Business hours schedule
    schedule: dict | None = None


class AlertRuleUpdate(BaseModel):
    enabled: bool | None = None
    condition: AlertCondition | None = None
    min_duration_seconds: int | None = Field(default=None, ge=0)
    channel_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    renotify_after_minutes: int | None = Field(default=None, ge=1, le=10080)
    threshold_value: float | None = Field(default=None, ge=0)
    digest_minutes: int | None = Field(default=None, ge=0, le=1440)
    storm_window_seconds: int | None = Field(default=None, ge=10, le=3600)
    storm_max_alerts: int | None = Field(default=None, ge=1, le=1000)
    baseline_factor: float | None = Field(default=None, ge=1.1, le=100.0)
    anomaly_zscore_threshold: float | None = Field(default=None, ge=1.0, le=10.0)
    schedule: dict | None = None


class AlertRuleOut(BaseModel):
    id: uuid.UUID
    monitor_id: uuid.UUID | None
    group_id: uuid.UUID | None
    condition: AlertCondition
    min_duration_seconds: int
    channels: list[AlertChannelOut]
    renotify_after_minutes: int | None
    threshold_value: float | None
    digest_minutes: int = 0
    storm_window_seconds: int | None = None
    storm_max_alerts: int | None = None
    baseline_factor: float | None = None
    anomaly_zscore_threshold: float | None = None
    schedule: dict | None = None
    enabled: bool = True

    model_config = {"from_attributes": True}


class AlertRuleSimulateOut(BaseModel):
    would_fire: bool
    reason: str
    monitor_name: str | None = None
    affected_monitors: list[str] = []


class AlertEventOut(BaseModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    channel_id: uuid.UUID
    sent_at: datetime
    status: AlertEventStatus
    monitor_name: str | None = None
    response_body: str | None = None

    model_config = {"from_attributes": True}
