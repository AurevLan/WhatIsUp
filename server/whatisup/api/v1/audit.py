"""Audit log endpoints."""

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.api.deps import require_superadmin
from whatisup.core.database import get_db
from whatisup.models.audit_log import AuditLog
from whatisup.models.user import User
from whatisup.schemas.audit_log import AuditLogOut

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/", response_model=list[AuditLogOut])
async def list_audit_logs(
    object_type: str | None = None,
    object_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _user: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.timestamp.desc())
    if object_type:
        query = query.where(AuditLog.object_type == object_type)
    if object_id:
        query = query.where(AuditLog.object_id == object_id)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    return list(result.scalars().all())
