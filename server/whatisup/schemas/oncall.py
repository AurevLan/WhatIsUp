"""Pydantic schemas for on-call rotations, escalation policies and contacts (B-0)."""

from __future__ import annotations

import re
import uuid
import zoneinfo
from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from whatisup.models.oncall import ContactMethod, EscalationTargetType, RotationType

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# Methods whose transport is autonomous (User.email, device_tokens,
# push_subscriptions). Everything else needs a carrier AlertChannel for its bot
# token or webhook — see UserContact.via_channel_id.
_SELF_CARRIED_METHODS = {ContactMethod.email, ContactMethod.push}


# ── UserContact ───────────────────────────────────────────────────────────────


class UserContactCreate(BaseModel):
    method: ContactMethod
    value: str = Field(min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=120)
    via_channel_id: uuid.UUID | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _check_carrier(self) -> UserContactCreate:
        if self.method in _SELF_CARRIED_METHODS:
            if self.via_channel_id is not None:
                raise ValueError(f"via_channel_id must be omitted for method '{self.method}'")
        elif self.via_channel_id is None:
            raise ValueError(
                f"method '{self.method}' needs via_channel_id: the bot token or webhook "
                "used to deliver the message lives on an alert channel"
            )
        return self


class UserContactUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=500)
    label: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None


class UserContactOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    method: ContactMethod
    value: str
    label: str | None
    via_channel_id: uuid.UUID | None
    enabled: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── OnCallSchedule ────────────────────────────────────────────────────────────


class OnCallParticipantIn(BaseModel):
    user_id: uuid.UUID
    position: int = Field(ge=0)


class OnCallParticipantOut(BaseModel):
    # user_id only: resolving usernames here would mean eager-loading
    # OnCallParticipant.user on every path, and the UI already holds a user list
    # to render the picker.
    user_id: uuid.UUID
    position: int

    model_config = {"from_attributes": True}


class _ScheduleFields(BaseModel):
    timezone: str = "UTC"
    rotation_type: RotationType = RotationType.weekly
    rotation_length_days: int = Field(default=7, ge=1, le=365)
    handoff_time: str = "09:00"

    @model_validator(mode="after")
    def _check_tz_and_time(self) -> _ScheduleFields:
        try:
            zoneinfo.ZoneInfo(self.timezone)
        except Exception as exc:
            raise ValueError(f"unknown timezone '{self.timezone}'") from exc
        if not _HHMM.match(self.handoff_time):
            raise ValueError("handoff_time must be HH:MM (24h)")
        return self


class OnCallScheduleCreate(_ScheduleFields):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    team_id: uuid.UUID | None = None
    start_at: datetime
    enabled: bool = True
    participants: list[OnCallParticipantIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_participants(self) -> OnCallScheduleCreate:
        _assert_participants_consistent(self.participants)
        return self


class OnCallScheduleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    team_id: uuid.UUID | None = None
    timezone: str | None = None
    rotation_type: RotationType | None = None
    rotation_length_days: int | None = Field(default=None, ge=1, le=365)
    handoff_time: str | None = None
    start_at: datetime | None = None
    enabled: bool | None = None
    # None = leave untouched; [] = explicitly clear the roster.
    participants: list[OnCallParticipantIn] | None = None

    @model_validator(mode="after")
    def _check(self) -> OnCallScheduleUpdate:
        if self.timezone is not None:
            try:
                zoneinfo.ZoneInfo(self.timezone)
            except Exception as exc:
                raise ValueError(f"unknown timezone '{self.timezone}'") from exc
        if self.handoff_time is not None and not _HHMM.match(self.handoff_time):
            raise ValueError("handoff_time must be HH:MM (24h)")
        if self.participants is not None:
            _assert_participants_consistent(self.participants)
        return self


class OnCallScheduleOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    team_id: uuid.UUID | None
    name: str
    description: str | None
    timezone: str
    rotation_type: RotationType
    rotation_length_days: int
    handoff_time: str
    start_at: datetime
    enabled: bool
    participants: list[OnCallParticipantOut] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}


class OnCallOverrideCreate(BaseModel):
    user_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    reason: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _check_window(self) -> OnCallOverrideCreate:
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class OnCallOverrideOut(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID
    user_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    reason: str | None

    model_config = {"from_attributes": True}


# ── EscalationPolicy ──────────────────────────────────────────────────────────


class EscalationLevelIn(BaseModel):
    position: int = Field(ge=0)
    delay_minutes: int = Field(default=0, ge=0, le=10080)  # ≤ 7 days
    target_type: EscalationTargetType
    target_channel_id: uuid.UUID | None = None
    target_schedule_id: uuid.UUID | None = None
    target_user_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_single_target(self) -> EscalationLevelIn:
        expected = {
            EscalationTargetType.channel: "target_channel_id",
            EscalationTargetType.schedule: "target_schedule_id",
            EscalationTargetType.user: "target_user_id",
        }[self.target_type]
        provided = {
            field
            for field in ("target_channel_id", "target_schedule_id", "target_user_id")
            if getattr(self, field) is not None
        }
        if provided != {expected}:
            raise ValueError(
                f"target_type '{self.target_type}' requires exactly {expected} to be set"
            )
        return self


class EscalationLevelOut(BaseModel):
    id: uuid.UUID
    position: int
    delay_minutes: int
    target_type: EscalationTargetType
    target_channel_id: uuid.UUID | None
    target_schedule_id: uuid.UUID | None
    target_user_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class EscalationPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    team_id: uuid.UUID | None = None
    repeat_count: int = Field(default=0, ge=0, le=10)
    enabled: bool = True
    levels: list[EscalationLevelIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_levels(self) -> EscalationPolicyCreate:
        _assert_levels_consistent(self.levels)
        return self


class EscalationPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    team_id: uuid.UUID | None = None
    repeat_count: int | None = Field(default=None, ge=0, le=10)
    enabled: bool | None = None
    # None = leave untouched; [] = explicitly clear the ladder.
    levels: list[EscalationLevelIn] | None = None

    @model_validator(mode="after")
    def _check_levels(self) -> EscalationPolicyUpdate:
        if self.levels is not None:
            _assert_levels_consistent(self.levels)
        return self


class EscalationPolicyOut(BaseModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    team_id: uuid.UUID | None
    name: str
    description: str | None
    repeat_count: int
    enabled: bool
    levels: list[EscalationLevelOut] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Shared validation ─────────────────────────────────────────────────────────


def _assert_participants_consistent(participants: list[OnCallParticipantIn]) -> None:
    positions = [p.position for p in participants]
    if len(set(positions)) != len(positions):
        raise ValueError("participant positions must be unique")
    user_ids = [p.user_id for p in participants]
    if len(set(user_ids)) != len(user_ids):
        raise ValueError("a user may appear only once in a rotation")


def _assert_levels_consistent(levels: list[EscalationLevelIn]) -> None:
    positions = [level.position for level in levels]
    if len(set(positions)) != len(positions):
        raise ValueError("escalation level positions must be unique")
    # Gaps are rejected rather than silently tolerated: a ladder jumping 0 → 2
    # reads as "there is a level 1" to whoever wrote it, and the engine would
    # skip a rung nobody meant to skip.
    if positions and sorted(positions) != list(range(len(positions))):
        raise ValueError("escalation level positions must be contiguous starting at 0")
