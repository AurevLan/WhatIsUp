"""Port-scan discovery source — bounds + SSRF gating + open-port detection (plan D, D-1)."""

from __future__ import annotations

import asyncio

import pytest

from whatisup_probe.discovery.port_scan import PortScanDiscoverySource

pytestmark = pytest.mark.asyncio


async def test_capability_available_always_true() -> None:
    assert await PortScanDiscoverySource().capability_available() is True


# ── bounds ─────────────────────────────────────────────────────────────────────


async def test_cidr_larger_than_24_rejected() -> None:
    source = PortScanDiscoverySource()
    items = await source.run({"cidr": "10.0.0.0/16", "ports": [80]})
    assert items == []


async def test_cidr_exactly_24_allowed_shape(monkeypatch) -> None:
    """A /24 is not rejected by the bound check (still gated by SSRF below)."""
    from whatisup_probe.discovery import port_scan as mod

    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)
    calls: list[str] = []

    async def _fake_probe(self, ip, port, semaphore):
        calls.append(ip)
        return None

    monkeypatch.setattr(PortScanDiscoverySource, "_probe_one", _fake_probe)
    await PortScanDiscoverySource().run({"cidr": "10.0.0.0/24", "ports": [80]})
    assert len(calls) == 254  # usable hosts in a /24


async def test_missing_cidr_returns_empty() -> None:
    assert await PortScanDiscoverySource().run({"ports": [80]}) == []


async def test_missing_ports_returns_empty() -> None:
    assert await PortScanDiscoverySource().run({"cidr": "10.0.0.0/24"}) == []


async def test_invalid_cidr_returns_empty() -> None:
    assert await PortScanDiscoverySource().run({"cidr": "not-a-cidr", "ports": [80]}) == []


async def test_ipv6_cidr_rejected() -> None:
    items = await PortScanDiscoverySource().run({"cidr": "fe80::/120", "ports": [80]})
    assert items == []


async def test_more_than_64_ports_rejected() -> None:
    """Mirrors the server's `_MAX_PORTS` cap — a tampered params blob refuses
    the whole run rather than scanning a best-effort subset."""
    items = await PortScanDiscoverySource().run(
        {"cidr": "10.0.0.0/24", "ports": list(range(1, 66))}
    )
    assert items == []


async def test_non_numeric_port_rejects_whole_run() -> None:
    items = await PortScanDiscoverySource().run(
        {"cidr": "10.0.0.0/24", "ports": [80, "not-a-port"]}
    )
    assert items == []


async def test_out_of_range_port_rejects_whole_run() -> None:
    items = await PortScanDiscoverySource().run({"cidr": "10.0.0.0/24", "ports": [80, 70000]})
    assert items == []


# ── SSRF gating — real pinning, not bypassed ─────────────────────────────────


async def test_loopback_range_never_yields_items() -> None:
    """Even a fully in-bounds /24 of loopback addresses is entirely refused —
    a declared CIDR does not override the probe's own SSRF posture."""
    items = await PortScanDiscoverySource().run({"cidr": "127.0.0.0/24", "ports": [22, 80]})
    assert items == []


async def test_link_local_range_never_yields_items() -> None:
    items = await PortScanDiscoverySource().run({"cidr": "169.254.1.0/24", "ports": [80]})
    assert items == []


# ── real open-port detection ──────────────────────────────────────────────────


async def test_open_port_detected_on_real_listener(monkeypatch) -> None:
    """End-to-end against a real local listener — SSRF pinning bypassed with
    identity (loopback is otherwise blocked, see tests above) so this test
    exercises only the connect-scan logic itself."""
    from whatisup_probe.discovery import port_scan as mod

    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)

    # The handler MUST close its writer: since Python 3.12 Server.wait_closed()
    # waits for every active connection, and a never-closed accepted socket
    # would hang the test (and the whole suite) forever.
    server = await asyncio.start_server(lambda r, w: w.close(), host="127.0.0.1", port=0)
    port = server.sockets[0].getsockname()[1]
    try:
        async with server:
            items = await PortScanDiscoverySource().run({"cidr": "127.0.0.0/24", "ports": [port]})
    finally:
        server.close()
        await server.wait_closed()

    assert len(items) == 1
    assert items[0].host == "127.0.0.1"
    assert items[0].port == port
    assert items[0].proto == "tcp"
    assert items[0].hints == {}


async def test_closed_port_not_reported(monkeypatch) -> None:
    from whatisup_probe.discovery import port_scan as mod

    monkeypatch.setattr(mod, "_ssrf_resolve_pinned_sync", lambda ip: ip)

    # Bind an ephemeral port then immediately close it — very likely free
    # again for the short lifetime of this test, giving us a "closed port".
    probe_srv = await asyncio.start_server(lambda r, w: None, host="127.0.0.1", port=0)
    closed_port = probe_srv.sockets[0].getsockname()[1]
    probe_srv.close()
    await probe_srv.wait_closed()

    items = await PortScanDiscoverySource().run({"cidr": "127.0.0.0/24", "ports": [closed_port]})
    assert all(item.port != closed_port or item.host != "127.0.0.1" for item in items)
