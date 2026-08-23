"""dns_zone discovery source — AXFR parsing + SSRF gating (plan D, D-4).

No real network anywhere in this suite: the AXFR transfer itself
(`_fetch_zone`) is monkeypatched to return a `dns.zone.Zone` built in-memory
via `dns.zone.from_text`, which exercises exactly the same parsing path
(`_zone_to_items`) a real transfer would feed. "Refused AXFR" is exercised by
making `_fetch_zone` behave the way it really does on a refusal: return
``None``.
"""

from __future__ import annotations

import pytest

from whatisup_probe.discovery.dns_zone import DnsZoneDiscoverySource

pytestmark = pytest.mark.asyncio

_ZONE_TEXT = """\
$ORIGIN example.com.
$TTL 300
@ IN SOA ns1.example.com. admin.example.com. 1 3600 900 604800 300
@ IN NS ns1.example.com.
@ IN A 10.0.0.1
www IN A 10.0.0.2
www IN AAAA fd00::2
api IN CNAME www.example.com.
UPPERCASE IN A 10.0.0.9
"""


def _build_zone(text: str = _ZONE_TEXT, origin: str = "example.com."):
    import dns.zone

    return dns.zone.from_text(text, origin=origin, check_origin=True, relativize=False)


def _by_host(items):
    out: dict[str, list[dict]] = {}
    for item in items:
        out.setdefault(item.host, []).append(item.hints)
    return out


# ── capability ─────────────────────────────────────────────────────────────


async def test_capability_available_true_when_dnspython_present() -> None:
    assert await DnsZoneDiscoverySource().capability_available() is True


async def test_capability_available_false_on_import_error(monkeypatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name in ("dns.query", "dns.zone"):
            raise ImportError(f"simulated missing {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert await DnsZoneDiscoverySource().capability_available() is False


# ── missing/invalid params ───────────────────────────────────────────────────


async def test_missing_zone_returns_empty() -> None:
    items = await DnsZoneDiscoverySource().run({"resolver": "10.0.0.1"})
    assert items == []


async def test_missing_resolver_returns_empty() -> None:
    items = await DnsZoneDiscoverySource().run({"zone": "example.com"})
    assert items == []


# ── SSRF gating — real pinning, not bypassed ─────────────────────────────────


async def test_loopback_resolver_refused() -> None:
    items = await DnsZoneDiscoverySource().run({"zone": "example.com", "resolver": "127.0.0.1"})
    assert items == []


async def test_metadata_resolver_refused() -> None:
    items = await DnsZoneDiscoverySource().run(
        {"zone": "example.com", "resolver": "169.254.169.254"}
    )
    assert items == []


async def test_link_local_resolver_refused() -> None:
    items = await DnsZoneDiscoverySource().run({"zone": "example.com", "resolver": "169.254.1.1"})
    assert items == []


# ── AXFR refusal / failure — no fallback scan ────────────────────────────────


async def test_axfr_refused_yields_empty_snapshot(monkeypatch) -> None:
    """A resolver that refuses the transfer (the common case for public
    resolvers) must yield an empty snapshot, never a fallback scan."""
    from whatisup_probe.discovery import dns_zone as mod

    # Bypass SSRF pinning with identity — this test is about the "refused
    # transfer" behaviour, not SSRF gating (already covered above).
    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)
    monkeypatch.setattr(mod, "_fetch_zone", lambda resolver_ip, zone_name: None)
    items = await DnsZoneDiscoverySource().run({"zone": "example.com", "resolver": "10.0.0.1"})
    assert items == []


async def test_run_survives_fetch_zone_raising_unexpectedly(monkeypatch) -> None:
    """`_fetch_zone` already contains AXFR failures (see the test below), but
    `run()` must never propagate one regardless — `BaseDiscoverySource.run`'s
    contract: a broken source must not take the scheduler job down."""
    from whatisup_probe.discovery import dns_zone as mod

    def _boom(resolver_ip, zone_name):
        raise RuntimeError("axfr exploded")

    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)
    monkeypatch.setattr(mod, "_fetch_zone", _boom)
    items = await DnsZoneDiscoverySource().run({"zone": "example.com", "resolver": "10.0.0.1"})
    assert items == []


