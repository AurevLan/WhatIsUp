"""Who is on call right now, and how to reach them (plan V2, B-2).

Two questions, deliberately separate:

1. **Which user** does a schedule designate at instant T — rotation maths plus
   any one-off override.
2. **How do we reach them** — their ``UserContact`` rows, each of which resolves
   to a transport the dispatch layer already knows how to drive.

Rotation maths counts calendar days, not seconds
────────────────────────────────────────────────
The obvious implementation, ``floor((now - start_at) / period)``, is wrong the
moment a timezone observes DST. A weekly rotation handing off at 09:00 Paris
would drift to 08:00 or 10:00 for half the year, and — worse — the shift would
change owner an hour early or late on the transition day, silently paging the
wrong person.

So the shift index is computed from **local calendar dates**: how many whole days
separate today's handoff from the anchor's, divided by the rotation length. A day
that is 23 or 25 hours long still counts as one day, which is exactly what
"hands off every Monday at 09:00" means to the people living it.

Never silently nobody
─────────────────────
Every function here can legitimately return "nobody" — an empty rotation, a
participant with no enabled contact, an override pointing at a departed user.
That is a real answer, and it is always returned *explicitly* so the caller can
be loud about it. An on-call ladder that pages nobody without saying so is the
failure mode this whole chantier exists to remove, and it is the same reasoning
as the CHECK constraint B-0 put on ``escalation_levels``.
"""

from __future__ import annotations

import uuid
import zoneinfo
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.models.oncall import (
    ContactMethod,
    OnCallOverride,
    OnCallSchedule,
    RotationType,
)
from whatisup.models.user import User

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OnCallTarget:
    """One deliverable way to reach one person."""

    user_id: uuid.UUID
    user_email: str
    method: ContactMethod
    value: str
    #: The AlertChannel supplying the bot token / webhook. None for `email` and
    #: `push`, whose transports are autonomous (see ``ContactMethod``).
    via_channel_id: uuid.UUID | None


def _tz(schedule: OnCallSchedule) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(schedule.timezone or "UTC")
    except Exception:  # noqa: BLE001 - a bad zone must not take the rotation down
        logger.warning(
            "oncall_bad_timezone", schedule_id=str(schedule.id), timezone=schedule.timezone
        )
        return zoneinfo.ZoneInfo("UTC")


def _handoff_time(schedule: OnCallSchedule) -> time:
    raw = schedule.handoff_time or "09:00"
    try:
        hour, minute = (int(part) for part in raw.split(":", 1))
        return time(hour=hour, minute=minute)
    except (ValueError, TypeError):
        logger.warning("oncall_bad_handoff_time", schedule_id=str(schedule.id), handoff_time=raw)
        return time(hour=9)


def _period_days(schedule: OnCallSchedule) -> int:
    if schedule.rotation_type is RotationType.daily:
        return 1
    if schedule.rotation_type is RotationType.weekly:
        return 7
    return max(int(schedule.rotation_length_days or 1), 1)


def _shift_day(moment: datetime, tz: zoneinfo.ZoneInfo, handoff: time) -> date:
    """The local date whose handoff opened the shift containing ``moment``.

    Before the handoff hour, the running shift is still the one that opened
    yesterday — which is what makes "hands off at 09:00" mean 09:00 and not
    midnight.
    """
    local = moment.astimezone(tz)
    if local.timetz().replace(tzinfo=None) < handoff:
        return local.date() - timedelta(days=1)
    return local.date()


def shift_index(schedule: OnCallSchedule, moment: datetime) -> int:
    """How many rotations have elapsed since the anchor, in whole local days.

    Negative before the anchor — Python's floor division makes the modulo below
    behave correctly there too, so a schedule queried before it starts still
    designates a coherent participant rather than raising.
    """
    tz = _tz(schedule)
    handoff = _handoff_time(schedule)
    start = schedule.start_at
    if start.tzinfo is None:  # SQLite hands back naive datetimes
        start = start.replace(tzinfo=UTC)

    anchor_day = _shift_day(start, tz, handoff)
    current_day = _shift_day(moment, tz, handoff)
    # Calendar days, so a 23- or 25-hour DST day still counts as one.
    elapsed = (current_day - anchor_day).days
    return elapsed // _period_days(schedule)


