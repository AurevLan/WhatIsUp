"""Status page announcement endpoints (plan cap V2, 5b).

Admin CRUD for `StatusAnnouncement`, nested under the owning `MonitorGroup` —
same visibility rule as every other group-scoped resource (`api/v1/groups.py`,
`api/v1/maintenance.py`): owner, or team member at >= the required role.

Deliberately does **not** touch `Incident`/`IS_AVAILABILITY_INCIDENT` — see
`models/status_announcement.py` module docstring.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from whatisup.api.deps import check_resource_access, get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.monitor import MonitorGroup
from whatisup.models.status_announcement import StatusAnnouncement, StatusAnnouncementUpdate
from whatisup.models.team import TeamRole
from whatisup.models.user import User
from whatisup.schemas.status_announcement import (
    StatusAnnouncementCreate,
    StatusAnnouncementOut,
    StatusAnnouncementTitleUpdate,
    StatusAnnouncementUpdateCreate,
    StatusAnnouncementUpdateOut,
)

router = APIRouter(prefix="/groups", tags=["status-announcements"])


async def _get_group_for_announcements(
    group_id: uuid.UUID,
    user: User,
    db: AsyncSession,
    min_role: TeamRole = TeamRole.viewer,
) -> MonitorGroup:
    group = (
        await db.execute(select(MonitorGroup).where(MonitorGroup.id == group_id))
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    await check_resource_access(group, user, db, min_role=min_role)
    return group


async def _get_announcement_or_404(
    group_id: uuid.UUID, announcement_id: uuid.UUID, db: AsyncSession
) -> StatusAnnouncement:
    announcement = (
        await db.execute(
            select(StatusAnnouncement)
            .options(selectinload(StatusAnnouncement.updates))
            .where(
                StatusAnnouncement.id == announcement_id,
                StatusAnnouncement.group_id == group_id,
            )
        )
    ).scalar_one_or_none()
    if announcement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Announcement not found")
    return announcement


@router.get(
    "/{group_id}/announcements",
    response_model=list[StatusAnnouncementOut],
)
@limiter.limit("60/minute")
async def list_announcements(
    request: Request,
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[StatusAnnouncement]:
    await _get_group_for_announcements(group_id, current_user, db)
    result = await db.execute(
        select(StatusAnnouncement)
        .options(selectinload(StatusAnnouncement.updates))
        .where(StatusAnnouncement.group_id == group_id)
        .order_by(StatusAnnouncement.started_at.desc())
    )
    return list(result.scalars().unique().all())


@router.post(
    "/{group_id}/announcements",
    response_model=StatusAnnouncementOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute")
async def create_announcement(
    request: Request,
    group_id: uuid.UUID,
    payload: StatusAnnouncementCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatusAnnouncement:
    await _get_group_for_announcements(group_id, current_user, db, min_role=TeamRole.editor)

    now = datetime.now(UTC)
    announcement = StatusAnnouncement(
        group_id=group_id,
        title=payload.title,
        status=payload.status,
        started_at=now,
        created_by_id=current_user.id,
    )
    # Appended before the parent is even flushed: a transient object's
    # collection needs no lazy load, unlike assigning to `.updates` on an
    # already-persisted announcement (that triggers a lazy SELECT, which
    # blows up here since nothing awaits it — MissingGreenlet).
    initial_update = StatusAnnouncementUpdate(
        created_by_id=current_user.id,
        created_by_name=current_user.email,
        status=payload.status,
        message=payload.message,
        is_public=True,
        created_at=now,
    )
    announcement.updates.append(initial_update)
    db.add(announcement)
    await db.flush()

    from whatisup.services.audit import log_action

    await log_action(
        db,
        "announcement.create",
        "status_announcement",
        announcement.id,
        announcement.title,
        current_user,
    )
    return announcement


@router.patch(
    "/{group_id}/announcements/{announcement_id}",
    response_model=StatusAnnouncementOut,
)
@limiter.limit("30/minute")
async def update_announcement_title(
    request: Request,
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    payload: StatusAnnouncementTitleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatusAnnouncement:
    """Correct the title after the fact. The narrative itself lives in the
    update thread — this never rewrites `status`/`ended_at`."""
    await _get_group_for_announcements(group_id, current_user, db, min_role=TeamRole.editor)
    announcement = await _get_announcement_or_404(group_id, announcement_id, db)

    announcement.title = payload.title
    await db.flush()

    from whatisup.services.audit import log_action

    await log_action(
        db,
        "announcement.update",
        "status_announcement",
        announcement.id,
        announcement.title,
        current_user,
    )
    return announcement


@router.post(
    "/{group_id}/announcements/{announcement_id}/updates",
    response_model=StatusAnnouncementUpdateOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def add_announcement_update(
    request: Request,
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    payload: StatusAnnouncementUpdateCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatusAnnouncementUpdate:
    await _get_group_for_announcements(group_id, current_user, db, min_role=TeamRole.editor)
    announcement = await _get_announcement_or_404(group_id, announcement_id, db)
    if announcement.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot post to a closed announcement",
        )

    update = StatusAnnouncementUpdate(
        announcement_id=announcement.id,
        created_by_id=current_user.id,
        created_by_name=current_user.email,
        status=payload.status,
        message=payload.message,
        is_public=payload.is_public,
        created_at=datetime.now(UTC),
    )
    db.add(update)
    # Keep the announcement's current state in sync with its latest post —
    # the public page reads `announcement.status`, not the thread, for the
    # headline state.
    announcement.status = payload.status
    await db.flush()
    await db.refresh(update)
    return update


@router.post(
    "/{group_id}/announcements/{announcement_id}/close",
    response_model=StatusAnnouncementOut,
)
@limiter.limit("30/minute")
async def close_announcement(
    request: Request,
    group_id: uuid.UUID,
    announcement_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StatusAnnouncement:
    await _get_group_for_announcements(group_id, current_user, db, min_role=TeamRole.editor)
    announcement = await _get_announcement_or_404(group_id, announcement_id, db)
    if announcement.ended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Announcement already closed"
        )
    announcement.ended_at = datetime.now(UTC)
    await db.flush()

    from whatisup.services.audit import log_action

    await log_action(
        db,
        "announcement.close",
        "status_announcement",
        announcement.id,
        announcement.title,
        current_user,
    )
    return announcement
