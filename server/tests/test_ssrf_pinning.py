"""SA1 — SSRF guard hardening: IP pinning against DNS rebinding.

The guard must resolve DNS exactly once, validate every A/AAAA record, and
connect to the validated IP (URL host rewritten, original hostname kept as
``Host`` header + TLS SNI). A DNS entry flipping to a private IP between
validation and request must never be reachable.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from whatisup.services.channels._helpers import (
    _PinnedHostTransport,
    _validate_webhook_url_sync,
    ssrf_safe_client,
    validate_webhook_url,
)

PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"
PRIVATE_V4 = "10.0.0.5"


def _addrinfo(ip: str) -> tuple:
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (ip, 0))


# ── _validate_webhook_url_sync returns the pinned IP ──────────────────────────


def test_sync_guard_returns_pinned_public_ip(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [_addrinfo(PUBLIC_V4)])
    assert _validate_webhook_url_sync("https://hooks.example.com/abc") == PUBLIC_V4


def test_sync_guard_prefers_ipv4_over_ipv6(monkeypatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [_addrinfo(PUBLIC_V6), _addrinfo(PUBLIC_V4)],
    )
    assert _validate_webhook_url_sync("https://hooks.example.com/abc") == PUBLIC_V4


def test_sync_guard_falls_back_to_ipv6(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [_addrinfo(PUBLIC_V6)])
    assert _validate_webhook_url_sync("https://hooks.example.com/abc") == PUBLIC_V6


def test_sync_guard_rejects_private_ip(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [_addrinfo(PRIVATE_V4)])
    with pytest.raises(ValueError, match="internal"):
        _validate_webhook_url_sync("https://rebind.example.com/abc")


def test_sync_guard_rejects_if_any_record_is_private(monkeypatch) -> None:
    """One poisoned AAAA/A record among public ones is enough to reject."""
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [_addrinfo(PUBLIC_V4), _addrinfo(PRIVATE_V4)],
    )
    with pytest.raises(ValueError, match="internal"):
        _validate_webhook_url_sync("https://rebind.example.com/abc")


def test_sync_guard_rejects_empty_resolution(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [])
    with pytest.raises(ValueError, match="resolved"):
        _validate_webhook_url_sync("https://ghost.example.com/abc")


@pytest.mark.asyncio
async def test_async_guard_returns_pinned_ip(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [_addrinfo(PUBLIC_V4)])
    assert await validate_webhook_url("https://hooks.example.com/abc") == PUBLIC_V4


# ── Pinning transport ──────────────────────────────────────────────────────────


def _capture_inner_transport(monkeypatch, captured: dict):
    """Intercept the wrapped AsyncHTTPTransport so no network IO occurs."""

    async def _fake_handle(self, request: httpx.Request) -> httpx.Response:
        captured.setdefault("requests", []).append(request)
        return httpx.Response(204)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _fake_handle)


@pytest.mark.asyncio
async def test_transport_pins_ip_keeps_host_and_sni(monkeypatch) -> None:
    captured: dict = {}
    _capture_inner_transport(monkeypatch, captured)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [_addrinfo(PUBLIC_V4)])

    async with ssrf_safe_client(timeout=10) as client:
        resp = await client.post("https://hooks.example.com/abc?x=1", json={"ok": True})

    assert resp.status_code == 204
    request = captured["requests"][0]
    # Connection target = validated IP, no second DNS resolution possible
    assert request.url.host == PUBLIC_V4
    assert request.url.path == "/abc"
    assert request.url.query == b"x=1"
    # Original hostname preserved for virtual hosting + TLS verification
    assert request.headers["Host"] == "hooks.example.com"
    assert request.extensions["sni_hostname"] == "hooks.example.com"


@pytest.mark.asyncio
async def test_transport_rejects_private_ip_before_any_io(monkeypatch) -> None:
    captured: dict = {}
    _capture_inner_transport(monkeypatch, captured)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [_addrinfo(PRIVATE_V4)])

    async with ssrf_safe_client(timeout=10) as client:
        with pytest.raises(ValueError, match="internal"):
            await client.post("https://rebind.example.com/abc", json={})

    assert "requests" not in captured  # nothing ever left the transport


@pytest.mark.asyncio
async def test_transport_single_resolution_defeats_rebinding(monkeypatch) -> None:
    """DNS flips public→private after validation: the private IP is unreachable.

    With a single getaddrinfo call, the IP that was validated is exactly the
    IP that gets connected to — the rebound record never gets a second lookup.
    """
    captured: dict = {}
    _capture_inner_transport(monkeypatch, captured)

    lookups: list[str] = []

    def _rebinding_dns(*a, **kw):
        # First resolution: legit public IP. Any later one: private (rebound).
        ip = PUBLIC_V4 if not lookups else PRIVATE_V4
        lookups.append(ip)
        return [_addrinfo(ip)]

    monkeypatch.setattr(socket, "getaddrinfo", _rebinding_dns)

    async with ssrf_safe_client(timeout=10) as client:
        await client.post("https://rebind.example.com/abc", json={})

    assert len(lookups) == 1  # resolved exactly once
    assert captured["requests"][0].url.host == PUBLIC_V4  # pinned, not re-resolved


@pytest.mark.asyncio
async def test_transport_public_ip_literal_passthrough(monkeypatch) -> None:
    """A public IP literal URL goes through unchanged (no Host/SNI rewrite)."""
    captured: dict = {}
    _capture_inner_transport(monkeypatch, captured)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [_addrinfo(PUBLIC_V4)])

    async with ssrf_safe_client(timeout=10) as client:
        await client.post(f"http://{PUBLIC_V4}/hook", json={})

    request = captured["requests"][0]
    assert request.url.host == PUBLIC_V4
    assert "sni_hostname" not in request.extensions


@pytest.mark.asyncio
async def test_transport_blocks_ip_literal_private(monkeypatch) -> None:
    captured: dict = {}
    _capture_inner_transport(monkeypatch, captured)

    async with ssrf_safe_client(timeout=10) as client:
        with pytest.raises(ValueError, match="blocked|internal"):
            await client.post("http://169.254.169.254/latest/meta-data/", json={})

    assert "requests" not in captured


def test_ssrf_safe_client_uses_pinning_transport() -> None:
    client = ssrf_safe_client(timeout=10)
    assert isinstance(client._transport, _PinnedHostTransport)
