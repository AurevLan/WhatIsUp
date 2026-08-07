"""Data retention — periodic purge of old check results and rollups.

Two horizons since A-4 (plan V2), because the two tables answer different
questions:

* ``check_results`` (raw) keeps the **per-result detail** — the scenario trace,
  the TLS audit, the DNS answers, the exact timestamp a probe saw. That is what
  incident forensics needs, and it is bulky. ``DATA_RETENTION_DAYS`` governs it.
* ``check_rollups_1h`` keeps the **shape of the history** — uptime, counters,
  latency percentiles per hour. Two orders of magnitude smaller, and the only
  thing left once the raw window has passed. ``ROLLUP_RETENTION_MONTHS``
  governs it, and is meant to be much longer.

Which makes the ordering constraint between them the interesting part: a raw
row deleted *before* it was folded is gone from both tables, so the purge never
crosses the rollup builder (see ``_raw_purge_floor``).
"""

from __future__ import annotations

import calendar
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.core.database import get_session_factory
from whatisup.core.partitions import drop_expired_check_result_partitions
from whatisup.models.result import CheckResult
from whatisup.models.rollup import CheckRollup1h
from whatisup.services.rollup import rollup_boundary

logger = structlog.get_logger(__name__)


def _months_before(moment: datetime, months: int) -> datetime:
    """``moment`` shifted back by whole calendar months.

    Calendar months, not ``months × 30 days``: 13 months has to mean "the same
    day last year, plus one" whatever the months in between were worth, or a
    year-on-year comparison drifts by a fortnight. Clamped to the last day when
    the target month is shorter (31 March − 1 month = 28/29 February).
    """
    total = moment.year * 12 + (moment.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    return moment.replace(
        year=year, month=month, day=min(moment.day, calendar.monthrange(year, month)[1])
    )


async def _raw_purge_floor(db: AsyncSession) -> datetime | None:
    """Earliest instant the raw purge must not delete past, or None for no limit.

    Deleting a raw row the builder has not folded yet destroys that hour in both
    tables at once — the rollup that would have outlived it never gets written.
    So when the rollups are in use, the purge stops at the builder's frontier,
    however short the configured retention is.

    Returns None — no interlock — in the two cases where the frontier means
    nothing: rollups switched off (the raw table is then the only history, and a
    stale watermark would freeze the purge forever), and an empty rollup table
    (a builder that has not written its first bucket yet; it does so within one
    interval of boot, long before the nightly job). The second case is logged:
    if it persists, the builder is broken and the guard is not protecting
    anything.
    """
    if not get_settings().rollup_enabled:
        return None
    boundary = await rollup_boundary(db)
    if boundary is None:
        logger.warning("retention_no_rollup_floor", reason="rollup table empty")
    return boundary


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

    Every cutoff here is additionally floored by the rollup builder's frontier
    (plan V2, A-4): whatever the configured retention, raw rows that have not
    been folded yet are never deleted. See :func:`_raw_purge_floor`.
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

        floor = await _raw_purge_floor(db)

        def _cutoff(days: int) -> datetime:
            wanted = now - timedelta(days=days)
            if floor is not None and floor < wanted:
                logger.info(
                    "retention_held_back_by_rollups",
                    wanted=wanted.isoformat(),
                    applied=floor.isoformat(),
                )
                return floor
            return wanted

        longest_days = max([retention_days, *(days for _, days in custom)])
        dropped = await drop_expired_check_result_partitions(db, _cutoff(longest_days))
        if dropped:
            logger.info("retention_partitions_dropped", partitions=dropped, count=len(dropped))

        for mid, days in custom:
            result = await db.execute(
                delete(CheckResult).where(
                    CheckResult.monitor_id == mid,
                    CheckResult.checked_at < _cutoff(days),
                )
            )
            total += result.rowcount

        # Global retention for monitors without custom setting
        custom_ids = [mid for mid, _ in custom]
        global_cutoff = _cutoff(retention_days)
        stmt = delete(CheckResult).where(CheckResult.checked_at < global_cutoff)
        if custom_ids:
            stmt = stmt.where(CheckResult.monitor_id.notin_(custom_ids))
        result = await db.execute(stmt)
        total += result.rowcount
        await db.commit()
        if total > 0:
            logger.info("retention_purge_done", deleted=total, cutoff=global_cutoff.isoformat())
        return total


async def purge_old_rollups(retention_months: int) -> int:
    """Delete ``check_rollups_1h`` rows older than ``retention_months``.

    A plain DELETE, unlike the raw table: at ~140 k rows a year the whole table
    is smaller than one day of raw results, so partitioning it would cost more
    than it saves. Returns the row count deleted.

    Global only — ``Monitor.data_retention_days`` stays a *raw* setting. A short
    per-monitor window means "I do not need this monitor's per-result detail",
    not "erase its uptime history"; that is exactly the separation A-4 exists to
    make.
    """
    if retention_months <= 0:
        return 0
    cutoff = _months_before(datetime.now(UTC), retention_months)
    async with get_session_factory()() as db:
        result = await db.execute(delete(CheckRollup1h).where(CheckRollup1h.bucket < cutoff))
        await db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("rollup_purge_done", deleted=deleted, cutoff=cutoff.isoformat())
        return deleted
