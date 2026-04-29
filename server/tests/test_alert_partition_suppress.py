"""V2-02-02 — Test suppress_on_network_partition gates dispatch.

Verifies that when an AlertRule has suppress_on_network_partition=True and the
incident's network_verdict is a network_partition_*, dispatch_alert is never
called from maybe_digest_or_dispatch. Conversely, service_down or null verdicts
must still go through.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.alert import AlertChannel, AlertChannelType, AlertCondition, AlertRule
from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.user import User
from whatisup.services.alert import maybe_digest_or_dispatch


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "verdict,suppress,expect_dispatch",
    [
        ("network_partition_asn", True, False),
        ("network_partition_geo", True, False),
        ("service_down",          True, True),
        ("inconclusive",          True, True),
        (None,                    True, True),
        ("network_partition_asn", False, True),  # opt-out → still paged
    ],
)
async def test_partition_suppression_matrix(
    service_db: AsyncSession,
    verdict: str | None,
    suppress: bool,
    expect_dispatch: bool,
) -> None:
    user = User(email="u@x", username="u", hashed_password="x")
    service_db.add(user)
    await service_db.flush()

    monitor = Monitor(name="m1", url="http://example.com", owner_id=user.id)
    service_db.add(monitor)
    await service_db.flush()

    channel = AlertChannel(
        owner_id=user.id,
        name="email",
        type=AlertChannelType.email,
        config={"to": "ops@x"},
    )
    service_db.add(channel)
    await service_db.flush()

    rule = AlertRule(
        id=uuid.uuid4(),
        owner_id=user.id,
        monitor_id=monitor.id,
        condition=AlertCondition.any_down,
        min_duration_seconds=0,
        digest_minutes=0,
        suppress_on_network_partition=suppress,
        channels=[channel],
    )
    service_db.add(rule)
    await service_db.flush()

    incident = Incident(
        monitor_id=monitor.id,
        started_at=datetime.now(UTC),
        scope=IncidentScope.geographic,
        affected_probe_ids=[],
        network_verdict=verdict,
    )
    service_db.add(incident)
    await service_db.flush()

    with patch(
        "whatisup.services.alert.dispatch_alert", new_callable=AsyncMock
    ) as mock_dispatch:
        await maybe_digest_or_dispatch(
            service_db,
            incident=incident,
            channel=channel,
            rule=rule,
            event_type="incident_opened",
            ctx={},
        )

    if expect_dispatch:
        mock_dispatch.assert_awaited_once()
    else:
        mock_dispatch.assert_not_awaited()
