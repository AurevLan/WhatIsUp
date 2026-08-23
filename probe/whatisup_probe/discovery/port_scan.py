"""Port-scan discovery source — bounded TCP connect scan (plan D, D-1).

TCP connect scan only: no raw SYN sockets (would need CAP_NET_RAW), no UDP,
no banner grabbing or application-level probing — an open port is the whole
signal this lot reports (plan_discovery.md § Hors périmètre / Sécurité).

The server already bounds ``params`` at creation time (``cidr`` <= /24 IPv4,
explicit ``ports`` list, see ``schemas/discovery.py``), but this module
re-checks both here — a stored source's params could in principle be edited
between validation passes, and the probe is the last line of defense before
an actual socket gets opened. Every candidate IP is additionally run through
the probe's own SSRF pinning helper: a declared CIDR does not get to
override "never connect to loopback/link-local/metadata" (same posture as
every other checker, see CLAUDE.md § Sécurité).
"""

from __future__ import annotations

import asyncio
import ipaddress
from typing import Any

import structlog

from whatisup_probe.checkers._shared import SSRFBlockedError, _ssrf_resolve_pinned_sync

from .base import BaseDiscoverySource, DiscoveredItem

logger = structlog.get_logger(__name__)

#: A /24 (256 addresses) is the largest network this source will ever scan —
#: mirrors `_MIN_PORT_SCAN_PREFIXLEN` in server/whatisup/schemas/discovery.py.
_MIN_PREFIXLEN = 24
#: Mirrors `_MAX_PORTS` in server/whatisup/schemas/discovery.py.
_MAX_PORTS = 64
_CONCURRENCY = 20
_CONNECT_TIMEOUT = 1.5


class PortScanDiscoverySource(BaseDiscoverySource):
    source_type = "port_scan"

    async def capability_available(self) -> bool:
        # Plain TCP connect via asyncio — no special OS resource, privilege,
        # or optional binary required, unlike the Docker socket.
        return True

    async def run(self, params: dict[str, Any]) -> list[DiscoveredItem]:
        cidr = params.get("cidr")
        ports = params.get("ports") or []
        if not cidr or not ports:
            logger.warning("discovery_port_scan_missing_params", cidr=cidr, ports=ports)
            return []

        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            logger.warning("discovery_port_scan_invalid_cidr", cidr=cidr)
            return []

        if network.version != 4 or network.prefixlen < _MIN_PREFIXLEN:
            logger.warning("discovery_port_scan_cidr_too_large", cidr=cidr)
            return []

        # Same posture as the cidr checks above: params come from our own
        # server, which enforced these exact rules at creation — a blob that
        # violates them here means tampering, so refuse the whole run rather
        # than scan a best-effort subset.
        if len(ports) > _MAX_PORTS:
            logger.warning("discovery_port_scan_too_many_ports", count=len(ports))
            return []
        try:
            port_ints = [int(port) for port in ports]
        except (TypeError, ValueError):
            logger.warning("discovery_port_scan_invalid_ports", ports=ports)
            return []
        if any(not (1 <= port <= 65535) for port in port_ints):
            logger.warning("discovery_port_scan_port_out_of_range", ports=ports)
            return []

        semaphore = asyncio.Semaphore(_CONCURRENCY)
        tasks = [
            self._probe_one(str(ip), port, semaphore)
            for ip in network.hosts()
            for port in port_ints
        ]
        if not tasks:
            return []
        results = await asyncio.gather(*tasks)
        return [item for item in results if item is not None]

    async def _probe_one(
        self, ip: str, port: int, semaphore: asyncio.Semaphore
    ) -> DiscoveredItem | None:
        async with semaphore:
            try:
                # `ip` is always a literal here (from `network.hosts()`), so
                # this resolves synchronously without a real DNS round-trip —
                # it only exists to reject loopback/link-local/metadata even
                # when the declared CIDR technically covers them.
                pinned_ip = _ssrf_resolve_pinned_sync(ip)
            except SSRFBlockedError as exc:
                logger.warning("discovery_port_scan_ip_blocked", ip=ip, reason=str(exc))
                return None

            writer = None
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection(pinned_ip, port), timeout=_CONNECT_TIMEOUT
                )
            except (TimeoutError, OSError):
                return None
            finally:
                if writer is not None:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except OSError:
                        pass

            return DiscoveredItem(host=ip, port=port, proto="tcp", hints={})


def setup(register: Any) -> None:
    register(PortScanDiscoverySource())
