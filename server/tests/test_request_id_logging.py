"""X-Request-ID middleware + structlog JSON/console configuration.

Covers C3 (bilan 2026-07, vague 2): structlog was declared as configured in
FEATURES.md but ``structlog.configure()`` was never actually called, and no
request-ID middleware existed. These tests pin the real behaviour:

- the response always carries ``X-Request-ID`` (reused or generated),
- the ID is bound into structlog's contextvars for the whole request so any
  downstream log line picks it up automatically,
- the context does not leak across requests,
- ``configure_logging`` renders JSON in production and a human console
  format everywhere else.
"""

from __future__ import annotations

import json
import logging
import uuid
from io import StringIO

import pytest
import structlog
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from whatisup.core.config import Settings, get_settings
from whatisup.core.logging import configure_logging
from whatisup.core.middleware import REQUEST_ID_HEADER, RequestIDMiddleware

# ── Response header: reused vs generated ────────────────────────────────────


@pytest.mark.asyncio
async def test_request_id_header_generated_when_absent(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    request_id = resp.headers.get(REQUEST_ID_HEADER)
    assert request_id
    # Generated IDs are uuid4 — parses cleanly and round-trips.
    assert str(uuid.UUID(request_id)) == request_id


@pytest.mark.asyncio
async def test_request_id_header_reused_when_present(client: AsyncClient) -> None:
    incoming = "trace-abc-123-from-upstream"
    resp = await client.get("/api/health", headers={REQUEST_ID_HEADER: incoming})
    assert resp.status_code == 200
    assert resp.headers.get(REQUEST_ID_HEADER) == incoming


@pytest.mark.asyncio
async def test_request_id_differs_across_requests_without_header(
    client: AsyncClient,
) -> None:
    first = await client.get("/api/health")
    second = await client.get("/api/health")
    assert first.headers[REQUEST_ID_HEADER] != second.headers[REQUEST_ID_HEADER]


# ── structlog contextvars propagation (isolated mini-app) ──────────────────
#
# Uses a standalone Starlette app (not whatisup's, to stay independent of its
# global structlog config/caching) with a handler that echoes back whatever
# structlog.contextvars sees mid-request — i.e. exactly what any
# ``logger.info(...)`` call in that handler would have picked up via the
# ``merge_contextvars`` processor.


async def _whoami(request):
    ctx = structlog.contextvars.get_contextvars()
    return JSONResponse({"request_id_in_context": ctx.get("request_id")})


def _build_probe_app() -> Starlette:
    app = Starlette(routes=[Route("/whoami", _whoami)])
    app.add_middleware(RequestIDMiddleware)
    return app


@pytest.mark.asyncio
async def test_request_id_bound_into_structlog_context_for_downstream_handlers() -> None:
    app = _build_probe_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/whoami", headers={REQUEST_ID_HEADER: "ctx-check-1"})

    assert resp.headers[REQUEST_ID_HEADER] == "ctx-check-1"
    assert resp.json()["request_id_in_context"] == "ctx-check-1"


@pytest.mark.asyncio
async def test_request_id_context_does_not_leak_between_requests() -> None:
    app = _build_probe_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        first = await ac.get("/whoami", headers={REQUEST_ID_HEADER: "leaky-id"})
        second = await ac.get("/whoami")  # no header -> fresh generated id

    assert first.json()["request_id_in_context"] == "leaky-id"
    second_id = second.headers[REQUEST_ID_HEADER]
    assert second_id != "leaky-id"
    assert second.json()["request_id_in_context"] == second_id


async def _boom(request):
    raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_request_id_middleware_logs_and_reraises_on_unhandled_exception() -> None:
    """Unhandled exceptions are logged (with context) and still propagate.

    Starlette's own ServerErrorMiddleware — always outermost, wrapping even
    our RequestIDMiddleware — is what turns this into the final 500 response.
    """
    app = Starlette(routes=[Route("/boom", _boom)])
    app.add_middleware(RequestIDMiddleware)

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/boom")

    assert resp.status_code == 500


# ── configure_logging: JSON in prod, console elsewhere ──────────────────────


def _make_settings(**overrides) -> Settings:
    defaults = dict(
        environment="development",
        secret_key="dev-only-not-a-real-secret",
        fernet_key="",
        cors_allowed_origins=["http://localhost:5173"],
        debug=False,
    )
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.fixture
def restore_logging_config():
    """Re-apply the suite's real logging config after mutating it in a test.

    ``configure_logging`` mutates *global* state (structlog config + the root
    stdlib logger's handlers). Other tests rely on that global state existing
    in its normal "test" shape, so every test that calls ``configure_logging``
    directly must restore it afterwards.
    """
    yield
    configure_logging(get_settings())


def _capture_one_log_line(settings: Settings, event: str = "test_event", **kw) -> str:
    configure_logging(settings)
    handler = logging.getLogger().handlers[0]
    stream = StringIO()
    handler.stream = stream
    logger = structlog.get_logger(f"test.logging.{settings.environment}.{uuid.uuid4().hex}")
    logger.info(event, **kw)
    handler.flush()
    return stream.getvalue().strip()


def test_configure_logging_renders_json_in_production(restore_logging_config) -> None:
    prod_settings = _make_settings(
        environment="production",
        secret_key="a-very-real-looking-secret-key-32c",
        fernet_key=Fernet.generate_key().decode(),
        cors_allowed_origins=["https://example.com"],
    )
    output = _capture_one_log_line(prod_settings, foo="bar")

    payload = json.loads(output)  # must be a single valid JSON object
    assert payload["event"] == "test_event"
    assert payload["foo"] == "bar"
    assert payload["level"] == "info"
    assert "timestamp" in payload
    assert "logger" in payload


def test_configure_logging_renders_console_in_dev(restore_logging_config) -> None:
    dev_settings = _make_settings(environment="development")
    output = _capture_one_log_line(dev_settings, foo="bar")

    with pytest.raises(json.JSONDecodeError):
        json.loads(output)
    assert "test_event" in output
    assert "foo" in output


def test_configure_logging_respects_debug_level(restore_logging_config) -> None:
    settings = _make_settings(environment="development", debug=True)
    configure_logging(settings)
    assert logging.getLogger().level == logging.DEBUG

    settings = _make_settings(environment="development", debug=False)
    configure_logging(settings)
    assert logging.getLogger().level == logging.INFO
