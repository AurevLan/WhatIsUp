"""Scheduler wiring for discovery sources (plan D, D-1).

Mirrors how `sync_monitors` already reconciles APScheduler jobs against the
`monitors` list in the heartbeat response — same add/update/remove-stale
mechanic, applied to `discovery_sources`, gated by the probe's own declared
capabilities.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from whatisup_probe.discovery import DiscoveredItem
from whatisup_probe.scheduler import ProbeScheduler

pytestmark = pytest.mark.asyncio

_HEARTBEAT_URL = "http://localhost:8000/api/v1/probes/heartbeat"


def _heartbeat_response(sources: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"monitors": [], "discovery_sources": sources})


def _source(
    source_id: str = "src-1", source_type: str = "port_scan", params: dict | None = None
) -> dict:
    return {"id": source_id, "source_type": source_type, "params": params or {}}


@pytest.fixture(autouse=True)
def _capabilities_available(monkeypatch):
    """Default: every known source type reports as available."""
    monkeypatch.setattr(
        "whatisup_probe.scheduler.capability_report",
        AsyncMock(return_value={"docker": True, "port_scan": True, "dns_zone": True}),
    )


@respx.mock
async def test_sync_monitors_schedules_a_discovery_job() -> None:
    respx.post(_HEARTBEAT_URL).mock(return_value=_heartbeat_response([_source("src-1")]))
    scheduler = ProbeScheduler()
    try:
        await scheduler.sync_monitors()
        assert "src-1" in scheduler._discovery_sources
        job = scheduler._scheduler.get_job(scheduler._make_discovery_job_id("src-1"))
        assert job is not None
    finally:
        await scheduler.aclose()


@respx.mock
async def test_sync_monitors_removes_stale_discovery_job() -> None:
    route = respx.post(_HEARTBEAT_URL)
    route.side_effect = [
        _heartbeat_response([_source("src-1")]),
        _heartbeat_response([]),
    ]
    scheduler = ProbeScheduler()
    try:
        await scheduler.sync_monitors()
        assert "src-1" in scheduler._discovery_sources

        await scheduler.sync_monitors()
        assert "src-1" not in scheduler._discovery_sources
        assert scheduler._scheduler.get_job(scheduler._make_discovery_job_id("src-1")) is None
    finally:
        await scheduler.aclose()


@respx.mock
async def test_sync_monitors_reschedules_on_param_change() -> None:
    route = respx.post(_HEARTBEAT_URL)
    route.side_effect = [
        _heartbeat_response([_source("src-1", params={"cidr": "10.0.0.0/24", "ports": [80]})]),
        _heartbeat_response([_source("src-1", params={"cidr": "10.0.0.0/24", "ports": [443]})]),
    ]
    scheduler = ProbeScheduler()
    try:
        await scheduler.sync_monitors()
        job_before = scheduler._scheduler.get_job(scheduler._make_discovery_job_id("src-1"))
        assert job_before is not None

        await scheduler.sync_monitors()
        assert scheduler._discovery_sources["src-1"]["params"]["ports"] == [443]
        job_after = scheduler._scheduler.get_job(scheduler._make_discovery_job_id("src-1"))
        assert job_after is not None
    finally:
        await scheduler.aclose()


@respx.mock
async def test_sync_monitors_skips_source_with_missing_capability(monkeypatch) -> None:
    monkeypatch.setattr(
        "whatisup_probe.scheduler.capability_report",
        AsyncMock(return_value={"docker": False, "port_scan": True}),
    )
    respx.post(_HEARTBEAT_URL).mock(
        return_value=_heartbeat_response([_source("docker-src", source_type="docker")])
    )
    scheduler = ProbeScheduler()
    try:
        await scheduler.sync_monitors()
        assert "docker-src" not in scheduler._discovery_sources
        assert scheduler._scheduler.get_job(scheduler._make_discovery_job_id("docker-src")) is None
    finally:
        await scheduler.aclose()


@respx.mock
async def test_sync_monitors_unchanged_source_is_left_alone() -> None:
    src = _source("src-1")
    respx.post(_HEARTBEAT_URL).mock(return_value=_heartbeat_response([src]))
    scheduler = ProbeScheduler()
    try:
        await scheduler.sync_monitors()
        job_id = scheduler._make_discovery_job_id("src-1")
        first_job = scheduler._scheduler.get_job(job_id)

        await scheduler.sync_monitors()
        second_job = scheduler._scheduler.get_job(job_id)
        # Same underlying job — reschedule/modify were never invoked for a
        # heartbeat that reports the exact same source config.
        assert first_job is second_job
    finally:
        await scheduler.aclose()


@respx.mock
async def test_heartbeat_request_carries_discovery_capabilities() -> None:
    route = respx.post(_HEARTBEAT_URL).mock(return_value=_heartbeat_response([]))
    scheduler = ProbeScheduler()
    try:
        await scheduler.sync_monitors()
    finally:
        await scheduler.aclose()

    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body["discovery_capabilities"] == ["dns_zone", "docker", "port_scan"]


# ── _run_discovery_source ─────────────────────────────────────────────────────


async def test_run_discovery_source_pushes_snapshot(monkeypatch) -> None:
    items = [DiscoveredItem(host="10.0.0.1", port=80, proto="tcp", hints={"a": "b"})]
    monkeypatch.setattr("whatisup_probe.scheduler.run_source", AsyncMock(return_value=items))
    scheduler = ProbeScheduler()
    push_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(scheduler._reporter, "push_discovery", push_mock)
    try:
        await scheduler._run_discovery_source(_source("src-1"))
    finally:
        await scheduler.aclose()

    push_mock.assert_awaited_once()
    args = push_mock.await_args.args
    assert args[0] == "src-1"
    assert args[1] == [{"host": "10.0.0.1", "port": 80, "proto": "tcp", "hints": {"a": "b"}}]


async def test_run_discovery_source_pushes_even_when_nothing_found(monkeypatch) -> None:
    """Piège n°1 (plan E, E-1): a scan that finds nothing must still push an
    (empty) snapshot — the server-side `last_scan_at` bookkeeping only
    updates on an actual push, so skipping it here would make "nothing
    found" indistinguishable from "never scanned"."""
    monkeypatch.setattr("whatisup_probe.scheduler.run_source", AsyncMock(return_value=[]))
    scheduler = ProbeScheduler()
    push_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(scheduler._reporter, "push_discovery", push_mock)
    try:
        await scheduler._run_discovery_source(_source("src-1"))
    finally:
        await scheduler.aclose()

    push_mock.assert_awaited_once_with("src-1", [])


