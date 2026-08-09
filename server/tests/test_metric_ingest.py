"""Batch ingestion, labels and quotas (plan V2, C-1).

The properties worth pinning, in order of how badly they would hurt:

1. the single-object push still works and still answers what it always did —
   every agent already pushing depends on it;
2. a quota refuses **loudly and completely**, because a partially-applied batch
   is indistinguishable from a lost one at the next scrape;
3. labels identify a series canonically, so key order cannot silently split one
   series into two.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.test_background_services import _FactoryStub
from whatisup.core import database as db_mod
from whatisup.core.config import get_settings
from whatisup.models.custom_metric import CustomMetric, MetricSeries, series_hash
from whatisup.models.monitor import Monitor
from whatisup.services.metric_ingest import (
    IngestPoint,
    QuotaExceeded,
    ingest_points,
)
from whatisup.services.metric_series import labels_match, resolve_series
from whatisup.services.retention import purge_stale_metric_series

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def bound_db(service_db: AsyncSession, monkeypatch) -> AsyncSession:
    """Point the retention job's own session factory at the test session.

    ``purge_stale_metric_series`` opens its own session, as every background
    job does; without this it reaches for the real database.
    """
    monkeypatch.setattr(db_mod, "_async_session_factory", _FactoryStub(service_db))
    return service_db


def _point(name="queue_depth", value=1.0, labels=None, at=NOW, unit=None) -> IngestPoint:
    return IngestPoint(metric_name=name, value=value, unit=unit, labels=labels or {}, pushed_at=at)


async def _count(db: AsyncSession, model) -> int:
    return (await db.execute(select(func.count(model.id)))).scalar_one()


# ── Series identity ───────────────────────────────────────────────────────────


def test_series_hash_is_canonical_across_key_order():
    """Label order is a serialisation accident, not part of the identity.

    Without sorting, `{"a":1,"b":2}` and `{"b":2,"a":1}` would be two series —
    the same data split in half, each with its own chart and its own alert.
    """
    assert series_hash("m", {"a": "1", "b": "2"}) == series_hash("m", {"b": "2", "a": "1"})


def test_series_hash_separates_what_should_be_separate():
    assert series_hash("m", {"a": "1"}) != series_hash("m", {"a": "2"})
    assert series_hash("m", {"a": "1"}) != series_hash("n", {"a": "1"})
    assert series_hash("m", None) == series_hash("m", {})


@pytest.mark.parametrize(
    ("labels", "selector", "expected"),
    [
        ({"route": "/api", "method": "GET"}, {"route": "/api"}, True),  # subset
        ({"route": "/api"}, {"route": "/api", "method": "GET"}, False),  # superset
        ({"route": "/api"}, None, True),  # no selector matches everything
        ({"route": "/api"}, {}, True),
        ({}, {"route": "/api"}, False),
    ],
)
def test_labels_match_is_a_subset_test(labels, selector, expected):
    assert labels_match(labels, selector) is expected


# ── Ingestion ─────────────────────────────────────────────────────────────────


async def test_batch_registers_one_series_per_label_set(
    service_db: AsyncSession, test_monitor: Monitor
):
    accepted = await ingest_points(
        service_db,
        test_monitor.id,
        [
            _point(labels={"route": "/api"}, value=1),
            _point(labels={"route": "/api"}, value=2),
            _point(labels={"route": "/health"}, value=3),
            _point(labels={}, value=4),
        ],
    )
    assert accepted == 4
    assert await _count(service_db, CustomMetric) == 4
    # Three distinct label sets, not four points.
    assert await _count(service_db, MetricSeries) == 3


async def test_series_registry_tracks_liveness_and_unit(
    service_db: AsyncSession, test_monitor: Monitor
):
    await ingest_points(service_db, test_monitor.id, [_point(at=NOW, unit="req/min")])
    later = NOW + timedelta(minutes=5)
    await ingest_points(service_db, test_monitor.id, [_point(at=later, unit="rpm")])

    (row,) = (await service_db.execute(select(MetricSeries))).scalars().all()
    assert row.first_seen_at.replace(tzinfo=UTC) == NOW
    assert row.last_seen_at.replace(tzinfo=UTC) == later
    # An application is allowed to correct the unit of a series it owns.
    assert row.unit == "rpm"


async def test_resolve_series_honours_the_selector(service_db: AsyncSession, test_monitor: Monitor):
    await ingest_points(
        service_db,
        test_monitor.id,
        [
            _point(labels={"route": "/api", "method": "GET"}),
            _point(labels={"route": "/api", "method": "POST"}),
            _point(labels={"route": "/health", "method": "GET"}),
        ],
    )
    assert len(await resolve_series(service_db, test_monitor.id, "queue_depth")) == 3
    assert (
        len(await resolve_series(service_db, test_monitor.id, "queue_depth", {"route": "/api"}))
        == 2
    )
    assert (
        len(
            await resolve_series(
                service_db, test_monitor.id, "queue_depth", {"route": "/api", "method": "GET"}
            )
        )
        == 1
    )
    assert (
        await resolve_series(service_db, test_monitor.id, "queue_depth", {"route": "/nope"}) == []
    )


# ── Quotas ────────────────────────────────────────────────────────────────────


async def test_rate_quota_refuses_the_whole_batch(
    service_db: AsyncSession, test_monitor: Monitor, monkeypatch
):
    """Nothing is stored, so the caller knows exactly what to resend."""
    settings = get_settings()
    monkeypatch.setattr(settings, "metrics_max_points_per_minute", 3, raising=False)

    await ingest_points(service_db, test_monitor.id, [_point(value=1), _point(value=2)])
    assert await _count(service_db, CustomMetric) == 2

    with pytest.raises(QuotaExceeded) as excinfo:
        await ingest_points(service_db, test_monitor.id, [_point(value=3), _point(value=4)])
    assert excinfo.value.kind == "rate"
    assert excinfo.value.retry_after >= 1
    # All-or-nothing: the two points of the refused batch are not there.
    assert await _count(service_db, CustomMetric) == 2


async def test_refused_batch_gives_its_budget_back(
    service_db: AsyncSession, test_monitor: Monitor, monkeypatch
):
    """A rejected caller must not also burn the window for the one that retries."""
    settings = get_settings()
    monkeypatch.setattr(settings, "metrics_max_points_per_minute", 3, raising=False)

    with pytest.raises(QuotaExceeded):
        await ingest_points(service_db, test_monitor.id, [_point()] * 5)
    # The window still has its full budget: the oversized batch consumed none.
    assert await ingest_points(service_db, test_monitor.id, [_point()] * 3) == 3


async def test_cardinality_quota_refuses_and_names_the_offender(
    service_db: AsyncSession, test_monitor: Monitor, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "metrics_max_series_per_monitor", 2, raising=False)

    await ingest_points(
        service_db,
        test_monitor.id,
        [_point(labels={"u": "1"}), _point(labels={"u": "2"})],
    )
    with pytest.raises(QuotaExceeded) as excinfo:
        await ingest_points(service_db, test_monitor.id, [_point(labels={"u": "3"})])

    assert excinfo.value.kind == "cardinality"
    # "cardinality exceeded" with no offending series is a message nobody can act on.
    assert "queue_depth" in excinfo.value.detail
    assert 'u="3"' in excinfo.value.detail
    assert await _count(service_db, MetricSeries) == 2


async def test_points_on_an_existing_series_ignore_the_cardinality_cap(
    service_db: AsyncSession, test_monitor: Monitor, monkeypatch
):
    """The cap bounds distinct series, never how often you push to them."""
    settings = get_settings()
    monkeypatch.setattr(settings, "metrics_max_series_per_monitor", 1, raising=False)

    await ingest_points(service_db, test_monitor.id, [_point(labels={"u": "1"})])
    assert await ingest_points(service_db, test_monitor.id, [_point(labels={"u": "1"})] * 10) == 10


async def test_zero_means_unlimited(service_db: AsyncSession, test_monitor: Monitor, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "metrics_max_points_per_minute", 0, raising=False)
    monkeypatch.setattr(settings, "metrics_max_series_per_monitor", 0, raising=False)
    assert (
        await ingest_points(
            service_db, test_monitor.id, [_point(labels={"u": str(i)}) for i in range(20)]
        )
        == 20
    )


# ── Retention of the registry ─────────────────────────────────────────────────


async def test_stale_series_free_their_slot(bound_db: AsyncSession, test_monitor: Monitor):
    service_db = bound_db
    """A renamed metric must not hold a cardinality slot forever."""
    old = datetime.now(UTC) - timedelta(days=120)
    await ingest_points(service_db, test_monitor.id, [_point(name="old_name", at=old)])
    await ingest_points(service_db, test_monitor.id, [_point(name="new_name")])
    await service_db.commit()
    assert await _count(service_db, MetricSeries) == 2

    assert await purge_stale_metric_series(90) == 1
    remaining = (await service_db.execute(select(MetricSeries))).scalars().all()
    assert [s.metric_name for s in remaining] == ["new_name"]


async def test_retention_disabled_keeps_every_series(bound_db: AsyncSession, test_monitor: Monitor):
    service_db = bound_db
    await ingest_points(
        service_db,
        test_monitor.id,
        [_point(at=datetime.now(UTC) - timedelta(days=400))],
    )
    await service_db.commit()
    assert await purge_stale_metric_series(0) == 0
    assert await _count(service_db, MetricSeries) == 1
