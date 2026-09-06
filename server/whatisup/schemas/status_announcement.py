"""Status page announcement schemas (plan cap V2, 5b)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from whatisup.models.incident_update import IncidentUpdateStatus


class StatusAnnouncementUpdateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: IncidentUpdateStatus
    message: str = Field(min_length=1, max_length=4000)
    is_public: bool = True


class StatusAnnouncementUpdateOut(BaseModel):
    id: uuid.UUID
    announcement_id: uuid.UUID
    created_by_id: uuid.UUID | None
    created_by_name: str | None
    status: IncidentUpdateStatus
    message: str
    is_public: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class StatusAnnouncementTitleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)


class StatusAnnouncementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    status: IncidentUpdateStatus = IncidentUpdateStatus.investigating
    # Initial post — becomes the first entry of the update thread.
    message: str = Field(min_length=1, max_length=4000)


class StatusAnnouncementOut(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    title: str
    status: IncidentUpdateStatus
    started_at: datetime
    ended_at: datetime | None
    created_at: datetime
    updates: list[StatusAnnouncementUpdateOut] = []

    model_config = {"from_attributes": True}
