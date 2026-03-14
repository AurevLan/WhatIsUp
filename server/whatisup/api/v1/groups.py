"""MonitorGroup CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.models.monitor import Monitor, MonitorGroup
from whatisup.models.tag import Tag
from whatisup.models.user import User
from whatisup.schemas.monitor import (
    MonitorGroupCreate,
    MonitorGroupOut,
    MonitorGroupUpdate,
    MonitorOut,
)

router = APIRouter(prefix="/groups", tags=["groups"])


async def _get_group_or_404(group_id: uuid.UUID, user: User, db: AsyncSession) -> MonitorGroup:
    group = (
        await db.execute(select(MonitorGroup).where(MonitorGroup.id == group_id))
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    if not user.is_superadmin and group.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return group


@router.get("/", response_model=list[MonitorGroupOut])
async def list_groups(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[MonitorGroup]:
    query = select(MonitorGroup)
    if not current_user.is_superadmin:
        query = query.where(MonitorGroup.owner_id == current_user.id)
    result = await db.execute(query.order_by(MonitorGroup.created_at.desc()))
    return list(result.scalars().all())


@router.post("/", response_model=MonitorGroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    payload: MonitorGroupCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonitorGroup:
    if payload.public_slug:
        existing = (
            await db.execute(
                select(MonitorGroup).where(MonitorGroup.public_slug == payload.public_slug)
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already in use")

    tags = []
    if payload.tag_ids:
        tags_result = await db.execute(select(Tag).where(Tag.id.in_(payload.tag_ids)))
        tags = list(tags_result.scalars().all())

    group = MonitorGroup(
        name=payload.name,
        description=payload.description,
        public_slug=payload.public_slug,
        owner_id=current_user.id,
        tags=tags,
    )
    db.add(group)
    await db.flush()
    return group


@router.get("/{group_id}", response_model=MonitorGroupOut)
async def get_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonitorGroup:
    return await _get_group_or_404(group_id, current_user, db)


@router.patch("/{group_id}", response_model=MonitorGroupOut)
async def update_group(
    group_id: uuid.UUID,
    payload: MonitorGroupUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonitorGroup:
    group = await _get_group_or_404(group_id, current_user, db)
    update_data = payload.model_dump(exclude_unset=True)
    tag_ids = update_data.pop("tag_ids", None)

    for field, value in update_data.items():
        setattr(group, field, value)

    if tag_ids is not None:
        tags_result = await db.execute(select(Tag).where(Tag.id.in_(tag_ids)))
        group.tags = list(tags_result.scalars().all())

    await db.flush()
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    group = await _get_group_or_404(group_id, current_user, db)
    await db.delete(group)


@router.get("/{group_id}/monitors", response_model=list[MonitorOut])
async def list_group_monitors(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Monitor]:
    await _get_group_or_404(group_id, current_user, db)
    result = await db.execute(
        select(Monitor).where(Monitor.group_id == group_id).order_by(Monitor.name)
    )
    return list(result.scalars().all())
