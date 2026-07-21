"""Pydantic schemas for user API keys."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# Portées reconnues. Volontairement grossières : elles se vérifient sur la
# méthode HTTP, donc sans exception possible sur une route oubliée.
VALID_SCOPES = ("read", "write")


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["WhatIsUp Recorder extension"])
    expires_at: datetime | None = Field(
        default=None, description="Optional expiry date (ISO 8601). Omit for no expiry."
    )
    scopes: list[str] = Field(
        default_factory=lambda: ["read", "write"],
        description=(
            'Key permissions: "read" allows GET only, "write" allows mutations. '
            "Defaults to both, matching keys issued before scopes existed."
        ),
        examples=[["read"]],
    )

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - set(VALID_SCOPES))
        if unknown:
            raise ValueError(f"Unknown scope(s): {', '.join(unknown)}")
        if "read" not in v:
            # Une clé sans lecture ne pourrait rien faire d'utile : mieux vaut
            # le refuser que d'émettre un jeton inerte.
            raise ValueError('Scope "read" is required')
        # Dédoublonne en gardant l'ordre canonique.
        return [s for s in VALID_SCOPES if s in v]


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    is_revoked: bool
    scopes: list[str]

    model_config = {"from_attributes": True}


class ApiKeyCreateResponse(ApiKeyOut):
    """Returned only once at creation — includes the full raw key."""

    key: str = Field(description="Full API key — store it safely, shown only once.")
