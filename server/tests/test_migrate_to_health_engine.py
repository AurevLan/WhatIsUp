"""Tests for the plan Cap v2 4b data migration helper.

``provision_missing_health_engine_coverage`` is the exact function the
Alembic migration ``h2i3j4k5l6m7`` (retire the legacy per-probe decider)
calls in its ``upgrade()`` — see that module's docstring for why it's written
against SQLAlchemy Core ``Table`` objects rather than raw SQL (dialect
portability, correct Postgres enum binding for ``rule_type``). Exercised here
through ``AsyncConnection.run_sync``, the same idiom ``tests/conftest.py``
already uses for ``Base.metadata.create_all``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.monitor_health import SLORule, SLORuleType
from whatisup.models.user import User
from whatisup.scripts.migrate_to_health_engine import provision_missing_health_engine_coverage


async def _run(db: AsyncSession) -> int:
    conn = await db.connection()
    return await conn.run_sync(provision_missing_health_engine_coverage)


async def _active_rules(db: AsyncSession, monitor_id) -> list[SLORule]:
    return list(
        (
            await db.execute(
                select(SLORule).where(
                    SLORule.monitor_id == monitor_id,
                    SLORule.enabled.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_migrates_monitor_with_no_active_rule(
    service_db: AsyncSession, test_user: User
) -> None:
    monitor = Monitor(
        name="legacy-mon",
        url="http://legacy.example.com",
        owner_id=test_user.id,
        health_engine_enabled=False,
    )
    service_db.add(monitor)
    await service_db.flush()

    migrated = await _run(service_db)
    assert migrated == 1

    await service_db.refresh(monitor)
    assert monitor.health_engine_enabled is True

    rules = await _active_rules(service_db, monitor.id)
    assert len(rules) == 1
    rule = rules[0]
    assert rule.rule_type == SLORuleType.quorum_down
    assert rule.min_probes == 1
    assert rule.quorum_ratio == 0.6
    assert rule.window_seconds == 300
    assert rule.cooldown_seconds == 60


@pytest.mark.asyncio
async def test_does_not_duplicate_an_existing_active_rule(
    service_db: AsyncSession, test_user: User
) -> None:
    """A monitor already carrying a hand-configured active rule (e.g.
    quorum_slow, set up before the flag was ever flipped) must not get a
    second, duplicate quorum_down rule — just the flag flip."""
    monitor = Monitor(
        name="custom-rule-mon",
        url="http://custom.example.com",
        owner_id=test_user.id,
        health_engine_enabled=False,
    )
    service_db.add(monitor)
    await service_db.flush()

    existing_rule = SLORule(
        monitor_id=monitor.id,
        rule_type=SLORuleType.quorum_slow,
        enabled=True,
        p95_threshold_ms=2000,
        window_seconds=300,
        min_probes=1,
        cooldown_seconds=60,
    )
    service_db.add(existing_rule)
    await service_db.flush()

    migrated = await _run(service_db)
    assert migrated == 1

    await service_db.refresh(monitor)
    assert monitor.health_engine_enabled is True

    rules = await _active_rules(service_db, monitor.id)
    assert len(rules) == 1
    assert rules[0].id == existing_rule.id


@pytest.mark.asyncio
async def test_leaves_an_already_migrated_monitor_untouched(
    service_db: AsyncSession, test_user: User
) -> None:
    monitor = Monitor(
        name="already-on-mon",
        url="http://already.example.com",
        owner_id=test_user.id,
        health_engine_enabled=True,
    )
    service_db.add(monitor)
    await service_db.flush()

    migrated = await _run(service_db)
    assert migrated == 0
    assert await _active_rules(service_db, monitor.id) == []


@pytest.mark.asyncio
async def test_idempotent_two_passes_same_state(service_db: AsyncSession, test_user: User) -> None:
    monitor = Monitor(
        name="idempotent-mon",
        url="http://idempotent.example.com",
        owner_id=test_user.id,
        health_engine_enabled=False,
    )
    service_db.add(monitor)
    await service_db.flush()

    first = await _run(service_db)
    second = await _run(service_db)

    assert first == 1
    assert second == 0

    await service_db.refresh(monitor)
    assert monitor.health_engine_enabled is True
    assert len(await _active_rules(service_db, monitor.id)) == 1


@pytest.mark.asyncio
async def test_never_leaves_a_migrated_monitor_without_an_active_rule(
    service_db: AsyncSession, test_user: User
) -> None:
    """Contract named after the plan's own invariant: flipping the flag and
    provisioning the rule happen together, for every affected monitor."""
    monitors = [
        Monitor(
            name=f"fleet-{i}",
            url=f"http://fleet-{i}.example.com",
            owner_id=test_user.id,
            health_engine_enabled=False,
        )
        for i in range(3)
    ]
    service_db.add_all(monitors)
    await service_db.flush()

    await _run(service_db)

    for monitor in monitors:
        await service_db.refresh(monitor)
        assert monitor.health_engine_enabled is True
        assert len(await _active_rules(service_db, monitor.id)) >= 1
