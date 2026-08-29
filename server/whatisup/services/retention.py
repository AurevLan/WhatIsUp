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
* ``custom_metrics`` keeps what the tenant's own application pushed, at the
  same grain it pushed it. ``METRICS_RETENTION_DAYS`` governs it (plan V2, C-2);
  before that phase nothing purged it at all.
* ``discovered_services`` (terminal states only) and ``alert_events`` are two
  plain, unpartitioned logs that had **no** retention at all before an audit
  flagged both (2026-08). ``DISCOVERED_SERVICES_RETENTION_DAYS`` and
  ``ALERT_EVENTS_RETENTION_DAYS`` govern them respectively — same "0 = keep
  forever" convention as everything else here, no floor to respect because
  nothing downstream aggregates either of them.

Which makes the ordering constraint between them the interesting part: a raw
row deleted *before* it was folded is gone from both tables, so the purge never
crosses the rollup builder (see ``_raw_purge_floor``).
"""

from __future__ import annotations

import calendar
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.core.database import get_session_factory
from whatisup.core.partitions import (
    drop_expired_check_result_partitions,
    drop_expired_custom_metric_partitions,
)
from whatisup.models.alert import AlertEvent
from whatisup.models.custom_metric import CustomMetric, MetricSeries
from whatisup.models.discovery import DiscoveredService
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


async def _purge_partitioned_table(
    db: AsyncSession,
    *,
    model: type,
    time_col: Any,
    monitor_col: Any,
    retention_days: int,
    drop_partitions: Callable[[AsyncSession, datetime], Awaitable[list[str]]],
    floor: datetime | None,
    label: str,
) -> int:
    """Purge one monthly-partitioned, monitor-scoped table. Returns rows deleted.

    Shared by the raw results and the pushed metrics because the rule is the
    same for both, and a second copy of it would be a second place to forget the
    per-monitor override:

    * on PostgreSQL the bulk is a **partition DROP** — O(1), no bloat, no
      autovacuum debt (a nightly ``DELETE`` on a table this size is the worst
      write pattern there is, which is what plan V2, A-1 removed);
    * the row-level DELETE only mops up what a drop cannot express, namely
      monitors whose own retention is shorter than the longest one in force.

    Which is why the partition cutoff uses the **longest** retention rather than
    the global one: a partition holds every monitor's rows side by side, so
    dropping on the global cutoff would destroy history a monitor with a longer
    ``data_retention_days`` explicitly asked to keep.

    ``floor`` clamps every cutoff (plan V2, A-4) when something downstream has
    not caught up yet; None means no clamp.
    """
    from whatisup.models.monitor import Monitor

    now = datetime.now(UTC)
    custom = (
        await db.execute(
            select(Monitor.id, Monitor.data_retention_days).where(
                Monitor.data_retention_days.isnot(None)
            )
        )
    ).all()

    def _cutoff(days: int) -> datetime:
        wanted = now - timedelta(days=days)
        if floor is not None and floor < wanted:
            logger.info(
                "retention_held_back_by_rollups",
                table=label,
                wanted=wanted.isoformat(),
                applied=floor.isoformat(),
            )
            return floor
        return wanted

    longest_days = max([retention_days, *(days for _, days in custom)])
    dropped = await drop_partitions(db, _cutoff(longest_days))
    if dropped:
        logger.info(
            "retention_partitions_dropped", table=label, partitions=dropped, count=len(dropped)
        )

    total = 0
    for mid, days in custom:
        result = await db.execute(delete(model).where(monitor_col == mid, time_col < _cutoff(days)))
        total += result.rowcount

    # Global retention for monitors without a custom setting
    custom_ids = [mid for mid, _ in custom]
    global_cutoff = _cutoff(retention_days)
    stmt = delete(model).where(time_col < global_cutoff)
    if custom_ids:
        stmt = stmt.where(monitor_col.notin_(custom_ids))
    result = await db.execute(stmt)
    total += result.rowcount
    await db.commit()
    if total > 0:
        logger.info(
            "retention_purge_done", table=label, deleted=total, cutoff=global_cutoff.isoformat()
        )
    return total


async def purge_old_results(retention_days: int) -> int:
    """Delete ``check_results`` rows older than ``retention_days``.

    Monitors with a custom ``data_retention_days`` value use their own cutoff;
    the rest fall back to the global ``retention_days``. Returns rows deleted.

    Every cutoff is floored by the rollup builder's frontier (plan V2, A-4):
    whatever the configured retention, raw rows that have not been folded yet
    are never deleted. See :func:`_raw_purge_floor`.
    """
    if retention_days <= 0:
        return 0
    async with get_session_factory()() as db:
        return await _purge_partitioned_table(
            db,
            model=CheckResult,
            time_col=CheckResult.checked_at,
            monitor_col=CheckResult.monitor_id,
            retention_days=retention_days,
            # Resolved here, at call time, so the module attribute stays the
            # single seam tests patch.
            drop_partitions=drop_expired_check_result_partitions,
            floor=await _raw_purge_floor(db),
            label="check_results",
        )


async def purge_old_metrics(retention_days: int) -> int:
    """Delete ``custom_metrics`` rows older than ``retention_days`` (plan V2, C-2).

    Until C-2 this table had **no retention at all** — nothing purged it, so it
    grew without bound for the lifetime of the deployment. It now ages out on
    the same terms as the raw results, per-monitor override included: a short
    ``Monitor.data_retention_days`` means "I do not need this monitor's raw
    detail", and a pushed metric is exactly that.

    No floor: nothing aggregates metrics yet, so there is no builder to outrun.
    """
    if retention_days <= 0:
        return 0
    async with get_session_factory()() as db:
        return await _purge_partitioned_table(
            db,
            model=CustomMetric,
            time_col=CustomMetric.pushed_at,
            monitor_col=CustomMetric.monitor_id,
            retention_days=retention_days,
            drop_partitions=drop_expired_custom_metric_partitions,
            floor=None,
            label="custom_metrics",
        )


async def purge_stale_metric_series(retention_days: int) -> int:
    """Forget series whose last point has aged out of the window (plan V2, C-1).

    The registry is what enforces the per-monitor cardinality cap, so a series
    that stops reporting must eventually free its slot — otherwise a monitor
    that renames its metrics once a quarter drifts into a permanent 429 while
    the points table holds nothing at all.

    Cut on ``last_seen_at`` against the *metrics* retention window, so a series
    disappears from the registry at the same moment its last point disappears
    from the table. Deleting it earlier would leave orphan points that no label
    selector can reach; later would keep charging a monitor for data it no
    longer has.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with get_session_factory()() as db:
        result = await db.execute(delete(MetricSeries).where(MetricSeries.last_seen_at < cutoff))
        await db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("metric_series_purged", deleted=deleted, cutoff=cutoff.isoformat())
        return deleted


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


