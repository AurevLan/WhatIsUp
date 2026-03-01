"""Monitor and MonitorGroup schemas."""

from __future__ import annotations

import uuid

from pydantic import AnyHttpUrl, BaseModel, Field, field_validator

from whatisup.schemas.tag import TagOut


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: AnyHttpUrl
    group_id: uuid.UUID | None = None
    interval_seconds: int = Field(default=60, ge=5, le=86400)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    follow_redirects: bool = True
    expected_status_codes: list[int] = Field(default=[200], min_length=1)
    enabled: bool = True
    ssl_check_enabled: bool = True
    ssl_expiry_warn_days: int = Field(default=30, ge=1, le=365)
    tag_ids: list[uuid.UUID] = Field(default=[])

    @field_validator("expected_status_codes")
    @classmethod
    def valid_status_codes(cls, v: list[int]) -> list[int]:
        for code in v:
            if not (100 <= code <= 599):
                raise ValueError(f"Invalid HTTP status code: {code}")
        return v

    @field_validator("url", mode="before")
    @classmethod
    def url_to_string(cls, v):
        return str(v) if not isinstance(v, str) else v


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: AnyHttpUrl | None = None
    group_id: uuid.UUID | None = None
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    timeout_seconds: int | None = Field(default=None, ge=1, le=60)
    follow_redirects: bool | None = None
    expected_status_codes: list[int] | None = None
    enabled: bool | None = None
    ssl_check_enabled: bool | None = None
    ssl_expiry_warn_days: int | None = Field(default=None, ge=1, le=365)
    tag_ids: list[uuid.UUID] | None = None


class MonitorOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    group_id: uuid.UUID | None
    owner_id: uuid.UUID
    interval_seconds: int
    timeout_seconds: int
    follow_redirects: bool
    expected_status_codes: list[int]
    enabled: bool
    ssl_check_enabled: bool
    ssl_expiry_warn_days: int
    tags: list[TagOut]
    # Runtime fields — populated by list_monitors, not stored in the DB row
    last_status: str | None = None
    uptime_24h: float | None = None

    model_config = {"from_attributes": True}


class MonitorGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    public_slug: str | None = Field(
        default=None, min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$"
    )
    tag_ids: list[uuid.UUID] = Field(default=[])


class MonitorGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    public_slug: str | None = Field(
        default=None, min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$"
    )
    tag_ids: list[uuid.UUID] | None = None


class MonitorGroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    public_slug: str | None
    owner_id: uuid.UUID
    tags: list[TagOut]

    model_config = {"from_attributes": True}


class PublicPageCreate(BaseModel):
    slug: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=255)
    group_id: uuid.UUID | None = None
    custom_domain: str | None = Field(default=None, max_length=255)


class PublicPageOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    group_id: uuid.UUID | None
    custom_domain: str | None

    model_config = {"from_attributes": True}
