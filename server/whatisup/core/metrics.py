"""Custom Prometheus metrics.

Complements the HTTP-level metrics from prometheus-fastapi-instrumentator with
application SLIs: background task health, alert dispatch latency per channel,
and auth cache effectiveness. Degrades to no-ops if prometheus_client is
unavailable (it ships with the optional instrumentator dependency).
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

try:
    from prometheus_client import Counter, Histogram

    _ENABLED = True
except ImportError:  # pragma: no cover — dep always present in the Docker image
    _ENABLED = False

if _ENABLED:
    BACKGROUND_TASK_RUNS = Counter(
        "whatisup_background_task_runs_total",
        "Background task iterations by outcome",
        ["task", "status"],
    )
    BACKGROUND_TASK_DURATION = Histogram(
        "whatisup_background_task_duration_seconds",
        "Background task iteration duration",
        ["task"],
        buckets=(0.01, 0.05, 0.25, 1, 5, 15, 60, 300),
    )
    ALERT_DISPATCH = Counter(
        "whatisup_alert_dispatch_total",
        "Alert dispatch attempts by channel type and outcome",
        ["channel_type", "status"],
    )
    ALERT_DISPATCH_DURATION = Histogram(
        "whatisup_alert_dispatch_seconds",
        "Alert dispatch duration per channel type",
        ["channel_type"],
        buckets=(0.05, 0.25, 1, 2.5, 5, 10, 30),
    )
    AUTH_CACHE = Counter(
        "whatisup_auth_cache_total",
        "Auth cache lookups (user API keys / probe keys) by result",
        ["cache", "result"],
    )


def observe_background_task(task: str, duration_seconds: float, status: str) -> None:
    if _ENABLED:
        BACKGROUND_TASK_RUNS.labels(task=task, status=status).inc()
        BACKGROUND_TASK_DURATION.labels(task=task).observe(duration_seconds)


@asynccontextmanager
async def track_background_task(task: str):
    """Time one iteration of a background loop and record its outcome."""
    start = time.perf_counter()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        observe_background_task(task, time.perf_counter() - start, status)


def observe_alert_dispatch(channel_type: str, duration_seconds: float, success: bool) -> None:
    if _ENABLED:
        ALERT_DISPATCH.labels(
            channel_type=channel_type, status="sent" if success else "failed"
        ).inc()
        ALERT_DISPATCH_DURATION.labels(channel_type=channel_type).observe(duration_seconds)


def observe_auth_cache(cache: str, hit: bool) -> None:
    if _ENABLED:
        AUTH_CACHE.labels(cache=cache, result="hit" if hit else "miss").inc()
