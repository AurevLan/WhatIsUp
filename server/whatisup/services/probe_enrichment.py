"""V2-02-01 — Probe ASN/IP enrichment.

Resolves the public IP of a probe (typically learned from the request client at
heartbeat time) to ASN + AS-name via Team Cymru's free DNS service.

Cymru protocol (https://team-cymru.com/community-services/ip-asn-mapping/):
  1. Reverse the IP octets, append ".origin.asn.cymru.com" → query TXT
     Example: 8.8.8.8 -> 8.8.8.8.origin.asn.cymru.com TXT
              "15169 | 8.8.8.0/24 | US | arin | 1992-12-01"
  2. Take the AS number (first field), then query "AS<N>.asn.cymru.com" TXT
     Example: AS15169.asn.cymru.com TXT
              "15169 | US | arin | 2000-03-30 | GOOGLE, US"

Both queries are async (dnspython). Lookups are best-effort: any failure leaves
the probe's ASN columns null and is logged as a warning.

Refresh policy:
  - On each successful probe heartbeat, if asn_updated_at is null OR older than
    settings.asn_refresh_hours, schedule a background lookup.
  - A nightly task (refresh_stale_probes) re-enriches probes whose data has
    aged out, in case heartbeats are sparse.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.core.config import get_settings
from whatisup.models.probe import Probe

logger = structlog.get_logger(__name__)

_CYMRU_LOOKUP_TIMEOUT_S = 3.0
_CYMRU_BACKEND = "cymru"
_DISABLED_BACKEND = "disabled"


@dataclass(frozen=True)
class AsnInfo:
    asn: int
    asn_name: str | None
    country: str | None = None


def is_public_ip(ip: str) -> bool:
    """Return True if ip is a globally routable address (not RFC1918, loopback…)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


def _cymru_origin_query(ip: str) -> str:
    """Build the Cymru origin lookup name (reversed octets for IPv4 only here)."""
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address):
        # IPv6 reverse representation à la cymru = nibbles + .origin6.asn.cymru.com
        nibbles = ".".join(reversed(addr.exploded.replace(":", "")))
        return f"{nibbles}.origin6.asn.cymru.com"
    reversed_octets = ".".join(reversed(str(addr).split(".")))
    return f"{reversed_octets}.origin.asn.cymru.com"


def _parse_cymru_origin_txt(txt: str) -> tuple[int | None, str | None]:
    """Parse 'AS | prefix | country | registry | allocated' into (asn, country)."""
    parts = [p.strip().strip('"') for p in txt.split("|")]
    if not parts or not parts[0].isdigit():
        return None, None
    asn = int(parts[0])
    country = parts[2] if len(parts) > 2 else None
    return asn, country


def _parse_cymru_asn_txt(txt: str) -> str | None:
    """Parse 'AS | country | registry | allocated | name' into AS name."""
    parts = [p.strip().strip('"') for p in txt.split("|")]
    if len(parts) >= 5:
        return parts[4] or None
    return None


async def lookup_asn(ip: str) -> AsnInfo | None:
    """
    Resolve `ip` to AS info via the configured backend.
    Returns None on any failure or if the backend is disabled.
    """
    settings = get_settings()
    backend = settings.asn_lookup_provider.lower()
    if backend == _DISABLED_BACKEND:
        return None
    if backend != _CYMRU_BACKEND:
        logger.warning("asn_lookup_unknown_backend", backend=backend)
        return None
    if not is_public_ip(ip):
        return None
    return await _lookup_via_cymru(ip)


async def _lookup_via_cymru(ip: str) -> AsnInfo | None:
    try:
        import dns.asyncresolver
        import dns.exception
    except ImportError:
        logger.warning("asn_lookup_dnspython_missing")
        return None

    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = _CYMRU_LOOKUP_TIMEOUT_S
    resolver.timeout = _CYMRU_LOOKUP_TIMEOUT_S

    origin_name = _cymru_origin_query(ip)
    try:
        answer = await resolver.resolve(origin_name, "TXT")
    except (TimeoutError, dns.exception.DNSException) as exc:
        logger.info("asn_lookup_origin_failed", ip=ip, error_type=type(exc).__name__)
        return None

    asn: int | None = None
    country: str | None = None
    for rdata in answer:
        for txt_bytes in rdata.strings:
            asn, country = _parse_cymru_origin_txt(txt_bytes.decode("ascii", errors="replace"))
            if asn is not None:
                break
        if asn is not None:
            break

    if asn is None:
        return None

    asn_name: str | None = None
    try:
        name_answer = await resolver.resolve(f"AS{asn}.asn.cymru.com", "TXT")
    except (TimeoutError, dns.exception.DNSException):
        # AS-name lookup is optional; we already have the ASN
        return AsnInfo(asn=asn, asn_name=None, country=country)

    for rdata in name_answer:
        for txt_bytes in rdata.strings:
            asn_name = _parse_cymru_asn_txt(txt_bytes.decode("ascii", errors="replace"))
            if asn_name:
                break
        if asn_name:
            break

    return AsnInfo(asn=asn, asn_name=asn_name, country=country)


