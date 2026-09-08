"""Maintenance / suppression window schemas (plan cap v2, 6d — merged with the
former ``AlertSilence``; see models/maintenance.py)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MaintenanceWindowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    # Cap v2, 5a — optional text shown to status-page visitors. Never derived
    # from name/description: the operator writes it, or nothing is shown.
    # Meaningless for a pure silence (is_maintenance=False): those never
    # reach the public page regardless of this field.
    public_message: str | None = None
    monitor_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    starts_at: datetime
    ends_at: datetime
    suppress_alerts: bool = True
    # Cap v2, 6d — True (default): planned maintenance, excluded from uptime,
    # requires a monitor or group target. False: a plain alert silence —
    # incident opens and counts normally, only dispatch is muted, and no
    # target at all is legal (means "every monitor I own").
    is_maintenance: bool = True

    @model_validator(mode="after")
    def validate_target_and_dates(self) -> MaintenanceWindowCreate:
        if self.is_maintenance and self.monitor_id is None and self.group_id is None:
            raise ValueError(
                "Either monitor_id or group_id must be specified for a maintenance window"
            )
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class MaintenanceWindowOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    public_message: str | None
    owner_id: uuid.UUID
    monitor_id: uuid.UUID | None
    group_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime
    suppress_alerts: bool
    is_maintenance: bool
    created_at: datetime

    model_config = {"from_attributes": True}
