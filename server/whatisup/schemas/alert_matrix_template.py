"""Pydantic schemas for admin-managed alert matrix templates."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlertMatrixTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    check_type: str = Field(min_length=1, max_length=32)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class AlertMatrixTemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    rows: list[dict[str, Any]] | None = None


class AlertMatrixTemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    check_type: str
    rows: list[dict[str, Any]]
    is_system: bool

    model_config = {"from_attributes": True}
