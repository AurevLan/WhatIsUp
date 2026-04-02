"""Autonomous renotify — background job that fires renotify alerts for open incidents.

Runs every 60s. Handles the case where no check results arrive (e.g. probe is also
down) but the incident is still open and the user needs to be re-alerted.
"""

from __future__ import annotations

import structlog
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from whatisup.models.alert import AlertRule
from whatisup.models.incident import Incident

logger = structlog.get_logger(__name__)


async def check_renotify() -> None:
    """Find open, non-acked incidents and fire renotify alerts if due."""
    from whatisup.core.database import get_session_factory
    from whatisup.services.incident import _fire_alerts

    factory = get_session_factory()
    async with factory() as db:
        # Only process incidents that are open, not acked, not suppressed
        open_incidents = (
            (
                await db.execute(
                    select(Incident)
                    .where(
                        Incident.resolved_at.is_(None),
                        Incident.acked_at.is_(None),
                        Incident.dependency_suppressed.is_(False),
                    )
                    .options(selectinload(Incident.monitor))
                )
            )
            .scalars()
            .all()
        )

        if not open_incidents:
            return

        for incident in open_incidents:
            monitor = incident.monitor
            if monitor is None or not monitor.enabled:
                continue

            # Check if any applicable rule has renotify_after_minutes
            conditions = [AlertRule.monitor_id == monitor.id]
            if monitor.group_id:
                conditions.append(AlertRule.group_id == monitor.group_id)

            has_renotify = (
                await db.execute(
                    select(AlertRule.id)
                    .where(
                        or_(*conditions),
                        AlertRule.enabled.is_(True),
                        AlertRule.renotify_after_minutes.isnot(None),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()

            if not has_renotify:
                continue

            try:
                await _fire_alerts(db, incident, monitor, event_type="incident_renotify")
            except Exception:
                logger.exception(
                    "autonomous_renotify_failed",
                    incident_id=str(incident.id),
                    monitor_id=str(monitor.id),
                )
                await db.rollback()
                continue

        await db.commit()
