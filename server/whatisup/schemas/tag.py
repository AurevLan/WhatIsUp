"""Tag schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator

from whatisup.models.tag import PermissionLevel


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str | None = None


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str | None = None


class TagOut(BaseModel):
    id: uuid.UUID
    name: str
    color: str | None
    description: str | None

    model_config = {"from_attributes": True}


class UserTagPermissionCreate(BaseModel):
    user_id: uuid.UUID
    tag_id: uuid.UUID
    permission: PermissionLevel


class UserTagPermissionOut(BaseModel):
    user_id: uuid.UUID
    tag_id: uuid.UUID
    permission: PermissionLevel

    model_config = {"from_attributes": True}
