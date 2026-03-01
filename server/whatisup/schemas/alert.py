"""Alert schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from whatisup.models.alert import AlertChannelType, AlertCondition, AlertEventStatus


class AlertChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: AlertChannelType
    config: dict

    @field_validator("config")
    @classmethod
    def validate_config(cls, v: dict, info) -> dict:
        channel_type = info.data.get("type")
        if channel_type == AlertChannelType.email:
            if "to" not in v or not isinstance(v["to"], list) or not v["to"]:
                raise ValueError("Email channel requires 'to' list of addresses")
        elif channel_type == AlertChannelType.webhook:
            if "url" not in v:
                raise ValueError("Webhook channel requires 'url'")
        elif channel_type == AlertChannelType.telegram:
            if "bot_token" not in v or "chat_id" not in v:
                raise ValueError("Telegram channel requires 'bot_token' and 'chat_id'")
        return v


class AlertChannelOut(BaseModel):
    id: uuid.UUID
    name: str
    type: AlertChannelType
    # config is intentionally excluded from output (contains secrets)

    model_config = {"from_attributes": True}


class AlertRuleCreate(BaseModel):
    monitor_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    condition: AlertCondition
    min_duration_seconds: int = Field(default=0, ge=0)
    channel_ids: list[uuid.UUID] = Field(min_length=1)


class AlertRuleOut(BaseModel):
    id: uuid.UUID
    monitor_id: uuid.UUID | None
    group_id: uuid.UUID | None
    condition: AlertCondition
    min_duration_seconds: int
    channels: list[AlertChannelOut]

    model_config = {"from_attributes": True}


class AlertEventOut(BaseModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    channel_id: uuid.UUID
    sent_at: datetime
    status: AlertEventStatus
    response_body: str | None

    model_config = {"from_attributes": True}
