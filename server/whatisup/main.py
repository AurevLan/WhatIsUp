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
from whatisup.core.logging import configure_logging
from whatisup.core.metrics import track_background_task
from whatisup.core.middleware import (
    MaxRequestSizeMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    unhandled_exception_handler,
)
from whatisup.core.redis import close_redis

# Configure structlog (+ stdlib logging bridge) before anything logs a line —
# every `structlog.get_logger(__name__)` call site across the codebase (lazy
# proxies) picks this up automatically, no per-module change needed.
configure_logging(get_settings())

logger = structlog.get_logger(__name__)


async def _retention_job() -> None:
    """Run nightly data retention purge at 03:00 UTC on the leader replica only.

    Cron-like schedule (sleep-until-03:00-then-run), so it can't use the generic
    ``run_leader_loop`` helper; it gates the purge behind a ``LeaderLock`` and
    releases it on shutdown.
    """
    from whatisup.core.leader import LeaderLock
    from whatisup.services.retention import purge_old_results

    settings = get_settings()
    lock = LeaderLock("retention")

    try:
        while True:
            now = datetime.now(UTC)
            # Next 03:00 UTC
            next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            wait_seconds = (next_run - now).total_seconds()
            await asyncio.sleep(wait_seconds)
            await lock.try_acquire()
            if not lock.is_leader:
                continue
            try:
                async with track_background_task("retention"):
                    await purge_old_results(settings.data_retention_days)
            except Exception as exc:
                logger.error("retention_job_failed", error_type=type(exc).__name__, error=str(exc))
    finally:
        await lock.release()


