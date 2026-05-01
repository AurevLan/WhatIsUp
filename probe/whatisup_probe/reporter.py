"""Push check results and heartbeat to the central server."""

from __future__ import annotations

import asyncio
import random

import httpx
import structlog

from whatisup_probe.checkers import CheckResult
from whatisup_probe.config import get_settings

logger = structlog.get_logger(__name__)

_FLUSH_INTERVAL = 5  # seconds between periodic flushes
_FLUSH_BATCH_SIZE = 10  # max concurrent POSTs per chunk
_QUEUE_MAX_SIZE = 500  # drop results if queue is full


class Reporter:
    def __init__(self) -> None:
        self._settings = get_settings()
        headers = {
            "X-Probe-Api-Key": self._settings.probe_api_key,
            "Content-Type": "application/json",
            "User-Agent": f"WhatIsUp-Probe/0.1 ({self._settings.probe_name})",
        }
        self._client = httpx.AsyncClient(
            timeout=10,
            verify=True,
            headers=headers,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        self._flush_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the background flush loop."""
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Cancel the flush loop and drain remaining results."""
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Final flush so nothing is lost on shutdown
        await self._flush_batch()

    async def push_result(self, result: CheckResult) -> None:
        """Queue a result for batched delivery (non-blocking)."""
        try:
            self._queue.put_nowait(result.to_dict())
        except asyncio.QueueFull:
            logger.warning("result_queue_full_dropping", monitor_id=result.monitor_id)

    async def _flush_loop(self) -> None:
        """Flush queued results every *_FLUSH_INTERVAL* seconds."""
        while True:
            await self._flush_batch()
            await asyncio.sleep(_FLUSH_INTERVAL)

    async def _flush_batch(self) -> None:
        """Send all queued results concurrently in chunks."""
        batch: list[dict] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not batch:
            return

        url = f"{self._settings.central_api_url}/api/v1/probes/results"
        for i in range(0, len(batch), _FLUSH_BATCH_SIZE):
            chunk = batch[i : i + _FLUSH_BATCH_SIZE]
            tasks = [self._post_one(url, payload) for payload in chunk]
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug("flush_batch_sent", count=len(batch))

    async def _post_one(self, url: str, payload: dict) -> bool:
        """Send a single result with retry (up to 3 attempts)."""
        for attempt in range(3):
            try:
                resp = await self._client.post(url, json=payload)
                if 200 <= resp.status_code < 300:
                    return True
                if resp.status_code < 500:
                    # 4xx — permanent error (bad key, forbidden…), no retry
                    logger.warning(
                        "push_rejected",
                        monitor_id=payload.get("monitor_id"),
                        status=resp.status_code,
                    )
                    return False
                # 5xx — retry
            except (httpx.ConnectError, httpx.TimeoutException):
                pass
            except Exception as exc:
                logger.warning(
                    "post_one_error",
                    monitor_id=payload.get("monitor_id"),
                    attempt=attempt + 1,
                    error=str(exc),
                )
            if attempt < 2:
                await asyncio.sleep(random.uniform(0.5, attempt + 1.5))
        logger.error("push_result_dropped", monitor_id=payload.get("monitor_id"))
        return False

    async def heartbeat(self, health: dict) -> dict | None:
        """Send heartbeat with system health metrics and retrieve probe directives.

        Returns the full server response (``{monitors, pending_diagnostics}``) or
        ``None`` on failure. V2-02-07: includes the probe's outbound public IP
        (resolved via api.ipify.org and friends) so the central server can
        detect proxy / NAT / VPN setups where the IP it observes
        (``request.client.host``) diverges from the IP the probe itself
        egresses through.
        """
        from whatisup_probe.public_ip import resolve_public_ip

        url = f"{self._settings.central_api_url}/api/v1/probes/heartbeat"
        self_reported_ip = await resolve_public_ip()
        body: dict = {"health": health}
        if self_reported_ip:
            body["self_reported_ip"] = self_reported_ip
        try:
            resp = await self._client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("heartbeat_failed", error=str(exc))
            return None

    async def push_diagnostics(
        self, incident_id: str, results: list[dict]
    ) -> bool:
        """POST a batch of diagnostic results for an incident (V2-01-01)."""
        url = f"{self._settings.central_api_url}/api/v1/probes/diagnostics"
        body = {"incident_id": incident_id, "results": results}
        try:
            resp = await self._client.post(url, json=body)
            if 200 <= resp.status_code < 300:
                return True
            logger.warning(
                "diagnostics_rejected",
                incident_id=incident_id,
                status=resp.status_code,
            )
            return False
        except Exception as exc:
            logger.warning(
                "diagnostics_push_error", incident_id=incident_id, error=str(exc)
            )
            return False

    async def aclose(self) -> None:
        await self.stop()
        await self._client.aclose()
