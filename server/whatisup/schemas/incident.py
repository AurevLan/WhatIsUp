"""Incident schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from whatisup.models.incident import IncidentScope
from whatisup.models.incident_update import IncidentUpdateStatus


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
    acked_at: datetime | None = None
    acked_by_id: uuid.UUID | None = None
    first_failure_at: datetime | None = None
    mttd_seconds: int | None = None
    mttr_seconds: int | None = None

    model_config = {"from_attributes": True}


class IncidentUpdateCreate(BaseModel):
    status: IncidentUpdateStatus
    message: str = Field(min_length=1, max_length=4000)
    is_public: bool = True


class IncidentUpdateOut(BaseModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    created_by_id: uuid.UUID | None
    created_by_name: str | None
    status: IncidentUpdateStatus
    message: str
    is_public: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class IncidentRef(BaseModel):
    id: uuid.UUID
    monitor_id: uuid.UUID

    model_config = {"from_attributes": True}


class IncidentGroupOut(BaseModel):
    id: uuid.UUID
    triggered_at: datetime
    resolved_at: datetime | None
    cause_probe_ids: list[str]
    status: str
    root_cause_monitor_id: uuid.UUID | None = None
    root_cause_monitor_name: str | None = None
    correlation_type: str | None = None
    incident_ids: list[uuid.UUID] = []
    incident_refs: list[IncidentRef] = []

    model_config = {"from_attributes": True}
