"""DNS-zone discovery source — AXFR against a declared resolver (plan D, D-4).

Decision D-0-2: "AXFR ou liste d'enregistrements via résolveur déclaré". This
module only does the AXFR half — a zone transfer against a resolver the
operator names explicitly (an IP literal, validated server-side in
``schemas/discovery.py::_DnsZoneParams``, never a hostname: the resolver
*is* the declared target, picking one at run time from a hostname would
defeat the point). A resolver that refuses the transfer (most public
resolvers do, by design — AXFR is meant for secondaries) yields an empty
snapshot and a warning log. There is deliberately no fallback to a record
guess-and-scan: an operator who wants ``dns_zone`` must actually be able to
transfer the zone, the same way ``port_scan`` doesn't fall back to "guess
some ports" when its bounds are violated.

``dnspython`` is already an unconditional dependency of the probe (the
``dns`` checker uses it) — no new dependency, no optional extra.
"""

from __future__ import annotations

from typing import Any

import structlog

from whatisup_probe.checkers._shared import SSRFBlockedError, _ssrf_resolve_pinned_sync

from .base import BaseDiscoverySource, DiscoveredItem

logger = structlog.get_logger(__name__)

#: Same cap philosophy as `port_scan`'s /24 + 64-port bound
#: (plan_discovery.md § Sécurité: "cap d'enregistrements traités côté sonde") —
#: a misconfigured or hostile zone must not turn one AXFR into an unbounded
#: payload.
_MAX_RECORDS = 500

#: Record types this source knows how to turn into a `DiscoveredItem` —
#: mirrors `schemas/discovery.py::_DnsZoneParams`'s own default. Kept as an
#: independent constant rather than imported from the server package: the
#: probe never imports server code (separate deployables, separate
#: processes).
_DEFAULT_RECORD_TYPES = ("A", "AAAA", "CNAME")

#: AXFR is TCP and can be slow on a large zone, but this is still a
#: background inventory job, not a liveness check — bounded, not generous.
_AXFR_TIMEOUT = 10.0

#: Standard DNS port. Not a param: a resolver reachable only on a
#: non-standard port is not "a resolver declared for AXFR" in any normal
#: deployment, and adding a knob for it would just be more surface to
#: validate for no real use case.
_AXFR_PORT = 53


class DnsZoneDiscoverySource(BaseDiscoverySource):
    source_type = "dns_zone"

    async def capability_available(self) -> bool:
        """`dnspython` is an unconditional dependency, so this is only ever
        `False` on a broken/partial install — same defensive posture as the
        docker source checking its socket rather than assuming it's there."""
        try:
            import dns.query  # noqa: F401
            import dns.zone  # noqa: F401
        except ImportError:
            return False
        return True

    async def run(self, params: dict[str, Any]) -> list[DiscoveredItem]:
        import asyncio

        zone_name = params.get("zone")
        resolver = params.get("resolver")
        record_types = params.get("record_types") or list(_DEFAULT_RECORD_TYPES)
        if not zone_name or not resolver:
            logger.warning("discovery_dns_zone_missing_params", zone=zone_name, resolver=resolver)
            return []

        try:
            # `resolver` is validated server-side as an IP literal — this is
            # defense in depth, same posture as `port_scan` re-checking
            # bounds the server already enforced. Never blocking: an IP
            # literal short-circuits before any real DNS round-trip.
            pinned_ip = _ssrf_resolve_pinned_sync(resolver)
        except SSRFBlockedError as exc:
            logger.warning(
                "discovery_dns_zone_resolver_blocked", resolver=resolver, reason=str(exc)
            )
            return []

        loop = asyncio.get_running_loop()
        try:
            # AXFR is blocking TCP I/O (dnspython has no async transfer API)
            # — run it in the default executor, never on the event loop
            # thread. `_fetch_zone` already contains its own failures; this
            # outer guard is defense in depth so a broken source can never
            # take the scheduler job down (`BaseDiscoverySource.run`'s
            # contract), even if that inner contract is ever violated.
            zone = await loop.run_in_executor(None, _fetch_zone, pinned_ip, zone_name)
        except Exception as exc:  # noqa: BLE001 — see comment above
            logger.warning("discovery_dns_zone_run_failed", zone=zone_name, error=str(exc))
            return []
        if zone is None:
            return []  # refusal/timeout/parse failure already logged by _fetch_zone

        return _zone_to_items(zone, set(record_types))


def _fetch_zone(resolver_ip: str, zone_name: str):
    """Blocking AXFR — run via executor, never on the event loop.

    Returns ``None`` on any failure (refused transfer, timeout, malformed
    response, missing SOA/NS...) rather than raising: a broken/uncooperative
    resolver is an expected outcome here, not a bug, and must not crash the
    scheduler loop (same posture as every other discovery source's ``run``).
    """
    import dns.query
    import dns.zone

    try:
        # `relativize=False` throughout: keeps every name in the resulting
        # zone absolute (node keys *and* name-valued rdata like a CNAME's
        # target), so `_zone_to_items` can read them straight off without
        # reconstructing the absolute form against `zone.origin` itself.
        xfr = dns.query.xfr(
            resolver_ip,
            zone_name,
            timeout=_AXFR_TIMEOUT,
            lifetime=_AXFR_TIMEOUT,
            port=_AXFR_PORT,
            relativize=False,
        )
        return dns.zone.from_xfr(xfr, relativize=False)
    except Exception as exc:  # noqa: BLE001 — see docstring: refusal is expected, not exceptional
        logger.warning(
            "discovery_dns_zone_axfr_failed", zone=zone_name, resolver=resolver_ip, error=str(exc)
        )
        return None


def _zone_to_items(zone, wanted_types: set[str]) -> list[DiscoveredItem]:
    """Pure parsing step, deliberately separate from `_fetch_zone` — a zone
    built with `dns.zone.from_text(..., relativize=False)` in a test exercises
    this exact function with no mocking of dnspython's transfer internals
    required. Assumes ``zone`` was built with ``relativize=False`` (see
    `_fetch_zone`), so every name — node keys and name-valued rdata alike —
    is already absolute."""
    import dns.rdatatype

    items: list[DiscoveredItem] = []
    for name, node in zone.nodes.items():
        if len(items) >= _MAX_RECORDS:
            break
        host = str(name).rstrip(".").lower()
        if not host:
            continue
        for rdataset in node.rdatasets:
            record_type = dns.rdatatype.to_text(rdataset.rdtype)
            if record_type not in wanted_types:
                continue
            for rdata in rdataset:
                if len(items) >= _MAX_RECORDS:
                    break
                value = str(rdata).rstrip(".")
                items.append(
                    DiscoveredItem(
                        host=host,
                        port=None,
                        proto="tcp",
                        hints={"record_type": record_type, "value": value},
                    )
                )

    return items


def setup(register: Any) -> None:
    register(DnsZoneDiscoverySource())
