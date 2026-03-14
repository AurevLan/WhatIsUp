"""Public heartbeat ping endpoint — called by monitored cron jobs/services."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import get_db
from whatisup.core.limiter import limiter
from whatisup.models.monitor import Monitor

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ping", tags=["ping"])


@router.post("/{slug}", status_code=status.HTTP_200_OK)
@router.get("/{slug}", status_code=status.HTTP_200_OK)
@limiter.limit("120/minute")
async def heartbeat_ping(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record a heartbeat ping for a monitored cron job.

    Call from your cron job to signal it is alive:
        curl -X POST https://your-instance/api/v1/ping/my-daily-backup
    """
    monitor = (
        await db.execute(
            select(Monitor).where(
                Monitor.heartbeat_slug == slug,
                Monitor.enabled.is_(True),
            )
        )
    ).scalar_one_or_none()

    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown heartbeat slug")

    now = datetime.now(UTC)
    monitor.last_heartbeat_at = now
    await db.flush()

    logger.info("heartbeat_ping_received", slug=slug, monitor_id=str(monitor.id))
    return {"ok": True, "received_at": now.isoformat(), "monitor": monitor.name}
