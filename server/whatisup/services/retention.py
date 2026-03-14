"""Data retention — periodic purge of old check results."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete

from whatisup.core.database import get_session_factory
from whatisup.models.result import CheckResult

logger = structlog.get_logger(__name__)


async def purge_old_results(retention_days: int) -> int:
    """Delete CheckResult rows older than retention_days. Returns row count deleted."""
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with get_session_factory()() as db:
        result = await db.execute(
            delete(CheckResult).where(CheckResult.checked_at < cutoff)
        )
        await db.commit()
        count = result.rowcount
        if count > 0:
            logger.info("retention_purge_done", deleted=count, cutoff=cutoff.isoformat())
        return count
