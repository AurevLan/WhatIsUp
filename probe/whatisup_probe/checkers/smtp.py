"""SMTP server checker."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from .base import BaseChecker, CheckResult


class SMTPChecker(BaseChecker):
    name = "smtp"

    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        parsed = urlparse(config.get("url", ""))
        host = parsed.hostname or config.get("url", "")
        port = config.get("smtp_port") or parsed.port or 25
        timeout_seconds = config["timeout_seconds"]
        starttls = config.get("smtp_starttls", False)

        checked_at = datetime.now(UTC)
        t0 = time.perf_counter()

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=timeout_seconds,
            )

            # Read SMTP banner (220 …)
            banner_line = await asyncio.wait_for(reader.readline(), timeout=timeout_seconds)
            banner = banner_line.decode(errors="replace").strip()
            if not banner.startswith("220"):
                writer.close()
                return CheckResult(
                    monitor_id=monitor_id,
                    checked_at=checked_at,
                    status="down",
                    response_time_ms=round((time.perf_counter() - t0) * 1000, 2),
                    error_message=f"Unexpected SMTP banner: {banner[:200]}",
                )

            # EHLO
            writer.write(b"EHLO whatisup-monitor\r\n")
            await writer.drain()
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=timeout_seconds)
                decoded = line.decode(errors="replace")
                if decoded.startswith("250 ") or not decoded.startswith("250"):
                    break

            if starttls:
                writer.write(b"STARTTLS\r\n")
                await writer.drain()
                starttls_line = await asyncio.wait_for(reader.readline(), timeout=timeout_seconds)
                starttls_resp = starttls_line.decode(errors="replace").strip()
                if not starttls_resp.startswith("220"):
                    writer.close()
                    return CheckResult(
                        monitor_id=monitor_id,
                        checked_at=checked_at,
                        status="down",
                        response_time_ms=round((time.perf_counter() - t0) * 1000, 2),
                        error_message=f"STARTTLS rejected: {starttls_resp[:200]}",
                    )

            writer.write(b"QUIT\r\n")
            await writer.drain()
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
                error_message=f"SMTP timeout after {timeout_seconds}s",
            )
        except (ConnectionRefusedError, OSError) as exc:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="down",
                response_time_ms=(time.perf_counter() - t0) * 1000,
                error_message=f"SMTP connection refused: {exc}",
            )
        except Exception as exc:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"{type(exc).__name__}: {str(exc)[:200]}",
            )


def setup(register):
    register(SMTPChecker())
