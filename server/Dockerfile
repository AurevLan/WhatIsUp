# ── Stage 1: Build ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends gcc libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY whatisup/ whatisup/

# Non-editable install into an isolated prefix
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libssl3 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Installed packages and console scripts
COPY --from=builder /install /usr/local

# App source (needed by alembic migrations imports)
COPY --from=builder /build/whatisup ./whatisup/
COPY alembic/ alembic/
COPY alembic.ini .

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh \
    && useradd -m -u 1000 whatisup \
    && chown -R whatisup:whatisup /app \
    && mkdir -p /shared && chown whatisup:whatisup /shared

USER whatisup

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=30s \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["whatisup-server"]