async def _override_for(
    db: AsyncSession, schedule_id: uuid.UUID, moment: datetime
) -> OnCallOverride | None:
    """The override covering ``moment``, most recently created first.

    Overrides beat the computed rotation — that is their entire purpose. When
    two overlap, the newest wins: someone fixing a mistake should not have to
    delete the earlier row first, at 3 a.m., to be reachable.
    """
    return (
        await db.execute(
            select(OnCallOverride)
            .where(
                OnCallOverride.schedule_id == schedule_id,
                OnCallOverride.starts_at <= moment,
                OnCallOverride.ends_at > moment,
            )
            .order_by(OnCallOverride.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def resolve_on_call_user(
    db: AsyncSession,
    schedule: OnCallSchedule,
    moment: datetime | None = None,
) -> uuid.UUID | None:
    """Which user this schedule designates at ``moment``, or None.

    None is a real answer — a disabled schedule, or one with no participants —
    and callers are expected to say so out loud rather than page nothing.
    """
    moment = moment or datetime.now(UTC)
    if not schedule.enabled:
        return None

    override = await _override_for(db, schedule.id, moment)
    if override is not None:
        return override.user_id

    participants = sorted(schedule.participants, key=lambda p: p.position)
    if not participants:
        return None
    return participants[shift_index(schedule, moment) % len(participants)].user_id


async def contacts_for_user(db: AsyncSession, user_id: uuid.UUID) -> list[OnCallTarget]:
    """Every enabled way to reach this user.

    An ``email`` contact is synthesised from ``User.email`` when the user has
    declared none: a person on call with no contact row would otherwise be
    unreachable through a ladder that named them explicitly, which is precisely
    the silent gap this module refuses to leave.
    """
    user = (
        await db.execute(
            select(User).where(User.id == user_id).options(selectinload(User.contacts))
        )
    ).scalar_one_or_none()
    if user is None or not user.is_active:
        return []

    targets = [
        OnCallTarget(
            user_id=user.id,
            user_email=user.email,
            method=c.method,
            value=c.value,
            via_channel_id=c.via_channel_id,
        )
        for c in user.contacts
        if c.enabled
    ]
    if not targets and user.email:
        targets.append(
            OnCallTarget(
                user_id=user.id,
                user_email=user.email,
                method=ContactMethod.email,
                value=user.email,
                via_channel_id=None,
            )
        )
    return targets


async def resolve_schedule_targets(
    db: AsyncSession,
    schedule_id: uuid.UUID,
    moment: datetime | None = None,
) -> list[OnCallTarget]:
    """Deliverable targets for whoever is on call on this schedule."""
    schedule = (
        await db.execute(
            select(OnCallSchedule)
            .where(OnCallSchedule.id == schedule_id)
            .options(selectinload(OnCallSchedule.participants))
        )
    ).scalar_one_or_none()
    if schedule is None:
        return []

    user_id = await resolve_on_call_user(db, schedule, moment)
    if user_id is None:
        logger.warning(
            "oncall_schedule_designates_nobody",
            schedule_id=str(schedule_id),
            enabled=schedule.enabled,
            participants=len(schedule.participants),
        )
        return []
    return await contacts_for_user(db, user_id)


async def who_is_on_call(
    db: AsyncSession,
    schedule_ids: list[uuid.UUID],
    moment: datetime | None = None,
) -> dict[uuid.UUID, uuid.UUID | None]:
    """``{schedule_id: user_id or None}`` — for the dashboard widget (B-4)."""
    moment = moment or datetime.now(UTC)
    if not schedule_ids:
        return {}
    schedules = (
        (
            await db.execute(
                select(OnCallSchedule)
                .where(OnCallSchedule.id.in_(schedule_ids))
                .options(selectinload(OnCallSchedule.participants))
            )
        )
        .scalars()
        .all()
    )
    return {s.id: await resolve_on_call_user(db, s, moment) for s in schedules}
