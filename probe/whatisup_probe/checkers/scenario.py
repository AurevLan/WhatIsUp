"""Playwright browser scenario checker."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

import structlog

from ._shared import BROWSER_LAUNCH_ARGS, validate_url_ssrf
from .base import BaseChecker, CheckResult

logger = structlog.get_logger(__name__)


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
                }, 50);
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
    cls_val = raw.get("cls")
    inp = raw.get("inp")
    result: dict = {}
    if lcp is not None:
        result["lcp_ms"] = round(float(lcp), 1)
    if cls_val is not None:
        result["cls"] = round(float(cls_val), 4)
    if inp is not None:
        result["inp_ms"] = round(float(inp), 1)
    return result or None


def _make_step_result(i: int, step_type: str, step_label: str, duration_ms: float, **extra) -> dict:
    """Build a step result dict."""
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


class ScenarioChecker(BaseChecker):
    name = "scenario"

    async def check(self, monitor_id: str, config: dict[str, Any], **kwargs: Any) -> CheckResult:
        import base64

        steps = config.get("steps") or []
        variables = list(config.get("variables") or [])  # copy — mutated by extract steps
        timeout_seconds = config["timeout_seconds"]
        browser_pool = kwargs.get("browser_pool")

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
        aggregate_vitals: dict = {}

        async def _run_steps(page) -> CheckResult:
            nonlocal steps_passed, current_url, aggregate_vitals

            for i, step in enumerate(steps):
                    step_type = step.get("type", "")
                    params = step.get("params", {})
                    step_label = step.get("label", f"Step {i + 1}")

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
                            nav_ssrf = await validate_url_ssrf(params["url"])
                            if nav_ssrf:
                                raise ValueError(f"SSRF blocked in scenario navigate: {nav_ssrf}")
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
                                raise AssertionError(
                                    f"URL contains: {expected!r} not in {current!r}"
                                )

                        elif step_type == "screenshot":
                            img_bytes = await page.screenshot(
                                type="jpeg", quality=30, full_page=False
                            )
                            b64 = base64.b64encode(img_bytes).decode()
                            if len(b64) < 50_000:
                                step_screenshot = f"data:image/jpeg;base64,{b64}"
                            else:
                                step_screenshot = None
                                logger.debug(
                                    "screenshot_truncated",
                                    step=step_label,
                                    size_kb=round(len(b64) / 1024, 1),
                                )

                        elif step_type == "hover":
                            await page.hover(params["selector"])

                        elif step_type == "scroll":
                            if "selector" in params:
                                await page.locator(params["selector"]).scroll_into_view_if_needed()
                            else:
                                x = int(params.get("x", 0))
                                y = int(params.get("y", 500))
                                await page.evaluate("([x, y]) => window.scrollTo(x, y)", [x, y])

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
                            # Limit extracted value size to prevent memory abuse
                            value = value[:10_000]
                            if variable_name:
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
                                i, step_type, step_label, dur,
                                status="passed", screenshot=step_screenshot,
                            )
                        )
                        steps_passed += 1

                    except (PlaywrightTimeout, AssertionError, KeyError, ValueError) as step_err:
                        page.set_default_timeout(timeout_seconds * 1000)
                        dur = (time.perf_counter() - step_t0) * 1000
                        if step.get("continue_on_fail", False):
                            step_results.append(
                                _make_step_result(
                                    i, step_type, step_label, dur,
                                    status="warned", error=str(step_err)[:300],
                                    screenshot=None, continue_on_fail=True,
                                )
                            )
                            continue
                        step_results.append(
                            _make_step_result(
                                i, step_type, step_label, dur,
                                status="failed", error=str(step_err)[:300], screenshot=None,
                            )
                        )
                        elapsed_ms = (time.perf_counter() - t0) * 1000
                        current_url = page.url
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

                    except Exception as step_err:
                        logger.warning(
                            "unexpected_scenario_error",
                            error=type(step_err).__name__,
                            detail=str(step_err),
                        )
                        page.set_default_timeout(timeout_seconds * 1000)
                        dur = (time.perf_counter() - step_t0) * 1000
                        step_results.append(
                            _make_step_result(
                                i, step_type, step_label, dur,
                                status="failed", error=str(step_err)[:300], screenshot=None,
                            )
                        )
                        elapsed_ms = (time.perf_counter() - t0) * 1000
                        current_url = page.url
                        web_vitals = _build_web_vitals(aggregate_vitals)
                        return CheckResult(
                            monitor_id=monitor_id,
                            checked_at=checked_at,
                            status="down",
                            response_time_ms=round(elapsed_ms, 2),
                            final_url=current_url,
                            error_message=f"Step {i+1} ({step_type}) unexpected error: {step_err}",
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

            # All steps passed
            elapsed_ms = (time.perf_counter() - t0) * 1000
            current_url = page.url
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

        # ── Browser acquisition ──────────────────────────────────────────────
        try:
            if browser_pool is not None and browser_pool.is_available():
                async with browser_pool.acquire_page(timeout_seconds) as page:
                    return await _run_steps(page)
            else:
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(
                        headless=True,
                        args=BROWSER_LAUNCH_ARGS,
                    )
                    context = await browser.new_context(viewport={"width": 1280, "height": 720})
                    page = await context.new_page()
                    page.set_default_timeout(timeout_seconds * 1000)
                    try:
                        return await _run_steps(page)
                    finally:
                        await browser.close()
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            err_msg = f"Scenario error: {type(exc).__name__}: {str(exc)[:300]}"
            return CheckResult(
                monitor_id=monitor_id,
                checked_at=checked_at,
                status="error",
                response_time_ms=round(elapsed_ms, 2),
                error_message=err_msg,
                scenario_result={
                    "steps_total": steps_total,
                    "steps_passed": steps_passed,
                    "steps_warned": 0,
                    "failed_step_index": len(step_results),
                    "failed_step_type": None,
                    "failed_step_label": None,
                    "steps": step_results,
                    "web_vitals": {},
                    "error": err_msg,
                },
            )


def setup(register):
    register(ScenarioChecker())
