from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AnnotationCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)
    annotated_at: datetime


class AnnotationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    monitor_id: uuid.UUID
    content: str
    annotated_at: datetime
    created_at: datetime
    created_by: str | None
