"""APScheduler-based check scheduler for the probe agent."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import psutil
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from whatisup_probe.checker import PlaywrightPool, kill_stale_chromium, perform_check
from whatisup_probe.config import get_settings
from whatisup_probe.reporter import Reporter

logger = structlog.get_logger(__name__)


class ProbeScheduler:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._reporter = Reporter()
        self._scheduler = AsyncIOScheduler()
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrent_checks)
        # Playwright/Chromium is memory-heavy — cap concurrent browser instances
        # independently of max_concurrent_checks to avoid OOM on low-resource machines.
        self._scenario_semaphore = asyncio.Semaphore(
            self._settings.max_concurrent_scenarios
        )
        self._monitors: dict[str, dict[str, Any]] = {}  # monitor_id -> config
        self._browser_pool = PlaywrightPool()
        psutil.cpu_percent(interval=None)  # first call always returns 0.0; discard it

    def _make_job_id(self, monitor_id: str) -> str:
        return f"check_{monitor_id}"

    def _collect_health(self) -> dict:
        """Collect current system health metrics (non-blocking)."""
        try:
            load_avg_1m: float | None = round(os.getloadavg()[0], 2)
        except (AttributeError, OSError):
            load_avg_1m = None

        checks_running = self._settings.max_concurrent_checks - self._semaphore._value

        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
            "load_avg_1m": load_avg_1m,
            "monitors_active": len(self._monitors),
            "checks_running": max(0, checks_running),
        }

    async def _run_check(self, monitor: dict[str, Any]) -> None:
        is_scenario = monitor.get("check_type") == "scenario"
        # Hard outer timeout: monitor timeout + overhead to absorb async scheduling lag.
        # Scenarios get +30 s for context creation; other checks only need +5 s.
        hard_timeout = monitor["timeout_seconds"] + (30 if is_scenario else 5)
        async with self._semaphore:
            if is_scenario:
                await self._scenario_semaphore.acquire()
            try:
                result = await asyncio.wait_for(
                    perform_check(
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
                        browser_pool=self._browser_pool,
                    ),
                    timeout=hard_timeout,
                )
            except TimeoutError:
                logger.error(
                    "check_hard_timeout",
                    monitor_id=str(monitor["id"]),
                    hard_timeout=hard_timeout,
                )
                await kill_stale_chromium()
                return
            finally:
                if is_scenario:
                    self._scenario_semaphore.release()
            logger.debug(
                "check_done",
                monitor_id=result.monitor_id,
                status=result.status,
                response_time_ms=result.response_time_ms,
            )
            await self._reporter.push_result(result)

    async def sync_monitors(self) -> None:
        """Fetch monitor list from central and synchronize scheduled jobs."""
        monitors = await self._reporter.heartbeat(self._collect_health())
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
                existing.reschedule(IntervalTrigger(seconds=monitor["interval_seconds"], jitter=10))
                existing.modify(args=[monitor])
            else:
                self._scheduler.add_job(
                    self._run_check,
                    trigger=IntervalTrigger(seconds=monitor["interval_seconds"], jitter=10),
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
        # Clean up any Chromium zombies left by a previous crash
        killed = await kill_stale_chromium()
        if killed:
            logger.info("stale_chromium_killed", count=killed)

        # Start persistent browser pool (non-fatal if Playwright not installed)
        await self._browser_pool.start()

        # Initial sync
        await self.sync_monitors()

        # Schedule periodic heartbeat/sync
        self._scheduler.add_job(
            self.sync_monitors,
            trigger=IntervalTrigger(seconds=self._settings.heartbeat_interval, jitter=5),
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

    async def aclose(self) -> None:
        await self._browser_pool.aclose()
        await self._reporter.aclose()
