"""MonitorTemplate schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TemplateVariableCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str | None = None
    default: str | None = None


class MonitorTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    variables: list[TemplateVariableCreate] = []
    monitor_config: dict
    is_public: bool = False


class MonitorTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    variables: list[TemplateVariableCreate] | None = None
    monitor_config: dict | None = None
    is_public: bool | None = None


class MonitorTemplateOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    variables: list | None
    monitor_config: dict
    is_public: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TemplateApplyIn(BaseModel):
    """Variable values to substitute when applying a template."""
    values: dict[str, str] = {}
    # Optional override fields (group_id, name suffix, etc.)
    name_override: str | None = None
    group_id: uuid.UUID | None = None
