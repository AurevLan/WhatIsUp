"""Sticky probe election for group-targeted discovery sources (plan E, E-2 / E-0-2).

A ``docker`` source targeting a ``ProbeGroup`` fans out to every capable
member — no election needed, the cross-push dedup on ``DiscoveredService``
already handles the overlap. ``port_scan``/``dns_zone`` sources scan the
network from one vantage point, so exactly one group member must run them:
this module "sticks" that choice on ``DiscoverySource.elected_probe_id`` so
an unrelated heartbeat or a routine restart doesn't bounce a port scan around
the network, and only re-elects when the current pick genuinely stops being
usable — dead heartbeat, dropped from the group, or capability withdrawn.

Not a distributed lock (plan_discovery_ergo.md, E-0-2): two replicas racing
this loop could each land on a different probe for one tick, and a stale
election simply costs one missed scan cycle, never an incident. Run from the
leader-elected background loop (``core/leader.py``) so only one replica
normally evaluates it, but correctness never depends on that being true —
`elect_for_source` is idempotent and safe to call from anywhere (also called
synchronously by `api/v1/discovery.py` right after creating/retargeting a
group source, so the UI doesn't wait up to a full loop interval for a first
pick).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.models.discovery import DiscoverySource
from whatisup.models.probe import Probe
from whatisup.models.probe_group import ProbeGroup

logger = structlog.get_logger(__name__)

#: Only these source types are ever routed to a single elected probe (see
#: module docstring) — `docker` fans out and never carries `elected_probe_id`.
ELECTABLE_SOURCE_TYPES = ("port_scan", "dns_zone")


def _is_probe_alive(probe: Probe, now: datetime) -> bool:
    """Same "interval + grace" shape as `services/heartbeat.py`'s overdue
    check, applied to a probe's own heartbeat cadence rather than a
    monitor's ping."""
    if probe.last_seen_at is None:
        return False
    settings = get_settings()
    deadline = probe.last_seen_at + timedelta(
        seconds=settings.probe_heartbeat_interval_seconds
        + settings.discovery_election_grace_seconds
    )
    return now <= deadline


def _capable_probes(group: ProbeGroup, source_type: str, now: datetime) -> list[Probe]:
    """Candidates for election, in a deterministic order — sticky election
    must be reproducible, not "whichever order the ORM happened to return"."""
    return sorted(
        (
            p
            for p in group.probes
            if p.is_active
            and source_type in (p.discovery_capabilities or [])
            and _is_probe_alive(p, now)
        ),
        key=lambda p: str(p.id),
    )


async def elect_for_source(db: AsyncSession, source: DiscoverySource, now: datetime) -> None:
    """(Re-)elect ``source.elected_probe_id`` in place. Caller commits/flushes.

    A no-op for anything that isn't a group-targeted, electable source type —
    callers may pass any `DiscoverySource` without pre-filtering.
    """
    if source.probe_group_id is None or source.source_type not in ELECTABLE_SOURCE_TYPES:
        return

    # `db.get()` short-circuits on the identity map and would return a
    # `ProbeGroup` whose `.probes` (lazy="selectin") was never actually
    # populated by a query — the eager loader only fires when a `select()` is
    # executed, not on a pure primary-key cache hit. A real `select()` here
    # guarantees `.probes` is loaded, whether or not the instance was already
    # cached.
    group = (
        await db.execute(select(ProbeGroup).where(ProbeGroup.id == source.probe_group_id))
    ).scalar_one_or_none()
    if group is None:
        # Defensive only — `probe_group_id` is CASCADE, so the source would
        # have been deleted along with its group.
        source.elected_probe_id = None
        return

    candidates = _capable_probes(group, source.source_type, now)
    candidate_ids = {p.id for p in candidates}

    if source.elected_probe_id is not None and source.elected_probe_id in candidate_ids:
        return  # sticky: the current pick is still capable and alive — keep it

    previous = source.elected_probe_id
    source.elected_probe_id = candidates[0].id if candidates else None
    if previous != source.elected_probe_id:
        logger.info(
            "discovery_source_elected",
            source_id=str(source.id),
            probe_group_id=str(source.probe_group_id),
            previous_probe_id=str(previous) if previous else None,
            elected_probe_id=(str(source.elected_probe_id) if source.elected_probe_id else None),
        )


async def run_discovery_elections(db: AsyncSession, *, now: datetime | None = None) -> int:
    """Evaluate every enabled, group-targeted, electable source.

    Returns how many elections actually changed (0 is the common case — most
    ticks find every sticky pick still alive and capable).

    Capped per tick (``discovery_election_max_sources_per_run``), ordered
    with never-yet-elected sources first (then ``id`` for determinism within
    each group). Unlike a ``next_fire_at``-style backlog, this query has no
    timestamp that naturally advances — every enabled electable source is
    "due" every tick — so a plain ``id`` order would let a fleet bigger than
    the cap starve the *same* tail forever. Prioritizing
    ``elected_probe_id IS NULL`` first gives real progress instead: a source
    that has never scanned at all outranks one that's merely due for a
    sticky-election recheck, and once elected it sorts behind whatever is
    still unelected — so a chronic excess drains one cap's worth of "new"
    sources per tick rather than only ever confirming the same head of the
    list.
    """
    now = now or datetime.now(UTC)
    settings = get_settings()
    max_per_run = settings.discovery_election_max_sources_per_run

    sources = (
        (
            await db.execute(
                select(DiscoverySource)
                .where(
                    DiscoverySource.probe_group_id.is_not(None),
                    DiscoverySource.source_type.in_(ELECTABLE_SOURCE_TYPES),
                    DiscoverySource.enabled.is_(True),
                )
                .order_by(DiscoverySource.elected_probe_id.is_not(None), DiscoverySource.id)
                .limit(max_per_run)
            )
        )
        .scalars()
        .all()
    )
    if len(sources) >= max_per_run:
        logger.warning(
            "discovery_election_run_capped",
            max_per_run=max_per_run,
            hint="more electable sources than the per-tick cap — remainder deferred",
        )
    changed = 0
    for source in sources:
        before = source.elected_probe_id
        await elect_for_source(db, source, now)
        if source.elected_probe_id != before:
            changed += 1
    await db.commit()
    return changed


async def check_discovery_elections() -> None:
    """Background-loop entry point (see lifespan in main.py)."""
    from whatisup.core.database import get_session_factory

    async with get_session_factory()() as db:
        await run_discovery_elections(db)