async def enrich_probe(db: AsyncSession, probe: Probe, public_ip: str) -> bool:
    """
    Update ``probe`` with ASN data resolved from ``public_ip``.

    Returns True if the probe was updated (DB modified, caller must flush/commit),
    False otherwise (lookup failed, IP private, backend disabled). Idempotent.
    """
    if not is_public_ip(public_ip):
        return False

    info = await lookup_asn(public_ip)
    now = datetime.now(UTC)

    # Even if the lookup failed, persist the IP we observed so we can retry next
    # cycle without re-resolving on every heartbeat.
    if probe.public_ip != public_ip:
        probe.public_ip = public_ip

    if info is None:
        # Mark as attempted to avoid retrying on every heartbeat.
        probe.asn_updated_at = now
        return True

    probe.asn = info.asn
    probe.asn_name = info.asn_name
    probe.asn_updated_at = now
    logger.info(
        "asn_enriched",
        probe_id=str(probe.id),
        ip=public_ip,
        asn=info.asn,
        asn_name=info.asn_name,
    )
    return True


async def maybe_enrich_on_heartbeat(
    db: AsyncSession,
    probe: Probe,
    request_client_host: str | None,
    self_reported_ip: str | None = None,
) -> None:
    """
    Called from the probe heartbeat handler. Skips lookup if data is fresh enough.

    V2-02-01 — enriches ``probe.public_ip`` from the IP we observed
    (``request.client.host``) and resolves its ASN.

    V2-02-07 — additionally records ``probe.self_reported_ip`` (the egress IP
    the probe sees on itself) and resolves its ASN, so the UI can flag
    proxy/NAT/VPN setups where the two diverge.

    Never raises — enrichment is best-effort and must not block the heartbeat.
    """
    settings = get_settings()
    backend = settings.asn_lookup_provider.lower()
    if backend == _DISABLED_BACKEND:
        return

    # 1) Server-observed IP enrichment (V2-02-01).
    if request_client_host is not None and is_public_ip(request_client_host):
        refresh_after = timedelta(hours=settings.asn_refresh_hours)
        is_stale = (
            probe.asn_updated_at is None
            or datetime.now(UTC) - probe.asn_updated_at > refresh_after
            or probe.public_ip != request_client_host
        )
        if is_stale:
            try:
                await enrich_probe(db, probe, request_client_host)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "asn_enrichment_failed",
                    probe_id=str(probe.id),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

    # 2) Self-reported IP enrichment (V2-02-07). Always re-lookup ASN when the
    # IP changes; otherwise piggyback on the same refresh window.
    if self_reported_ip and is_public_ip(self_reported_ip):
        ip_changed = probe.self_reported_ip != self_reported_ip
        if ip_changed or probe.self_reported_asn is None:
            probe.self_reported_ip = self_reported_ip
            try:
                info = await lookup_asn(self_reported_ip)
                probe.self_reported_asn = info.asn if info else None
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "self_reported_asn_failed",
                    probe_id=str(probe.id),
                    error_type=type(exc).__name__,
                )


async def refresh_stale_probes(db: AsyncSession) -> int:
    """
    Background task — re-enrich probes whose ASN data is stale or missing.
    Returns the number of probes refreshed. Called from the lifespan loop.
    """
    settings = get_settings()
    if settings.asn_lookup_provider.lower() == _DISABLED_BACKEND:
        return 0

    cutoff = datetime.now(UTC) - timedelta(hours=settings.asn_refresh_hours)
    rows = (
        await db.execute(
            select(Probe).where(
                Probe.is_active.is_(True),
                Probe.public_ip.is_not(None),
            )
        )
    ).scalars().all()

    refreshed = 0
    for probe in rows:
        if probe.asn_updated_at is not None and probe.asn_updated_at >= cutoff:
            continue
        if not probe.public_ip:
            continue
        if await enrich_probe(db, probe, probe.public_ip):
            refreshed += 1
    if refreshed:
        await db.commit()
    return refreshed
