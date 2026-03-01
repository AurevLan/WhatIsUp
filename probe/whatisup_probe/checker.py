"""HTTP/HTTPS check engine — performs one check and returns a structured result."""

from __future__ import annotations

import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class CheckResult:
    monitor_id: str
    checked_at: datetime
    status: str  # up | down | timeout | error
    http_status: int | None = None
    response_time_ms: float | None = None
    redirect_count: int = 0
    final_url: str | None = None
    ssl_valid: bool | None = None
    ssl_expires_at: datetime | None = None
    ssl_days_remaining: int | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "checked_at": self.checked_at.isoformat(),
            "status": self.status,
            "http_status": self.http_status,
            "response_time_ms": self.response_time_ms,
            "redirect_count": self.redirect_count,
            "final_url": self.final_url,
            "ssl_valid": self.ssl_valid,
            "ssl_expires_at": self.ssl_expires_at.isoformat() if self.ssl_expires_at else None,
            "ssl_days_remaining": self.ssl_days_remaining,
            "error_message": self.error_message,
        }


def _extract_ssl_info(url: str) -> tuple[bool, datetime | None, int | None]:
    """
    Extract SSL certificate information for an HTTPS URL.
    Returns (ssl_valid, ssl_expires_at, ssl_days_remaining).
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        port = parsed.port or 443

        ctx = ssl.create_default_context()
        with ctx.wrap_socket(
            socket.create_connection((hostname, port), timeout=5),
            server_hostname=hostname,
        ) as ssock:
            cert = ssock.getpeercert()

        # not_after format: 'May 15 12:00:00 2025 GMT'
        not_after_str = cert.get("notAfter", "")
        if not_after_str:
            expires_at = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=UTC)
            days_remaining = (expires_at - datetime.now(UTC)).days
            return days_remaining > 0, expires_at, days_remaining

        return True, None, None
    except ssl.SSLCertVerificationError as exc:
        return False, None, None
    except Exception:
        return False, None, None


async def perform_check(
    monitor_id: str,
    url: str,
    timeout_seconds: int,
    follow_redirects: bool,
    expected_status_codes: list[int],
    ssl_check_enabled: bool,
) -> CheckResult:
    """
    Perform an HTTP(S) check and return a structured result.
    Uses httpx for async HTTP, ssl stdlib for certificate inspection.
    """
    import httpx

    checked_at = datetime.now(UTC)
    t0 = time.perf_counter()

    try:
        async with httpx.AsyncClient(
            follow_redirects=follow_redirects,
            timeout=httpx.Timeout(timeout_seconds),
            verify=True,
        ) as client:
            response = await client.get(url)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        http_status = response.status_code
        redirect_count = len(response.history)
        final_url = str(response.url)

        is_up = http_status in expected_status_codes
        status = "up" if is_up else "down"

        # SSL check
        ssl_valid = ssl_expires_at = ssl_days_remaining = None
        if ssl_check_enabled and url.startswith("https://"):
            ssl_valid, ssl_expires_at, ssl_days_remaining = _extract_ssl_info(final_url or url)

        return CheckResult(
            monitor_id=monitor_id,
            checked_at=checked_at,
            status=status,
            http_status=http_status,
            response_time_ms=round(elapsed_ms, 2),
            redirect_count=redirect_count,
            final_url=final_url,
            ssl_valid=ssl_valid,
            ssl_expires_at=ssl_expires_at,
            ssl_days_remaining=ssl_days_remaining,
        )

    except httpx.TimeoutException as exc:
        return CheckResult(
            monitor_id=monitor_id,
            checked_at=checked_at,
            status="timeout",
            response_time_ms=(time.perf_counter() - t0) * 1000,
            error_message=f"Timeout after {timeout_seconds}s",
        )
    except httpx.ConnectError as exc:
        return CheckResult(
            monitor_id=monitor_id,
            checked_at=checked_at,
            status="error",
            error_message=f"Connection error: {type(exc).__name__}",
        )
    except Exception as exc:
        return CheckResult(
            monitor_id=monitor_id,
            checked_at=checked_at,
            status="error",
            error_message=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
