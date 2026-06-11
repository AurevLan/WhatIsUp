"""Tests for reporter flush-loop resilience and scenario RAM throttling."""

from __future__ import annotations

import asyncio

import pytest

import whatisup_probe.reporter as reporter_module
from whatisup_probe.reporter import Reporter
from whatisup_probe.scheduler import ProbeScheduler

# ── Flush loop resilience ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_flush_loop_survives_flush_batch_exception(monkeypatch) -> None:
    """An unexpected exception in _flush_batch must not kill the flush loop."""
    monkeypatch.setattr(reporter_module, "_FLUSH_INTERVAL", 0.01)
    reporter = Reporter()

    calls = 0

    async def boom() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(reporter, "_flush_batch", boom)
    await reporter.start()
    await asyncio.sleep(0.08)

    assert calls >= 2  # the loop kept iterating despite the exceptions
    assert not reporter._flush_task.done()  # task is still alive

    # Restore a working _flush_batch so the final flush in stop() succeeds
    async def noop() -> None:
        return None

    monkeypatch.setattr(reporter, "_flush_batch", noop)
    await reporter.aclose()


@pytest.mark.asyncio
async def test_flush_loop_still_cancellable(monkeypatch) -> None:
    """CancelledError must NOT be swallowed by the resilience guard."""
    monkeypatch.setattr(reporter_module, "_FLUSH_INTERVAL", 0.01)
    reporter = Reporter()
    await reporter.start()
    await asyncio.sleep(0.03)
    await reporter.aclose()

    assert reporter._flush_task.cancelled() or reporter._flush_task.done()


# ── Scenario RAM throttling ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scenario_throttled_on_high_ram(monkeypatch) -> None:
    """RAM > 85% skips the scenario check, increments the counter, pushes nothing."""
    scheduler = ProbeScheduler()
    monkeypatch.setattr(scheduler, "_collect_health", lambda: {"ram_percent": 92.0})

    pushed: list = []

    async def fake_push(result) -> None:
        pushed.append(result)

    monkeypatch.setattr(scheduler._reporter, "push_result", fake_push)

    monitor = {
        "id": "mon-1",
        "name": "scenario-test",
        "check_type": "scenario",
        "timeout_seconds": 5,
    }
    await scheduler._run_check(monitor)

    assert scheduler._throttled_scenarios == 1
    assert pushed == []  # no false `error` result that would open an incident

    await scheduler._run_check(monitor)
    assert scheduler._throttled_scenarios == 2


def test_collect_health_includes_throttled_scenarios() -> None:
    """The throttle counter is exposed in the heartbeat health payload."""
    scheduler = ProbeScheduler()
    health = scheduler._collect_health()

    assert health["throttled_scenarios"] == 0

    scheduler._throttled_scenarios = 3
    health = scheduler._collect_health()
    assert health["throttled_scenarios"] == 3
