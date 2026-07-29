"""On-call rotations, escalation policies and personal contacts (plan V2, B-0).

Three routers, one scoping rule. Every resource here follows the ``AlertChannel``
model — ``owner_id`` plus an optional ``team_id`` — so reads are filtered by
``owner_id == me OR team_id IN my_teams`` and writes go through
``check_resource_access`` / ``assert_can_assign_team``.

Two cross-tenant hazards are specific to this module and are guarded explicitly:

- **Borrowed carriers.** ``via_channel_id`` / ``target_channel_id`` name an
  ``AlertChannel`` whose config holds a Fernet-encrypted bot token. Accepting an
  arbitrary id would let anyone send messages through someone else's bot.
- **Paging strangers.** Rotations, overrides and ``target_user`` levels all name
  a ``User``. Without a check, any account could put an arbitrary user on an
  on-call ladder and page them at will — an authenticated spam primitive.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import (
    assert_can_assign_team,
    check_resource_access,
    get_current_user,
    get_user_team_ids,
)
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.alert import AlertChannel
from whatisup.models.oncall import (
    EscalationLevel,
    EscalationPolicy,
    EscalationTargetType,
    OnCallOverride,
    OnCallParticipant,
    OnCallSchedule,
    UserContact,
)
from whatisup.models.team import TeamMembership, TeamRole
from whatisup.models.user import User
from whatisup.schemas.oncall import (
    EscalationLevelIn,
    EscalationPolicyCreate,
    EscalationPolicyOut,
    EscalationPolicyUpdate,
    OnCallOverrideCreate,
    OnCallOverrideOut,
    OnCallParticipantIn,
    OnCallScheduleCreate,
    OnCallScheduleOut,
    OnCallScheduleUpdate,
    UserContactCreate,
    UserContactOut,
    UserContactUpdate,
)

contacts_router = APIRouter(prefix="/contacts", tags=["oncall"])
schedules_router = APIRouter(prefix="/oncall/schedules", tags=["oncall"])
policies_router = APIRouter(prefix="/escalation-policies", tags=["oncall"])


# ── Shared guards ─────────────────────────────────────────────────────────────


async def _assert_can_use_channel(
    db: AsyncSession, user: User, channel_id: uuid.UUID | None
) -> None:
    """Reject referencing an alert channel the caller cannot access.

    The channel carries the bot token / webhook used to deliver the message, so
    an unchecked id is a licence to send through another tenant's credentials.
    """
    if channel_id is None:
        return
    channel = (
        await db.execute(select(AlertChannel).where(AlertChannel.id == channel_id))
    ).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    await check_resource_access(channel, user, db)


async def _assert_can_page_users(db: AsyncSession, user: User, user_ids: set[uuid.UUID]) -> None:
    """Reject putting a stranger on a rotation or an escalation ladder.

    A caller may page themselves, or anyone sharing at least one team with them.
    Anything else would turn on-call configuration into an authenticated way to
    spam arbitrary accounts.
    """
    if not user_ids or user.is_superadmin:
        return

    targets = user_ids - {user.id}
    if not targets:
        return

    my_team_ids = await get_user_team_ids(user, db)
    reachable: set[uuid.UUID] = set()
    if my_team_ids:
        rows = (
            (
                await db.execute(
                    select(TeamMembership.user_id).where(
                        TeamMembership.team_id.in_(my_team_ids),
                        TeamMembership.user_id.in_(targets),
                    )
                )
            )
            .scalars()
            .all()
        )
        reachable = set(rows)

    unreachable = targets - reachable
    if unreachable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only add yourself or members of your teams",
        )


def _visibility_filter(user: User, model, team_ids: list[uuid.UUID]):
    """`owner_id == me OR team_id IN my_teams` — the read scope for this module."""
    clauses = [model.owner_id == user.id]
    if team_ids:
        clauses.append(model.team_id.in_(team_ids))
    return or_(*clauses)


# ── UserContact ───────────────────────────────────────────────────────────────


@contacts_router.get("/", response_model=list[UserContactOut])
@limiter.limit("60/minute")
async def list_contacts(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UserContact]:
    """A user's own contact methods. Never another user's — these are personal."""
    rows = (
        (
            await db.execute(
                select(UserContact)
                .where(UserContact.user_id == current_user.id)
                .order_by(UserContact.created_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@contacts_router.post("/", response_model=UserContactOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_contact(
    request: Request,
    payload: UserContactCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserContact:
    await _assert_can_use_channel(db, current_user, payload.via_channel_id)

    contact = UserContact(
        user_id=current_user.id,
        method=payload.method,
        value=payload.value,
        label=payload.label,
        via_channel_id=payload.via_channel_id,
        enabled=payload.enabled,
    )
    db.add(contact)
    await db.flush()
    await db.refresh(contact)
    return contact


@contacts_router.patch("/{contact_id}", response_model=UserContactOut)
@limiter.limit("30/minute")
async def update_contact(
    request: Request,
    contact_id: uuid.UUID,
    payload: UserContactUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserContact:
    contact = await _get_own_contact(contact_id, current_user, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(contact, field, value)
    await db.flush()
    await db.refresh(contact)
    return contact


@contacts_router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_contact(
    request: Request,
    contact_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    contact = await _get_own_contact(contact_id, current_user, db)
    await db.delete(contact)
    await db.flush()


async def _get_own_contact(contact_id: uuid.UUID, user: User, db: AsyncSession) -> UserContact:
    contact = (
        await db.execute(select(UserContact).where(UserContact.id == contact_id))
    ).scalar_one_or_none()
    # 404 rather than 403 on someone else's contact: existence itself is private.
    if contact is None or (contact.user_id != user.id and not user.is_superadmin):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Contact not found")
    return contact


# ── OnCallSchedule ────────────────────────────────────────────────────────────


@schedules_router.get("/", response_model=list[OnCallScheduleOut])
@limiter.limit("60/minute")
async def list_schedules(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OnCallSchedule]:
    team_ids = await get_user_team_ids(current_user, db)
    stmt = select(OnCallSchedule).options(selectinload(OnCallSchedule.participants))
    if not current_user.is_superadmin:
        stmt = stmt.where(_visibility_filter(current_user, OnCallSchedule, team_ids))
    rows = (await db.execute(stmt.order_by(OnCallSchedule.name))).scalars().all()
    return list(rows)


@schedules_router.post("/", response_model=OnCallScheduleOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_schedule(
    request: Request,
    payload: OnCallScheduleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnCallSchedule:
    await assert_can_assign_team(db, current_user, payload.team_id)
    await _assert_can_page_users(db, current_user, {p.user_id for p in payload.participants})

    schedule = OnCallSchedule(
        owner_id=current_user.id,
        team_id=payload.team_id,
        name=payload.name,
        description=payload.description,
        timezone=payload.timezone,
        rotation_type=payload.rotation_type,
        rotation_length_days=payload.rotation_length_days,
        handoff_time=payload.handoff_time,
        start_at=payload.start_at,
        enabled=payload.enabled,
        # Populated through the constructor, not `_replace_participants`: on a
        # pending instance, touching the collection would emit a lazy SELECT
        # from async context and raise MissingGreenlet.
        participants=_build_participants(payload.participants),
    )
    db.add(schedule)
    await db.flush()
    await db.refresh(schedule, ["participants"])
    return schedule


@schedules_router.get("/{schedule_id}", response_model=OnCallScheduleOut)
@limiter.limit("60/minute")
async def get_schedule(
    request: Request,
    schedule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnCallSchedule:
    return await _get_visible_schedule(schedule_id, current_user, db)


@schedules_router.patch("/{schedule_id}", response_model=OnCallScheduleOut)
@limiter.limit("30/minute")
async def update_schedule(
    request: Request,
    schedule_id: uuid.UUID,
    payload: OnCallScheduleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnCallSchedule:
    schedule = await _get_visible_schedule(schedule_id, current_user, db, TeamRole.editor)

    data = payload.model_dump(exclude_unset=True)
    participants = data.pop("participants", None)
    if "team_id" in data:
        await assert_can_assign_team(db, current_user, data["team_id"])
    for field, value in data.items():
        setattr(schedule, field, value)

    if participants is not None:
        parsed = [OnCallParticipantIn(**p) for p in participants]
        await _assert_can_page_users(db, current_user, {p.user_id for p in parsed})
        _replace_participants(schedule, parsed)

    await db.flush()
    await db.refresh(schedule, ["participants"])
    return schedule


@schedules_router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_schedule(
    request: Request,
    schedule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    schedule = await _get_visible_schedule(schedule_id, current_user, db, TeamRole.admin)
    await db.delete(schedule)
    await db.flush()


@schedules_router.get("/{schedule_id}/overrides", response_model=list[OnCallOverrideOut])
@limiter.limit("60/minute")
async def list_overrides(
    request: Request,
    schedule_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[OnCallOverride]:
    await _get_visible_schedule(schedule_id, current_user, db)
    rows = (
        (
            await db.execute(
                select(OnCallOverride)
                .where(OnCallOverride.schedule_id == schedule_id)
                .order_by(OnCallOverride.starts_at)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


@schedules_router.post(
    "/{schedule_id}/overrides",
    response_model=OnCallOverrideOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute")
async def create_override(
    request: Request,
    schedule_id: uuid.UUID,
    payload: OnCallOverrideCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnCallOverride:
    await _get_visible_schedule(schedule_id, current_user, db, TeamRole.editor)
    await _assert_can_page_users(db, current_user, {payload.user_id})

    override = OnCallOverride(
        schedule_id=schedule_id,
        user_id=payload.user_id,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        reason=payload.reason,
    )
    db.add(override)
    await db.flush()
    await db.refresh(override)
    return override


@schedules_router.delete(
    "/{schedule_id}/overrides/{override_id}", status_code=status.HTTP_204_NO_CONTENT
)
@limiter.limit("30/minute")
async def delete_override(
    request: Request,
    schedule_id: uuid.UUID,
    override_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_visible_schedule(schedule_id, current_user, db, TeamRole.editor)
    override = (
        await db.execute(
            select(OnCallOverride).where(
                OnCallOverride.id == override_id,
                # Scoped by schedule_id too: without it, knowing an override id
                # from another tenant's schedule would be enough to delete it.
                OnCallOverride.schedule_id == schedule_id,
            )
        )
    ).scalar_one_or_none()
    if override is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Override not found")
    await db.delete(override)
    await db.flush()


def _build_participants(participants: list[OnCallParticipantIn]) -> list[OnCallParticipant]:
    return [
        OnCallParticipant(user_id=entry.user_id, position=entry.position) for entry in participants
    ]


def _replace_participants(
    schedule: OnCallSchedule, participants: list[OnCallParticipantIn]
) -> None:
    """Only safe on a schedule loaded with ``selectinload(participants)``."""
    schedule.participants.clear()
    schedule.participants.extend(_build_participants(participants))


async def _get_visible_schedule(
    schedule_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> OnCallSchedule:
    schedule = (
        await db.execute(
            select(OnCallSchedule)
            .where(OnCallSchedule.id == schedule_id)
            .options(selectinload(OnCallSchedule.participants))
        )
    ).scalar_one_or_none()
    if schedule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    await check_resource_access(schedule, user, db, min_role=min_role)
    return schedule


# ── EscalationPolicy ──────────────────────────────────────────────────────────


@policies_router.get("/", response_model=list[EscalationPolicyOut])
@limiter.limit("60/minute")
async def list_policies(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EscalationPolicy]:
    team_ids = await get_user_team_ids(current_user, db)
    stmt = select(EscalationPolicy).options(selectinload(EscalationPolicy.levels))
    if not current_user.is_superadmin:
        stmt = stmt.where(_visibility_filter(current_user, EscalationPolicy, team_ids))
    rows = (await db.execute(stmt.order_by(EscalationPolicy.name))).scalars().all()
    return list(rows)


@policies_router.post("/", response_model=EscalationPolicyOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_policy(
    request: Request,
    payload: EscalationPolicyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EscalationPolicy:
    await assert_can_assign_team(db, current_user, payload.team_id)
    await _validate_levels(db, current_user, payload.levels)

    policy = EscalationPolicy(
        owner_id=current_user.id,
        team_id=payload.team_id,
        name=payload.name,
        description=payload.description,
        repeat_count=payload.repeat_count,
        enabled=payload.enabled,
        # Constructor rather than `_replace_levels`, same reason as schedules:
        # touching the collection on a pending instance lazy-loads it.
        levels=_build_levels(payload.levels),
    )
    db.add(policy)
    await db.flush()
    await db.refresh(policy, ["levels"])
    return policy


@policies_router.get("/{policy_id}", response_model=EscalationPolicyOut)
@limiter.limit("60/minute")
async def get_policy(
    request: Request,
    policy_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EscalationPolicy:
    return await _get_visible_policy(policy_id, current_user, db)


@policies_router.patch("/{policy_id}", response_model=EscalationPolicyOut)
@limiter.limit("30/minute")
async def update_policy(
    request: Request,
    policy_id: uuid.UUID,
    payload: EscalationPolicyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EscalationPolicy:
    policy = await _get_visible_policy(policy_id, current_user, db, TeamRole.editor)

    data = payload.model_dump(exclude_unset=True)
    levels = data.pop("levels", None)
    if "team_id" in data:
        await assert_can_assign_team(db, current_user, data["team_id"])
    for field, value in data.items():
        setattr(policy, field, value)

    if levels is not None:
        parsed = [EscalationLevelIn(**level) for level in levels]
        await _validate_levels(db, current_user, parsed)
        _replace_levels(policy, parsed)

    await db.flush()
    await db.refresh(policy, ["levels"])
    return policy


@policies_router.delete("/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_policy(
    request: Request,
    policy_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    policy = await _get_visible_policy(policy_id, current_user, db, TeamRole.admin)
    # Alert rules pointing here fall back to their channel list: the FK is
    # ON DELETE SET NULL, so no rule is destroyed along with the policy.
    await db.delete(policy)
    await db.flush()


async def _validate_levels(db: AsyncSession, user: User, levels: list[EscalationLevelIn]) -> None:
    """Every referenced channel, schedule and user must be one the caller may use."""
    for level in levels:
        await _assert_can_use_channel(db, user, level.target_channel_id)
        if level.target_schedule_id is not None:
            await _get_visible_schedule(level.target_schedule_id, user, db)
    await _assert_can_page_users(
        db,
        user,
        {
            level.target_user_id
            for level in levels
            if level.target_type == EscalationTargetType.user and level.target_user_id
        },
    )


def _build_levels(levels: list[EscalationLevelIn]) -> list[EscalationLevel]:
    return [
        EscalationLevel(
            position=entry.position,
            delay_minutes=entry.delay_minutes,
            target_type=entry.target_type,
            target_channel_id=entry.target_channel_id,
            target_schedule_id=entry.target_schedule_id,
            target_user_id=entry.target_user_id,
        )
        for entry in levels
    ]


def _replace_levels(policy: EscalationPolicy, levels: list[EscalationLevelIn]) -> None:
    """Only safe on a policy loaded with ``selectinload(levels)``."""
    policy.levels.clear()
    policy.levels.extend(_build_levels(levels))


async def _get_visible_policy(
    policy_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> EscalationPolicy:
    policy = (
        await db.execute(
            select(EscalationPolicy)
            .where(EscalationPolicy.id == policy_id)
            .options(selectinload(EscalationPolicy.levels))
        )
    ).scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Policy not found")
    await check_resource_access(policy, user, db, min_role=min_role)
    return policy
