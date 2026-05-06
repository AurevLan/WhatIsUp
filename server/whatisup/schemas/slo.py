"""SLO rule schemas — V2 Global Health Engine."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from whatisup.models.monitor_health import SLORuleType


class SLORuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_type: SLORuleType
    enabled: bool = True
    quorum_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    window_seconds: int | None = Field(default=None, ge=30, le=86400)
    p95_threshold_ms: int | None = Field(default=None, ge=1)
    slo_target: float | None = Field(default=None, gt=0.0, lt=1.0)
    burn_factor: float | None = Field(default=None, gt=0.0)
    min_probes: int = Field(default=1, ge=1)
    cooldown_seconds: int = Field(default=60, ge=0, le=86400)

    @model_validator(mode="after")
    def validate_required_fields(self) -> SLORuleCreate:
        if self.rule_type == SLORuleType.quorum_down:
            if self.quorum_ratio is None or self.window_seconds is None:
                raise ValueError("quorum_down requires quorum_ratio and window_seconds")
        elif self.rule_type == SLORuleType.quorum_slow:
            if self.p95_threshold_ms is None or self.window_seconds is None:
                raise ValueError("quorum_slow requires p95_threshold_ms and window_seconds")
        elif self.rule_type == SLORuleType.burn_rate:
            if self.slo_target is None or self.burn_factor is None:
                raise ValueError("burn_rate requires slo_target and burn_factor")
        return self


class SLORuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    quorum_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    window_seconds: int | None = Field(default=None, ge=30, le=86400)
    p95_threshold_ms: int | None = Field(default=None, ge=1)
    slo_target: float | None = Field(default=None, gt=0.0, lt=1.0)
    burn_factor: float | None = Field(default=None, gt=0.0)
    min_probes: int | None = Field(default=None, ge=1)
    cooldown_seconds: int | None = Field(default=None, ge=0, le=86400)


class SLORuleOut(BaseModel):
    id: uuid.UUID
    monitor_id: uuid.UUID
    rule_type: SLORuleType
    enabled: bool
    quorum_ratio: float | None
    window_seconds: int | None
    p95_threshold_ms: int | None
    slo_target: float | None
    burn_factor: float | None
    min_probes: int
    cooldown_seconds: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
