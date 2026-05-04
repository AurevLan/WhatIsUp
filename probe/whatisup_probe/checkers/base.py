"""Base classes for the checker plugin system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class CheckResult:
    """Result of a single monitor check."""

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
    scenario_result: dict | None = None
    dns_resolved_values: list[str] | None = None
    # HTTP waterfall timing
    dns_resolve_ms: int | None = None
    ttfb_ms: int | None = None
    download_ms: int | None = None
    # API schema fingerprint
    schema_fingerprint: str | None = None
    # V2-02-03 — TLS chain audit (version, cipher, SAN, SCT, grade)
    tls_audit: dict | None = None
    # V2-02-04 — DNS authoritative consistency (per-NS responses + drift flag)
    dns_consistency: dict | None = None

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
            "scenario_result": self.scenario_result,
            "dns_resolved_values": self.dns_resolved_values,
            "dns_resolve_ms": self.dns_resolve_ms,
            "ttfb_ms": self.ttfb_ms,
            "download_ms": self.download_ms,
            "schema_fingerprint": self.schema_fingerprint,
            "tls_audit": self.tls_audit,
            "dns_consistency": self.dns_consistency,
        }


class BaseChecker(ABC):
    """Abstract base class for all check type plugins.

    Subclasses must define ``name`` (the check_type string) and implement
    ``check()``.  They may also list ``aliases`` for check_type variants
    that should be routed to the same checker (e.g. keyword → http).
    """

    name: str = ""
    aliases: list[str] = []

    @abstractmethod
    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        """Execute the check and return a CheckResult.

        Parameters
        ----------
        monitor_id : str
            UUID of the monitor being checked.
        config : dict
            Full monitor configuration dict as received from the API.
        **kwargs : Any
            Extra runtime context (e.g. ``browser_pool``).
        """
        ...
