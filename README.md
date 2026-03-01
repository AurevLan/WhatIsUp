# WhatIsUp

Web monitoring platform with multi-probe geographic correlation, RBAC, real-time dashboard, and public status pages.

## Features

- **HTTP/HTTPS monitoring** — status code checks, redirect following, response time
- **SSL certificate monitoring** — validity and expiry warnings
- **Multi-probe architecture** — deploy probes in multiple locations, correlate global vs geographic outages
- **Real-time dashboard** — WebSocket updates, no page refresh needed
- **Alerting** — Email, Webhook (HMAC-signed), Telegram
- **Public status pages** — shareable `yoursite.com/status/my-services`
- **RBAC** — tag-based permissions (view/edit/admin per tag)
- **External API** — integrate with your own monitoring tools

## Quick Start (Development)

```bash
# 1. Clone and enter project
cd WhatIsUp

# 2. Start infrastructure (PostgreSQL + Redis)
docker compose up postgres redis -d

# 3. Install server
cd server
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env  # Edit as needed

# 4. Run migrations
DATABASE_URL=postgresql+asyncpg://whatisup:whatisup_dev_password@localhost:5432/whatisup \
  .venv/bin/alembic upgrade head

# 5. Start server
.venv/bin/uvicorn whatisup.main:app --reload --port 8000

# 6. Install and start frontend
cd ../frontend
npm install
npm run dev  # http://localhost:5173
```

## Running Tests

```bash
# Server tests
cd server && .venv/bin/pytest tests/ -v

# Probe tests
cd probe
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/ -v
```

## Deploying a Probe

```bash
# On the remote server:
pip install whatisup-probe

# Configure (copy and edit):
cp .env.example .env
# Set CENTRAL_API_URL, PROBE_API_KEY, PROBE_NAME, PROBE_LOCATION

# Run
whatisup-probe

# Or via Docker:
docker run -e CENTRAL_API_URL=https://your-server.com \
           -e PROBE_API_KEY=wiu_... \
           -e PROBE_NAME=ny-probe \
           -e PROBE_LOCATION="New York, US" \
           whatisup/probe:latest
```

## Production Deployment

```bash
# Set required env vars in docker-compose.prod.yml or a .env.prod file
POSTGRES_PASSWORD=... SECRET_KEY=... REDIS_PASSWORD=... \
  docker compose -f docker-compose.prod.yml up -d
```

## Architecture

```
┌─────────────────────────────────┐
│         Central Server          │
│  FastAPI + PostgreSQL + Redis   │
│  Vue.js 3 Dashboard             │
└────────────┬────────────────────┘
             │ HTTPS (push)
    ┌────────┼────────┐
    │        │        │
 Probe    Probe    Probe
 Paris    New York  Tokyo
```

## API Documentation

Available at `http://localhost:8000/api/docs` (development mode only).

## Security

See [SECURITY.md](SECURITY.md) for vulnerability reporting.
