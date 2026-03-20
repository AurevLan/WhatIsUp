"""Multi-protocol check engine — HTTP, TCP, DNS, keyword, JSON path."""

from __future__ import annotations

import asyncio
import json
import re
import socket
import ssl
import time
from dataclasses import dataclass
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
    scenario_result: dict | None = None
    dns_resolved_values: list[str] | None = None
    # HTTP waterfall timing
    dns_resolve_ms: int | None = None
    ttfb_ms: int | None = None
    download_ms: int | None = None
    # API schema fingerprint
    schema_fingerprint: str | None = None

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
        }


def _extract_ssl_info(url: str) -> tuple[bool, datetime | None, int | None]:
    """Extract SSL certificate info for an HTTPS URL."""
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

        not_after_str = cert.get("notAfter", "")
        if not_after_str:
            expires_at = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(
                tzinfo=UTC
            )
            days_remaining = (expires_at - datetime.now(UTC)).days
            return days_remaining > 0, expires_at, days_remaining

        return True, None, None
    except ssl.SSLCertVerificationError:
        return False, None, None
    except Exception:
        return False, None, None


def _compute_schema_fingerprint(data: Any) -> str:
    """Compute a structural fingerprint of a JSON value (keys + types, not values)."""
    import hashlib

    def _structure(obj: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "..."
        if isinstance(obj, dict):
            return {k: _structure(v, depth + 1) for k, v in sorted(obj.items())}
        if isinstance(obj, list):
            if not obj:
                return []
            # Sample first element to represent list structure
            return [_structure(obj[0], depth + 1)]
        return type(obj).__name__

    structure = _structure(data)
    canonical = json.dumps(structure, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


async def _check_http(
    monitor_id: str,
    url: str,
    timeout_seconds: int,
    follow_redirects: bool,
    expected_status_codes: list[int],
    ssl_check_enabled: bool,
    keyword: str | None = None,
    keyword_negate: bool = False,
    expected_json_path: str | None = None,
    expected_json_value: str | None = None,
    body_regex: str | None = None,
    expected_headers: dict[str, str] | None = None,
    json_schema: dict | None = None,
    schema_drift_enabled: bool = False,
) -> CheckResult:
    """HTTP/HTTPS check with optional keyword and JSON path validation."""
    import hashlib
    from urllib.parse import urlparse

    import httpx

    checked_at = datetime.now(UTC)
    t0 = time.perf_counter()

    # DNS pre-resolution timing
    dns_resolve_ms: int | None = None
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if hostname:
            t_dns = time.perf_counter()
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, socket.getaddrinfo, hostname, None)
            dns_resolve_ms = int((time.perf_counter() - t_dns) * 1000)
    except Exception:
        pass

    ttfb_ms: int | None = None
    download_ms: int | None = None

    try:
        async with httpx.AsyncClient(
            follow_redirects=follow_redirects,
            timeout=httpx.Timeout(timeout_seconds),
            verify=True,
        ) as client:
            # Use streaming to capture TTFB and download time separately
            async with client.stream("GET", url) as response:
                ttfb_ms = int((time.perf_counter() - t0) * 1000)
                body_bytes = await response.aread()
                download_ms = int((time.perf_counter() - t0) * 1000) - ttfb_ms

        elapsed_ms = (time.perf_counter() - t0) * 1000
        http_status = response.status_code
        redirect_count = len(response.history)
        final_url = str(response.url)

        # Decode body for text-based checks
        try:
            body_text = body_bytes.decode("utf-8", errors="replace")
        except Exception:
            body_text = ""

        # Monkey-patch response.text and response.json() for downstream checks
        class _FakeResponse:
            def __init__(self, orig, text_content, raw_bytes):
                self._orig = orig
                self.text = text_content
                self.status_code = orig.status_code
                self.history = orig.history
                self.url = orig.url
                self.headers = orig.headers

            def json(self):
                return json.loads(self.text)

        response = _FakeResponse(response, body_text, body_bytes)

        is_up = http_status in expected_status_codes
        status = "up" if is_up else "down"
        error_message = None

        # Keyword check
        if is_up and keyword:
            body = response.text
            found = keyword in body
            if keyword_negate and found:
                status = "down"
                error_message = f"Forbidden keyword found: {keyword!r}"
            elif not keyword_negate and not found:
                status = "down"
                error_message = f"Expected keyword not found: {keyword!r}"

        # JSON path check
        if is_up and status == "up" and expected_json_path:
            try:
                data = response.json()
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

        # Regex body check
        if body_regex and status == "up":
            try:
                if not re.search(body_regex, response.text or ""):
                    status = "down"
                    error_message = (
                        f"body_regex_no_match: pattern {body_regex!r} not found in response body"
                    )
            except re.error as exc:
                status = "down"
                error_message = f"body_regex_invalid: {exc}"

        # Header assertions
        if expected_headers and status == "up":
            for header_name, expected_value in expected_headers.items():
                actual = response.headers.get(header_name.lower(), "")
                if expected_value.startswith("/") and expected_value.endswith("/"):
                    pattern = expected_value[1:-1]
                    try:
                        if not re.search(pattern, actual):
                            status = "down"
                            error_message = (
                                f"header_{header_name}_mismatch: expected pattern"
                                f" {pattern!r}, got {actual!r}"
                            )
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

                body = json.loads(response.text or "")
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
            ssl_valid, ssl_expires_at, ssl_days_remaining = _extract_ssl_info(final_url or url)

        # Schema fingerprint
        schema_fingerprint: str | None = None
        if schema_drift_enabled and status == "up":
            try:
                data = json.loads(body_text)
                schema_fingerprint = _compute_schema_fingerprint(data)
            except Exception:
                pass

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


def _resolve_json_path(data: Any, path: str) -> Any:
    """
    Simple dot-notation JSON path resolver.
    Supports: $.key, $.key.subkey, $.key[0].subkey
    Returns None when the path does not exist or is malformed.
    """
    try:
        # Strip leading $. or $
        if path.startswith("$."):
            path = path[2:]
        elif path.startswith("$"):
            path = path[1:]

        parts = path.split(".")
        current = data
        for part in parts:
            if not part:
                continue
            # Handle array index: key[0]
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


async def _check_tcp(
    monitor_id: str,
    host: str,
    port: int,
    timeout_seconds: int,
) -> CheckResult:
    """TCP port reachability check."""
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


async def _check_dns(
    monitor_id: str,
    host: str,
    record_type: str,
    expected_value: str | None,
    timeout_seconds: int,
) -> CheckResult:
    """DNS resolution check with optional record value assertion."""
    import dns.resolver  # type: ignore[import]

    checked_at = datetime.now(UTC)
    t0 = time.perf_counter()

    try:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = timeout_seconds
        answers = resolver.resolve(host, record_type)
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


async def _capture_web_vitals(page) -> dict:
    """Capture LCP, CLS, INP via PerformanceObserver."""
    try:
        vitals = await page.evaluate("""
            () => new Promise((resolve) => {
                const vitals = { lcp: null, cls: 0, inp: null };
                const obs_lcp = new PerformanceObserver(list => {
                    const entries = list.getEntries();
                    vitals.lcp = entries[entries.length - 1].startTime;
                });
                const obs_cls = new PerformanceObserver(list => {
                    list.getEntries().forEach(e => {
                        if (!e.hadRecentInput) vitals.cls += e.value;
                    });
                });
                const obs_inp = new PerformanceObserver(list => {
                    list.getEntries().forEach(e => {
                        if (!vitals.inp || e.duration > vitals.inp) vitals.inp = e.duration;
                    });
                });
                try {
                    obs_lcp.observe({ type: 'largest-contentful-paint', buffered: true });
                    obs_cls.observe({ type: 'layout-shift', buffered: true });
                    obs_inp.observe({ type: 'event', buffered: true, durationThreshold: 16 });
                } catch(e) {}
                setTimeout(() => {
                    obs_lcp.disconnect(); obs_cls.disconnect(); obs_inp.disconnect();
                    resolve(vitals);
                }, 1000);
            })
        """)
        return vitals
    except Exception:
        return {}


def _build_web_vitals(raw: dict) -> dict | None:
    """Convert raw PerformanceObserver vitals into the stored format."""
    if not raw:
        return None
    lcp = raw.get("lcp")
    cls = raw.get("cls")
    inp = raw.get("inp")
    # Only include vitals that were actually captured
    result: dict = {}
    if lcp is not None:
        result["lcp_ms"] = round(float(lcp), 1)
    if cls is not None:
        result["cls"] = round(float(cls), 4)
    if inp is not None:
        result["inp_ms"] = round(float(inp), 1)
    return result or None


def _make_step_result(i: int, step_type: str, step_label: str, duration_ms: float, **extra) -> dict:
    """Build a step result dict with common fields + optional status-specific extras."""
    return {
        "index": i,
        "type": step_type,
        "label": step_label,
        "duration_ms": round(duration_ms, 2),
        **extra,
    }


def _substitute_vars(text: str, variables: list[dict]) -> str:
    """Replace {{VAR_NAME}} placeholders with variable values."""
    for var in variables:
        text = text.replace(f"{{{{{var['name']}}}}}", str(var.get("value", "")))
    return text


async def _check_scenario(
    monitor_id: str,
    steps: list[dict],
    variables: list[dict],
    timeout_seconds: int,
) -> CheckResult:
    """Execute a multi-step browser scenario using Playwright."""
    import base64

    checked_at = datetime.now(UTC)
    t0 = time.perf_counter()

    try:
        from playwright.async_api import TimeoutError as PlaywrightTimeout
        from playwright.async_api import async_playwright
    except ImportError:
        return CheckResult(
            monitor_id=monitor_id,
            checked_at=checked_at,
            status="error",
            error_message="Playwright not installed — run: playwright install chromium",
        )

    steps_total = len(steps)
    steps_passed = 0
    current_url = ""
    step_results: list[dict] = []
    # Aggregate Web Vitals from navigate steps (last wins for LCP/INP, CLS sums)
    aggregate_vitals: dict = {}

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                ignore_https_errors=True,
            )
            page = await context.new_page()
            page.set_default_timeout(timeout_seconds * 1000)

            for i, step in enumerate(steps):
                step_type = step.get("type", "")
                params = step.get("params", {})
                step_label = step.get("label", f"Step {i + 1}")

                # Substitute variables in all string params
                params = {
                    k: _substitute_vars(str(v), variables) if isinstance(v, str) else v
                    for k, v in params.items()
                }

                step_t0 = time.perf_counter()
                step_screenshot: str | None = None

                try:
                    step_timeout_ms = step.get("timeout_ms")
                    if step_timeout_ms:
                        page.set_default_timeout(int(step_timeout_ms))

                    if step_type == "navigate":
                        await page.goto(params["url"], wait_until="domcontentloaded")
                        current_url = page.url
                        vitals = await _capture_web_vitals(page)
                        if vitals:
                            aggregate_vitals = vitals

                    elif step_type == "click":
                        await page.click(params["selector"])

                    elif step_type == "fill":
                        await page.fill(params["selector"], params.get("value", ""))

                    elif step_type == "select":
                        await page.select_option(params["selector"], params.get("value", ""))

                    elif step_type == "wait_element":
                        state = params.get("state", "visible")
                        t = int(params.get("timeout", timeout_seconds * 1000))
                        await page.wait_for_selector(params["selector"], state=state, timeout=t)

                    elif step_type == "wait_time":
                        await asyncio.sleep(int(params.get("duration_ms", 500)) / 1000)

                    elif step_type == "assert_text":
                        selector = params["selector"]
                        expected = params.get("expected", "")
                        mode = params.get("mode", "contains")
                        el = await page.query_selector(selector)
                        if el is None:
                            raise AssertionError(f"Element '{selector}' not found")
                        actual = (await el.text_content() or "").strip()
                        if mode == "equals" and actual != expected:
                            raise AssertionError(
                                f"Text equals check: expected {expected!r}, got {actual!r}"
                            )
                        elif mode == "contains" and expected not in actual:
                            raise AssertionError(
                                f"Text contains check: {expected!r} not in {actual!r}"
                            )

                    elif step_type == "assert_visible":
                        el = await page.query_selector(params["selector"])
                        if el is None or not await el.is_visible():
                            raise AssertionError(f"Element '{params['selector']}' not visible")

                    elif step_type == "assert_url":
                        current = page.url
                        expected = params.get("expected", "")
                        mode = params.get("mode", "contains")
                        if mode == "equals" and current != expected:
                            raise AssertionError(
                                f"URL equals: expected {expected!r}, got {current!r}"
                            )
                        elif mode == "contains" and expected not in current:
                            raise AssertionError(f"URL contains: {expected!r} not in {current!r}")

                    elif step_type == "screenshot":
                        img_bytes = await page.screenshot(type="jpeg", quality=50, full_page=False)
                        step_screenshot = (
                            "data:image/jpeg;base64," + base64.b64encode(img_bytes).decode()
                        )

                    elif step_type == "hover":
                        await page.hover(params["selector"])

                    elif step_type == "scroll":
                        if "selector" in params:
                            await page.locator(params["selector"]).scroll_into_view_if_needed()
                        else:
                            x = int(params.get("x", 0))
                            y = int(params.get("y", 500))
                            await page.evaluate(f"window.scrollTo({x}, {y})")

                    elif step_type == "press":
                        key = params["key"]
                        selector = params.get("selector", "")
                        if selector:
                            await page.press(selector, key)
                        else:
                            await page.keyboard.press(key)

                    elif step_type == "type":
                        text = params.get("text", "")
                        selector = params.get("selector", "")
                        if selector:
                            await page.type(selector, text)
                        else:
                            await page.keyboard.type(text)

                    elif step_type == "extract":
                        selector = params["selector"]
                        attribute = params.get("attribute", "text")
                        variable_name = params.get("variable", "")
                        el = await page.query_selector(selector)
                        if el is None:
                            raise AssertionError(f"Extract: element '{selector}' not found")
                        if attribute == "text":
                            value = (await el.text_content() or "").strip()
                        elif attribute == "value":
                            value = await el.get_attribute("value") or ""
                        else:
                            value = await el.get_attribute(attribute) or ""
                        if variable_name:
                            # Inject extracted value into runtime variables list
                            found = False
                            for var in variables:
                                if var["name"] == variable_name:
                                    var["value"] = value
                                    found = True
                                    break
                            if not found:
                                variables.append(
                                    {"name": variable_name, "value": value, "secret": False}
                                )

                    page.set_default_timeout(timeout_seconds * 1000)
                    dur = (time.perf_counter() - step_t0) * 1000
                    step_results.append(
                        _make_step_result(
                            i,
                            step_type,
                            step_label,
                            dur,
                            status="passed",
                            screenshot=step_screenshot,
                        )
                    )
                    steps_passed += 1

                except (PlaywrightTimeout, AssertionError, KeyError, Exception) as step_err:
                    page.set_default_timeout(timeout_seconds * 1000)
                    dur = (time.perf_counter() - step_t0) * 1000
                    if step.get("continue_on_fail", False):
                        step_results.append(
                            _make_step_result(
                                i,
                                step_type,
                                step_label,
                                dur,
                                status="warned",
                                error=str(step_err)[:300],
                                screenshot=None,
                                continue_on_fail=True,
                            )
                        )
                        continue
                    step_results.append(
                        _make_step_result(
                            i,
                            step_type,
                            step_label,
                            dur,
                            status="failed",
                            error=str(step_err)[:300],
                            screenshot=None,
                        )
                    )
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    current_url = page.url
                    await browser.close()
                    web_vitals = _build_web_vitals(aggregate_vitals)
                    return CheckResult(
                        monitor_id=monitor_id,
                        checked_at=checked_at,
                        status="down",
                        response_time_ms=round(elapsed_ms, 2),
                        final_url=current_url,
                        error_message=f"Step {i + 1} ({step_type}) failed: {step_err}",
                        scenario_result={
                            "steps_total": steps_total,
                            "steps_passed": steps_passed,
                            "failed_step_index": i,
                            "failed_step_type": step_type,
                            "failed_step_label": step_label,
                            "steps": step_results,
                            "web_vitals": web_vitals,
                        },
                    )

            elapsed_ms = (time.perf_counter() - t0) * 1000
            current_url = page.url
            await browser.close()

            steps_warned = sum(1 for s in step_results if s.get("status") == "warned")
            web_vitals = _build_web_vitals(aggregate_vitals)
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="up",
                response_time_ms=round(elapsed_ms, 2),
                final_url=current_url,
                scenario_result={
                    "steps_total": steps_total,
                    "steps_passed": steps_passed,
                    "steps_warned": steps_warned,
                    "failed_step_index": None,
                    "failed_step_type": None,
                    "failed_step_label": None,
                    "steps": step_results,
                    "web_vitals": web_vitals,
                },
            )

    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        return CheckResult(
            monitor_id=monitor_id,
            checked_at=checked_at,
            status="error",
            response_time_ms=round(elapsed_ms, 2),
            error_message=f"Scenario error: {type(exc).__name__}: {str(exc)[:300]}",
        )


