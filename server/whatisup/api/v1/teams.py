"""Teams API — CRUD teams and manage memberships."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    _ROLE_HIERARCHY,
    _has_min_role,
    get_current_user,
)
from whatisup.core.database import get_db
from whatisup.models.team import Team, TeamMembership, TeamRole
from whatisup.models.user import User
from whatisup.schemas.team import (
    TeamCreate,
    TeamMemberAdd,
    TeamMemberOut,
    TeamMemberUpdate,
    TeamOut,
    TeamUpdate,
)

router = APIRouter(prefix="/teams", tags=["teams"])


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_team_or_404(
    team_id: uuid.UUID, db: AsyncSession
) -> Team:
    team = (
        await db.execute(select(Team).where(Team.id == team_id))
    ).scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def _get_membership_or_403(
    team_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> TeamMembership:
    """Return the caller's membership if they have at least *min_role*."""
    if user.is_superadmin:
        # Superadmin always has implicit owner-level access
        membership = (
            await db.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == team_id,
                    TeamMembership.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            # Create a synthetic object for superadmins not in the team
            class _FakeMembership:
                role = TeamRole.owner
            return _FakeMembership()
        return membership

    membership = (
        await db.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this team")
    if not _has_min_role(membership.role, min_role):
        raise HTTPException(status_code=403, detail=f"Requires at least {min_role} role")
    return membership


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[TeamOut])
async def list_teams(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List teams the current user belongs to (superadmin sees all)."""
    if current_user.is_superadmin:
        query = select(Team)
    else:
        query = (
            select(Team)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(TeamMembership.user_id == current_user.id)
        )
    teams = (await db.execute(query.order_by(Team.name))).scalars().all()

    # Compute member counts
    counts_q = (
        select(TeamMembership.team_id, func.count().label("cnt"))
        .group_by(TeamMembership.team_id)
    )
    counts = {
        r.team_id: r.cnt
        for r in (await db.execute(counts_q)).all()
    }

    return [
        TeamOut(
            id=t.id,
            name=t.name,
            slug=t.slug,
            created_at=t.created_at,
            member_count=counts.get(t.id, 0),
        )
        for t in teams
    ]


@router.post("/", response_model=TeamOut, status_code=201)
async def create_team(
    payload: TeamCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new team. The creator becomes the owner."""
    # Check slug uniqueness
    existing = (
        await db.execute(select(Team).where(Team.slug == payload.slug))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Team slug already taken")

    team = Team(name=payload.name, slug=payload.slug)
    db.add(team)
    await db.flush()

    # Creator becomes owner
    membership = TeamMembership(
        user_id=current_user.id,
        team_id=team.id,
        role=TeamRole.owner,
    )
    db.add(membership)
    await db.refresh(team)

    return TeamOut(
        id=team.id,
        name=team.name,
        slug=team.slug,
        created_at=team.created_at,
        member_count=1,
    )


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    team = await _get_team_or_404(team_id, db)
    await _get_membership_or_403(team_id, current_user, db)
    count = (
        await db.execute(
            select(func.count()).select_from(TeamMembership).where(
                TeamMembership.team_id == team_id
            )
        )
    ).scalar()
    return TeamOut(
        id=team.id,
        name=team.name,
        slug=team.slug,
        created_at=team.created_at,
        member_count=count or 0,
    )


@router.patch("/{team_id}", response_model=TeamOut)
async def update_team(
    team_id: uuid.UUID,
    payload: TeamUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    team = await _get_team_or_404(team_id, db)
    await _get_membership_or_403(team_id, current_user, db, min_role=TeamRole.admin)

    if payload.name is not None:
        team.name = payload.name

    await db.refresh(team)
    count = (
        await db.execute(
            select(func.count()).select_from(TeamMembership).where(
                TeamMembership.team_id == team_id
            )
        )
    ).scalar()
    return TeamOut(
        id=team.id,
        name=team.name,
        slug=team.slug,
        created_at=team.created_at,
        member_count=count or 0,
    )


@router.delete("/{team_id}", status_code=204)
async def delete_team(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    team = await _get_team_or_404(team_id, db)
    await _get_membership_or_403(team_id, current_user, db, min_role=TeamRole.owner)
    await db.delete(team)


# ── Members ──────────────────────────────────────────────────────────────────


@router.get("/{team_id}/members", response_model=list[TeamMemberOut])
async def list_members(
    team_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_team_or_404(team_id, db)
    await _get_membership_or_403(team_id, current_user, db)

    rows = (
        await db.execute(
            select(TeamMembership, User)
            .join(User, TeamMembership.user_id == User.id)
            .where(TeamMembership.team_id == team_id)
            .order_by(User.username)
        )
    ).all()

    return [
        TeamMemberOut(
            user_id=m.user_id,
            email=u.email,
            username=u.username,
            full_name=u.full_name,
            role=m.role.value,
        )
        for m, u in rows
    ]


@router.post("/{team_id}/members", response_model=TeamMemberOut, status_code=201)
async def add_member(
    team_id: uuid.UUID,
    payload: TeamMemberAdd,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_team_or_404(team_id, db)
    await _get_membership_or_403(team_id, current_user, db, min_role=TeamRole.admin)

    # Check user exists
    target_user = (
        await db.execute(select(User).where(User.id == payload.user_id))
    ).scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Check not already a member
    existing = (
        await db.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == payload.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="User is already a team member")

    membership = TeamMembership(
        user_id=payload.user_id,
        team_id=team_id,
        role=TeamRole(payload.role),
    )
    db.add(membership)

    return TeamMemberOut(
        user_id=target_user.id,
        email=target_user.email,
        username=target_user.username,
        full_name=target_user.full_name,
        role=membership.role.value,
    )


@router.patch("/{team_id}/members/{user_id}", response_model=TeamMemberOut)
async def update_member_role(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: TeamMemberUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_team_or_404(team_id, db)
    caller_membership = await _get_membership_or_403(
        team_id, current_user, db, min_role=TeamRole.admin
    )

    target_membership = (
        await db.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if target_membership is None:
        raise HTTPException(status_code=404, detail="Member not found")

    new_role = TeamRole(payload.role)

    # Cannot promote someone above your own role (unless superadmin)
    if not current_user.is_superadmin:
        if _ROLE_HIERARCHY.get(new_role, 0) > _ROLE_HIERARCHY.get(caller_membership.role, 0):
            raise HTTPException(status_code=403, detail="Cannot assign a role higher than your own")

    target_membership.role = new_role

    target_user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()

    return TeamMemberOut(
        user_id=user_id,
        email=target_user.email if target_user else "",
        username=target_user.username if target_user else "",
        full_name=target_user.full_name if target_user else None,
        role=target_membership.role.value,
    )


@router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_team_or_404(team_id, db)
    await _get_membership_or_403(team_id, current_user, db, min_role=TeamRole.admin)

    membership = (
        await db.execute(
            select(TeamMembership).where(
                TeamMembership.team_id == team_id,
                TeamMembership.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")

    # Prevent removing the last owner
    if membership.role == TeamRole.owner:
        owner_count = (
            await db.execute(
                select(func.count()).select_from(TeamMembership).where(
                    TeamMembership.team_id == team_id,
                    TeamMembership.role == TeamRole.owner,
                )
            )
        ).scalar()
        if owner_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot remove the last owner. Transfer ownership first.",
            )

    await db.delete(membership)
