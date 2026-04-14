"""Tag CRUD endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import get_current_user
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.tag import Tag
from whatisup.models.user import User
from whatisup.schemas.tag import TagCreate, TagOut, TagUpdate

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("/", response_model=list[TagOut])
async def list_tags(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Tag]:
    result = await db.execute(select(Tag).order_by(Tag.name))
    return list(result.scalars().all())


@router.post("/", response_model=TagOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
async def create_tag(
    payload: TagCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tag:
    existing = (
        await db.execute(select(Tag).where(Tag.name == payload.name))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    tag = Tag(name=payload.name, color=payload.color, description=payload.description)
    db.add(tag)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(select(Tag).where(Tag.name == payload.name))
        ).scalar_one_or_none()
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Could not create tag"
            )
        return existing
    return tag


@router.patch("/{tag_id}", response_model=TagOut)
@limiter.limit("30/minute")
async def update_tag(
    tag_id: uuid.UUID,
    payload: TagUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tag:
    tag = (
        await db.execute(select(Tag).where(Tag.id == tag_id))
    ).scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    if payload.name is not None:
        tag.name = payload.name
    if payload.color is not None:
        tag.color = payload.color
    if payload.description is not None:
        tag.description = payload.description
    await db.flush()
    return tag


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_tag(
    tag_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    tag = (
        await db.execute(select(Tag).where(Tag.id == tag_id))
    ).scalar_one_or_none()
    if tag is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    await db.delete(tag)
