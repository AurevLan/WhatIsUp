"""AuditLog schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: uuid.UUID
    timestamp: datetime
    user_id: uuid.UUID | None
    user_email: str | None
    action: str
    object_type: str
    object_id: uuid.UUID | None
    object_name: str | None
    diff: dict | None
    ip_address: str | None

    model_config = {"from_attributes": True}
