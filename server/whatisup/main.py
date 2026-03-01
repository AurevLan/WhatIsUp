"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from whatisup.core.config import get_settings
from whatisup.core.limiter import limiter
from whatisup.core.middleware import SecurityHeadersMiddleware
from whatisup.core.redis import close_redis

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("whatisup_starting", version=settings.app_version, env=settings.environment)

    # Start Redis subscriber for WebSocket broadcasting
    from whatisup.api.v1.ws import _redis_subscriber
    subscriber_task = asyncio.create_task(_redis_subscriber())

    yield

    subscriber_task.cancel()
    try:
        await subscriber_task
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

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS — no wildcard with credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Probe-Api-Key"],
    )

    # Routers
    from whatisup.api.v1 import alerts, auth, groups, monitors, probes, public, status, ws

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(monitors.router, prefix="/api/v1")
    app.include_router(groups.router, prefix="/api/v1")
    app.include_router(probes.router, prefix="/api/v1")
    app.include_router(alerts.router, prefix="/api/v1")
    app.include_router(public.router, prefix="/api/v1")
    app.include_router(status.router, prefix="/api/v1")
    app.include_router(ws.router)

    @app.get("/api/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "version": settings.app_version}

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
