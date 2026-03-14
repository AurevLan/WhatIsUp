"""Heartbeat monitor checker — detects overdue pings and manages incidents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor

logger = structlog.get_logger(__name__)


async def check_heartbeats() -> None:
    """Check all heartbeat monitors for overdue pings. Opens/closes incidents."""
    from whatisup.core.database import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        now = datetime.now(UTC)
        monitors = (
            (
                await db.execute(
                    select(Monitor).where(
                        Monitor.check_type == "heartbeat",
                        Monitor.enabled.is_(True),
                        Monitor.heartbeat_interval_seconds.isnot(None),
                    )
                )
            )
            .scalars()
            .all()
        )

        for monitor in monitors:
            interval = monitor.heartbeat_interval_seconds
            grace = monitor.heartbeat_grace_seconds or 60
            last = monitor.last_heartbeat_at or datetime(1970, 1, 1, tzinfo=UTC)
            deadline = last + timedelta(seconds=interval + grace)
            is_overdue = now > deadline

            open_incident = (
                await db.execute(
                    select(Incident).where(
                        Incident.monitor_id == monitor.id,
                        Incident.resolved_at.is_(None),
                    )
                )
            ).scalar_one_or_none()

            if is_overdue and open_incident is None:
                incident = Incident(
                    monitor_id=monitor.id,
                    started_at=now,
                    scope=IncidentScope.global_,
                    affected_probe_ids=[],
                )
                db.add(incident)
                logger.warning(
                    "heartbeat_overdue",
                    monitor_id=str(monitor.id),
                    name=monitor.name,
                    last_ping=last.isoformat(),
                )
            elif not is_overdue and open_incident is not None:
                duration = int((now - open_incident.started_at).total_seconds())
                open_incident.resolved_at = now
                open_incident.duration_seconds = duration
                logger.info(
                    "heartbeat_recovered",
                    monitor_id=str(monitor.id),
                    name=monitor.name,
                    duration_seconds=duration,
                )

        await db.commit()
