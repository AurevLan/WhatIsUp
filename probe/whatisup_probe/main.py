"""WhatIsUp probe agent entrypoint."""

from __future__ import annotations

import asyncio
import signal
import sys

import structlog

from whatisup_probe.config import get_settings
from whatisup_probe.scheduler import ProbeScheduler

logger = structlog.get_logger(__name__)


async def run() -> None:
    settings = get_settings()
    scheduler = ProbeScheduler()

    loop = asyncio.get_running_loop()

    def _shutdown(sig: signal.Signals) -> None:
        logger.info("shutdown_signal", signal=sig.name)
        scheduler.stop()
        loop.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    logger.info(
        "probe_starting",
        name=settings.probe_name,
        location=settings.probe_location,
        central=settings.central_api_url,
    )

    await scheduler.start()

    # Keep running until stopped
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass


def main() -> None:
    import logging
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper(), stream=sys.stdout)
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
    )
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
