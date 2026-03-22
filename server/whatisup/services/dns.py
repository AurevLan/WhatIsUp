"""DNS semantic checks — drift detection with optional split baseline by probe network type.

Called server-side after storing a DNS CheckResult (before commit).
Modifies result.status / result.error_message in-place when a violation is found.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from whatisup.models.monitor import Monitor
from whatisup.models.result import CheckResult, CheckStatus

logger = structlog.get_logger(__name__)


async def apply_dns_semantic_check(
    db: AsyncSession,
    monitor: Monitor,
    result: CheckResult,
) -> None:
    """
    Run drift detection on a freshly stored DNS result.

    In split mode (dns_split_enabled), maintains separate baselines for
    internal and external probes.

    Must be called after db.flush() (result has an id) but before db.commit().
    Modifies result.status / result.error_message in-place when a violation is found.
    Does nothing if check_type != 'dns' or dns_drift_alert is not enabled.
    """
    if monitor.check_type != "dns":
        return
    if not monitor.dns_drift_alert:
        return
    if result.dns_resolved_values is None:
        return
    # Only analyse results that are currently 'up' — don't override existing failures
    if result.status != CheckStatus.up:
        return

    current_ips = sorted(result.dns_resolved_values)

    if monitor.dns_split_enabled:
        # Split mode: separate baseline per probe network_type
        from whatisup.models.probe import NetworkType, Probe

        probe_row = (
            await db.execute(select(Probe).where(Probe.id == result.probe_id))
        ).scalar_one_or_none()
        net_type = probe_row.network_type if probe_row else NetworkType.external

        if net_type == NetworkType.internal:
            baseline = monitor.dns_baseline_ips_internal
            if baseline is None:
                monitor.dns_baseline_ips_internal = current_ips
                logger.info(
                    "dns_baseline_internal_learned",
                    monitor_id=str(monitor.id),
                    baseline=current_ips,
                )
                return
            baseline = sorted(baseline)
        else:
            baseline = monitor.dns_baseline_ips_external
            if baseline is None:
                monitor.dns_baseline_ips_external = current_ips
                logger.info(
                    "dns_baseline_external_learned",
                    monitor_id=str(monitor.id),
                    baseline=current_ips,
                )
                return
            baseline = sorted(baseline)

        if current_ips != baseline:
            net_label = "internal" if net_type == NetworkType.internal else "external"
            result.status = CheckStatus.down
            result.error_message = (
                f"DNS split drift ({net_label}): expected {baseline}, got {current_ips}"
            )
            logger.warning(
                "dns_split_drift_detected",
                monitor_id=str(monitor.id),
                net_type=net_label,
                baseline=baseline,
                got=current_ips,
            )
    else:
        # Normal mode: single baseline
        if monitor.dns_baseline_ips is None:
            monitor.dns_baseline_ips = current_ips
            logger.info(
                "dns_baseline_learned",
                monitor_id=str(monitor.id),
                baseline=current_ips,
            )
            return
        baseline = sorted(monitor.dns_baseline_ips)
        if current_ips != baseline:
            result.status = CheckStatus.down
            result.error_message = (
                f"DNS drift detected: expected {baseline}, got {current_ips}"
            )
            logger.warning(
                "dns_drift_detected",
                monitor_id=str(monitor.id),
                baseline=baseline,
                got=current_ips,
            )
