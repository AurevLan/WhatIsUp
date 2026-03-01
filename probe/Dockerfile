FROM python:3.12-slim

WORKDIR /app

# System deps for SSL/cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Install probe package
COPY pyproject.toml README.md ./
COPY whatisup_probe/ whatisup_probe/

RUN pip install --no-cache-dir -e .

# Non-root user
RUN useradd -m -u 1000 probe

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER probe

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["whatisup-probe"]
