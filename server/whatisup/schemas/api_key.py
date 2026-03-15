"""Pydantic schemas for user API keys."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["WhatIsUp Recorder extension"])
    expires_at: datetime | None = Field(
        default=None, description="Optional expiry date (ISO 8601). Omit for no expiry."
    )


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    is_revoked: bool

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyOut):
    """Returned only once at creation — includes the full raw key."""

    key: str = Field(description="Full API key — store it safely, shown only once.")
