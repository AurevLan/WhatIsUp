"""Audit log service — records state-changing actions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.audit_log import AuditLog
from whatisup.models.user import User

logger = structlog.get_logger(__name__)


async def log_action(
    db: AsyncSession,
    action: str,
    object_type: str,
    object_id: uuid.UUID | None = None,
    object_name: str | None = None,
    user: User | None = None,
    diff: dict | None = None,
    ip_address: str | None = None,
) -> None:
    """Record an auditable action. Never raises — audit failures must not block the main flow."""
    try:
        entry = AuditLog(
            timestamp=datetime.now(UTC),
            user_id=user.id if user else None,
            user_email=user.email if user else None,
            action=action,
            object_type=object_type,
            object_id=object_id,
            object_name=object_name,
            diff=diff,
            ip_address=ip_address,
        )
        db.add(entry)
        logger.info(
            "audit",
            action=action,
            object_type=object_type,
            object_id=str(object_id) if object_id else None,
            user_id=str(user.id) if user else None,
        )
    except Exception as exc:
        logger.error("audit_log_failed", error=str(exc))
