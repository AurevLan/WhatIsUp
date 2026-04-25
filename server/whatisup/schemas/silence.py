"""Pydantic schemas for AlertSilence (T1-01)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class AlertSilenceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)
    monitor_id: uuid.UUID | None = None  # None → all monitors of the owner
    starts_at: datetime
    ends_at: datetime

    @model_validator(mode="after")
    def _check_window(self) -> "AlertSilenceCreate":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AlertSilenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=500)
    monitor_id: uuid.UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def _check_window(self) -> "AlertSilenceUpdate":
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AlertSilenceOut(BaseModel):
    id: uuid.UUID
    name: str
    reason: str | None
    owner_id: uuid.UUID
    monitor_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
