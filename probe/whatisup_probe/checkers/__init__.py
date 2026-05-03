"""Checker plugin system — registry and dispatch.

Usage::

    from whatisup_probe.checkers import perform_check, CheckResult, REGISTRY

All built-in checkers are auto-registered on import.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseChecker, CheckResult

logger = logging.getLogger(__name__)

# ── Registry ──────────────────────────────────────────────────────────────────

REGISTRY: dict[str, BaseChecker] = {}


def register(checker: BaseChecker) -> BaseChecker:
    """Register a checker instance for its name and aliases."""
    REGISTRY[checker.name] = checker
    for alias in checker.aliases:
        REGISTRY[alias] = checker
    return checker


def _load_builtins() -> None:
    """Import all built-in checker modules and call their setup(register)."""
    from . import dns, domain_expiry, http, ping, scenario, smtp, tcp, udp

    for module in (http, tcp, udp, dns, smtp, ping, domain_expiry, scenario):
        module.setup(register)


_load_builtins()


# ── Dispatch ──────────────────────────────────────────────────────────────────

async def perform_check(
    monitor_id: str,
    url: str,
    timeout_seconds: int,
    follow_redirects: bool,
    expected_status_codes: list[int],
    ssl_check_enabled: bool,
    check_type: str = "http",
    tcp_port: int | None = None,
    udp_port: int | None = None,
    dns_record_type: str | None = None,
    dns_expected_value: str | None = None,
    keyword: str | None = None,
    keyword_negate: bool = False,
    expected_json_path: str | None = None,
    expected_json_value: str | None = None,
    steps: list | None = None,
    variables: list | None = None,
    body_regex: str | None = None,
    expected_headers: dict[str, str] | None = None,
    json_schema: dict | None = None,
    custom_headers: dict[str, str] | None = None,
    smtp_port: int | None = None,
    smtp_starttls: bool = False,
    domain_expiry_warn_days: int = 30,
    schema_drift_enabled: bool = False,
    browser_pool: Any | None = None,
) -> CheckResult:
    """Dispatch to the appropriate checker plugin.

    Signature is kept backward-compatible with scheduler.py.
    Internally packs all parameters into a config dict and delegates
    to the registered checker.
    """
    config: dict[str, Any] = {
        "url": url,
        "timeout_seconds": timeout_seconds,
        "follow_redirects": follow_redirects,
        "expected_status_codes": expected_status_codes,
        "ssl_check_enabled": ssl_check_enabled,
        "check_type": check_type,
        "tcp_port": tcp_port,
        "udp_port": udp_port,
        "dns_record_type": dns_record_type,
        "dns_expected_value": dns_expected_value,
        "keyword": keyword,
        "keyword_negate": keyword_negate,
        "expected_json_path": expected_json_path,
        "expected_json_value": expected_json_value,
        "steps": steps,
        "variables": variables,
        "body_regex": body_regex,
        "expected_headers": expected_headers,
        "json_schema": json_schema,
        "custom_headers": custom_headers,
        "smtp_port": smtp_port,
        "smtp_starttls": smtp_starttls,
        "domain_expiry_warn_days": domain_expiry_warn_days,
        "schema_drift_enabled": schema_drift_enabled,
    }

    checker = REGISTRY.get(check_type)
    if checker is None:
        # Fallback to http for unknown types
        checker = REGISTRY["http"]
        logger.warning("unknown_check_type_fallback_http: %s", check_type)

    return await checker.check(monitor_id, config, browser_pool=browser_pool)


__all__ = [
    "BaseChecker",
    "CheckResult",
    "REGISTRY",
    "register",
    "perform_check",
]
