"""V2 Global Health Engine — bulk opt-in migration (M5).

Idempotent: running it twice is safe — only monitors without an existing
``quorum_down`` SLO rule get one created, and only those still on the legacy
toggle get flipped.

Usage (inside the server container or a venv with the package installed):

    # Show what would happen, change nothing
    python -m scripts.migrate_to_health_engine --dry-run

    # Apply migration
    python -m scripts.migrate_to_health_engine

    # Restrict to a single monitor (UUID), useful for staged rollouts
    python -m scripts.migrate_to_health_engine --monitor-id <uuid>

Default rule created per monitor:
    quorum_down · 60% / 5 min · min 2 probes · cooldown 60s

To roll back, either:
    - Disable per-monitor: ``UPDATE monitors SET health_engine_enabled=false WHERE …``
    - Disable globally: set env ``LEGACY_INCIDENT_ENGINE=true`` and restart.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select
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


async def migrate(
    *, dry_run: bool, only_monitor: uuid.UUID | None = None
) -> dict[str, int]:
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
