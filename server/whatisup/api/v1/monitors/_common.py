"""Shared helpers for the monitors sub-routers."""

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    check_resource_access,
)
from whatisup.models.monitor import Monitor
from whatisup.models.team import TeamRole
from whatisup.models.user import User

logger = logging.getLogger(__name__)


async def _get_monitor_or_404(
    monitor_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> Monitor:
    monitor = (
        await db.execute(select(Monitor).where(Monitor.id == monitor_id))
    ).scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")
    await check_resource_access(monitor, user, db, min_role=min_role)
    return monitor
