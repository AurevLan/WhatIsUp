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

# Install Playwright browsers in a shared path accessible to any user
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium \
    && chmod -R 755 /ms-playwright

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
