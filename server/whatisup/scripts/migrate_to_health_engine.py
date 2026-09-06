"""V2 Global Health Engine — bulk opt-in migration (M5).

Idempotent: running it twice is safe — only monitors without an existing
``quorum_down`` SLO rule get one created, and only those still on the legacy
toggle get flipped.

Usage (inside the server container or a venv with the package installed):

    # Show what would happen, change nothing
    python -m whatisup.scripts.migrate_to_health_engine --dry-run

    # Apply migration
    python -m whatisup.scripts.migrate_to_health_engine

    # Restrict to a single monitor (UUID), useful for staged rollouts
    python -m whatisup.scripts.migrate_to_health_engine --monitor-id <uuid>

Default rule created per monitor:
    quorum_down · 60% / 5 min · min 2 probes · cooldown 60s

To roll back: disable per-monitor with ``UPDATE monitors SET
health_engine_enabled=false WHERE …``. There is no global rollback flag any
more (``LEGACY_INCIDENT_ENGINE`` retired in plan Cap v2 4b along with the
per-probe decider it short-circuited to) — disabling a monitor here now
leaves it with no detection at all unless you also keep a matching active
``SLORule``, see ``provision_missing_health_engine_coverage`` below for the
migration invariant this tool no longer enforces alone.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.database import get_session_factory
from whatisup.models.monitor import Monitor
from whatisup.models.monitor_health import SLORule, SLORuleType

DEFAULT_RULE_KWARGS = {
    "rule_type": SLORuleType.quorum_down,
    "enabled": True,
    "quorum_ratio": 0.6,
    "window_seconds": 300,
    "min_probes": 2,
    "cooldown_seconds": 60,
}


def provision_missing_health_engine_coverage(bind) -> int:
    """Flip ``health_engine_enabled`` + backfill a default ``SLORule`` for
    every monitor still stuck on the retired legacy per-probe decider (plan
    Cap v2 4b).

    Runs against a plain synchronous ``Connection`` — Alembic's
    ``op.get_bind()`` in production, or a SQLite connection borrowed via
    ``AsyncConnection.run_sync()`` in tests (same idiom as
    ``Base.metadata.create_all`` in ``tests/conftest.py``) — using the ORM's
    mapped ``Table`` objects rather than raw SQL. That matters specifically
    for ``rule_type``: it's a native Postgres enum, and only a Core insert
    against the *typed* ``SLORule.__table__`` column gets it bound correctly;
    an untyped ``sa.table()`` would hand the driver a plain string the server
    rejects with "column is of type slo_rule_type but expression is of type
    text". This dialect-agnostic path is what lets this exact function run
    unit-tested against SQLite and unmodified against Postgres in prod.

    Idempotent and never leaves a monitor uncovered:
    - A monitor already on ``health_engine_enabled=True`` is left untouched
      (a second run over an already-migrated fleet is a no-op).
    - A monitor that already carries *any* active ``SLORule`` (someone may
      have hand-configured ``quorum_slow`` before flipping the flag — or this
      function ran once already) does not get a duplicate ``quorum_down``.
    - ``min_probes=1`` here, not ``DEFAULT_RULE_KWARGS``' 2 (crud.py's
      MonitorCreate path made the same call in plan Cap v2 4a) — a
      single-probe install must not go blind the moment its last monitor is
      migrated off the legacy decider.

    Returns the number of monitors migrated.
    """
    monitors_table = Monitor.__table__
    slo_table = SLORule.__table__

    monitor_ids = (
        bind.execute(
            select(monitors_table.c.id).where(monitors_table.c.health_engine_enabled.is_(False))
        )
        .scalars()
        .all()
    )
    if not monitor_ids:
        return 0

    covered = set(
        bind.execute(
            select(slo_table.c.monitor_id).where(
                slo_table.c.monitor_id.in_(monitor_ids),
                slo_table.c.enabled.is_(True),
            )
        )
        .scalars()
        .all()
    )

    now = datetime.now(UTC)
    to_create = [
        {
            "id": uuid.uuid4(),
            "created_at": now,
            "updated_at": now,
            "monitor_id": monitor_id,
            **DEFAULT_RULE_KWARGS,
            "min_probes": 1,
        }
        for monitor_id in monitor_ids
        if monitor_id not in covered
    ]
    if to_create:
        bind.execute(insert(slo_table), to_create)

    bind.execute(
        update(monitors_table)
        .where(monitors_table.c.health_engine_enabled.is_(False))
        .values(health_engine_enabled=True)
    )
    return len(monitor_ids)


async def _ensure_quorum_rule(db: AsyncSession, monitor_id: uuid.UUID) -> bool:
    """Create the default quorum_down rule if none exists. Returns True if created."""
    existing = (
        await db.execute(
            select(SLORule.id).where(
                SLORule.monitor_id == monitor_id,
                SLORule.rule_type == SLORuleType.quorum_down,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False
    db.add(SLORule(monitor_id=monitor_id, **DEFAULT_RULE_KWARGS))
    return True


async def migrate(*, dry_run: bool, only_monitor: uuid.UUID | None = None) -> dict[str, int]:
    stats = {"checked": 0, "rules_created": 0, "toggles_flipped": 0}
    factory = get_session_factory()
    async with factory() as db:
        query = select(Monitor)
        if only_monitor is not None:
            query = query.where(Monitor.id == only_monitor)
        monitors = (await db.execute(query)).scalars().all()
        for m in monitors:
            stats["checked"] += 1
            would_create_rule = (
                await db.execute(
                    select(SLORule.id).where(
                        SLORule.monitor_id == m.id,
                        SLORule.rule_type == SLORuleType.quorum_down,
                    )
                )
            ).scalar_one_or_none() is None
            would_flip = not m.health_engine_enabled
            if would_create_rule:
                stats["rules_created"] += 1
            if would_flip:
                stats["toggles_flipped"] += 1
            print(
                f"  - {m.name} ({m.id}): "
                f"rule={'create' if would_create_rule else 'keep'} "
                f"toggle={'flip→on' if would_flip else 'keep'}"
            )
            if not dry_run:
                if would_create_rule:
                    await _ensure_quorum_rule(db, m.id)
                if would_flip:
                    m.health_engine_enabled = True
        if not dry_run:
            await db.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print actions, change nothing")
    parser.add_argument("--monitor-id", type=str, help="Restrict to a single monitor UUID")
    args = parser.parse_args()

    only = uuid.UUID(args.monitor_id) if args.monitor_id else None
    stats = asyncio.run(migrate(dry_run=args.dry_run, only_monitor=only))
    print()
    print(f"checked: {stats['checked']}")
    print(f"rules to create: {stats['rules_created']}")
    print(f"toggles to flip: {stats['toggles_flipped']}")
    if args.dry_run:
        print("(dry run — nothing was written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
