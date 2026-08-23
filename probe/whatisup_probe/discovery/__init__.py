"""Discovery source plugin system — registry and dispatch (plan D, D-1).

Mirrors ``checkers/__init__.py``: built-in sources auto-register on import,
keyed by ``source_type``.

Usage::

    from whatisup_probe.discovery import run_source, capability_report, REGISTRY
"""

from __future__ import annotations

import structlog

from .base import BaseDiscoverySource, DiscoveredItem

logger = structlog.get_logger(__name__)

# ── Registry ──────────────────────────────────────────────────────────────────

REGISTRY: dict[str, BaseDiscoverySource] = {}


def register(source: BaseDiscoverySource) -> BaseDiscoverySource:
    """Register a discovery source instance under its ``source_type``."""
    REGISTRY[source.source_type] = source
    return source


def _load_builtins() -> None:
    from . import dns_zone, docker, port_scan

    for module in (docker, port_scan, dns_zone):
        module.setup(register)


_load_builtins()


# ── Dispatch ──────────────────────────────────────────────────────────────────


async def run_source(source_type: str, params: dict) -> list[DiscoveredItem]:
    """Run one discovery source by type. Unknown types return an empty snapshot
    (logged) rather than raising — a server-side type this probe build
    predates must not crash the scheduler loop."""
    source = REGISTRY.get(source_type)
    if source is None:
        logger.warning("discovery_unknown_source_type", source_type=source_type)
        return []
    return await source.run(params)


async def capability_report() -> dict[str, bool]:
    """``{source_type: capability_available()}`` for every registered source.

    Sent (filtered to the ``True`` entries) as ``discovery_capabilities`` in
    the heartbeat request, and used locally to decide which distributed
    sources actually get scheduled (cf. ``scheduler.sync_monitors``).
    """
    report: dict[str, bool] = {}
    for source_type, source in REGISTRY.items():
        try:
            report[source_type] = await source.capability_available()
        except Exception as exc:  # noqa: BLE001 — a broken probe must not crash the heartbeat
            logger.warning(
                "discovery_capability_check_failed", source_type=source_type, error=str(exc)
            )
            report[source_type] = False
    return report


__all__ = [
    "BaseDiscoverySource",
    "DiscoveredItem",
    "REGISTRY",
    "register",
    "run_source",
    "capability_report",
]
