"""Shared helpers for the alerts sub-routers."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import build_access_filter, get_user_team_ids
from whatisup.models.alert import AlertChannel
from whatisup.models.user import User


async def _fetch_channels_by_ids(
    db: AsyncSession,
    user: User,
    channel_ids: list[uuid.UUID] | set[uuid.UUID],
) -> list[AlertChannel]:
    """Return user-visible channels for all requested ids, or raise 400 on any miss.

    Honours team sharing via `build_access_filter` — `owner_id`-only checks would
    silently drop channels shared through a team.
    """
    ids = list(channel_ids)
    if not ids:
        return []
    query = select(AlertChannel).where(AlertChannel.id.in_(ids))
    if not user.is_superadmin:
        team_ids = await get_user_team_ids(user, db)
        query = query.where(build_access_filter(AlertChannel, user, team_ids))
    result = await db.execute(query)
    channels = list(result.scalars().all())
    if len(channels) != len({*ids}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Some channels not found"
        )
    return channels
