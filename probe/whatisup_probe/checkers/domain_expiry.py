"""Domain WHOIS expiry checker."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .base import BaseChecker, CheckResult


class DomainExpiryChecker(BaseChecker):
    name = "domain_expiry"

    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        parsed = urlparse(config.get("url", ""))
        host = parsed.hostname or config.get("url", "")
        warn_days = config.get("domain_expiry_warn_days", 30)
        timeout_seconds = config["timeout_seconds"]

        checked_at = datetime.now(UTC)
        t0 = time.perf_counter()

        try:
            import whois  # type: ignore[import]
        except ImportError:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message="python-whois not installed — add it to probe dependencies",
            )

        try:
            loop = asyncio.get_running_loop()
            w = await asyncio.wait_for(
                loop.run_in_executor(None, whois.whois, host),
                timeout=timeout_seconds,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000

            expiry = w.expiration_date
            if isinstance(expiry, list):
                expiry = expiry[0]

            if expiry is None:
                return CheckResult(
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    status="error",
                    response_time_ms=round(elapsed_ms, 2),
                    error_message="Could not determine domain expiry date from WHOIS",
                )

            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=UTC)

            days_remaining = (expiry - datetime.now(UTC)).days

            if days_remaining <= 0:
                return CheckResult(
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    status="down",
                    response_time_ms=round(elapsed_ms, 2),
                    ssl_expires_at=expiry,
                    ssl_days_remaining=days_remaining,
                    error_message=f"Domain expired {-days_remaining} day(s) ago",
                )
            elif days_remaining <= warn_days:
                return CheckResult(
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    status="down",
                    response_time_ms=round(elapsed_ms, 2),
                    ssl_expires_at=expiry,
                    ssl_days_remaining=days_remaining,
                    error_message=f"Domain expires in {days_remaining}d (threshold: {warn_days}d)",
                )
            else:
                return CheckResult(
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    status="up",
                    response_time_ms=round(elapsed_ms, 2),
                    ssl_expires_at=expiry,
                    ssl_days_remaining=days_remaining,
                )

        except TimeoutError:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="timeout",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"WHOIS timeout after {timeout_seconds}s",
            )
        except Exception as exc:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"WHOIS error: {type(exc).__name__}: {str(exc)[:200]}",
            )


def setup(register):
    register(DomainExpiryChecker())
