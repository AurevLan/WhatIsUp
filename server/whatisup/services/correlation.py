"""Correlation pattern learning — track monitors that frequently fail together."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from itertools import combinations

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.correlation_pattern import CorrelationPattern
from whatisup.models.incident import Incident, IncidentGroup

logger = structlog.get_logger(__name__)


async def update_patterns_for_group(
    db: AsyncSession,
    group: IncidentGroup,
) -> None:
    """
    Called when an IncidentGroup is created or expanded.
    For every pair of monitors in the group, upsert a CorrelationPattern row.
    """
    incidents = (
        (await db.execute(select(Incident.monitor_id).where(Incident.group_id == group.id)))
        .scalars()
        .all()
    )

    monitor_ids = sorted(set(str(mid) for mid in incidents))
    if len(monitor_ids) < 2:
        return

    now = datetime.now(UTC)

    # Collect all pairs and batch-upsert in a single statement
    rows = []
    for a, b in combinations(monitor_ids, 2):
        a_uuid, b_uuid = uuid.UUID(a), uuid.UUID(b)
        # Ensure consistent ordering (smaller UUID first)
        if a_uuid > b_uuid:
            a_uuid, b_uuid = b_uuid, a_uuid
        rows.append(
            {
                "monitor_a_id": a_uuid,
                "monitor_b_id": b_uuid,
                "co_occurrence_count": 1,
                "last_seen": now,
            }
        )

    if rows:
        stmt = (
            pg_insert(CorrelationPattern)
            .values(rows)
            .on_conflict_do_update(
                index_elements=["monitor_a_id", "monitor_b_id"],
                set_={
                    "co_occurrence_count": CorrelationPattern.co_occurrence_count + 1,
                    "last_seen": now,
                },
            )
        )
        await db.execute(stmt)

    await db.flush()
    logger.info(
        "correlation_patterns_updated",
        group_id=str(group.id),
        monitor_count=len(monitor_ids),
        pairs=len(list(combinations(monitor_ids, 2))),
    )


async def get_correlated_monitors(
    db: AsyncSession,
    monitor_id: uuid.UUID,
    min_occurrences: int = 2,
) -> list[dict]:
    """
    Return monitors that frequently fail together with the given monitor.
    Used for proactive suggestions when one monitor goes down.
    """
    mid = monitor_id

    rows = (
        (
            await db.execute(
                select(CorrelationPattern)
                .where(
                    (CorrelationPattern.monitor_a_id == mid)
                    | (CorrelationPattern.monitor_b_id == mid),
                    CorrelationPattern.co_occurrence_count >= min_occurrences,
                )
                .order_by(CorrelationPattern.co_occurrence_count.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )

    result = []
    for row in rows:
        other_id = row.monitor_b_id if row.monitor_a_id == mid else row.monitor_a_id
        result.append(
            {
                "monitor_id": str(other_id),
                "co_occurrence_count": row.co_occurrence_count,
                "last_seen": row.last_seen.isoformat(),
            }
        )
    return result
