"""User schemas."""

from __future__ import annotations

import uuid
import zoneinfo

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

# Cached once at import — cheap enough, but we only need it for validation.
_VALID_TIMEZONES = frozenset(zoneinfo.available_timezones())


def _validate_timezone(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if v not in _VALID_TIMEZONES:
        raise ValueError(f"Invalid IANA timezone: {v!r}")
    return v


class UserCreate(BaseModel):
    email: EmailStr
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserSelfUpdate(BaseModel):
    """Fields the user may edit on their own account via `PATCH /auth/me`."""

    full_name: str | None = Field(default=None, max_length=255)
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("timezone")
    @classmethod
    def _tz_must_be_iana(cls, v: str | None) -> str | None:
        return _validate_timezone(v)


class AdminUserCreate(BaseModel):
    email: EmailStr
    username: str | None = Field(
        default=None, min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_-]+$"
    )
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    can_create_monitors: bool = False
    is_superadmin: bool = False


class AdminUserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None
    can_create_monitors: bool | None = None
    is_superadmin: bool | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    username: str
    full_name: str | None
    is_active: bool
    is_superadmin: bool
    can_create_monitors: bool
    onboarding_completed: bool = False
    timezone: str | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def compute_onboarding(cls, data):
        if hasattr(data, "onboarding_completed_at"):
            # ORM model
            obj = data
            return {
                "id": obj.id,
                "email": obj.email,
                "username": obj.username,
                "full_name": obj.full_name,
                "is_active": obj.is_active,
                "is_superadmin": obj.is_superadmin,
                "can_create_monitors": obj.can_create_monitors,
                "onboarding_completed": obj.onboarding_completed_at is not None,
                "timezone": obj.timezone,
            }
        return data


class AdminUserOut(UserOut):
    monitor_count: int = 0


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefreshRequest(BaseModel):
    refresh_token: str
