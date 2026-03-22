"""APScheduler-based check scheduler for the probe agent."""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from whatisup_probe.checker import perform_check
from whatisup_probe.config import get_settings
from whatisup_probe.reporter import Reporter

logger = structlog.get_logger(__name__)


class ProbeScheduler:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._reporter = Reporter()
        self._scheduler = AsyncIOScheduler()
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrent_checks)
        self._monitors: dict[str, dict[str, Any]] = {}  # monitor_id -> config

    def _make_job_id(self, monitor_id: str) -> str:
        return f"check_{monitor_id}"

    async def _run_check(self, monitor: dict[str, Any]) -> None:
        async with self._semaphore:
            result = await perform_check(
                monitor_id=str(monitor["id"]),
                url=monitor["url"],
                timeout_seconds=monitor["timeout_seconds"],
                follow_redirects=monitor["follow_redirects"],
                expected_status_codes=monitor["expected_status_codes"],
                ssl_check_enabled=monitor["ssl_check_enabled"],
                check_type=monitor.get("check_type", "http"),
                tcp_port=monitor.get("tcp_port"),
                udp_port=monitor.get("udp_port"),
                dns_record_type=monitor.get("dns_record_type"),
                dns_expected_value=monitor.get("dns_expected_value"),
                keyword=monitor.get("keyword"),
                keyword_negate=monitor.get("keyword_negate", False),
                expected_json_path=monitor.get("expected_json_path"),
                expected_json_value=monitor.get("expected_json_value"),
                steps=monitor.get("scenario_steps") or monitor.get("steps"),
                variables=monitor.get("scenario_variables") or monitor.get("variables"),
                body_regex=monitor.get("body_regex"),
                expected_headers=monitor.get("expected_headers"),
                json_schema=monitor.get("json_schema"),
                smtp_port=monitor.get("smtp_port"),
                smtp_starttls=monitor.get("smtp_starttls", False),
                domain_expiry_warn_days=monitor.get("domain_expiry_warn_days", 30),
                schema_drift_enabled=monitor.get("schema_drift_enabled", False),
            )
            logger.debug(
                "check_done",
                monitor_id=result.monitor_id,
                status=result.status,
                response_time_ms=result.response_time_ms,
            )
            await self._reporter.push_result(result)

    async def sync_monitors(self) -> None:
        """Fetch monitor list from central and synchronize scheduled jobs."""
        monitors = await self._reporter.heartbeat()
        if monitors is None:
            logger.warning("heartbeat_failed_skipping_sync")
            return

        new_ids = {str(m["id"]) for m in monitors}
        current_ids = set(self._monitors.keys())

        # Remove stale jobs
        for mid in current_ids - new_ids:
            job = self._scheduler.get_job(self._make_job_id(mid))
            if job:
                job.remove()
            del self._monitors[mid]
            logger.info("monitor_removed", monitor_id=mid)

        # Add or update jobs
        for monitor in monitors:
            mid = str(monitor["id"])
            old = self._monitors.get(mid)
            if old and old == monitor:
                continue  # No change needed

            self._monitors[mid] = monitor
            job_id = self._make_job_id(mid)
            existing = self._scheduler.get_job(job_id)

            if existing:
                existing.reschedule(IntervalTrigger(seconds=monitor["interval_seconds"]))
                existing.modify(args=[monitor])
            else:
                self._scheduler.add_job(
                    self._run_check,
                    trigger=IntervalTrigger(seconds=monitor["interval_seconds"]),
                    args=[monitor],
                    id=job_id,
                    name=f"check:{mid[:8]}",
                    max_instances=1,
                    coalesce=True,
                    replace_existing=True,
                )
                logger.info("monitor_added", monitor_id=mid, interval=monitor["interval_seconds"])

        # Trigger immediate checks for monitors flagged by the server
        for monitor in monitors:
            if monitor.get("trigger_now"):
                logger.info("trigger_check_immediate", monitor_id=str(monitor["id"]))
                task = asyncio.ensure_future(self._run_check(monitor))
                task.add_done_callback(
                    lambda t: logger.error(
                        "trigger_check_failed",
                        error=str(t.exception()),
                    )
                    if not t.cancelled() and t.exception()
                    else None
                )

    async def start(self) -> None:
        """Start the scheduler and heartbeat loop."""
        # Initial sync
        await self.sync_monitors()

        # Schedule periodic heartbeat/sync
        self._scheduler.add_job(
            self.sync_monitors,
            trigger=IntervalTrigger(seconds=self._settings.heartbeat_interval),
            id="heartbeat",
            name="heartbeat",
            max_instances=1,
            coalesce=True,
        )

        self._scheduler.start()
        logger.info("probe_scheduler_started", location=self._settings.probe_location)

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        logger.info("probe_scheduler_stopped")
