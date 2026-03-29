"""DNS resolution checker."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .base import BaseChecker, CheckResult


class DNSChecker(BaseChecker):
    name = "dns"

    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        import dns.resolver  # type: ignore[import]

        parsed = urlparse(config.get("url", ""))
        host = parsed.hostname or config.get("url", "")
        record_type = config.get("dns_record_type") or "A"
        expected_value = config.get("dns_expected_value")
        timeout_seconds = config["timeout_seconds"]

        checked_at = datetime.now(UTC)
        t0 = time.perf_counter()

        try:
            resolver = dns.resolver.Resolver()
            resolver.lifetime = timeout_seconds

            loop = asyncio.get_running_loop()
            answers = await asyncio.wait_for(
                loop.run_in_executor(None, resolver.resolve, host, record_type),
                timeout=timeout_seconds + 2,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000

            resolved_values = [str(r) for r in answers]

            if expected_value and not any(expected_value in v for v in resolved_values):
                return CheckResult(
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    status="down",
                    response_time_ms=round(elapsed_ms, 2),
                    error_message=(
                        f"DNS {record_type} for {host}: expected {expected_value!r}, "
                        f"got {resolved_values}"
                    ),
                )

            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="up",
                response_time_ms=round(elapsed_ms, 2),
                dns_resolved_values=resolved_values,
            )

        except dns.resolver.NXDOMAIN:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="down",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"DNS NXDOMAIN: {host} does not exist",
            )
        except dns.resolver.Timeout:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="timeout",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"DNS timeout after {timeout_seconds}s",
            )
        except Exception as exc:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"DNS error: {type(exc).__name__}: {str(exc)[:200]}",
            )


def setup(register):
    register(DNSChecker())
