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
@pytest.mark.parametrize(
    "malicious",
    [
        "x" * 129,  # too long (limit 128)
        "id with spaces",  # forbidden charset
        "evil;id=(injection)",  # forbidden charset
        '{"json": "payload"}',  # forbidden charset
    ],
)
async def test_request_id_invalid_client_value_is_never_echoed(
    client: AsyncClient, malicious: str
) -> None:
    """Malformed client-supplied IDs are discarded, not echoed back.

    A fresh uuid4 must be generated instead — the client value must appear
    neither in the response header nor (via contextvars) in the logs.
    """
    resp = await client.get("/api/health", headers={REQUEST_ID_HEADER: malicious})
    assert resp.status_code == 200
    echoed = resp.headers.get(REQUEST_ID_HEADER)
    assert echoed != malicious
    assert str(uuid.UUID(echoed)) == echoed  # regenerated, valid uuid4


@pytest.mark.asyncio
async def test_request_id_max_valid_length_accepted(client: AsyncClient) -> None:
    incoming = "A" * 128  # exactly at the limit, valid charset
    resp = await client.get("/api/health", headers={REQUEST_ID_HEADER: incoming})
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


@pytest.mark.asyncio
async def test_500_response_carries_request_id_header() -> None:
    """Unhandled exceptions → generic JSON 500 *with* X-Request-ID.

    The real app registers ``unhandled_exception_handler`` for ``Exception``,
    so Starlette's ServerErrorMiddleware builds the 500 from it (header
    included) instead of its bare plain-text response — the support-facing
    correlation ID must survive the one path where users need it most.
    """
    from whatisup.main import app as real_app

    async def _boom_route():
        raise RuntimeError("boom")

    real_app.add_api_route("/api/test-boom-500", _boom_route, methods=["GET"])
    try:
        transport = ASGITransport(app=real_app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/test-boom-500", headers={REQUEST_ID_HEADER: "err-trace-42"})
    finally:
        real_app.router.routes[:] = [
            r for r in real_app.router.routes if getattr(r, "path", None) != "/api/test-boom-500"
        ]

    assert resp.status_code == 500
    assert resp.headers.get(REQUEST_ID_HEADER) == "err-trace-42"
    assert resp.json() == {"detail": "Internal Server Error"}


# ── CORS: X-Request-ID readable cross-origin ─────────────────────────────────


@pytest.mark.asyncio
async def test_cors_exposes_request_id_header(client: AsyncClient) -> None:
    """Cross-origin JS (browser/Capacitor) must be able to read the ID."""
    resp = await client.get("/api/health", headers={"Origin": "capacitor://localhost"})
    assert resp.status_code == 200
    exposed = resp.headers.get("access-control-expose-headers", "")
    assert "x-request-id" in exposed.lower()


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


# ── uvicorn log config: default clobbers ours, log_config=None must be used ──
#
# uvicorn.Config applies its default dictConfig when instantiated — i.e. AFTER
# our module-level configure_logging() has run. Review M1: the `whatisup-server`
# binary (Docker prod ENTRYPOINT) originally called uvicorn.run() without
# log_config=None, so uvicorn re-attached a plain-text StreamHandler on
# `uvicorn.access` (propagate=False) → double access line per request in prod
# (JSON `request_handled` + plain text) and non-JSON uvicorn lifecycle logs.


def test_uvicorn_default_log_config_reattaches_access_handler(restore_logging_config) -> None:
    """Pin the bug that motivates log_config=None (empirically validated in review).

    If this ever stops failing-the-old-way (i.e. uvicorn's default config no
    longer re-attaches handlers), the log_config=None guard becomes optional.
    """
    import uvicorn

    configure_logging(_make_settings())
    access = logging.getLogger("uvicorn.access")
    assert access.handlers == []
    assert access.propagate is False

    cfg = uvicorn.Config("whatisup.main:app", log_level="info")  # default log_config
    cfg.configure_logging()

    assert access.handlers, "uvicorn default dictConfig no longer re-attaches a handler?"
    assert access.propagate is False  # plain-text handler, bypasses our JSON renderer


def test_uvicorn_log_config_none_preserves_structlog_setup(restore_logging_config) -> None:
    import uvicorn

    configure_logging(_make_settings())
    root_handler = logging.getLogger().handlers[0]

    cfg = uvicorn.Config("whatisup.main:app", log_config=None, log_level="info")
    cfg.configure_logging()

    access = logging.getLogger("uvicorn.access")
    assert access.handlers == []
    assert access.propagate is False
    assert logging.getLogger("uvicorn").handlers == []
    assert logging.getLogger().handlers == [root_handler]  # ours, untouched


def test_server_entrypoint_passes_log_config_none(monkeypatch) -> None:
    """The `whatisup-server` binary must run uvicorn with log_config=None."""
    import uvicorn

    import whatisup.main as main_module

    captured: dict = {}

    def _fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", _fake_run)
    main_module.main()

    assert captured["app"] == "whatisup.main:app"
    assert "log_config" in captured, "uvicorn.run() called without log_config → default dictConfig"
    assert captured["log_config"] is None
