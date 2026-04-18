"""Shared utilities for checker plugins — SSRF, SSL, DNS cache, HTTP client."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import socket
import ssl
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# ── DNS cache (TTL 60s, max 1000 entries) ───────────────────────────────────

_dns_cache: dict[str, tuple[list, float]] = {}
_DNS_TTL = 60  # seconds
_DNS_CACHE_MAX = 1000


def _cached_getaddrinfo(hostname: str, port: object = None, **kwargs: object) -> list:
    """DNS resolution with 60-second TTL cache (bounded to 1000 entries)."""
    now = time.monotonic()
    cached = _dns_cache.get(hostname)
    if cached and now - cached[1] < _DNS_TTL:
        return cached[0]
    result = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    # Evict oldest entries when cache is full
    if len(_dns_cache) >= _DNS_CACHE_MAX:
        oldest_key = min(_dns_cache, key=lambda k: _dns_cache[k][1])
        del _dns_cache[oldest_key]
    _dns_cache[hostname] = (result, now)
    return result


# ── SSRF protection ──────────────────────────────────────────────────────────


def _is_internal_ip(ip_str: str) -> bool:
    """Return True if IP is private, loopback, link-local, or multicast."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
    except ValueError:
        return False


def validate_host_ssrf(hostname: str) -> str | None:
    """Reject hostnames that resolve to internal/private IPs.

    Returns an error message if blocked, None if safe.
    Works for non-HTTP checkers (TCP, UDP, SMTP, DNS).
    """
    blocked = {
        "localhost", "127.0.0.1", "::1", "0.0.0.0",
        "169.254.169.254", "metadata.google.internal",
    }
    if hostname.lower() in blocked:
        return f"Blocked host: {hostname!r}"
    # Check if hostname is a raw IP address
    try:
        if _is_internal_ip(hostname):
            return f"Blocked internal IP: {hostname!r}"
    except Exception:
        pass
    # Resolve and check
    try:
        for ai in socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP):
            if _is_internal_ip(ai[4][0]):
                return f"Host resolves to internal IP: {ai[4][0]!r}"
    except socket.gaierror:
        return f"DNS resolution failed for {hostname!r}"
    return None


def _validate_url_ssrf_fast(url: str) -> str | None:
    """Synchronous SSRF check — scheme and static hostname only (no DNS, non-blocking)."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Blocked scheme: {parsed.scheme!r}"
    hostname = parsed.hostname or ""
    blocked = {
        "localhost", "127.0.0.1", "::1", "0.0.0.0",
        "169.254.169.254", "metadata.google.internal",
    }
    if hostname.lower() in blocked:
        return f"Blocked host: {hostname!r}"
    return None


def _ssrf_dns_check_sync(hostname: str) -> str | None:
    """Resolve hostname and reject internal IPs (blocking — run via executor)."""
    try:
        for ai in _cached_getaddrinfo(hostname):
            if _is_internal_ip(ai[4][0]):
                return f"Host resolves to internal IP: {ai[4][0]!r}"
    except socket.gaierror:
        return f"DNS resolution failed for {hostname!r}"
    return None


async def validate_url_ssrf(url: str) -> str | None:
    """Full async SSRF validation: fast string check then DNS resolution in executor."""
    err = _validate_url_ssrf_fast(url)
    if err:
        return err
    hostname = urlparse(url).hostname or ""
    if not hostname:
        return None
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _ssrf_dns_check_sync, hostname),
            timeout=3.0,
        )
    except TimeoutError:
        return f"DNS resolution timed out for {hostname!r}"
    except Exception as exc:
        return f"DNS resolution error for {hostname!r}: {type(exc).__name__}"


# ── SSL info extraction ──────────────────────────────────────────────────────


def _extract_ssl_info_sync(url: str) -> tuple[bool, datetime | None, int | None]:
    """Extract SSL certificate info for an HTTPS URL (blocking — run in executor)."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        port = parsed.port or 443

        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
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


async def extract_ssl_info(url: str) -> tuple[bool, datetime | None, int | None]:
    """Extract SSL certificate info without blocking the event loop."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, _extract_ssl_info_sync, url),
            timeout=10.0,
        )
    except Exception:
        return False, None, None


# ── Shared HTTP client ────────────────────────────────────────────────────────

_http_client: httpx.AsyncClient | None = None
_http_client_lock = asyncio.Lock()


async def get_http_client() -> httpx.AsyncClient:
    """Return a shared AsyncClient (connection pooling across checks)."""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        return _http_client
    async with _http_client_lock:
        # Double-check after acquiring lock
        if _http_client is not None and not _http_client.is_closed:
            return _http_client
        _http_client = httpx.AsyncClient(
            verify=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _http_client


# ── Schema fingerprint ────────────────────────────────────────────────────────


def compute_schema_fingerprint(data: Any) -> str:
    """Compute a structural fingerprint of a JSON value (keys + types, not values)."""
    def _structure(obj: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "..."
        if isinstance(obj, dict):
            return {k: _structure(v, depth + 1) for k, v in sorted(obj.items())}
        if isinstance(obj, list):
            if not obj:
                return []
            return [_structure(obj[0], depth + 1)]
        return type(obj).__name__

    structure = _structure(data)
    canonical = json.dumps(structure, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# ── Playwright browser args (shared between pool and fallback) ───────────────

BROWSER_LAUNCH_ARGS = [
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
]


# ── Playwright browser pool ──────────────────────────────────────────────────


class PlaywrightPool:
    """Keeps a single Chromium browser alive between scenario checks."""

    def __init__(self) -> None:
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    def is_available(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def start(self) -> None:
        try:
            from playwright.async_api import async_playwright
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(
                headless=True,
                # --no-sandbox required in Docker (container provides isolation)
                # --disable-web-security disabled to prevent CORS bypass in scenarios
                args=BROWSER_LAUNCH_ARGS,
            )
            logger.info("playwright_pool_started")
        except ImportError:
            logger.warning("playwright_not_installed_scenarios_will_fail")
        except Exception as exc:
            logger.warning("playwright_pool_start_failed", error=str(exc))

    async def _ensure_connected(self) -> None:
        """Relaunch browser if it crashed; protected by lock against concurrent restarts."""
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return
            try:
                from playwright.async_api import async_playwright
                if self._pw is None:
                    self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=True,
                args=BROWSER_LAUNCH_ARGS,
                )
                logger.info("playwright_browser_relaunched")
            except Exception as exc:
                logger.error("playwright_browser_relaunch_failed", error=str(exc))
                raise

    @asynccontextmanager
    async def acquire_page(self, timeout_seconds: int):
        """Yield a fresh Page in an isolated BrowserContext; close context on exit."""
        await self._ensure_connected()
        context = await self._browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        page.set_default_timeout(timeout_seconds * 1000)
        try:
            yield page
        finally:
            try:
                await context.close()
            except Exception:
                pass

    async def aclose(self) -> None:
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._browser = None
        self._pw = None


async def kill_stale_chromium(max_age_seconds: int = 120) -> int:
    """Kill chromium processes older than *max_age_seconds*."""
    import psutil as _psutil

    now = time.time()
    killed = 0
    for proc in _psutil.process_iter(["pid", "name", "create_time"]):
        try:
            name = (proc.info["name"] or "").lower()
            if "chromium" not in name and "chrome-headless-shell" not in name:
                continue
            age = now - proc.info["create_time"]
            if age > max_age_seconds:
                proc.kill()
                killed += 1
                logger.info("killed_stale_chromium", pid=proc.info["pid"], age_s=int(age))
        except (_psutil.NoSuchProcess, _psutil.AccessDenied):
            pass
    return killed
