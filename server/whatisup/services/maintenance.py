"""Maintenance window service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.maintenance import MaintenanceWindow


async def is_in_maintenance(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    group_id: uuid.UUID | None = None,
) -> bool:
    """Return True if the monitor (or its group) is currently in a maintenance window."""
    now = datetime.now(UTC)
    conditions = [MaintenanceWindow.monitor_id == monitor_id]
    if group_id:
        conditions.append(MaintenanceWindow.group_id == group_id)

    result = (
        await db.execute(
            select(MaintenanceWindow)
            .where(
                or_(*conditions),
                MaintenanceWindow.starts_at <= now,
                MaintenanceWindow.ends_at >= now,
            )
            .limit(1)
        )
    ).scalar_one_or_none()

    return result is not None


async def is_group_maintenance_suppressed(
    db: AsyncSession,
    group_id: uuid.UUID,
) -> bool:
    """Return True if there is an active maintenance window on the group.

    This is used to suppress individual alerts when the entire group is down
    and a group-level maintenance window is active.
    """
    now = datetime.now(UTC)
    result = (
        await db.execute(
            select(MaintenanceWindow)
            .where(
                MaintenanceWindow.group_id == group_id,
                MaintenanceWindow.starts_at <= now,
                MaintenanceWindow.ends_at >= now,
                MaintenanceWindow.suppress_alerts.is_(True),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return result is not None
