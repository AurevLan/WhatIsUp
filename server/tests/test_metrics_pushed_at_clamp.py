"""`pushed_at` bounds on metric ingestion (audit hardening, 2026-08).

Before this, `pushed_at` was stored verbatim. `retention.py` purges on
`time_col < cutoff` and, on PostgreSQL, drops whole monthly partitions — a
point dated far in the future skips both and lands in the catch-all
`DEFAULT` partition, which is never itself dropped. At up to
6000 points/min/monitor that is an unrecoverable leak. The fix rejects with a
422 rather than silently clamping, consistent with how the other C-1 quotas
on this endpoint (rate, cardinality) already refuse loudly instead of
reshaping what the caller sent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_monitor(client: AsyncClient, token: str, name: str) -> dict:
    resp = await client.post(
        "/api/v1/monitors/",
        json={"name": name, "url": "https://example.com"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_pushed_at_within_bounds_is_accepted(client: AsyncClient, user_token: str) -> None:
    monitor = await _create_monitor(client, user_token, "ClampOk")
    at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    resp = await client.post(
        f"/api/v1/metrics/{monitor['id']}",
        json={"metric_name": "queue_depth", "value": 1.0, "pushed_at": at},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_pushed_at_missing_defaults_to_now(client: AsyncClient, user_token: str) -> None:
    """No `pushed_at` at all must keep working exactly as before this change."""
    monitor = await _create_monitor(client, user_token, "ClampDefault")
    resp = await client.post(
        f"/api/v1/metrics/{monitor['id']}",
        json={"metric_name": "queue_depth", "value": 1.0},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_pushed_at_far_in_the_future_is_rejected(
    client: AsyncClient, user_token: str
) -> None:
    """The upper bound: a few minutes of clock drift is fine, an hour is not."""
    monitor = await _create_monitor(client, user_token, "ClampFuture")
    at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    resp = await client.post(
        f"/api/v1/metrics/{monitor['id']}",
        json={"metric_name": "queue_depth", "value": 1.0, "pushed_at": at},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pushed_at_just_inside_the_future_slack_is_accepted(
    client: AsyncClient, user_token: str
) -> None:
    monitor = await _create_monitor(client, user_token, "ClampFutureOk")
    at = (datetime.now(UTC) + timedelta(minutes=2)).isoformat()
    resp = await client.post(
        f"/api/v1/metrics/{monitor['id']}",
        json={"metric_name": "queue_depth", "value": 1.0, "pushed_at": at},
        headers=_auth(user_token),
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_pushed_at_older_than_retention_is_rejected(
    client: AsyncClient, user_token: str
) -> None:
    """The lower bound: a point that would be purged on the next nightly run.

    Default `metrics_retention_days` is 90 — a point dated 91 days ago would
    never survive to be read back.
    """
    monitor = await _create_monitor(client, user_token, "ClampPast")
    at = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    resp = await client.post(
        f"/api/v1/metrics/{monitor['id']}",
        json={"metric_name": "queue_depth", "value": 1.0, "pushed_at": at},
        headers=_auth(user_token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_pushed_at_bounds_apply_per_item_in_a_batch(
    client: AsyncClient, user_token: str
) -> None:
    """One bad timestamp in a batch refuses the whole thing (all-or-nothing)."""
    monitor = await _create_monitor(client, user_token, "ClampBatch")
    good = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    bad = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = await client.post(
        f"/api/v1/metrics/{monitor['id']}",
        json=[
            {"metric_name": "queue_depth", "value": 1.0, "pushed_at": good},
            {"metric_name": "queue_depth", "value": 2.0, "pushed_at": bad},
        ],
        headers=_auth(user_token),
    )
    assert resp.status_code == 422

    listed = await client.get(f"/api/v1/metrics/{monitor['id']}", headers=_auth(user_token))
    assert listed.status_code == 200
    assert listed.json() == []
