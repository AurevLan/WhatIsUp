"""Composite monitor evaluation.

After any CheckResult is stored for a member monitor, this service recomputes
the state of all composite monitors that include it, creating synthetic CheckResults
(probe_id=None) and running them through the normal incident pipeline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import CompositeMonitorMember, Monitor
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.services.stats import latest_results_subq

logger = structlog.get_logger(__name__)

_DOWN_STATUSES = {CheckStatus.down, CheckStatus.timeout, CheckStatus.error}


def _apply_aggregation_rule(
    rule: str | None,
    members: list[CompositeMonitorMember],
    status_by_monitor: dict[uuid.UUID, CheckStatus],
) -> CheckStatus:
    """Compute composite status from member statuses according to the aggregation rule."""
    statuses = [status_by_monitor.get(m.monitor_id) for m in members]
    known = [s for s in statuses if s is not None]

    if not known:
        return CheckStatus.up  # No data yet — treat as unknown / up

    up_count = sum(1 for s in known if s == CheckStatus.up)
    total = len(known)

    if rule == "all_up":
        return CheckStatus.up if up_count == total else CheckStatus.down
    elif rule == "any_up":
        return CheckStatus.up if up_count > 0 else CheckStatus.down
    elif rule == "weighted_up":
        total_weight = sum(m.weight for m in members)
        up_weight = sum(
            m.weight
            for m in members
            if status_by_monitor.get(m.monitor_id) == CheckStatus.up
        )
        return CheckStatus.up if up_weight * 2 > total_weight else CheckStatus.down
    else:
        # Default: majority_up
        return CheckStatus.up if up_count * 2 > total else CheckStatus.down


async def evaluate_composite_parents(
    db: AsyncSession,
    triggered_monitor_id: uuid.UUID,
    publish_event,
) -> None:
    """
    Find all composite monitors that list `triggered_monitor_id` as a member,
    recompute their state, and create synthetic CheckResults to drive the
    existing incident pipeline.

    Must be called at the end of process_check_result (inside the same session,
    after the triggering result is already committed to the DB).
    """
    memberships = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.monitor_id == triggered_monitor_id
            )
        )
    ).scalars().all()

    if not memberships:
        return

    composite_ids = {m.composite_id for m in memberships}

    for composite_id in composite_ids:
        composite = await db.get(Monitor, composite_id)
        if composite is None or not composite.enabled:
            continue
        await _recompute_composite(db, composite, publish_event)


async def _recompute_composite(
    db: AsyncSession,
    composite: Monitor,
    publish_event,
) -> None:
    """Recompute the state of one composite monitor and store a synthetic CheckResult."""
    # Import here to avoid circular import (composite → incident → composite)
    from whatisup.services.incident import process_check_result

    all_members = (
        await db.execute(
            select(CompositeMonitorMember).where(
                CompositeMonitorMember.composite_id == composite.id
            )
        )
    ).scalars().all()

    if not all_members:
        logger.warning("composite_no_members", composite_id=str(composite.id))
        return

    member_monitor_ids = [m.monitor_id for m in all_members]

    # Latest result per member monitor (one query)
    latest_subq = latest_results_subq(
        CheckResult.monitor_id.in_(member_monitor_ids),
        group_col=CheckResult.monitor_id,
    )
    latest_results = (
        await db.execute(
            select(CheckResult).join(
                latest_subq,
                (CheckResult.monitor_id == latest_subq.c.monitor_id)
                & (CheckResult.checked_at == latest_subq.c.max_at),
            )
        )
    ).scalars().all()

    status_by_monitor: dict[uuid.UUID, CheckStatus] = {
        r.monitor_id: r.status for r in latest_results
    }

    computed_status = _apply_aggregation_rule(
        composite.composite_aggregation, all_members, status_by_monitor
    )

    # Build context error message
    down_members = [
        m
        for m in all_members
        if status_by_monitor.get(m.monitor_id) in _DOWN_STATUSES
    ]
    error_msg: str | None = None
    if computed_status != CheckStatus.up and down_members:
        labels = [m.role or str(m.monitor_id)[:8] for m in down_members]
        error_msg = f"Members down: {', '.join(labels)}"

    # Create synthetic CheckResult (probe_id=None — no physical probe)
    synthetic = CheckResult(
        monitor_id=composite.id,
        probe_id=None,
        checked_at=datetime.now(UTC),
        status=computed_status,
        error_message=error_msg,
    )
    db.add(synthetic)
    await db.flush()

    logger.info(
        "composite_evaluated",
        composite_id=str(composite.id),
        status=computed_status,
        rule=composite.composite_aggregation,
        members_total=len(all_members),
        members_down=len(down_members),
    )

    # Run the full incident pipeline for the composite
    await process_check_result(db, synthetic, publish_event)
