"""V2 Global Health Engine — server-side aggregator (M0 skeleton).

The probe stays a pure sensor. After every CheckResult is persisted, this
service updates ``MonitorHealthState`` so SLO rules can be evaluated against a
consistent fleet view rather than per-probe local decisions.

M0 ships only the no-op skeleton + DB row materialization. M1 fills in
``probes_state``, percentiles and T-Digests. M2/M3 wires SLO evaluation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor_health import MonitorHealthState
from whatisup.models.result import CheckResult

logger = logging.getLogger(__name__)


async def ensure_state(db: AsyncSession, monitor_id) -> MonitorHealthState:
    """Get-or-create the MonitorHealthState row for a monitor (used by tests + ingest)."""
    state = (
        await db.execute(
            select(MonitorHealthState).where(MonitorHealthState.monitor_id == monitor_id)
        )
    ).scalar_one_or_none()
    if state is not None:
        return state
    state = MonitorHealthState(
        monitor_id=monitor_id,
        updated_at=datetime.now(UTC),
        probes_state={},
        probe_health={},
    )
    db.add(state)
    await db.flush()
    return state


async def ingest(db: AsyncSession, check_result: CheckResult) -> None:
    """Update the monitor's health state from a freshly-persisted CheckResult.

    M0: no-op beyond materializing the row + bumping ``updated_at``. M1 adds
    the per-probe view, percentiles, and T-Digests.
    """
    state = await ensure_state(db, check_result.monitor_id)
    state.updated_at = datetime.now(UTC)
