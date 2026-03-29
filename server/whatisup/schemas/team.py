"""Team and TeamMembership schemas."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=200, pattern=r"^[a-z0-9][a-z0-9-]*$")

    model_config = {"extra": "forbid"}

    def model_post_init(self, __context):
        """Auto-generate slug from name if not provided."""
        if not self.slug:
            generated = re.sub(r"[^a-z0-9]+", "-", self.name.lower()).strip("-")[:200]
            object.__setattr__(self, "slug", generated or "team")


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)

    model_config = {"extra": "forbid"}


class TeamMemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = Field(default="editor", pattern=r"^(owner|admin|editor|viewer)$")

    model_config = {"extra": "forbid"}


class TeamMemberUpdate(BaseModel):
    role: str = Field(pattern=r"^(owner|admin|editor|viewer)$")

    model_config = {"extra": "forbid"}


class TeamMemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    username: str
    full_name: str | None = None
    role: str

    model_config = {"from_attributes": True}


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime
    member_count: int = 0

    model_config = {"from_attributes": True}