async def _check_udp(
    monitor_id: str,
    host: str,
    port: int,
    timeout_seconds: int,
) -> CheckResult:
    """UDP port check — sends an empty datagram and interprets ICMP unreachable as down."""
    checked_at = datetime.now(UTC)
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
                # No ICMP unreachable received → port is open or filtered
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
        loop = asyncio.get_event_loop()
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


async def _check_smtp(
    monitor_id: str,
    host: str,
    port: int,
    timeout_seconds: int,
    starttls: bool = False,
) -> CheckResult:
    """SMTP server check — connects, reads banner, sends EHLO, optionally STARTTLS."""
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
        # Read multi-line EHLO response (lines ending with "250 " signal end)
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


_SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]{1,253}$")


async def _check_ping(
    monitor_id: str,
    host: str,
    timeout_seconds: int,
) -> CheckResult:
    """ICMP ping check via subprocess."""
    checked_at = datetime.now(UTC)

    # Validate host to prevent command injection (only hostname/IP chars allowed)
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
            # Parse RTT from ping output: "time=X.X ms"
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


async def _check_domain_expiry(
    monitor_id: str,
    host: str,
    warn_days: int,
    timeout_seconds: int,
) -> CheckResult:
    """Domain WHOIS expiry check — alerts when expiry is within warn_days."""
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
        loop = asyncio.get_event_loop()
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
    smtp_port: int | None = None,
    smtp_starttls: bool = False,
    domain_expiry_warn_days: int = 30,
    schema_drift_enabled: bool = False,
) -> CheckResult:
    """
    Dispatch to the appropriate check engine based on check_type.
    Supported types: http, tcp, udp, dns, keyword, json_path, smtp, ping, domain_expiry
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or url

    if check_type == "tcp":
        port = tcp_port or parsed.port or 80
        return await _check_tcp(monitor_id, host, port, timeout_seconds)

    elif check_type == "udp":
        port = udp_port or parsed.port or 80
        return await _check_udp(monitor_id, host, port, timeout_seconds)

    elif check_type == "smtp":
        port = smtp_port or parsed.port or 25
        return await _check_smtp(monitor_id, host, port, timeout_seconds, starttls=smtp_starttls)

    elif check_type == "ping":
        return await _check_ping(monitor_id, host, timeout_seconds)

    elif check_type == "domain_expiry":
        return await _check_domain_expiry(  # noqa: E501
            monitor_id, host, domain_expiry_warn_days, timeout_seconds
        )

    elif check_type == "dns":  # noqa: SIM114
        return await _check_dns(
            monitor_id,
            host,
            dns_record_type or "A",
            dns_expected_value,
            timeout_seconds,
        )

    elif check_type in ("keyword", "json_path"):
        # These are HTTP checks with additional body validation
        return await _check_http(
            monitor_id,
            url,
            timeout_seconds,
            follow_redirects,
            expected_status_codes,
            ssl_check_enabled,
            keyword=keyword,
            keyword_negate=keyword_negate,
            expected_json_path=expected_json_path if check_type == "json_path" else None,
            expected_json_value=expected_json_value if check_type == "json_path" else None,
            body_regex=body_regex,
            expected_headers=expected_headers,
            json_schema=json_schema,
            schema_drift_enabled=schema_drift_enabled,
        )

    elif check_type == "scenario":
        return await _check_scenario(
            monitor_id,
            steps or [],
            variables or [],
            timeout_seconds,
        )

    else:
        # Default: http
        return await _check_http(
            monitor_id,
            url,
            timeout_seconds,
            follow_redirects,
            expected_status_codes,
            ssl_check_enabled,
            body_regex=body_regex,
            expected_headers=expected_headers,
            json_schema=json_schema,
            schema_drift_enabled=schema_drift_enabled,
        )
