"""On-call rotations, escalation policies and per-user contact methods (plan V2, B-0).

The alert stack before this module was **channel-centred**: an ``AlertRule`` fans
out to a fixed set of ``AlertChannel`` rows, and ``renotify`` re-fires that very
same set forever. Nothing modelled *a person*, so there was no way to express
"page whoever is on call, then page their backup if nobody acknowledges".

Three pieces close that gap:

- ``OnCallSchedule`` answers **who** is on call at an instant T (rotation over an
  ordered participant list, plus ad-hoc ``OnCallOverride`` rows for swaps).
- ``EscalationPolicy`` / ``EscalationLevel`` answer **in what order and how fast**
  targets get paged.
- ``UserContact`` answers **how** to actually reach a person once resolved.

Scoping follows ``AlertChannel`` exactly — ``owner_id`` NOT NULL plus a nullable
``team_id`` — so ``api/deps.assert_can_own`` / ``assert_can_assign_team`` apply
unchanged. A solo operator leaves ``team_id`` NULL and gets a personal rotation.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from whatisup.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from whatisup.models.alert import AlertChannel
    from whatisup.models.incident import Incident
    from whatisup.models.user import User


class ContactMethod(enum.StrEnum):
    """How to reach a person.

    ``email`` and ``push`` are self-sufficient transports: the address lives on
    ``User.email`` / ``device_tokens`` / ``push_subscriptions``. The messaging
    kinds are **not** — delivering a Telegram or Slack message needs the bot
    token or webhook that only exists on an ``AlertChannel``, hence
    ``UserContact.via_channel_id``.
    """

    email = "email"
    push = "push"
    telegram = "telegram"
    slack = "slack"
    discord = "discord"
    mattermost = "mattermost"
    signal = "signal"


class RotationType(enum.StrEnum):
    daily = "daily"
    weekly = "weekly"
    custom_days = "custom_days"


class EscalationTargetType(enum.StrEnum):
    """What a level pages.

    ``channel`` reuses the existing dispatch path untouched. ``schedule`` and
    ``user`` resolve to a person, then to their ``UserContact`` rows.
    """

    channel = "channel"
    schedule = "schedule"
    user = "user"


class UserContact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A way to reach one user outside the UI."""

    __tablename__ = "user_contacts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[ContactMethod] = mapped_column(
        Enum(ContactMethod, name="contact_method"), nullable=False
    )
    # Address / handle / chat id. Not a secret (the bot token it travels with is,
    # and lives Fernet-encrypted on the AlertChannel), so stored in clear.
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Carrier channel for messaging methods — supplies the bot token / webhook.
    # NULL for `email` and `push`, which have autonomous transports.
    via_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("alert_channels.id", ondelete="CASCADE"), nullable=True
    )

    # A contact that is off duty is skipped without being deleted — the operator
    # keeps their holiday phone number on file.
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    user: Mapped[User] = relationship("User", back_populates="contacts")
    via_channel: Mapped[AlertChannel | None] = relationship("AlertChannel")

    # No explicit index on user_id: the column already carries `index=True`, and
    # the unique constraint below leads with it too.
    __table_args__ = (
        UniqueConstraint("user_id", "method", "value", name="uq_user_contact_method_value"),
    )

    def __repr__(self) -> str:
        return f"<UserContact {self.method}:{self.value!r}>"


class OnCallSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A rotation over an ordered list of participants."""

    __tablename__ = "oncall_schedules"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # IANA name. The handoff happens at `handoff_time` *local to this zone*, which
    # is the whole point: a rotation that flips at 09:00 Paris must not drift with
    # DST. Resolution (B-2) converts to UTC at evaluation time.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default="UTC", server_default="UTC"
    )
    rotation_type: Mapped[RotationType] = mapped_column(
        Enum(RotationType, name="rotation_type"),
        nullable=False,
        default=RotationType.weekly,
    )
    # Only meaningful for `custom_days`; kept NOT NULL with a default so the
    # rotation maths never has to special-case a NULL.
    rotation_length_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7, server_default="7"
    )
    handoff_time: Mapped[str] = mapped_column(
        String(5), nullable=False, default="09:00", server_default="09:00"
    )
    # Anchor of the rotation maths: shift index = floor((now - start_at) / period).
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    participants: Mapped[list[OnCallParticipant]] = relationship(
        "OnCallParticipant",
        back_populates="schedule",
        cascade="all, delete-orphan",
        order_by="OnCallParticipant.position",
    )
    overrides: Mapped[list[OnCallOverride]] = relationship(
        "OnCallOverride", back_populates="schedule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("rotation_length_days > 0", name="ck_oncall_rotation_length_positive"),
    )

    def __repr__(self) -> str:
        return f"<OnCallSchedule {self.name!r}>"


class OnCallParticipant(Base):
    """One user's slot in a rotation. ``position`` drives the shift order."""

    __tablename__ = "oncall_participants"

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("oncall_schedules.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    schedule: Mapped[OnCallSchedule] = relationship("OnCallSchedule", back_populates="participants")
    user: Mapped[User] = relationship("User")

    # Lookups are always "participants of schedule X": the composite primary key
    # (schedule_id, user_id) already leads with schedule_id, so a dedicated index
    # would only duplicate it.
    __table_args__ = (
        UniqueConstraint("schedule_id", "position", name="uq_oncall_participant_position"),
    )


class OnCallOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A one-off swap that wins over the computed rotation for a time window."""

    __tablename__ = "oncall_overrides"

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("oncall_schedules.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    schedule: Mapped[OnCallSchedule] = relationship("OnCallSchedule", back_populates="overrides")
    user: Mapped[User] = relationship("User")

    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_oncall_override_window"),
        # B-2 resolution always asks "which override covers now?" for one schedule.
        Index("ix_oncall_overrides_lookup", "schedule_id", "starts_at", "ends_at"),
    )


class EscalationPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An ordered ladder of targets with a delay between rungs."""

    __tablename__ = "escalation_policies"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # How many extra times to replay the whole ladder once the last level fired
    # without an ack. 0 = stop at the top rung and let renotify take over.
    repeat_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, server_default="true"
    )

    levels: Mapped[list[EscalationLevel]] = relationship(
        "EscalationLevel",
        back_populates="policy",
        cascade="all, delete-orphan",
        order_by="EscalationLevel.position",
    )

    __table_args__ = (
        CheckConstraint("repeat_count >= 0", name="ck_escalation_repeat_non_negative"),
    )

    def __repr__(self) -> str:
        return f"<EscalationPolicy {self.name!r}>"


