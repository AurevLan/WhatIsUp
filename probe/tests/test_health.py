"""Tests for probe health collection and heartbeat POST payload."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from whatisup_probe.reporter import Reporter
from whatisup_probe.scheduler import ProbeScheduler

# ── Health collection ─────────────────────────────────────────────────────────


def test_collect_health_returns_all_keys() -> None:
    """_collect_health() always returns the full set of expected metric keys."""
    scheduler = ProbeScheduler()
    health = scheduler._collect_health()

    assert "cpu_percent" in health
    assert "ram_percent" in health
    assert "disk_percent" in health
    assert "load_avg_1m" in health
    assert "monitors_active" in health
    assert "checks_running" in health


def test_collect_health_types() -> None:
    """Health metrics have the expected types and sane ranges."""
    scheduler = ProbeScheduler()
    health = scheduler._collect_health()

    assert isinstance(health["monitors_active"], int)
    assert isinstance(health["checks_running"], int)
    assert health["monitors_active"] >= 0
    assert health["checks_running"] >= 0

    if health["cpu_percent"] is not None:
        assert 0.0 <= health["cpu_percent"] <= 100.0
    if health["ram_percent"] is not None:
        assert 0.0 <= health["ram_percent"] <= 100.0
    if health["disk_percent"] is not None:
        assert 0.0 <= health["disk_percent"] <= 100.0


def test_collect_health_monitors_active_reflects_state() -> None:
    """monitors_active matches the number of monitors tracked by the scheduler."""
    scheduler = ProbeScheduler()
    # Initially no monitors
    health = scheduler._collect_health()
    assert health["monitors_active"] == 0

    # Simulate two monitors registered
    scheduler._monitors["aaa"] = {"id": "aaa"}
    scheduler._monitors["bbb"] = {"id": "bbb"}
    health = scheduler._collect_health()
    assert health["monitors_active"] == 2


def test_collect_health_checks_running_zero_at_idle() -> None:
    """checks_running is 0 when the semaphore is fully available (no active checks)."""
    scheduler = ProbeScheduler()
    health = scheduler._collect_health()
    # At idle, semaphore._value == max_concurrent_checks → checks_running == 0
    assert health["checks_running"] == 0


# ── Reporter heartbeat POST ───────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_reporter_heartbeat_sends_health_in_body() -> None:
    """heartbeat() sends health data as a POST request body."""
    route = respx.post("http://localhost:8000/api/v1/probes/heartbeat").mock(
        return_value=httpx.Response(200, json={"monitors": []})
    )
    reporter = Reporter()
    health = {
        "cpu_percent": 33.0,
        "ram_percent": 50.0,
        "disk_percent": 20.0,
        "load_avg_1m": 0.5,
        "monitors_active": 3,
        "checks_running": 0,
    }
    result = await reporter.heartbeat(health)
    await reporter.aclose()

    assert result == []
    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body["health"]["cpu_percent"] == 33.0
    assert body["health"]["monitors_active"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_reporter_heartbeat_returns_monitors() -> None:
    """heartbeat() returns the monitors list from the server response."""
    monitors = [
        {"id": "mon-1", "url": "https://example.com", "interval_seconds": 60},
    ]
    respx.post("http://localhost:8000/api/v1/probes/heartbeat").mock(
        return_value=httpx.Response(200, json={"monitors": monitors})
    )
    reporter = Reporter()
    result = await reporter.heartbeat({})
    await reporter.aclose()

    assert result is not None
    assert len(result) == 1
    assert result[0]["id"] == "mon-1"


@pytest.mark.asyncio
@respx.mock
async def test_reporter_heartbeat_returns_none_on_error() -> None:
    """heartbeat() returns None when the server is unreachable."""
    respx.post("http://localhost:8000/api/v1/probes/heartbeat").mock(
        side_effect=httpx.ConnectError("refused")
    )
    reporter = Reporter()
    result = await reporter.heartbeat({})
    await reporter.aclose()

    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_reporter_heartbeat_returns_none_on_http_error() -> None:
    """heartbeat() returns None on HTTP 5xx."""
    respx.post("http://localhost:8000/api/v1/probes/heartbeat").mock(
        return_value=httpx.Response(503)
    )
    reporter = Reporter()
    result = await reporter.heartbeat({})
    await reporter.aclose()

    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_reporter_reuses_client_across_calls() -> None:
    """Reporter reuses the same AsyncClient (connection pooling — not a new client per call)."""
    respx.post("http://localhost:8000/api/v1/probes/heartbeat").mock(
        return_value=httpx.Response(200, json={"monitors": []})
    )
    reporter = Reporter()
    client_id_1 = id(reporter._client)
    await reporter.heartbeat({})
    client_id_2 = id(reporter._client)
    await reporter.aclose()

    assert client_id_1 == client_id_2
