"""Alert schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from whatisup.core.validators import validate_email_list
from whatisup.models.alert import (
    AlertChannelType,
    AlertCondition,
    AlertEventStatus,
)

# ── Per-type channel config validators ────────────────────────────────────────


class EmailChannelConfig(BaseModel):
    to: list[str] = Field(min_length=1, max_length=20)

    @field_validator("to")
    @classmethod
    def validate_emails(cls, v: list[str]) -> list[str]:
        return validate_email_list(v)


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
    # B-3 — the `secret_token` pinned on setWebhook, echoed back by Telegram in
    # X-Telegram-Bot-Api-Secret-Token. Same rule as Slack: no secret, no button.
    signing_secret: str | None = Field(default=None, max_length=256)

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, v: str) -> str:
        # Telegram bot tokens format: {digits}:{alphanumeric_string}
        if not re.match(r"^\d+:[A-Za-z0-9_-]{10,}$", v):
            raise ValueError("Invalid Telegram bot token format")
        return v


class SlackChannelConfig(BaseModel):
    webhook_url: str = Field(min_length=8, max_length=2048)
    # B-3 — the Slack app's signing secret. Optional: without it the channel
    # still sends alerts, it just carries no acknowledge button, because a
    # callback we cannot verify is one we will refuse.
    signing_secret: str | None = Field(default=None, max_length=256)

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


class SignalChannelConfig(BaseModel):
    api_url: str = Field(min_length=8, max_length=2048)
    sender_number: str = Field(min_length=5, max_length=20)
    recipients: list[str] = Field(min_length=1, max_length=20)

    @field_validator("api_url")
    @classmethod
    def validate_api_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Signal API URL must start with http:// or https://")
        return v

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, v: list[str]) -> list[str]:
        pattern = re.compile(r"^\+\d{7,15}$")
        for number in v:
            if not pattern.match(number):
                msg = f"Invalid phone number: {number!r} (E.164 format: +1234567890)"
                raise ValueError(msg)
        return v

    @field_validator("sender_number")
    @classmethod
    def validate_sender(cls, v: str) -> str:
        if not re.match(r"^\+\d{7,15}$", v):
            raise ValueError("Sender number must be E.164 format: +1234567890")
        return v


class DiscordChannelConfig(BaseModel):
    webhook_url: str = Field(min_length=8, max_length=2048)

    @field_validator("webhook_url")
    @classmethod
    def validate_discord_url(cls, v: str) -> str:
        if not v.startswith(
            ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/")
        ):
            raise ValueError(
                "Discord webhook URL must start with https://discord.com/api/webhooks/"
            )
        return v


class MattermostChannelConfig(BaseModel):
    webhook_url: str = Field(min_length=8, max_length=2048)

    @field_validator("webhook_url")
    @classmethod
    def validate_mm_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Mattermost webhook URL must start with http:// or https://")
        return v


class TeamsChannelConfig(BaseModel):
    webhook_url: str = Field(min_length=8, max_length=2048)

    @field_validator("webhook_url")
    @classmethod
    def validate_teams_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("Teams webhook URL must start with https://")
        return v


_CONFIG_VALIDATORS: dict[AlertChannelType, type[BaseModel]] = {
    AlertChannelType.email: EmailChannelConfig,
    AlertChannelType.webhook: WebhookChannelConfig,
    AlertChannelType.telegram: TelegramChannelConfig,
    AlertChannelType.slack: SlackChannelConfig,
    AlertChannelType.pagerduty: PagerDutyChannelConfig,
    AlertChannelType.opsgenie: OpsgenieChannelConfig,
    AlertChannelType.signal: SignalChannelConfig,
    AlertChannelType.discord: DiscordChannelConfig,
    AlertChannelType.mattermost: MattermostChannelConfig,
    AlertChannelType.teams: TeamsChannelConfig,
}


# ── Public schemas ─────────────────────────────────────────────────────────────


class AlertChannelCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    type: AlertChannelType
    config: dict
    team_id: uuid.UUID | None = None
    webhook_template: str | None = None

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


class AlertChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict | None = None
    webhook_template: str | None = None


class AlertChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    type: AlertChannelType
    team_id: uuid.UUID | None = None
    webhook_template: str | None = None
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


def assert_latency_rule_is_fireable(
    condition: AlertCondition,
    threshold_value: float | None,
    baseline_factor: float | None,
    anomaly_zscore_threshold: float | None,
) -> None:
    """Reject a ``latency_anomaly`` rule that names zero or several modes.

    Plan cap v2, F4 — the merged condition infers its sensitivity mode
    (absolute / relative / statistical) from which one of the three fields is
    set (``services/conditions/latency.py``). Called on creation *and* on the
    merged state after a PATCH — a rule flipped to ``latency_anomaly`` without
    any of the three, or a PATCH that sets a second one without clearing the
    first, would otherwise be stored happily and either never fire or fire
    off whichever field the handler happens to check first. Raises
    ``ValueError``; both callers turn it into a 4xx.
    """
    if condition is not AlertCondition.latency_anomaly:
        return
    modes_set = sum(
        1 for v in (threshold_value, baseline_factor, anomaly_zscore_threshold) if v is not None
    )
    if modes_set == 0:
        raise ValueError(
            "condition 'latency_anomaly' requires exactly one of threshold_value "
            "(absolute), baseline_factor (relative) or anomaly_zscore_threshold "
            "(statistical) — none is set"
        )
    if modes_set > 1:
        raise ValueError(
            "condition 'latency_anomaly' accepts exactly one sensitivity mode — "
            "set only one of threshold_value, baseline_factor, anomaly_zscore_threshold"
        )


class AlertRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monitor_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    tag_selector: list[str] | None = Field(default=None, max_length=32)
    condition: AlertCondition
    min_duration_seconds: int = Field(default=0, ge=0)
    channel_ids: list[uuid.UUID] = Field(min_length=1)
    threshold_value: float | None = Field(default=None, ge=0)
    digest_minutes: int = Field(default=0, ge=0, le=1440)
    # Storm protection
    storm_window_seconds: int | None = Field(default=None, ge=10, le=3600)
    storm_max_alerts: int | None = Field(default=None, ge=1, le=1000)
    # Plan cap v2, F1-conditions — `availability`'s quorum. See
    # AlertRule.quorum_ratio's docstring for the boundary semantics.
    quorum_ratio: float | None = Field(default=None, gt=0, le=1.0)
    # Baseline
    baseline_factor: float | None = Field(default=None, ge=1.1, le=100.0)
    # Anomaly detection
    anomaly_zscore_threshold: float | None = Field(default=None, ge=1.0, le=10.0)
    # Business hours schedule
    schedule: dict | None = None
    # V2-02-02 — opt-in: skip dispatch when incident.network_verdict is a partition
    suppress_on_network_partition: bool = False
    # B-0 — opt-in escalation ladder. None keeps the channel fan-out (single shot).
    # Plan cap v2 6e: this is also how "renotify me every N minutes" is expressed
    # now — a one-rung, repeating ladder — see services/escalation.py.
    escalation_policy_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def check_latency_fields(self) -> AlertRuleCreate:
        assert_latency_rule_is_fireable(
            self.condition,
            self.threshold_value,
            self.baseline_factor,
            self.anomaly_zscore_threshold,
        )
        return self


class AlertRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    condition: AlertCondition | None = None
    tag_selector: list[str] | None = Field(default=None, max_length=32)
    min_duration_seconds: int | None = Field(default=None, ge=0)
    channel_ids: list[uuid.UUID] | None = Field(default=None, min_length=1)
    threshold_value: float | None = Field(default=None, ge=0)
    digest_minutes: int | None = Field(default=None, ge=0, le=1440)
    storm_window_seconds: int | None = Field(default=None, ge=10, le=3600)
    storm_max_alerts: int | None = Field(default=None, ge=1, le=1000)
    quorum_ratio: float | None = Field(default=None, gt=0, le=1.0)
    baseline_factor: float | None = Field(default=None, ge=1.1, le=100.0)
    anomaly_zscore_threshold: float | None = Field(default=None, ge=1.0, le=10.0)
    schedule: dict | None = None
    suppress_on_network_partition: bool | None = None
    escalation_policy_id: uuid.UUID | None = None


class AlertRuleOut(BaseModel):
    id: uuid.UUID
    monitor_id: uuid.UUID | None
    group_id: uuid.UUID | None
    tag_selector: list[str] | None = None
    condition: AlertCondition
    min_duration_seconds: int
    channels: list[AlertChannelOut]
    threshold_value: float | None
    digest_minutes: int = 0
    storm_window_seconds: int | None = None
    storm_max_alerts: int | None = None
    quorum_ratio: float | None = None
    baseline_factor: float | None = None
    anomaly_zscore_threshold: float | None = None
    schedule: dict | None = None
    enabled: bool = True
    suppress_on_network_partition: bool = False
    escalation_policy_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class AlertMatrixRow(AlertRuleUpdate):
    """One row of the alerting matrix.

    Inherits every mutable rule field (and their bounds) from `AlertRuleUpdate`
    so constraints can never drift between the single-rule and matrix endpoints.
    """

    condition: AlertCondition
    channel_ids: list[uuid.UUID] = Field(default_factory=list)
    enabled: bool = True
    min_duration_seconds: int = Field(default=0, ge=0)
    digest_minutes: int = Field(default=0, ge=0, le=1440)


class AlertMatrixIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[AlertMatrixRow] = Field(default_factory=list)


class AlertMatrixOut(BaseModel):
    monitor_id: uuid.UUID
    rows: list[AlertRuleOut]


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
