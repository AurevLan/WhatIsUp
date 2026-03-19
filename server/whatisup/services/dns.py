"""DNS semantic checks — drift detection and cross-probe consistency.

Called server-side after storing a DNS CheckResult (before commit).
Modifies result.status / result.error_message in-place when a violation is found.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
    Run drift detection and cross-probe consistency on a freshly stored DNS result.

    Must be called after db.flush() (result has an id) but before db.commit().
    Modifies result.status / result.error_message in-place when a violation is found.
    Does nothing if check_type != 'dns' or no DNS feature is enabled.
    """
    if monitor.check_type != "dns":
        return
    if not monitor.dns_drift_alert and not monitor.dns_consistency_check:
        return
    if result.dns_resolved_values is None:
        return
    # Only analyse results that are currently 'up' — don't override existing failures
    if result.status != CheckStatus.up:
        return

    current_ips = sorted(result.dns_resolved_values)

    # 1. Drift detection against stored baseline
    if monitor.dns_drift_alert:
        if monitor.dns_baseline_ips is None:
            # Auto-learn baseline on first successful check
            monitor.dns_baseline_ips = current_ips
            logger.info(
                "dns_baseline_learned",
                monitor_id=str(monitor.id),
                baseline=current_ips,
            )
        else:
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
                return  # Skip consistency check — already marked down

    # 2. Cross-probe consistency check
    if monitor.dns_consistency_check:
        # Look at recent results from other probes within 2 × interval window
        cutoff = datetime.now(UTC) - timedelta(seconds=monitor.interval_seconds * 2)
        other_results = (
            await db.execute(
                select(CheckResult.probe_id, CheckResult.dns_resolved_values)
                .where(
                    CheckResult.monitor_id == monitor.id,
                    CheckResult.probe_id != result.probe_id,
                    CheckResult.checked_at >= cutoff,
                    CheckResult.status == CheckStatus.up,
                    CheckResult.dns_resolved_values.isnot(None),
                )
                .order_by(CheckResult.checked_at.desc())
            )
        ).all()

        seen_probe_ips: dict[str, list[str]] = {}
        for row in other_results:
            pid = str(row.probe_id)
            if pid not in seen_probe_ips:
                seen_probe_ips[pid] = sorted(row.dns_resolved_values or [])

        for other_probe_id, other_ips in seen_probe_ips.items():
            if other_ips != current_ips:
                if monitor.dns_allow_split_horizon:
                    logger.info(
                        "dns_split_horizon_allowed",
                        monitor_id=str(monitor.id),
                        probe_a=str(result.probe_id),
                        ips_a=current_ips,
                        probe_b=other_probe_id,
                        ips_b=other_ips,
                    )
                else:
                    result.status = CheckStatus.down
                    result.error_message = (
                        f"DNS inconsistency: probe {str(result.probe_id)[:8]} sees "
                        f"{current_ips}, probe {other_probe_id[:8]} sees {other_ips}"
                    )
                    logger.warning(
                        "dns_inconsistency_detected",
                        monitor_id=str(monitor.id),
                        probe_a=str(result.probe_id),
                        ips_a=current_ips,
                        probe_b=other_probe_id,
                        ips_b=other_ips,
                    )
                    return
