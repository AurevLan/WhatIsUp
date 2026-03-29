"""ICMP ping checker."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .base import BaseChecker, CheckResult

_SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]{1,253}$")


class PingChecker(BaseChecker):
    name = "ping"

    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        parsed = urlparse(config.get("url", ""))
        host = parsed.hostname or config.get("url", "")
        timeout_seconds = config["timeout_seconds"]

        checked_at = datetime.now(UTC)

        # Validate host to prevent command injection
        if not _SAFE_HOST_RE.match(host):
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message="Invalid host for ping check",
            )

        t0 = time.perf_counter()

        try:
            proc = await asyncio.create_subprocess_exec(
                "ping",
                "-c", "1",
                "-W", str(timeout_seconds),
                host,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds + 5)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            if proc.returncode == 0:
                match = re.search(r"time=(\d+\.?\d*)", stdout.decode(errors="replace"))
                rtt_ms = float(match.group(1)) if match else round(elapsed_ms, 2)
                return CheckResult(
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    status="up",
                    response_time_ms=round(rtt_ms, 2),
                )
            else:
                return CheckResult(
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    status="down",
                    response_time_ms=round(elapsed_ms, 2),
                    error_message="Ping failed: host unreachable",
                )

        except TimeoutError:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="timeout",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"Ping timeout after {timeout_seconds}s",
            )
        except FileNotFoundError:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message="ping binary not found",
            )
        except Exception as exc:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"{type(exc).__name__}: {str(exc)[:200]}",
            )


def setup(register):
    register(PingChecker())
