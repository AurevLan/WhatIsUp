"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from whatisup.core.config import get_settings
from whatisup.core.database import get_db as get_db_dep
from whatisup.core.limiter import limiter
from whatisup.core.middleware import MaxRequestSizeMiddleware, SecurityHeadersMiddleware
from whatisup.core.redis import close_redis

logger = structlog.get_logger(__name__)


async def _retention_job() -> None:
    """Run nightly data retention purge at 03:00 UTC."""
    from whatisup.services.retention import purge_old_results

    settings = get_settings()

    while True:
        now = datetime.now(UTC)
        # Next 03:00 UTC
        next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        wait_seconds = (next_run - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        try:
            await purge_old_results(settings.data_retention_days)
        except Exception as exc:
            logger.error("retention_job_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("whatisup_starting", version=settings.app_version, env=settings.environment)

    # Start Redis subscriber for WebSocket broadcasting
    from whatisup.api.v1.ws import _redis_subscriber

    subscriber_task = asyncio.create_task(_redis_subscriber())

    # Start nightly data retention job
    retention_task = asyncio.create_task(_retention_job())

    # Heartbeat monitor checker (every 30s)
    async def _heartbeat_checker():
        from whatisup.services.heartbeat import check_heartbeats

        while True:
            try:
                await check_heartbeats()
            except Exception as exc:
                logger.error("heartbeat_checker_error", error=str(exc))
            await asyncio.sleep(30)

    heartbeat_task = asyncio.create_task(_heartbeat_checker())

    # Digest flusher (every 30s) — survives restarts via Redis sorted set
    async def _digest_flusher():
        from whatisup.services.alert import flush_pending_digests

        while True:
            try:
                await flush_pending_digests()
            except Exception as exc:
                logger.error("digest_flusher_error", error=str(exc))
            await asyncio.sleep(30)

    digest_flusher_task = asyncio.create_task(_digest_flusher())

    yield

    subscriber_task.cancel()
    try:
        await subscriber_task
    except asyncio.CancelledError:
        pass

    retention_task.cancel()
    try:
        await retention_task
    except asyncio.CancelledError:
        pass

    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    digest_flusher_task.cancel()
    try:
        await digest_flusher_task
    except asyncio.CancelledError:
        pass

    await close_redis()
    logger.info("whatisup_stopped")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        openapi_url="/api/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # Rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Trust proxy headers from nginx (fixes https:// in redirects behind reverse proxy)
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    # Request size limit (5 MB)
    app.add_middleware(MaxRequestSizeMiddleware)

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS — no wildcard with credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Probe-Api-Key", "X-Api-Key"],
    )

    # Routers
    from whatisup.api.v1 import (
        admin,
        alerts,
        api_keys,
        audit,
        auth,
        groups,
        incident_updates,
        incidents,
        maintenance,
        metrics,
        monitors,
        ping,
        probes,
        public,
        status,
        templates,
        ws,
    )

    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(api_keys.router, prefix="/api/v1")
    app.include_router(monitors.router, prefix="/api/v1")
    app.include_router(groups.router, prefix="/api/v1")
    app.include_router(probes.router, prefix="/api/v1")
    app.include_router(alerts.router, prefix="/api/v1")
    app.include_router(public.router, prefix="/api/v1")
    app.include_router(status.router, prefix="/api/v1")
    app.include_router(ws.router)
    app.include_router(audit.router, prefix="/api/v1")
    app.include_router(maintenance.router, prefix="/api/v1")
    app.include_router(ping.router, prefix="/api/v1")
    app.include_router(metrics.router, prefix="/api/v1")
    app.include_router(incidents.router, prefix="/api/v1")
    app.include_router(incident_updates.router, prefix="/api/v1")
    app.include_router(templates.router, prefix="/api/v1")

    # Prometheus metrics (optional dependency)
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")
    except ImportError:
        logger.warning("prometheus_fastapi_instrumentator not installed, /api/metrics unavailable")

    @app.get("/api/health", tags=["health"])
    async def health(db: AsyncSession = Depends(get_db_dep)) -> dict:
        from sqlalchemy import text

        from whatisup.core.redis import get_redis

        db_ok = False
        redis_ok = False

        try:
            await db.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            pass

        try:
            r = get_redis()
            await r.ping()
            redis_ok = True
        except Exception:
            pass

        overall = "ok" if db_ok and redis_ok else "degraded"
        return {
            "status": overall,
            "version": settings.app_version,
            "services": {
                "db": "ok" if db_ok else "error",
                "redis": "ok" if redis_ok else "error",
            },
        }

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "whatisup.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="info",
    )
