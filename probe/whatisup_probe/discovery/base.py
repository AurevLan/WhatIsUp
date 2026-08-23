"""Base classes for the discovery source plugin system (plan D, D-1).

Mirrors ``checkers/base.py``: an abstract base + a registry keyed by
``source_type``, the same shape as the checker plugin system so a third
source (``dns_zone``, D-4) slots in the same way a new check type does.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiscoveredItem:
    """One service observed by a discovery source run.

    Deliberately thin — no ``normalized_target``: that canonical form is
    computed server-side (plan_discovery.md: "calculé côté serveur, ne jamais
    faire confiance à une forme canonique venue de la sonde"), so the probe
    has no reason to compute or carry one.
    """

    host: str
    port: int | None
    proto: str
    hints: dict[str, Any] = field(default_factory=dict)


class BaseDiscoverySource(ABC):
    """Abstract base for all discovery source plugins.

    Subclasses declare ``source_type`` (matching ``schemas/discovery.py``'s
    ``SourceType`` literal server-side) and implement ``capability_available``
    + ``run``.
    """

    source_type: str = ""

    @abstractmethod
    async def capability_available(self) -> bool:
        """Whether this probe can currently run this source kind.

        Reported to the server at every heartbeat (``discovery_capabilities``)
        and re-checked before each scheduled run — a capability that
        disappears between two heartbeats (socket unmounted, etc.) must make
        the run skip cleanly, not crash.
        """
        ...

    @abstractmethod
    async def run(self, params: dict[str, Any]) -> list[DiscoveredItem]:
        """Execute one discovery run and return the full current snapshot.

        Full snapshot per call (decision D-0-3), not a delta — the server
        diffs against what it already has. Must never raise for expected
        failure modes (socket unreachable, scan timeout): return ``[]`` and
        let the caller log instead, so one broken source doesn't take down
        the scheduler loop.
        """
        ...
