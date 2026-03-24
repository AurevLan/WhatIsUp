"""Schemas for Web Push subscriptions."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, HttpUrl


class WebPushSubscribeIn(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    user_agent: str | None = None


class WebPushSubscriptionOut(BaseModel):
    id: uuid.UUID
    endpoint: str
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WebPushPublicKeyOut(BaseModel):
    public_key: str
    enabled: bool
