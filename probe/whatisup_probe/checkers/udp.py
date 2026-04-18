"""UDP port checker."""

from __future__ import annotations

import asyncio
import socket
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .base import BaseChecker, CheckResult
from ._shared import validate_host_ssrf


class UDPChecker(BaseChecker):
    name = "udp"

    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        parsed = urlparse(config.get("url", ""))
        host = parsed.hostname or config.get("url", "")
        port = config.get("udp_port") or parsed.port or 80
        timeout_seconds = config["timeout_seconds"]

        checked_at = datetime.now(UTC)

        ssrf_err = validate_host_ssrf(host)
        if ssrf_err:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"SSRF blocked: {ssrf_err}",
            )

        t0 = time.perf_counter()

        def _udp_probe() -> tuple[str, str | None]:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout_seconds)
            try:
                sock.connect((host, port))
                sock.send(b"")
                try:
                    sock.recv(1024)
                    return "up", None
                except TimeoutError:
                    return "up", None
            except ConnectionRefusedError:
                return "down", f"UDP port {port} unreachable (ICMP port unreachable)"
            except TimeoutError:
                return "timeout", f"UDP timeout after {timeout_seconds}s"
            except OSError as exc:
                return "error", str(exc)
            finally:
                sock.close()

        try:
            loop = asyncio.get_running_loop()
            status, error_message = await asyncio.wait_for(
                loop.run_in_executor(None, _udp_probe),
                timeout=timeout_seconds + 2,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status=status,
                response_time_ms=round(elapsed_ms, 2),
                error_message=error_message,
            )
        except TimeoutError:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="timeout",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"UDP timeout after {timeout_seconds}s",
            )
        except Exception as exc:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"{type(exc).__name__}: {str(exc)[:200]}",
            )


def setup(register):
    register(UDPChecker())
