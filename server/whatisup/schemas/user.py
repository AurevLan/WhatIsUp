"""User schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


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
