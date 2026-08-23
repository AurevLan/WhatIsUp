"""Push check results and heartbeat to the central server."""

from __future__ import annotations

import asyncio
import random
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

import httpx
import structlog

from whatisup_probe.checkers import CheckResult
from whatisup_probe.config import get_settings
from whatisup_probe.spill import DiskSpill

logger = structlog.get_logger(__name__)

try:
    PROBE_VERSION = pkg_version("whatisup-probe")
except PackageNotFoundError:  # editable/dev checkout without install
    PROBE_VERSION = "0.0.0-dev"

_FLUSH_INTERVAL = 5  # seconds between periodic flushes
_FLUSH_BATCH_SIZE = 10  # max concurrent POSTs per chunk
_QUEUE_MAX_SIZE = 500  # spill to disk if queue is full
_SPILL_RETRY_EVERY = 6  # retry spilled results every N flushes (~30 s)


class Reporter:
    def __init__(self) -> None:
        self._settings = get_settings()
        headers = {
            "X-Probe-Api-Key": self._settings.probe_api_key,
            "Content-Type": "application/json",
            "User-Agent": f"WhatIsUp-Probe/{PROBE_VERSION} ({self._settings.probe_name})",
        }
        self._client = httpx.AsyncClient(
            timeout=10,
            verify=True,
            headers=headers,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=_QUEUE_MAX_SIZE)
        self._flush_task: asyncio.Task | None = None
        self._spill = DiskSpill(
            path=self._settings.result_spill_path,
            max_entries=self._settings.result_spill_max_entries,
        )
        self._flush_count = 0

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
            # Queue overflow (central API likely down) — persist to disk
            # instead of dropping; re-sent once the API is reachable again.
            logger.warning("result_queue_full_spilling", monitor_id=result.monitor_id)
            self._spill.append(result.to_dict())

    async def _flush_loop(self) -> None:
        """Flush queued results every *_FLUSH_INTERVAL* seconds."""
        while True:
            try:
                await self._flush_batch()
            except Exception as exc:  # noqa: BLE001 — a dead flush loop means silent data loss
                logger.error("flush_loop_unexpected_error", error=str(exc))
            await asyncio.sleep(_FLUSH_INTERVAL)

    async def _flush_batch(self) -> None:
        """Send all queued results concurrently in chunks."""
        batch: list[dict] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        # Periodically retry results spilled to disk during an API outage
        self._flush_count += 1
        if self._flush_count % _SPILL_RETRY_EVERY == 0:
            spilled = self._spill.pop_batch(_FLUSH_BATCH_SIZE * 2)
            if spilled:
                logger.info("spill_resend_attempt", count=len(spilled))
                batch.extend(spilled)

        if not batch:
            return

        url = f"{self._settings.central_api_url}/api/v1/probes/results"
        for i in range(0, len(batch), _FLUSH_BATCH_SIZE):
            chunk = batch[i : i + _FLUSH_BATCH_SIZE]
            tasks = [self._post_one(url, payload) for payload in chunk]
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            for payload, outcome in zip(chunk, outcomes, strict=True):
                # None = transient failure (network/5xx after retries) → keep on disk.
                # False = permanent 4xx reject → drop. Exception = unexpected → keep.
                if outcome is None or isinstance(outcome, Exception):
                    self._spill.append(payload)

        logger.debug("flush_batch_sent", count=len(batch))

    async def _post_one(self, url: str, payload: dict) -> bool | None:
        """Send a single result with retry (up to 3 attempts).

        Returns True if delivered, False on permanent 4xx rejection, and
        None on transient failure (caller spills the payload to disk).
        """
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
        logger.warning("push_result_spilled", monitor_id=payload.get("monitor_id"))
        return None

    async def heartbeat(
        self, health: dict, discovery_capabilities: list[str] | None = None
    ) -> dict | None:
        """Send heartbeat with system health metrics and retrieve probe directives.

        Returns the full server response (``{monitors, pending_diagnostics,
        discovery_sources}``) or ``None`` on failure. V2-02-07: includes the
        probe's outbound public IP (resolved via api.ipify.org and friends)
        so the central server can detect proxy / NAT / VPN setups where the
        IP it observes (``request.client.host``) diverges from the IP the
        probe itself egresses through.

        ``discovery_capabilities`` (plan D, D-1) is omitted entirely from the
        body when ``None`` — not sent as ``null`` — so the server's
        write-if-present rule (``model_fields_set``) never clears a
        previously-declared value on a heartbeat this build doesn't compute
        it for.
        """
        from whatisup_probe.public_ip import resolve_public_ip

        url = f"{self._settings.central_api_url}/api/v1/probes/heartbeat"
        self_reported_ip = await resolve_public_ip()
        body: dict = {"health": health, "version": PROBE_VERSION}
        if self_reported_ip:
            body["self_reported_ip"] = self_reported_ip
        if discovery_capabilities is not None:
            body["discovery_capabilities"] = discovery_capabilities
        try:
            resp = await self._client.post(url, json=body)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("heartbeat_failed", error=str(exc))
            return None

    async def push_diagnostics(self, incident_id: str, results: list[dict]) -> bool:
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
            logger.warning("diagnostics_push_error", incident_id=incident_id, error=str(exc))
            return False

    async def push_discovery(self, source_id: str, services: list[dict]) -> bool:
        """POST a discovery snapshot for one source (plan D, D-1).

        Best-effort like ``push_diagnostics`` — no disk spill: a lost
        snapshot is simply replayed at the next scheduled run of the same
        source (``discovery_interval_seconds``), unlike a check result there
        is no incident pipeline waiting on this push.
        """
        url = f"{self._settings.central_api_url}/api/v1/probes/discovery"
        body = {"source_id": source_id, "services": services}
        try:
            resp = await self._client.post(url, json=body)
            if 200 <= resp.status_code < 300:
                return True
            logger.warning(
                "discovery_push_rejected",
                source_id=source_id,
                status=resp.status_code,
            )
            return False
        except Exception as exc:
            logger.warning("discovery_push_error", source_id=source_id, error=str(exc))
            return False

    async def aclose(self) -> None:
        await self.stop()
        await self._client.aclose()
