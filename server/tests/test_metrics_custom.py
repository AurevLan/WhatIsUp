"""Tests for the custom Prometheus application metrics."""

from __future__ import annotations

import pytest
from prometheus_client import REGISTRY

from whatisup.core.metrics import (
    observe_alert_dispatch,
    observe_auth_cache,
    track_background_task,
)


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.mark.asyncio
async def test_track_background_task_records_ok() -> None:
    before = _sample("whatisup_background_task_runs_total", {"task": "test_task", "status": "ok"})
    async with track_background_task("test_task"):
        pass
    after = _sample("whatisup_background_task_runs_total", {"task": "test_task", "status": "ok"})
    assert after == before + 1
    assert _sample("whatisup_background_task_duration_seconds_count", {"task": "test_task"}) >= 1


@pytest.mark.asyncio
async def test_track_background_task_records_error_and_reraises() -> None:
    before = _sample("whatisup_background_task_runs_total", {"task": "test_err", "status": "error"})
    with pytest.raises(RuntimeError):
        async with track_background_task("test_err"):
            raise RuntimeError("boom")
    after = _sample("whatisup_background_task_runs_total", {"task": "test_err", "status": "error"})
    assert after == before + 1


def test_observe_alert_dispatch_counts_by_outcome() -> None:
    sent_before = _sample(
        "whatisup_alert_dispatch_total", {"channel_type": "webhook", "status": "sent"}
    )
    failed_before = _sample(
        "whatisup_alert_dispatch_total", {"channel_type": "webhook", "status": "failed"}
    )
    observe_alert_dispatch("webhook", 0.12, success=True)
    observe_alert_dispatch("webhook", 0.5, success=False)
    assert (
        _sample("whatisup_alert_dispatch_total", {"channel_type": "webhook", "status": "sent"})
        == sent_before + 1
    )
    assert (
        _sample("whatisup_alert_dispatch_total", {"channel_type": "webhook", "status": "failed"})
        == failed_before + 1
    )


def test_observe_auth_cache_hit_miss() -> None:
    hit_before = _sample("whatisup_auth_cache_total", {"cache": "probe_api_key", "result": "hit"})
    miss_before = _sample("whatisup_auth_cache_total", {"cache": "probe_api_key", "result": "miss"})
    observe_auth_cache("probe_api_key", hit=True)
    observe_auth_cache("probe_api_key", hit=False)
    assert (
        _sample("whatisup_auth_cache_total", {"cache": "probe_api_key", "result": "hit"})
        == hit_before + 1
    )
    assert (
        _sample("whatisup_auth_cache_total", {"cache": "probe_api_key", "result": "miss"})
        == miss_before + 1
    )
