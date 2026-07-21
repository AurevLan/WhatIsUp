"""Monitor annotations CRUD."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import (
    get_current_user,
)
from whatisup.api.v1.monitors._common import _get_monitor_or_404
from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.annotation import MonitorAnnotation
from whatisup.models.user import User
from whatisup.schemas.annotation import AnnotationCreate, AnnotationOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitors", tags=["monitors"])


@router.get("/{monitor_id}/annotations")
@limiter.limit("60/minute")
async def list_annotations(
    request: Request,
    monitor_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_monitor_or_404(monitor_id, current_user, db)
    rows = (
        (
            await db.execute(
                select(MonitorAnnotation)
                .where(MonitorAnnotation.monitor_id == monitor_id)
                .order_by(MonitorAnnotation.annotated_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    return [AnnotationOut.model_validate(r).model_dump(mode="json") for r in rows]


@router.post("/{monitor_id}/annotations", status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")
async def create_annotation(
    request: Request,
    monitor_id: uuid.UUID,
    payload: AnnotationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_monitor_or_404(monitor_id, current_user, db)
    ann = MonitorAnnotation(
        monitor_id=monitor_id,
        content=payload.content,
        annotated_at=payload.annotated_at,
        created_at=datetime.now(UTC),
        created_by=current_user.username,
    )
    db.add(ann)
    await db.flush()
    return AnnotationOut.model_validate(ann).model_dump(mode="json")


@router.delete("/{monitor_id}/annotations/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_annotation(
    request: Request,
    monitor_id: uuid.UUID,
    annotation_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _get_monitor_or_404(monitor_id, current_user, db)
    ann = (
        await db.execute(
            select(MonitorAnnotation).where(
                MonitorAnnotation.id == annotation_id,
                MonitorAnnotation.monitor_id == monitor_id,
            )
        )
    ).scalar_one_or_none()
    if ann is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annotation not found")
    await db.delete(ann)