async def test_run_discovery_source_failure_does_not_raise(monkeypatch) -> None:
    async def boom(*_a, **_kw):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr("whatisup_probe.scheduler.run_source", boom)
    scheduler = ProbeScheduler()
    push_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(scheduler._reporter, "push_discovery", push_mock)
    try:
        await scheduler._run_discovery_source(_source("src-1"))  # must not raise
    finally:
        await scheduler.aclose()

    push_mock.assert_not_awaited()


# ── scan-now (plan E, E-1) ────────────────────────────────────────────────────


async def _run_and_collect_tasks(monkeypatch, scheduler: ProbeScheduler) -> list[asyncio.Task]:
    """Capture every task `sync_monitors` fires off (trigger-now runs are
    detached with `asyncio.create_task`, not awaited inline) and wait for them
    to finish before the caller makes assertions."""
    created: list[asyncio.Task] = []
    orig_create_task = asyncio.create_task

    def _capture(coro, *a, **kw):
        task = orig_create_task(coro, *a, **kw)
        created.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", _capture)
    await scheduler.sync_monitors()
    if created:
        await asyncio.gather(*created)
    return created


@respx.mock
async def test_sync_monitors_fires_immediate_run_for_triggered_source(monkeypatch) -> None:
    respx.post(_HEARTBEAT_URL).mock(
        return_value=_heartbeat_response([{**_source("src-1"), "trigger_now": True}])
    )
    scheduler = ProbeScheduler()
    run_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_run_discovery_source", run_mock)
    try:
        await _run_and_collect_tasks(monkeypatch, scheduler)
    finally:
        await scheduler.aclose()

    run_mock.assert_awaited_once()
    args = run_mock.await_args.args
    assert args[0]["id"] == "src-1"


@respx.mock
async def test_sync_monitors_does_not_fire_immediate_run_without_flag(monkeypatch) -> None:
    respx.post(_HEARTBEAT_URL).mock(return_value=_heartbeat_response([_source("src-1")]))
    scheduler = ProbeScheduler()
    run_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_run_discovery_source", run_mock)
    try:
        await _run_and_collect_tasks(monkeypatch, scheduler)
    finally:
        await scheduler.aclose()

    run_mock.assert_not_awaited()


@respx.mock
async def test_sync_monitors_does_not_fire_triggered_source_missing_capability(
    monkeypatch,
) -> None:
    """A source skipped for lacking capability must not be run either —
    trigger-now only ever fires on `available_sources`."""
    monkeypatch.setattr(
        "whatisup_probe.scheduler.capability_report",
        AsyncMock(return_value={"docker": False, "port_scan": True}),
    )
    respx.post(_HEARTBEAT_URL).mock(
        return_value=_heartbeat_response(
            [{**_source("docker-src", source_type="docker"), "trigger_now": True}]
        )
    )
    scheduler = ProbeScheduler()
    run_mock = AsyncMock()
    monkeypatch.setattr(scheduler, "_run_discovery_source", run_mock)
    try:
        await _run_and_collect_tasks(monkeypatch, scheduler)
    finally:
        await scheduler.aclose()

    run_mock.assert_not_awaited()