class EscalationLevel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One rung: wait ``delay_minutes``, then page exactly one target."""

    __tablename__ = "escalation_levels"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("escalation_policies.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Delay counted from the *previous* level firing (from the incident alert for
    # position 0), not from the incident start — so inserting a rung in the middle
    # does not silently shift every rung above it.
    delay_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    target_type: Mapped[EscalationTargetType] = mapped_column(
        Enum(EscalationTargetType, name="escalation_target_type"), nullable=False
    )
    target_channel_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("alert_channels.id", ondelete="CASCADE"), nullable=True
    )
    target_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("oncall_schedules.id", ondelete="CASCADE"), nullable=True
    )
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )

    policy: Mapped[EscalationPolicy] = relationship("EscalationPolicy", back_populates="levels")

    __table_args__ = (
        UniqueConstraint("policy_id", "position", name="uq_escalation_level_position"),
        CheckConstraint("delay_minutes >= 0", name="ck_escalation_delay_non_negative"),
        # The discriminator and the FK columns must agree. Enforced in the database
        # rather than only in Pydantic: a level whose target_type says `schedule`
        # while only target_channel_id is set would page nobody, silently — the
        # worst possible failure mode for an on-call ladder.
        CheckConstraint(
            "(target_type = 'channel' AND target_channel_id IS NOT NULL "
            " AND target_schedule_id IS NULL AND target_user_id IS NULL) OR "
            "(target_type = 'schedule' AND target_schedule_id IS NOT NULL "
            " AND target_channel_id IS NULL AND target_user_id IS NULL) OR "
            "(target_type = 'user' AND target_user_id IS NOT NULL "
            " AND target_channel_id IS NULL AND target_schedule_id IS NULL)",
            name="ck_escalation_level_single_target",
        ),
        # uq_escalation_level_position already leads with policy_id — no separate
        # index needed to fetch a policy's ladder.
    )

    def __repr__(self) -> str:
        return f"<EscalationLevel {self.position} → {self.target_type}>"


class EscalationState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Where one incident stands on its ladder (plan V2, B-1).

    One row per incident, created when ``fire_alerts`` hands the incident to a
    policy and deleted when the incident stops needing one. Persisted rather
    than held in memory for the same reason the digest windows are: a server
    restart in the middle of a night-time escalation must not leave an incident
    stuck between two rungs, silently un-escalated.

    ``next_fire_at`` is the whole scheduler. The background loop asks for rows
    whose turn has come rather than re-deriving every incident's position, so
    the cost of the loop tracks the number of *escalating* incidents, not the
    number of open ones.
    """

    __tablename__ = "escalation_states"

    # One ladder per incident. Unique rather than merely indexed: two states for
    # the same incident would page twice and advance independently.
    incident_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # CASCADE, unlike ``AlertRule.escalation_policy_id`` which is SET NULL:
    # a rule outliving its policy degrades to its channels, but an in-flight
    # ladder whose policy just vanished has nothing left to walk.
    policy_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("escalation_policies.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: The rule that armed this ladder. Needed to fall back to its channels when
    #: the ladder turns out to reach nobody.
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True
    )

    #: Position of the level to fire next. Equal to the ladder length means the
    #: ladder is exhausted for this pass.
    next_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: How many full passes have already been replayed (``repeat_count``).
    repeats_done: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    #: When the next rung is due. Indexed — it is the loop's only filter.
    next_fire_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    incident: Mapped[Incident] = relationship("Incident")
    policy: Mapped[EscalationPolicy] = relationship("EscalationPolicy")

    __table_args__ = (
        CheckConstraint("next_position >= 0", name="ck_escalation_state_position"),
        CheckConstraint("repeats_done >= 0", name="ck_escalation_state_repeats"),
    )

    def __repr__(self) -> str:
        return f"<EscalationState incident={self.incident_id} pos={self.next_position}>"
