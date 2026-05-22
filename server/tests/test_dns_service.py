"""Coverage for DNS drift detection (split + normal baselines)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.probe import NetworkType, Probe
from whatisup.models.result import CheckResult, CheckStatus
from whatisup.models.user import User
from whatisup.services.dns import apply_dns_semantic_check


def _dns_monitor(owner: User, *, split: bool = False) -> Monitor:
    return Monitor(
        name="dns-test",
        url="dns://example.com",
        owner_id=owner.id,
        check_type="dns",
        dns_drift_alert=True,
        dns_split_enabled=split,
    )


async def _store(
    db: AsyncSession,
    monitor: Monitor,
    probe: Probe,
    values: list[str] | None,
    status: CheckStatus = CheckStatus.up,
) -> CheckResult:
    r = CheckResult(
        monitor_id=monitor.id,
        probe_id=probe.id,
        status=status,
        dns_resolved_values=values,
        checked_at=datetime.now(UTC),
    )
    db.add(r)
    await db.flush()
    return r


@pytest.mark.asyncio
async def test_non_dns_monitor_short_circuits(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    m = Monitor(name="http", url="http://x", owner_id=test_user.id, check_type="http")
    service_db.add(m)
    await service_db.flush()
    r = await _store(service_db, m, test_probe, ["1.2.3.4"])
    await apply_dns_semantic_check(service_db, m, r)
    assert r.status == CheckStatus.up


@pytest.mark.asyncio
async def test_drift_alert_disabled_skips(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    m = Monitor(
        name="dns-no-alert",
        url="dns://x",
        owner_id=test_user.id,
        check_type="dns",
        dns_drift_alert=False,
    )
    service_db.add(m)
    await service_db.flush()
    r = await _store(service_db, m, test_probe, ["1.2.3.4"])
    await apply_dns_semantic_check(service_db, m, r)
    assert m.dns_baseline_ips is None  # baseline never learned


@pytest.mark.asyncio
async def test_dns_baseline_learned_on_first_resolution(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    m = _dns_monitor(test_user)
    service_db.add(m)
    await service_db.flush()
    r = await _store(service_db, m, test_probe, ["1.2.3.4", "5.6.7.8"])
    await apply_dns_semantic_check(service_db, m, r)
    assert m.dns_baseline_ips == ["1.2.3.4", "5.6.7.8"]
    assert r.status == CheckStatus.up  # learning, not drift


@pytest.mark.asyncio
async def test_dns_drift_flips_status_when_ips_change(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    m = _dns_monitor(test_user)
    m.dns_baseline_ips = ["1.2.3.4"]
    service_db.add(m)
    await service_db.flush()
    r = await _store(service_db, m, test_probe, ["9.9.9.9"])
    await apply_dns_semantic_check(service_db, m, r)
    assert r.status == CheckStatus.down
    assert "DNS drift" in (r.error_message or "")


@pytest.mark.asyncio
async def test_dns_already_down_is_not_overridden(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    """Drift inspection must only run on currently-up results."""
    m = _dns_monitor(test_user)
    m.dns_baseline_ips = ["1.2.3.4"]
    service_db.add(m)
    await service_db.flush()
    r = await _store(service_db, m, test_probe, ["9.9.9.9"], status=CheckStatus.down)
    r.error_message = "original"
    await apply_dns_semantic_check(service_db, m, r)
    assert r.status == CheckStatus.down
    assert r.error_message == "original"


@pytest.mark.asyncio
async def test_dns_no_resolved_values_short_circuits(
    service_db: AsyncSession, test_user: User, test_probe: Probe
) -> None:
    m = _dns_monitor(test_user)
    service_db.add(m)
    await service_db.flush()
    r = await _store(service_db, m, test_probe, None)
    await apply_dns_semantic_check(service_db, m, r)
    assert m.dns_baseline_ips is None


# ── Split mode ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dns_split_learns_internal_and_external_separately(
    service_db: AsyncSession, test_user: User
) -> None:
    m = _dns_monitor(test_user, split=True)
    service_db.add(m)
    internal = Probe(
        name="int", location_name="lan", api_key_hash="x", network_type=NetworkType.internal
    )
    external = Probe(
        name="ext", location_name="wan", api_key_hash="y", network_type=NetworkType.external
    )
    service_db.add_all([internal, external])
    await service_db.flush()

    r_int = await _store(service_db, m, internal, ["10.0.0.1"])
    await apply_dns_semantic_check(service_db, m, r_int)
    assert m.dns_baseline_ips_internal == ["10.0.0.1"]
    assert m.dns_baseline_ips_external is None

    r_ext = await _store(service_db, m, external, ["8.8.8.8"])
    await apply_dns_semantic_check(service_db, m, r_ext)
    assert m.dns_baseline_ips_external == ["8.8.8.8"]


@pytest.mark.asyncio
async def test_dns_split_drift_internal(service_db: AsyncSession, test_user: User) -> None:
    m = _dns_monitor(test_user, split=True)
    m.dns_baseline_ips_internal = ["10.0.0.1"]
    m.dns_baseline_ips_external = ["8.8.8.8"]
    service_db.add(m)
    internal = Probe(
        name="int", location_name="lan", api_key_hash="x", network_type=NetworkType.internal
    )
    service_db.add(internal)
    await service_db.flush()

    r = await _store(service_db, m, internal, ["10.0.0.99"])
    await apply_dns_semantic_check(service_db, m, r)
    assert r.status == CheckStatus.down
    assert "internal" in (r.error_message or "")


@pytest.mark.asyncio
async def test_dns_split_falls_back_to_external_when_probe_unknown(
    service_db: AsyncSession, test_user: User
) -> None:
    """A result whose probe_id resolves to nothing is treated as external."""
    import uuid

    m = _dns_monitor(test_user, split=True)
    m.dns_baseline_ips_external = ["8.8.8.8"]
    service_db.add(m)
    await service_db.flush()

    # Probe row missing → service should still take the "external" branch.
    r = CheckResult(
        monitor_id=m.id,
        probe_id=uuid.uuid4(),
        status=CheckStatus.up,
        dns_resolved_values=["1.1.1.1"],
        checked_at=datetime.now(UTC),
    )
    service_db.add(r)
    await service_db.flush()
    await apply_dns_semantic_check(service_db, m, r)
    assert r.status == CheckStatus.down
    assert "external" in (r.error_message or "")
