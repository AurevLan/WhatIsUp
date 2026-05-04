"""HTTP/HTTPS checker — also handles keyword and json_path variants."""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from ._shared import (
    _cached_getaddrinfo,
    compute_schema_fingerprint,
    extract_ssl_info,
    extract_tls_audit,
    get_http_client,
    validate_url_ssrf,
)
from .base import BaseChecker, CheckResult

logger = structlog.get_logger(__name__)


_MAX_JSON_PATH_DEPTH = 20


def _resolve_json_path(data: Any, path: str) -> Any:
    """Simple dot-notation JSON path resolver.

    Supports: $.key, $.key.subkey, $.key[0].subkey
    Max depth enforced to prevent abuse. Dunder access blocked.
    """
    try:
        if path.startswith("$."):
            path = path[2:]
        elif path.startswith("$"):
            path = path[1:]

        parts = path.split(".")
        if len(parts) > _MAX_JSON_PATH_DEPTH:
            return None
        current = data
        for part in parts:
            if not part:
                continue
            if "__" in part:
                return None  # Block dunder access
            if "[" in part:
                key, idx_str = part.split("[", 1)
                idx = int(idx_str.rstrip("]"))
                if key:
                    current = current[key]
                current = current[idx]
            else:
                current = current[part]
        return current
    except (KeyError, IndexError, TypeError, AttributeError):
        return None