async def _recover_digests_once(redis=None) -> None:
    """One-shot at startup: flush digest windows persisted in DB during downtime.

    Gated by a leader lock held for the duration of the run — the recovery does
    SELECT-then-delete without any DB-level lock, so two replicas booting in
    parallel could otherwise double-send the same stale digests. Fails open if
    Redis is down, consistent with the other leader-gated tasks (worst case a
    duplicate digest, never a dropped one).
    """
    from whatisup.core.leader import LeaderLock

    lock = LeaderLock("digest_recovery", redis=redis)
    try:
        if await lock.try_acquire():
            from whatisup.services.alert import recover_digest_windows

            await recover_digest_windows()
    except Exception as exc:
        logger.error("digest_recovery_error", error=str(exc))
    finally:
        await lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    # Re-assert our logging config: uvicorn applies its own dictConfig *after*
    # this module was imported (uvicorn.Config.__init__), re-attaching a
    # plain-text StreamHandler on `uvicorn.access` (propagate=False) and its
    # own handlers on `uvicorn`/`uvicorn.error`. The `whatisup-server` binary
    # passes `log_config=None` (see main() below), but anyone running
    # `uvicorn whatisup.main:app` directly gets the default config — lifespan
    # runs after uvicorn's logging setup, so this call always wins.
    configure_logging(settings)
    logger.info("whatisup_starting", version=settings.app_version, env=settings.environment)

    # Singleton background loops are wrapped in a Redis leader lock so that when
    # the API runs as N replicas each loop still executes on one replica only
    # (no duplicate incidents / alerts / purges). See whatisup.core.leader.
    from whatisup.api.v1.ws import _redis_subscriber
    from whatisup.core.leader import run_leader_loop

    # Start Redis subscriber for WebSocket broadcasting.
    # NOT leader-elected: every replica must subscribe to fan broadcasts out to
    # its own connected WebSocket clients.
    subscriber_task = asyncio.create_task(_redis_subscriber())

    # Start nightly data retention job (self-gates via LeaderLock).
    retention_task = asyncio.create_task(_retention_job())

    # Heartbeat monitor checker (every 30s)
    async def _heartbeat_work():
        from whatisup.services.heartbeat import check_heartbeats

        await check_heartbeats()

    heartbeat_task = asyncio.create_task(
        run_leader_loop("heartbeat_checker", _heartbeat_work, interval=30)
    )

    # Autonomous renotify checker (every 60s)
    async def _renotify_work():
        from whatisup.services.renotify import check_renotify

        await check_renotify()

    renotify_task = asyncio.create_task(
        run_leader_loop("renotify_checker", _renotify_work, interval=60)
    )

    # Recover any digest windows lost during Redis downtime (leader-gated
    # one-shot — see _recover_digests_once).
    await _recover_digests_once()

    # Digest flusher (every 30s) — survives restarts via Redis sorted set
    async def _digest_flusher_work():
        from whatisup.services.alert import flush_pending_digests

        await flush_pending_digests()

    digest_flusher_task = asyncio.create_task(
        run_leader_loop("digest_flusher", _digest_flusher_work, interval=30)
    )

    # SLA report scheduler (hourly check)
    async def _report_scheduler_work():
        from whatisup.services.reports import check_and_send_reports

        await check_and_send_reports()

    report_task = asyncio.create_task(
        run_leader_loop("report_scheduler", _report_scheduler_work, interval=3600)
    )

    # V2-02-02 — Network verdict recompute (every 5 min) for all open incidents.
    async def _network_verdict_work():
        from whatisup.core.database import get_session_factory
        from whatisup.services.network_verdict import recompute_open_incidents_verdicts

        async with get_session_factory()() as bg_db:
            await recompute_open_incidents_verdicts(bg_db)

    # Wait once at startup so we don't race with migrations / probe registration.
    network_verdict_task = asyncio.create_task(
        run_leader_loop("network_verdict", _network_verdict_work, interval=300, initial_delay=60)
    )

    # V2-02-01 — Probe ASN refresh (every 6h, picks up stale probes that haven't
    # heartbeated since the last refresh window).
    async def _asn_refresh_work():
        from whatisup.core.database import get_session_factory
        from whatisup.services.probe_enrichment import refresh_stale_probes

        async with get_session_factory()() as bg_db:
            await refresh_stale_probes(bg_db)

    asn_refresh_task = asyncio.create_task(
        run_leader_loop("asn_refresh", _asn_refresh_work, interval=6 * 3600, initial_delay=120)
    )

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

    renotify_task.cancel()
    try:
        await renotify_task
    except asyncio.CancelledError:
        pass

    digest_flusher_task.cancel()
    try:
        await digest_flusher_task
    except asyncio.CancelledError:
        pass

    report_task.cancel()
    try:
        await report_task
    except asyncio.CancelledError:
        pass

    network_verdict_task.cancel()
    try:
        await network_verdict_task
    except asyncio.CancelledError:
        pass

    asn_refresh_task.cancel()
    try:
        await asn_refresh_task
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

    # Unhandled exceptions: Starlette's ServerErrorMiddleware uses this handler
    # to build the 500 response (generic JSON + X-Request-ID header for support
    # correlation), then still re-raises so the exception reaches the server
    # logs / test client exactly as before.
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Trust proxy headers from nginx — `trusted_hosts` expects client IPs (the
    # reverse proxy's IP), not CORS origin URLs. Passing a list like
    # ['https://whatisup.aurevan.com'] silently disables the middleware and
    # breaks X-Forwarded-Proto: redirects (e.g. FastAPI's trailing-slash 307 on
    # `/probes` → `/probes/`) are then emitted with scheme `http`, which the
    # browser blocks under HTTPS. The API container is only reachable via nginx
    # on the internal docker network, so wildcard trust is safe here.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    # Request size limit (5 MB)
    app.add_middleware(MaxRequestSizeMiddleware)

    # Security headers
    app.add_middleware(SecurityHeadersMiddleware)

    # CORS — no wildcard with credentials.
    # Always allow the Capacitor mobile app origins so self-hosted users never
    # have to whitelist them manually. These are stable, well-known origins
    # baked into every Capacitor build (see frontend/capacitor.config.json).
    mobile_app_origins = ["https://localhost", "capacitor://localhost"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins + mobile_app_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Probe-Api-Key", "X-Api-Key"],
        # Without this, cross-origin JS (browser dashboard on another origin,
        # Capacitor app) cannot read the correlation ID to show it to support.
        expose_headers=["X-Request-ID"],
    )

    # Request ID — added last so it's the outermost middleware (Starlette
    # wraps in reverse registration order): it runs before everything else on
    # the way in, binding `request_id` into structlog's contextvars so every
    # log line for this request carries it, and runs last on the way out so
    # the response header always makes it through untouched.
    app.add_middleware(RequestIDMiddleware)

    # Routers
    from whatisup.api.v1 import (
        admin,
        alerts,
        api_keys,
        audit,
        auth,
        bgp,
        config,
        extension,
        groups,
        incident_updates,
        incidents_list,
        maintenance,
        metrics,
        monitors,
        onboarding,
        ping,
        probes,
        public,
        sessions,
        silences,
        status,
        tags,
        teams,
        templates,
        tls_fleet,
        totp,
        web_push,
        ws,
    )

    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(totp.router, prefix="/api/v1")
    app.include_router(sessions.router, prefix="/api/v1")
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
    app.include_router(silences.router, prefix="/api/v1")
    app.include_router(ping.router, prefix="/api/v1")
    app.include_router(metrics.router, prefix="/api/v1")
    app.include_router(incidents_list.router, prefix="/api/v1")
    app.include_router(incident_updates.router, prefix="/api/v1")
    app.include_router(config.router, prefix="/api/v1")
    app.include_router(onboarding.router, prefix="/api/v1")
    app.include_router(tags.router, prefix="/api/v1")
    app.include_router(teams.router, prefix="/api/v1")
    app.include_router(templates.router, prefix="/api/v1")
    app.include_router(web_push.router, prefix="/api/v1")
    app.include_router(tls_fleet.router, prefix="/api/v1")
    app.include_router(bgp.router, prefix="/api/v1")
    from whatisup.api.v1 import devices

    app.include_router(devices.router, prefix="/api/v1")
    app.include_router(extension.router, prefix="/api/v1")

    # Prometheus metrics (optional dependency)
    try:
        import secrets as _secrets

        from fastapi import Header, HTTPException
        from prometheus_fastapi_instrumentator import Instrumentator

        def _require_metrics_access(authorization: str | None = Header(default=None)) -> None:
            """Defence-in-depth gate on /api/metrics.

            No-op unless ``METRICS_AUTH_TOKEN`` is configured (deployments already
            restrict this endpoint at the reverse proxy — SECURITY.md §8). When
            set, a constant-time bearer-token match is required.
            """
            token = get_settings().metrics_auth_token
            if not token:
                return
            expected = f"Bearer {token}"
            if not authorization or not _secrets.compare_digest(authorization, expected):
                raise HTTPException(status_code=401, detail="Unauthorized")

        Instrumentator().instrument(app).expose(
            app,
            endpoint="/api/metrics",
            dependencies=[Depends(_require_metrics_access)],
        )
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
        except Exception as exc:
            logger.warning("health_db_error", error=str(exc))

        try:
            r = get_redis()
            await r.ping()
            redis_ok = True
        except Exception as exc:
            logger.warning("health_redis_error", error=str(exc))

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
        # CRITICAL: without this, uvicorn.Config applies its default dictConfig
        # *after* our configure_logging() (module import above) and re-attaches
        # a plain-text StreamHandler on `uvicorn.access` (propagate=False) →
        # in production every request is logged twice (structured
        # `request_handled` JSON + plain-text access line) and uvicorn
        # lifecycle logs bypass the JSON renderer. `log_config=None` makes
        # uvicorn leave logging configuration entirely to us (lifespan also
        # re-asserts it as a second line of defence).
        log_config=None,
    )
