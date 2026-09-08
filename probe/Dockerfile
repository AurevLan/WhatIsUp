# ── Stage 1: Build ─────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /build

# System deps for SSL/cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY whatisup_probe/ whatisup_probe/

RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    traceroute iputils-ping dnsutils openssl curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Chromium is opt-in (plan cap v2, 6b): deploying a probe is the product's
# central, repeated gesture, while `scenario` monitors are its least-used
# feature. The default image ships WITHOUT a browser (≈480 Mo measured vs ≈1,97 Go
# with one). Build with `--build-arg WITH_BROWSER=true` — published as the
# `whatisup-probe:X.Y.Z-browser` / `:latest-browser` tags — to get a probe
# that can run `scenario` monitors. A browserless probe still runs every
# other check type; assigning it a `scenario` monitor fails with a clear,
# actionable CheckResult (see checkers/scenario.py), never a raw Playwright
# stack trace.
ARG WITH_BROWSER=false
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN if [ "$WITH_BROWSER" = "true" ]; then \
        playwright install --with-deps chromium && chmod -R 755 /ms-playwright; \
    fi

# Non-root user
RUN useradd -m -u 1000 probe

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER probe

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# The scheduler touches /tmp/whatisup_probe_alive at every sync cycle
# (heartbeat_interval, default 30 s). Stale for >180 s → unhealthy.
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,sys,time; p=os.environ.get('LIVENESS_FILE','/tmp/whatisup_probe_alive'); sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p)<180 else 1)"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["whatisup-probe"]
