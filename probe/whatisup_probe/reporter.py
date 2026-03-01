"""Push check results and heartbeat to the central server."""

from __future__ import annotations

import httpx
import structlog

from whatisup_probe.checker import CheckResult
from whatisup_probe.config import get_settings

logger = structlog.get_logger(__name__)


class Reporter:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._headers = {
            "X-Probe-Api-Key": self._settings.probe_api_key,
            "Content-Type": "application/json",
            "User-Agent": f"WhatIsUp-Probe/0.1 ({self._settings.probe_name})",
        }

    async def push_result(self, result: CheckResult) -> bool:
        url = f"{self._settings.central_api_url}/api/v1/probes/results"
        try:
            async with httpx.AsyncClient(timeout=10, verify=True) as client:
                resp = await client.post(url, json=result.to_dict(), headers=self._headers)
                resp.raise_for_status()
                return True
        except httpx.HTTPStatusError as exc:
            logger.error(
                "push_result_failed",
                monitor_id=result.monitor_id,
                status_code=exc.response.status_code,
            )
            return False
        except Exception as exc:
            logger.error("push_result_error", monitor_id=result.monitor_id, error=str(exc))
            return False

    async def heartbeat(self) -> list[dict] | None:
        """Send heartbeat and retrieve current monitor configs."""
        url = f"{self._settings.central_api_url}/api/v1/probes/heartbeat"
        try:
            async with httpx.AsyncClient(timeout=10, verify=True) as client:
                resp = await client.get(url, headers=self._headers)
                resp.raise_for_status()
                data = resp.json()
                return data.get("monitors", [])
        except Exception as exc:
            logger.error("heartbeat_failed", error=str(exc))
            return None