class HTTPChecker(BaseChecker):
    name = "http"
    aliases = ["keyword", "json_path"]

    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        url = config["url"]
        timeout_seconds = config["timeout_seconds"]
        follow_redirects = config.get("follow_redirects", True)
        expected_status_codes = config.get("expected_status_codes", [200])
        ssl_check_enabled = config.get("ssl_check_enabled", False)
        ssl_pin_sha256 = (config.get("ssl_pin_sha256") or "").lower() or None
        ssl_min_chain_days = config.get("ssl_min_chain_days")
        check_type = config.get("check_type", "http")

        keyword = config.get("keyword")
        keyword_negate = config.get("keyword_negate", False)
        expected_json_path = config.get("expected_json_path") if check_type == "json_path" else None
        expected_json_value = (
            config.get("expected_json_value") if check_type == "json_path" else None
        )
        body_regex = config.get("body_regex")
        expected_headers = config.get("expected_headers")
        json_schema = config.get("json_schema")
        custom_headers = config.get("custom_headers") or None
        schema_drift_enabled = config.get("schema_drift_enabled", False)

        checked_at = datetime.now(UTC)
        t0 = time.perf_counter()

        # SSRF protection
        ssrf_err = await validate_url_ssrf(url)
        if ssrf_err:
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                error_message=f"SSRF blocked: {ssrf_err}",
            )

        # DNS pre-resolution timing
        dns_resolve_ms: int | None = None
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            if hostname:
                t_dns = time.perf_counter()
                loop = asyncio.get_running_loop()
                await asyncio.wait_for(
                    loop.run_in_executor(None, _cached_getaddrinfo, hostname),
                    timeout=5.0,
                )
                dns_resolve_ms = int((time.perf_counter() - t_dns) * 1000)
        except TimeoutError:
            logger.warning("dns_resolve_timeout", hostname=hostname)
        except Exception as exc:
            logger.debug("dns_resolve_error", hostname=hostname, error=str(exc))

        ttfb_ms: int | None = None
        download_ms: int | None = None
        http_status: int | None = None
        redirect_count = 0
        final_url: str = url
        response_headers: httpx.Headers | None = None

        try:
            for _attempt in range(2):
                try:
                    async with (await get_http_client()).stream(
                        "GET",
                        url,
                        follow_redirects=follow_redirects,
                        timeout=httpx.Timeout(timeout_seconds),
                        headers=custom_headers,
                    ) as response:
                        ttfb_ms = int((time.perf_counter() - t0) * 1000)
                        body_bytes = await response.aread()
                        download_ms = int((time.perf_counter() - t0) * 1000) - ttfb_ms
                        # Snapshot response attrs while the stream is still open —
                        # some httpx internals may reset after __aexit__.
                        http_status = response.status_code
                        redirect_count = len(response.history)
                        final_url = str(response.url)
                        response_headers = response.headers
                    break
                except httpx.RemoteProtocolError:
                    if _attempt == 0:
                        t0 = time.perf_counter()
                        continue
                    raise

            elapsed_ms = (time.perf_counter() - t0) * 1000

            # SSRF check on final URL after redirects
            if redirect_count > 0:
                ssrf_final = await validate_url_ssrf(final_url)
                if ssrf_final:
                    return CheckResult(
                        monitor_id=monitor_id,
                        checked_at=checked_at,
                        status="error",
                        response_time_ms=round(elapsed_ms, 1),
                        error_message=f"SSRF blocked after redirect: {ssrf_final}",
                    )

            try:
                body_text = body_bytes.decode("utf-8", errors="replace")
            except Exception:
                body_text = ""

            is_up = http_status in expected_status_codes
            status = "up" if is_up else "down"
            error_message = None

            # Keyword check
            if is_up and keyword:
                found = keyword in body_text
                if keyword_negate and found:
                    status = "down"
                    error_message = f"Forbidden keyword found: {keyword!r}"
                elif not keyword_negate and not found:
                    status = "down"
                    error_message = f"Expected keyword not found: {keyword!r}"

            # JSON path check
            if is_up and status == "up" and expected_json_path:
                try:
                    data = json.loads(body_text)
                    actual_value = _resolve_json_path(data, expected_json_path)
                    if expected_json_value is not None and str(actual_value) != expected_json_value:
                        status = "down"
                        error_message = (
                            f"JSON path {expected_json_path!r}: "
                            f"expected {expected_json_value!r}, got {actual_value!r}"
                        )
                except Exception as exc:
                    status = "down"
                    error_message = f"JSON path check failed: {exc}"

            # Regex body check (with ReDoS protection via timeout)
            if body_regex and status == "up":
                try:
                    if len(body_text) > 5_000_000:
                        status = "down"
                        error_message = "Response too large for regex validation"
                    else:
                        compiled = re.compile(body_regex, re.DOTALL)
                        match = await asyncio.wait_for(
                            asyncio.get_running_loop().run_in_executor(
                                None, compiled.search, body_text,
                            ),
                            timeout=5.0,
                        )
                        if not match:
                            status = "down"
                            error_message = f"body_regex not matched: {body_regex!r}"
                except TimeoutError:
                    status = "down"
                    error_message = f"body_regex timed out (possible ReDoS): {body_regex!r}"
                except re.error as exc:
                    status = "down"
                    error_message = f"body_regex_invalid: {exc}"

            # Header assertions (with ReDoS protection via timeout)
            if expected_headers and status == "up" and response_headers is not None:
                for header_name, expected_value in expected_headers.items():
                    actual = response_headers.get(header_name.lower(), "")
                    if expected_value.startswith("/") and expected_value.endswith("/"):
                        pattern = expected_value[1:-1]
                        try:
                            compiled = re.compile(pattern)
                            match = await asyncio.wait_for(
                                asyncio.get_running_loop().run_in_executor(
                                    None, compiled.search, actual,
                                ),
                                timeout=5.0,
                            )
                            if not match:
                                status = "down"
                                error_message = (
                                    f"header_{header_name}_mismatch: expected pattern"
                                    f" {pattern!r}, got {actual!r}"
                                )
                                break
                        except TimeoutError:
                            status = "down"
                            error_message = f"header_{header_name}_regex timed out (possible ReDoS)"
                            break
                        except re.error as exc:
                            status = "down"
                            error_message = f"header_{header_name}_regex_invalid: {exc}"
                            break
                    else:
                        if actual != expected_value:
                            status = "down"
                            error_message = (
                                f"header_{header_name}_mismatch: expected"
                                f" {expected_value!r}, got {actual!r}"
                            )
                            break

            # JSON Schema validation
            if json_schema and status == "up":
                try:
                    from jsonschema import ValidationError, validate  # type: ignore[import]

                    body = json.loads(body_text)
                    validate(instance=body, schema=json_schema)
                except ValidationError as exc:
                    status = "down"
                    error_message = f"json_schema_invalid: {exc.message[:200]}"
                except Exception as exc:
                    status = "down"
                    error_message = f"json_schema_error: {exc}"

            # SSL check
            ssl_valid = ssl_expires_at = ssl_days_remaining = None
            if ssl_check_enabled and url.startswith("https://"):
                ssl_info = await extract_ssl_info(final_url or url)
                ssl_valid, ssl_expires_at, ssl_days_remaining, leaf_sha256 = ssl_info

                # T2-05: pinning — refuse the cert if its SHA-256 doesn't match
                # the configured pin. We do this even when ssl_valid was True
                # (chain trusted) because pinning catches a valid-but-rotated
                # cert that the operator hasn't approved yet.
                if ssl_pin_sha256 and leaf_sha256 and leaf_sha256 != ssl_pin_sha256:
                    if status == "up":
                        status = "down"
                        error_message = (
                            f"ssl_pin_mismatch: served={leaf_sha256[:16]}… "
                            f"expected={ssl_pin_sha256[:16]}…"
                        )
                    ssl_valid = False

                # T2-05: stricter chain expiry threshold than the user-facing
                # warning (ssl_expiry_warn_days only tints the UI).
                if (
                    ssl_min_chain_days is not None
                    and ssl_days_remaining is not None
                    and ssl_days_remaining < ssl_min_chain_days
                    and status == "up"
                ):
                    status = "down"
                    error_message = (
                        f"ssl_chain_expiring: {ssl_days_remaining}d remaining "
                        f"< minimum {ssl_min_chain_days}d"
                    )

            # Schema fingerprint
            schema_fingerprint: str | None = None
            if schema_drift_enabled and status == "up":
                try:
                    data = json.loads(body_text)
                    schema_fingerprint = compute_schema_fingerprint(data)
                except Exception:
                    pass

            # V2-02-03 — TLS audit (parallel to ssl_check, more thorough).
            # Only collected on HTTPS — null otherwise. Failure is non-fatal.
            tls_audit: dict | None = None
            if ssl_check_enabled and url.startswith("https://"):
                tls_audit = await extract_tls_audit(final_url or url)

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
                error_message=error_message,
                dns_resolve_ms=dns_resolve_ms,
                ttfb_ms=ttfb_ms,
                download_ms=download_ms,
                schema_fingerprint=schema_fingerprint,
                tls_audit=tls_audit,
            )

        except httpx.TimeoutException:
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


def setup(register):
    register(HTTPChecker())
