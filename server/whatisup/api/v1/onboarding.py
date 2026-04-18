"""Onboarding endpoints — track first-time user setup progress."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.models.alert import AlertChannel
from whatisup.models.monitor import Monitor
from whatisup.models.team import TeamMembership
from whatisup.models.user import User

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class OnboardingStatus(BaseModel):
    completed: bool
    completed_at: str | None = None
    has_monitors: bool
    has_alert_channels: bool
    has_team: bool
    monitor_count: int
    channel_count: int


@router.get("/status", response_model=OnboardingStatus)
async def get_onboarding_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return onboarding progress for the current user."""
    monitor_count = (
        await db.execute(
            select(func.count()).select_from(Monitor).where(
                Monitor.owner_id == current_user.id
            )
        )
    ).scalar() or 0

    channel_count = (
        await db.execute(
            select(func.count()).select_from(AlertChannel).where(
                AlertChannel.owner_id == current_user.id
            )
        )
    ).scalar() or 0

    has_team = (
        await db.execute(
            select(func.count()).select_from(TeamMembership).where(
                TeamMembership.user_id == current_user.id
            )
        )
    ).scalar() or 0 > 0

    return OnboardingStatus(
        completed=current_user.onboarding_completed_at is not None,
        completed_at=(
            current_user.onboarding_completed_at.isoformat()
            if current_user.onboarding_completed_at
            else None
        ),
        has_monitors=monitor_count > 0,
        has_alert_channels=channel_count > 0,
        has_team=has_team,
        monitor_count=monitor_count,
        channel_count=channel_count,
    )


@router.post("/complete", response_model=OnboardingStatus)
async def complete_onboarding(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark onboarding as completed for the current user."""
    if current_user.onboarding_completed_at is None:
        current_user.onboarding_completed_at = datetime.now(UTC)
        await db.flush()

    # Return fresh status
    monitor_count = (
        await db.execute(
            select(func.count()).select_from(Monitor).where(
                Monitor.owner_id == current_user.id
            )
        )
    ).scalar() or 0

    channel_count = (
        await db.execute(
            select(func.count()).select_from(AlertChannel).where(
                AlertChannel.owner_id == current_user.id
            )
        )
    ).scalar() or 0

    has_team = (
        await db.execute(
            select(func.count()).select_from(TeamMembership).where(
                TeamMembership.user_id == current_user.id
            )
        )
    ).scalar() or 0 > 0

    return OnboardingStatus(
        completed=True,
        completed_at=current_user.onboarding_completed_at.isoformat(),
        has_monitors=monitor_count > 0,
        has_alert_channels=channel_count > 0,
        has_team=has_team,
        monitor_count=monitor_count,
        channel_count=channel_count,
    )