async def purge_old_discovered_services(retention_days: int) -> int:
    """Delete ``discovered_services`` rows stuck in a terminal state.

    Only ``dismissed`` and ``orphaned`` age out. ``proposed`` is a decision
    nobody has made yet — purging it would make discovery silently forget a
    review the operator hasn't seen — and ``accepted`` is the provenance of a
    live ``Monitor``, not disposable review-queue clutter.

    Cut on ``status_changed_at``, not ``last_seen_at``: the reconciler
    (``services/discovery.py``) bumps ``status_changed_at`` every time a
    terminal row's state actually changes — a dismissed row whose fingerprint
    drifted, an orphan whose target came back — so this measures how long a
    row has sat *unchanged* in its terminal state, not how recently a scan
    merely touched it. No table before this had ever purged it at all.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with get_session_factory()() as db:
        result = await db.execute(
            delete(DiscoveredService).where(
                DiscoveredService.status.in_(("dismissed", "orphaned")),
                DiscoveredService.status_changed_at < cutoff,
            )
        )
        await db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("discovered_services_purged", deleted=deleted, cutoff=cutoff.isoformat())
        return deleted


async def purge_old_alert_events(retention_days: int) -> int:
    """Delete ``alert_events`` rows older than ``retention_days``.

    A plain DELETE, same shape as the rollup and series purges above: the
    table is not partitioned, and every reader of it — the 60-second dispatch
    dedup, the storm-window counter, digest recovery, renotify, one incident's
    own alert history in the UI — only ever looks at a short recent window or
    at the events of one specific incident, never at "every event ever sent".
    No interlock like ``_raw_purge_floor`` is needed because nothing
    aggregates this table the way rollups fold raw results.

    Before this (audit finding, 2026-08) ``alert_events`` was the only
    temporal table in the product with no retention at all.
    """
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    async with get_session_factory()() as db:
        result = await db.execute(delete(AlertEvent).where(AlertEvent.sent_at < cutoff))
        await db.commit()
        deleted = result.rowcount
        if deleted > 0:
            logger.info("alert_events_purged", deleted=deleted, cutoff=cutoff.isoformat())
        return deleted
