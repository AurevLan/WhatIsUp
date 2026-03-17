"""Incident schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from whatisup.models.incident import IncidentScope


class IncidentOut(BaseModel):
    id: uuid.UUID
    monitor_id: uuid.UUID
    started_at: datetime
    resolved_at: datetime | None
    duration_seconds: int | None
    scope: IncidentScope
    affected_probe_ids: list[str]
    dependency_suppressed: bool = False
    group_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class IncidentGroupOut(BaseModel):
    id: uuid.UUID
    triggered_at: datetime
    resolved_at: datetime | None
    cause_probe_ids: list[str]
    status: str
    incident_ids: list[uuid.UUID] = []

    model_config = {"from_attributes": True}