def test_fetch_zone_contains_axfr_exceptions(monkeypatch) -> None:
    """The real boundary: `_fetch_zone` swallows a failed transfer and logs,
    it never raises out to the scheduler loop.

    Targets loopback with nothing listening on the AXFR port — an instant,
    local connection refusal, not a real network round-trip — and caps the
    timeout tight so a sandbox without even that guarantee can't turn this
    into a slow test."""
    from whatisup_probe.discovery import dns_zone as mod

    monkeypatch.setattr(mod, "_AXFR_TIMEOUT", 0.5)
    result = mod._fetch_zone("127.0.0.1", "example.com")
    assert result is None


# ── parsing — pinned resolver bypassed, real _fetch_zone monkeypatched ──────


async def test_axfr_parsed_into_discovered_items(monkeypatch) -> None:
    from whatisup_probe.discovery import dns_zone as mod

    zone = _build_zone()
    monkeypatch.setattr(mod, "_fetch_zone", lambda resolver_ip, zone_name: zone)
    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)

    items = await DnsZoneDiscoverySource().run({"zone": "example.com", "resolver": "10.0.0.1"})
    by_host = _by_host(items)

    assert by_host["example.com"] == [{"record_type": "A", "value": "10.0.0.1"}]
    assert {"record_type": "A", "value": "10.0.0.2"} in by_host["www.example.com"]
    assert {"record_type": "AAAA", "value": "fd00::2"} in by_host["www.example.com"]
    assert by_host["api.example.com"] == [{"record_type": "CNAME", "value": "www.example.com"}]
    # SOA/NS are never in the default type set — never surfaced as targets.
    assert not any(h["record_type"] in ("SOA", "NS") for hs in by_host.values() for h in hs)


async def test_host_names_normalized_lowercase(monkeypatch) -> None:
    from whatisup_probe.discovery import dns_zone as mod

    zone = _build_zone()
    monkeypatch.setattr(mod, "_fetch_zone", lambda resolver_ip, zone_name: zone)
    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)

    items = await DnsZoneDiscoverySource().run({"zone": "example.com", "resolver": "10.0.0.1"})
    hosts = {item.host for item in items}
    # Exact-equality membership spelled out — CodeQL's
    # py/incomplete-url-substring-sanitization misreads a bare
    # `"name" in hosts` as URL substring matching (false positive).
    assert any(h == "uppercase.example.com" for h in hosts)
    assert not any(h != h.lower() for h in hosts)


async def test_port_and_proto_are_fixed(monkeypatch) -> None:
    from whatisup_probe.discovery import dns_zone as mod

    zone = _build_zone()
    monkeypatch.setattr(mod, "_fetch_zone", lambda resolver_ip, zone_name: zone)
    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)

    items = await DnsZoneDiscoverySource().run({"zone": "example.com", "resolver": "10.0.0.1"})
    assert items
    assert all(item.port is None and item.proto == "tcp" for item in items)


async def test_record_types_filter_applied(monkeypatch) -> None:
    from whatisup_probe.discovery import dns_zone as mod

    zone = _build_zone()
    monkeypatch.setattr(mod, "_fetch_zone", lambda resolver_ip, zone_name: zone)
    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)

    items = await DnsZoneDiscoverySource().run(
        {"zone": "example.com", "resolver": "10.0.0.1", "record_types": ["CNAME"]}
    )
    assert len(items) == 1
    assert items[0].host == "api.example.com"
    assert items[0].hints["record_type"] == "CNAME"


# ── cap ───────────────────────────────────────────────────────────────────────


async def test_records_capped_at_500(monkeypatch) -> None:
    from whatisup_probe.discovery import dns_zone as mod

    lines = [
        "$ORIGIN example.com.",
        "$TTL 300",
        "@ IN SOA a.example.com. b.example.com. 1 1 1 1 1",
        "@ IN NS a.example.com.",
    ]
    for i in range(600):
        lines.append(f"host{i} IN A 10.0.{i // 256}.{i % 256}")
    big_zone = _build_zone("\n".join(lines) + "\n")

    monkeypatch.setattr(mod, "_fetch_zone", lambda resolver_ip, zone_name: big_zone)
    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)

    items = await DnsZoneDiscoverySource().run({"zone": "example.com", "resolver": "10.0.0.1"})
    assert len(items) == mod._MAX_RECORDS
