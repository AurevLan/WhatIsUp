"""Data retention — periodic purge of old check results."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select

from whatisup.core.database import get_session_factory
from whatisup.core.partitions import drop_expired_check_result_partitions
from whatisup.models.result import CheckResult

logger = structlog.get_logger(__name__)


async def purge_old_results(retention_days: int) -> int:
    """Delete CheckResult rows older than retention_days.

    Monitors with a custom ``data_retention_days`` value use their own cutoff;
    the rest fall back to the global ``retention_days``.  Returns total row
    count deleted.

    On PostgreSQL the bulk of the work is done by dropping whole partitions
    (plan V2, A-1) — O(1), no bloat, no autovacuum debt — and the row-level
    DELETE only mops up what a partition drop cannot express: monitors whose
    own retention is shorter than the longest one in force. That distinction is
    the reason the partition cutoff uses the **longest** retention rather than
    the global one; using the global cutoff would drop months that a monitor
    with a longer ``data_retention_days`` explicitly asked to keep.
    """
    if retention_days <= 0:
        return 0
    total = 0
    now = datetime.now(UTC)
    async with get_session_factory()() as db:
        # Monitors with custom retention
        from whatisup.models.monitor import Monitor

        custom = (
            await db.execute(
                select(Monitor.id, Monitor.data_retention_days).where(
                    Monitor.data_retention_days.isnot(None)
                )
            )
        ).all()

        longest_days = max([retention_days, *(days for _, days in custom)])
        dropped = await drop_expired_check_result_partitions(db, now - timedelta(days=longest_days))
        if dropped:
            logger.info("retention_partitions_dropped", partitions=dropped, count=len(dropped))

        for mid, days in custom:
            cutoff = now - timedelta(days=days)
            result = await db.execute(
                delete(CheckResult).where(
                    CheckResult.monitor_id == mid,
                    CheckResult.checked_at < cutoff,
                )
            )
            total += result.rowcount

        # Global retention for monitors without custom setting
        custom_ids = [mid for mid, _ in custom]
        global_cutoff = now - timedelta(days=retention_days)
        stmt = delete(CheckResult).where(CheckResult.checked_at < global_cutoff)
        if custom_ids:
            stmt = stmt.where(CheckResult.monitor_id.notin_(custom_ids))
        result = await db.execute(stmt)
        total += result.rowcount
        await db.commit()
        if total > 0:
            logger.info("retention_purge_done", deleted=total, cutoff=global_cutoff.isoformat())
        return total
