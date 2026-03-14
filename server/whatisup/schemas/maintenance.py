"""Maintenance window schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class MaintenanceWindowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    monitor_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    starts_at: datetime
    ends_at: datetime
    suppress_alerts: bool = True

    @model_validator(mode="after")
    def validate_target_and_dates(self) -> MaintenanceWindowCreate:
        if self.monitor_id is None and self.group_id is None:
            raise ValueError("Either monitor_id or group_id must be specified")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class MaintenanceWindowOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    monitor_id: uuid.UUID | None
    group_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime
    suppress_alerts: bool
    created_at: datetime

    model_config = {"from_attributes": True}
