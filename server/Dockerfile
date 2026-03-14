# ── Stage 1: Build ─────────────────────────────────────────────────────────────
FROM python:3.14-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends gcc libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY whatisup/ whatisup/

# Non-editable install into an isolated prefix
RUN pip install --no-cache-dir --prefix=/install .

# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends libssl-dev \
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
    && chown -R whatisup:whatisup /app

USER whatisup

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["whatisup-server"]
