"""TCP port reachability checker."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .base import BaseChecker, CheckResult


class TCPChecker(BaseChecker):
    name = "tcp"

    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        parsed = urlparse(config.get("url", ""))
        host = parsed.hostname or config.get("url", "")
        port = config.get("tcp_port") or parsed.port or 80
        timeout_seconds = config["timeout_seconds"]

        checked_at = datetime.now(UTC)
        t0 = time.perf_counter()

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout_seconds,
            )
            writer.close()
            await writer.wait_closed()
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="up",
                response_time_ms=round(elapsed_ms, 2),
            )
        except TimeoutError:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="timeout",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"TCP timeout after {timeout_seconds}s",
            )
        except (ConnectionRefusedError, OSError) as exc:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="down",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"TCP connection refused: {exc}",
            )
        except Exception as exc:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"{type(exc).__name__}: {str(exc)[:200]}",
            )


def setup(register):
    register(TCPChecker())
