"""V2-02-07 — Resolve the probe's outbound public IP.

The IP the probe sees as its egress (via api.ipify.org) may differ from the IP
the central server observes on the heartbeat (request.client.host). When they
diverge, an intermediate proxy / NAT / VPN is in the path — useful diagnostic
for "this AWS Frankfurt probe is actually exiting through a corporate VPN".

Resolution is best-effort + cached: at boot we try a small list of resolvers
and stash the first successful answer. Failure is non-fatal — heartbeat
proceeds with self_reported_ip = None.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Public, free, RFC-compliant echo services. Tried in order until one works.
# Plain-text endpoints (no JSON parsing required) — robust to schema changes.
_RESOLVER_URLS: tuple[str, ...] = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
)
_TIMEOUT_S = 4.0
_MAX_RETRIES = 2


_cached_ip: str | None = None
_resolved_once = False


async def _query_resolver(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await client.get(url, timeout=_TIMEOUT_S)
        if resp.status_code != 200:
            return None
        ip = resp.text.strip()
        # Sanity check: very loose. We accept anything that parses as IPv4/IPv6.
        # Strict validation lives server-side.
        if not ip or len(ip) > 45:
            return None
        return ip
    except (TimeoutError, httpx.HTTPError):
        return None


async def resolve_public_ip(force: bool = False) -> str | None:
    """
    Return the probe's outbound public IP, or None if all resolvers failed.

    Cached across calls. Pass ``force=True`` to bypass the cache.
    Never raises — callers should treat None as "unknown".
    """
    global _cached_ip, _resolved_once

    if not force and _resolved_once:
        return _cached_ip

    async with httpx.AsyncClient(follow_redirects=True) as client:
        for url in _RESOLVER_URLS:
            for attempt in range(1, _MAX_RETRIES + 1):
                ip = await _query_resolver(client, url)
                if ip:
                    _cached_ip = ip
                    _resolved_once = True
                    logger.info(
                        "public_ip_resolved",
                        ip=ip,
                        resolver=url,
                        attempt=attempt,
                    )
                    return ip
                # short backoff between retries on the same resolver
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(0.5 * attempt)

    _resolved_once = True
    _cached_ip = None
    logger.warning("public_ip_resolution_failed", resolvers_tried=len(_RESOLVER_URLS))
    return None


def reset_cache() -> None:
    """Test-only — drop the in-process cache."""
    global _cached_ip, _resolved_once
    _cached_ip = None
    _resolved_once = False
