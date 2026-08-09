"""Correlating pushed metrics with an incident (plan V2, C-3).

Most of what matters here is where the module **refuses to answer**. Ranking
series by how much they moved is easy; the value of the feature rests on it not
manufacturing a figure when there is nothing to compare — an SRE reading a
post-mortem at 3 a.m. has no way to tell an invented number from a measured one.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.incident import Incident, IncidentScope
from whatisup.models.monitor import Monitor
from whatisup.models.user import User
from whatisup.services.metric_correlation import (
    MIN_SAMPLES,
    MIN_WINDOW,
    correlate_incident_metrics,
    format_markdown,
)
from whatisup.services.metric_ingest import IngestPoint, ingest_points

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
STARTED = NOW - timedelta(hours=1)


async def _incident(db: AsyncSession, monitor: Monitor, *, resolved=None) -> Incident:
    inc = Incident(
        monitor_id=monitor.id,
        started_at=STARTED,
        resolved_at=resolved,
        scope=IncidentScope.global_,
        affected_probe_ids=[],
    )
    db.add(inc)
    await db.flush()
    return inc


async def _push(db, monitor, name, values, *, start, step_seconds=60, labels=None):
    """Push ``values`` at a regular cadence starting at ``start``."""
    await ingest_points(
        db,
        monitor.id,
        [
            IngestPoint(
                metric_name=name,
                value=float(v),
                unit=None,
                labels=labels or {},
                pushed_at=start + timedelta(seconds=i * step_seconds),
            )
            for i, v in enumerate(values)
        ],
    )


def _by_name(result, name):
    return next(m for m in result["series"] if m.metric_name == name)


# ── Ranking ───────────────────────────────────────────────────────────────────


async def test_ranks_series_by_how_much_they_moved(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    baseline_start = STARTED - timedelta(hours=1)

    # queue_depth quadruples; cache_hit barely moves.
    await _push(service_db, test_monitor, "queue_depth", [10] * 10, start=baseline_start)
    await _push(service_db, test_monitor, "queue_depth", [40] * 10, start=STARTED)
    await _push(service_db, test_monitor, "cache_hit", [90] * 10, start=baseline_start)
    await _push(service_db, test_monitor, "cache_hit", [88] * 10, start=STARTED)

    result = await correlate_incident_metrics(service_db, inc, now=NOW)
    assert [m.metric_name for m in result["series"]] == ["queue_depth", "cache_hit"]

    top = result["series"][0]
    assert top.change_ratio == pytest.approx(3.0)  # 10 → 40
    assert top.not_comparable is None


async def test_a_collapse_ranks_as_high_as_a_spike(service_db: AsyncSession, test_monitor: Monitor):
    """Ranking is on magnitude: a cache hit rate falling off matters as much."""
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    baseline_start = STARTED - timedelta(hours=1)

    await _push(service_db, test_monitor, "cache_hit", [100] * 10, start=baseline_start)
    await _push(service_db, test_monitor, "cache_hit", [10] * 10, start=STARTED)
    await _push(service_db, test_monitor, "steady", [5] * 10, start=baseline_start)
    await _push(service_db, test_monitor, "steady", [5] * 10, start=STARTED)

    result = await correlate_incident_metrics(service_db, inc, now=NOW)
    assert result["series"][0].metric_name == "cache_hit"
    assert result["series"][0].change_ratio == pytest.approx(-0.9)


async def test_labelled_series_are_ranked_independently(
    service_db: AsyncSession, test_monitor: Monitor
):
    """One route degrading must not be averaged away by its healthy siblings."""
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    baseline_start = STARTED - timedelta(hours=1)

    for route, before, during in (("/api", 10, 100), ("/health", 10, 10)):
        await _push(
            service_db,
            test_monitor,
            "latency",
            [before] * 10,
            start=baseline_start,
            labels={"route": route},
        )
        await _push(
            service_db,
            test_monitor,
            "latency",
            [during] * 10,
            start=STARTED,
            labels={"route": route},
        )

    result = await correlate_incident_metrics(service_db, inc, now=NOW)
    assert len(result["series"]) == 2
    assert result["series"][0].labels == {"route": "/api"}
    assert result["series"][0].change_ratio == pytest.approx(9.0)
    assert result["series"][1].change_ratio == pytest.approx(0.0)


# ── Where it refuses to answer ────────────────────────────────────────────────


async def test_a_series_born_with_the_incident_has_no_baseline(
    service_db: AsyncSession, test_monitor: Monitor
):
    """+∞ or 100% would both be inventions. Say there is no 'before'."""
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    await _push(service_db, test_monitor, "errors", [1] * 10, start=STARTED)

    result = await correlate_incident_metrics(service_db, inc, now=NOW)
    movement = _by_name(result, "errors")
    assert movement.not_comparable == "no_baseline"
    assert movement.change_ratio is None
    assert movement.baseline_samples == 0


async def test_too_few_samples_is_not_a_trend(service_db: AsyncSession, test_monitor: Monitor):
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    baseline_start = STARTED - timedelta(hours=1)
    few = MIN_SAMPLES - 1

    await _push(service_db, test_monitor, "sparse", [1] * few, start=baseline_start)
    await _push(service_db, test_monitor, "sparse", [50] * few, start=STARTED)

    movement = _by_name(await correlate_incident_metrics(service_db, inc, now=NOW), "sparse")
    assert movement.not_comparable == "too_few_samples"
    assert movement.change_ratio is None


async def test_zero_baseline_reports_an_absolute_delta(
    service_db: AsyncSession, test_monitor: Monitor
):
    """A ratio against zero is undefined, not infinite."""
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    baseline_start = STARTED - timedelta(hours=1)

    await _push(service_db, test_monitor, "errors", [0] * 10, start=baseline_start)
    await _push(service_db, test_monitor, "errors", [7] * 10, start=STARTED)

    movement = _by_name(await correlate_incident_metrics(service_db, inc, now=NOW), "errors")
    assert movement.not_comparable == "zero_baseline"
    assert movement.change_ratio is None
    assert movement.change_absolute == pytest.approx(7.0)


async def test_not_comparable_series_sort_last(service_db: AsyncSession, test_monitor: Monitor):
    """A measured +20% must outrank an unquantifiable one, never the reverse."""
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    baseline_start = STARTED - timedelta(hours=1)

    await _push(service_db, test_monitor, "measured", [10] * 10, start=baseline_start)
    await _push(service_db, test_monitor, "measured", [12] * 10, start=STARTED)
    await _push(service_db, test_monitor, "newborn", [999] * 10, start=STARTED)

    result = await correlate_incident_metrics(service_db, inc, now=NOW)
    assert [m.metric_name for m in result["series"]] == ["measured", "newborn"]


async def test_series_silent_on_both_sides_are_omitted(
    service_db: AsyncSession, test_monitor: Monitor
):
    """Not information — the series simply was not reporting in this period."""
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    await _push(service_db, test_monitor, "ancient", [1] * 5, start=STARTED - timedelta(days=30))
    result = await correlate_incident_metrics(service_db, inc, now=NOW)
    assert result["series"] == []


# ── Window handling ───────────────────────────────────────────────────────────


async def test_a_very_short_incident_still_gets_a_usable_window(
    service_db: AsyncSession, test_monitor: Monitor
):
    """40 seconds of baseline against a metric pushed each minute is nothing."""
    brief = await _incident(service_db, test_monitor, resolved=STARTED + timedelta(seconds=40))
    result = await correlate_incident_metrics(service_db, brief, now=NOW)
    assert result["window_seconds"] == int(MIN_WINDOW.total_seconds())


async def test_an_open_incident_is_measured_up_to_now(
    service_db: AsyncSession, test_monitor: Monitor
):
    inc = await _incident(service_db, test_monitor, resolved=None)
    result = await correlate_incident_metrics(service_db, inc, now=NOW)
    assert result["window_end"] == NOW
    # The baseline is the same length, immediately before.
    assert result["window_start"] - result["baseline_start"] == NOW - result["window_start"]


async def test_correlation_never_leaves_the_monitor(
    service_db: AsyncSession, test_monitor: Monitor, test_user: User
):
    """Metrics are pushed per monitor, so this cannot reach another tenant's."""
    other = Monitor(name="other", url="http://other", owner_id=test_user.id)
    service_db.add(other)
    await service_db.flush()

    inc = await _incident(service_db, test_monitor, resolved=NOW)
    await _push(service_db, other, "someone_elses", [1] * 10, start=STARTED)

    result = await correlate_incident_metrics(service_db, inc, now=NOW)
    assert result["series"] == []


# ── Post-mortem rendering ─────────────────────────────────────────────────────


async def test_markdown_says_correlation_not_causation(
    service_db: AsyncSession, test_monitor: Monitor
):
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    baseline_start = STARTED - timedelta(hours=1)
    await _push(service_db, test_monitor, "queue_depth", [10] * 10, start=baseline_start)
    await _push(service_db, test_monitor, "queue_depth", [40] * 10, start=STARTED)

    md = format_markdown(await correlate_incident_metrics(service_db, inc, now=NOW))
    assert "queue_depth" in md
    assert "+300%" in md
    assert "correlation, not causation" in md


async def test_markdown_is_explicit_when_there_is_nothing_to_show(
    service_db: AsyncSession, test_monitor: Monitor
):
    """An empty table would read as 'nothing moved', which is a different claim."""
    inc = await _incident(service_db, test_monitor, resolved=NOW)
    md = format_markdown(await correlate_incident_metrics(service_db, inc, now=NOW))
    assert "No application metrics" in md
