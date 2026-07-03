"""Security headers, request size, and request-ID middleware."""

from __future__ import annotations

import re
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_MAX_BODY = 5 * 1024 * 1024  # 5 MB
REQUEST_ID_HEADER = "X-Request-ID"

# Accepted shape for a client-supplied request ID. Anything else (too long,
# spaces, control/exotic characters, ...) is discarded and replaced by a
# server-generated uuid4 — we never echo an arbitrary client string back in
# the response header or into the logs.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

logger = structlog.get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to every request/response and to structlog's context.

    Reuses the incoming ``X-Request-ID`` header when present *and* well-formed
    (``_REQUEST_ID_RE`` — e.g. set by an upstream reverse proxy or another
    service), otherwise generates a fresh uuid4. The ID is bound into
    structlog's contextvars for the lifetime of the request, so every log line
    emitted while handling it — regardless of which module logs it — carries
    ``request_id`` automatically. It is also echoed back in the response
    header so clients/proxies can correlate.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        if incoming and _REQUEST_ID_RE.fullmatch(incoming):
            request_id = incoming
        else:
            request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Reset any leftover context (defence in depth — each request should
        # run in its own asyncio Task/context, but this guarantees isolation
        # even if that assumption is ever violated by a server integration).
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed", method=request.method, path=request.url.path)
            raise
        else:
            # Access-log line — emitted while `request_id` is still bound
            # (the `finally` below only clears the context afterwards). The
            # explicit kwarg is belt-and-braces in case structlog is ever
            # reconfigured without `merge_contextvars`.
            logger.info(
                "request_handled",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                request_id=request_id,
            )
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Build the generic 500 response for unhandled exceptions.

    Registered in ``main.py`` via ``app.add_exception_handler(Exception, ...)``
    so Starlette's ``ServerErrorMiddleware`` (always outermost, wrapping even
    ``RequestIDMiddleware``) uses it instead of its bare plain-text response.
    Without this, 500s would be the only responses missing ``X-Request-ID`` —
    exactly the ones users report to support. Note that ``ServerErrorMiddleware``
    still re-raises the original exception after sending this response, so
    server-side error reporting/logging is unchanged.

    ``request.state`` is backed by ``scope["state"]``, which is shared with
    ``RequestIDMiddleware`` — the ID set there is readable here even though the
    middleware's own response path never ran.
    """
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return JSONResponse(
        {"detail": "Internal Server Error"},
        status_code=500,
        headers={REQUEST_ID_HEADER: request_id},
    )


class MaxRequestSizeMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds _MAX_BODY (5 MB)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_BODY:
            return JSONResponse(
                {"detail": "Request body too large (max 5 MB)"},
                status_code=413,
            )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if "server" in response.headers:
            del response.headers["server"]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self'; "
            "connect-src 'self' wss:; "
            "frame-ancestors 'none';"
        )
        # HSTS only for HTTPS responses
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )
        return response
