"""structlog configuration — JSON logs in production, readable console in dev.

Every module in the codebase already does ``logger = structlog.get_logger(__name__)``
at import time. ``get_logger`` is lazy — it doesn't touch global config until the
first actual log call — so calling :func:`configure_logging` once at process
startup (``main.py``) is enough for all of them to pick up the shared processor
chain, without touching a single call site.

Also bridges the standard library ``logging`` module (uvicorn, sqlalchemy, ...)
through the same renderer, so third-party logs match the app's own format.
"""

from __future__ import annotations

import logging
import sys

import structlog

from whatisup.core.config import Settings

# Processors that run for *every* log entry, structlog- or stdlib-originated,
# before the final renderer (JSON vs console) is applied.
_SHARED_PROCESSORS: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.stdlib.PositionalArgumentsFormatter(),
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    structlog.processors.UnicodeDecoder(),
]


def configure_logging(settings: Settings) -> None:
    """Configure structlog + stdlib logging for the whole process.

    - Production (``settings.is_production``): single-line JSON to stdout,
      suitable for log aggregators (ISO timestamps, level, logger name).
    - Anything else (dev/test): a human-readable, optionally colored console
      renderer.
    """
    json_logs = settings.is_production
    log_level = logging.DEBUG if settings.debug else logging.INFO

    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        cache_logger_on_first_use=True,
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Route uvicorn's own loggers through the same handler/formatter instead
    # of letting them print their default plain-text format.
    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = []
        uv_logger.propagate = True

    # uvicorn's access log is redundant: RequestIDMiddleware already emits a
    # structured `request_handled` line (with request_id, duration, status)
    # for every request. Silence the plain-text duplicate.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers = []
    access_logger.propagate = False
