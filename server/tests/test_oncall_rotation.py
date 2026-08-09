"""On-call rotation resolution (plan V2, B-2).

The rotation maths is the part that is easy to get subtly wrong and hard to
notice: a schedule that hands off an hour early for half the year pages the
wrong person once, at 3 a.m., and nobody reads the code afterwards. So the DST
behaviour is pinned explicitly rather than left to `timedelta` arithmetic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.oncall import (
    ContactMethod,
    OnCallOverride,
    OnCallParticipant,
    OnCallSchedule,
    RotationType,
    UserContact,
)
from whatisup.models.user import User
from whatisup.services.oncall import (
    contacts_for_user,
    resolve_on_call_user,
    resolve_schedule_targets,
    shift_index,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def people(service_db: AsyncSession) -> list[User]:
    users = [
        User(email=f"oncall{i}@example.com", username=f"oncall{i}", hashed_password="x")
        for i in range(3)
    ]
    service_db.add_all(users)
    await service_db.flush()
    return users


async def _schedule(
    db: AsyncSession,
    owner: User,
    members: list[User],
    *,
    tz: str = "UTC",
    rotation: RotationType = RotationType.daily,
    length: int = 1,
    handoff: str = "09:00",
    start: datetime | None = None,
    enabled: bool = True,
) -> OnCallSchedule:
    schedule = OnCallSchedule(
        owner_id=owner.id,
        name="rota",
        timezone=tz,
        rotation_type=rotation,
        rotation_length_days=length,
        handoff_time=handoff,
        start_at=start or datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
        enabled=enabled,
    )
    db.add(schedule)
    await db.flush()
    for i, member in enumerate(members):
        db.add(OnCallParticipant(schedule_id=schedule.id, user_id=member.id, position=i))
    await db.flush()
    await db.refresh(schedule, ["participants"])
    return schedule


# ── Rotation maths ────────────────────────────────────────────────────────────


async def test_daily_rotation_advances_one_participant_per_day(
    service_db: AsyncSession, test_user: User, people: list[User]
):
    schedule = await _schedule(service_db, test_user, people)
    anchor = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)

    for day, expected in enumerate([people[0], people[1], people[2], people[0]]):
        moment = anchor + timedelta(days=day, hours=1)
        assert await resolve_on_call_user(service_db, schedule, moment) == expected.id


async def test_the_shift_turns_at_the_handoff_hour_not_at_midnight(
    service_db: AsyncSession, test_user: User, people: list[User]
):
    schedule = await _schedule(service_db, test_user, people, handoff="09:00")
    # 08:59 still belongs to the shift that opened the previous morning.
    before = datetime(2026, 1, 6, 8, 59, tzinfo=UTC)
    after = datetime(2026, 1, 6, 9, 1, tzinfo=UTC)
    assert await resolve_on_call_user(service_db, schedule, before) == people[0].id
    assert await resolve_on_call_user(service_db, schedule, after) == people[1].id


async def test_weekly_rotation_holds_for_seven_days(
    service_db: AsyncSession, test_user: User, people: list[User]
):
    schedule = await _schedule(service_db, test_user, people, rotation=RotationType.weekly)
    anchor = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    for day in range(7):
        assert await resolve_on_call_user(service_db, schedule, anchor + timedelta(days=day)) == (
            people[0].id
        )
    assert await resolve_on_call_user(service_db, schedule, anchor + timedelta(days=7)) == (
        people[1].id
    )


async def test_custom_length_is_honoured(
    service_db: AsyncSession, test_user: User, people: list[User]
):
    schedule = await _schedule(
        service_db, test_user, people, rotation=RotationType.custom_days, length=3
    )
    anchor = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    assert await resolve_on_call_user(service_db, schedule, anchor + timedelta(days=2)) == (
        people[0].id
    )
    assert await resolve_on_call_user(service_db, schedule, anchor + timedelta(days=3)) == (
        people[1].id
    )


async def test_handoff_does_not_drift_across_a_dst_transition(
    service_db: AsyncSession, test_user: User, people: list[User]
):
    """The whole reason the maths counts calendar days rather than seconds.

    Europe/Paris springs forward on 2026-03-29. A weekly rotation anchored
    before it must still hand off at 09:00 *local* after it — with second-based
    arithmetic the boundary slides by an hour and the shift changes owner on the
    wrong side of the morning.
    """
    schedule = await _schedule(
        service_db,
        test_user,
        people,
        tz="Europe/Paris",
        rotation=RotationType.weekly,
        handoff="09:00",
        # A Monday well before the transition.
        start=datetime(2026, 3, 2, 8, 0, tzinfo=UTC),  # 09:00 Paris (CET, +1)
    )

    # 08:59 Paris on a handoff day, after the clocks moved (CEST, +2).
    before = datetime(2026, 4, 6, 6, 59, tzinfo=UTC)
    after = datetime(2026, 4, 6, 7, 1, tzinfo=UTC)
    assert shift_index(schedule, before) == 4
    assert shift_index(schedule, after) == 5


async def test_an_empty_or_disabled_rotation_designates_nobody(
    service_db: AsyncSession, test_user: User, people: list[User]
):
    """A real answer, returned explicitly so the caller can be loud about it."""
    empty = await _schedule(service_db, test_user, [])
    assert await resolve_on_call_user(service_db, empty, datetime.now(UTC)) is None

    disabled = await _schedule(service_db, test_user, people, enabled=False)
    assert await resolve_on_call_user(service_db, disabled, datetime.now(UTC)) is None


# ── Overrides ─────────────────────────────────────────────────────────────────


async def test_an_override_beats_the_computed_rotation(
    service_db: AsyncSession, test_user: User, people: list[User]
):
    schedule = await _schedule(service_db, test_user, people)
    moment = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    assert await resolve_on_call_user(service_db, schedule, moment) == people[0].id

    service_db.add(
        OnCallOverride(
            schedule_id=schedule.id,
            user_id=people[2].id,
            starts_at=moment - timedelta(hours=1),
            ends_at=moment + timedelta(hours=1),
        )
    )
    await service_db.flush()
    assert await resolve_on_call_user(service_db, schedule, moment) == people[2].id

    # Outside its window the rotation takes over again.
    assert (
        await resolve_on_call_user(service_db, schedule, moment + timedelta(hours=2))
        == people[0].id
    )


async def test_the_newest_override_wins_when_two_overlap(
    service_db: AsyncSession, test_user: User, people: list[User]
):
    """Fixing a mistake must not require deleting the earlier row first."""
    schedule = await _schedule(service_db, test_user, people)
    moment = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
    window = {"starts_at": moment - timedelta(hours=1), "ends_at": moment + timedelta(hours=1)}

    service_db.add(OnCallOverride(schedule_id=schedule.id, user_id=people[1].id, **window))
    await service_db.flush()
    service_db.add(OnCallOverride(schedule_id=schedule.id, user_id=people[2].id, **window))
    await service_db.flush()

    assert await resolve_on_call_user(service_db, schedule, moment) == people[2].id


# ── Reaching the person ───────────────────────────────────────────────────────


async def test_contacts_fall_back_to_the_account_email(
    service_db: AsyncSession, people: list[User]
):
    """Someone named on a ladder must never be unreachable for lack of a row."""
    targets = await contacts_for_user(service_db, people[0].id)
    assert [t.method for t in targets] == [ContactMethod.email]
    assert targets[0].value == people[0].email


async def test_declared_contacts_replace_the_fallback(service_db: AsyncSession, people: list[User]):
    service_db.add(UserContact(user_id=people[0].id, method=ContactMethod.telegram, value="12345"))
    await service_db.flush()
    targets = await contacts_for_user(service_db, people[0].id)
    assert [t.method for t in targets] == [ContactMethod.telegram]


async def test_disabled_contacts_are_skipped(service_db: AsyncSession, people: list[User]):
    """The holiday phone stays on file without being paged."""
    service_db.add(
        UserContact(
            user_id=people[0].id, method=ContactMethod.telegram, value="12345", enabled=False
        )
    )
    await service_db.flush()
    targets = await contacts_for_user(service_db, people[0].id)
    # Falls back to email rather than returning nothing.
    assert [t.method for t in targets] == [ContactMethod.email]


async def test_a_deactivated_user_is_not_paged(service_db: AsyncSession, people: list[User]):
    people[0].is_active = False
    await service_db.flush()
    assert await contacts_for_user(service_db, people[0].id) == []


async def test_resolving_a_missing_schedule_is_not_an_error(service_db: AsyncSession):
    assert await resolve_schedule_targets(service_db, uuid.uuid4()) == []
