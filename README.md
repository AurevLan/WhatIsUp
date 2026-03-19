# WhatIsUp

> Open-source uptime monitoring with multi-probe geographic correlation, real-time dashboard, SLO tracking, alerting, and public status pages.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![Vue 3](https://img.shields.io/badge/Vue-3.5-42b883)](https://vuejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.125+-009688)](https://fastapi.tiangolo.com)
[![PostgreSQL 16](https://img.shields.io/badge/PostgreSQL-16-336791)](https://postgresql.org)

---

## Screenshots

| Dashboard | Monitor detail |
|-----------|---------------|
| ![Dashboard](docs/screenshots/dashboard.svg) | ![Monitor detail](docs/screenshots/monitor-detail.svg) |

| Monitors list | Probe map |
|--------------|-----------|
| ![Monitors](docs/screenshots/monitors-view.svg) | ![Probes](docs/screenshots/probes-map.svg) |

| Public status page | Scenario builder |
|-------------------|-----------------|
| ![Status page](docs/screenshots/public-status.svg) | ![Scenario](docs/screenshots/scenario-builder.svg) |

| Browser extension recorder | |
|---------------------------|---|
| ![Extension](docs/screenshots/extension-recorder.svg) | |

---

## Features

### Monitoring
- **HTTP / HTTPS** — status codes, redirect following, response time, SSL certificate expiry
- **TCP** — port reachability (databases, SSH, SMTP, custom services)
- **UDP** — datagram probe; ICMP port-unreachable = down, timeout = filtered/open
- **DNS** — record resolution with optional value assertion (A, AAAA, CNAME, MX, TXT, NS); drift detection (baseline auto-learn); cross-probe consistency check with split-horizon support
- **Keyword** — response body scan with optional negate mode
- **JSON Path** — structured response validation (e.g. `$.status == "ok"`)
- **SMTP** — banner + EHLO handshake with optional STARTTLS; measures banner-to-ready time
- **Ping** — ICMP round-trip time via system `ping`
- **Domain expiry** — WHOIS lookup; configurable warning days before domain expiration
- **Browser scenarios** — multi-step Playwright automation (navigate, click, fill, assert, extract, screenshot) with Core Web Vitals (LCP, CLS, INP)
- **Composite monitors** — aggregate multiple monitors with `all_up`, `any_up`, `majority_up`, or `weighted_up` rules; drives the full incident pipeline
- **Heartbeat / cron monitoring** — dead-man's switch for scheduled jobs; unique ping URL per monitor
- **Advanced assertions** — regex body check, response header validation (exact or `/regex/`), JSON Schema validation

### Infrastructure
- **Multi-probe architecture** — deploy lightweight probe agents in any location; correlate outages geographically
- **Network type** — tag each probe as `external` (public internet) or `internal` (corporate LAN) to distinguish internal vs external failures
- **Probe map on dashboard** — Leaflet world map with per-probe 24h uptime (🟢 ≥ 99 % / 🟡 ≥ 90 % / 🔴 < 90 %) and online/offline status; auto-refreshes every 60 s
- **City / address geocoding** — type any address or city to auto-resolve GPS coordinates (Nominatim, no API key)

### Observability
- **Real-time dashboard** — WebSocket push, no polling
- **SLO / Error budget** — configurable target (%) and window (days); burn rate and budget-remaining tracking
- **SLA reports** — custom date range, uptime %, incident list, P95 response time; JSON download
- **Custom push metrics** — `POST /api/v1/metrics/{monitor_id}` for business KPIs (orders, latency…)
- **Annotations** — timestamped notes on the monitor timeline (deployments, changes)
- **Response time trend** — 6-hour rolling comparison with colour-coded indicator

### Incidents & alerting
- **Automatic incident lifecycle** — open on failure, resolve on recovery, flapping detection with per-monitor thresholds
- **Incident groups** — monitors sharing the same failing probes within a 90 s window are grouped into one persistent incident group; one notification instead of N
- **Monitor dependencies** — when a parent monitor is down, child incidents are automatically suppressed; eliminates cascade alert storms
- **Alert storm protection** — per-rule rate cap (`storm_max_alerts` within `storm_window_seconds`); forced digest when threshold is exceeded
- **Performance baseline alerting** — alert when response time exceeds a configurable multiple of the 7-day rolling hourly baseline
- **Auto post-mortem** — Markdown report generated on incident resolution (timeline, alerts, metrics)
- **Alert channels** — Email (SMTP), Webhook (HMAC-SHA256), Telegram Bot, Slack, PagerDuty, Opsgenie
- **Persistent digest** — digest scheduling stored in Redis; survives server restarts
- **Maintenance windows** — suppress alerts during planned downtime; group-level suppression support

### Public status pages
- **Shareable URL** — `/status/{slug}`, no login required
- **90-day history bars** — daily uptime visualisation per component
- **Incident timeline** — 30-day incident log with duration
- **Email subscriptions** — visitors subscribe to outage updates; secure unsubscribe token

### Platform
- **Multi-language** — English (default) and French; toggle in the sidebar; persisted to `localStorage`
- **Bulk actions** — multi-select monitors; bulk enable / pause / delete / export CSV
- **Audit trail** — every admin action logged with before/after diff
- **RBAC** — superadmin + per-resource ownership enforcement
- **Data retention** — configurable auto-purge of old check results (default: 90 days)
- **One-command deploy** — interactive wizard generates secrets, `.env`, and starts the stack

### Browser extension — scenario recorder

The WhatIsUp Chrome extension records browser actions and sends them directly to a monitor:

1. Click **Start recording** in the extension popup
2. Navigate and interact with any website — clicks, form fills (including passwords), and navigations are captured automatically
3. Click **Stop** then **Send to WhatIsUp** — the scenario is created as a monitor in one click

**Security**: password values are stored as `{{password_N}}` placeholders in the step list; the real values are kept in a separate encrypted store, encrypted at rest with Fernet, and masked in all API responses. They are decrypted only when delivered to the probe at check time.

Install the extension from `extension/` by loading it as an unpacked extension in Chrome (`chrome://extensions → Load unpacked`).

---

## Quick start

### Requirements

- Docker ≥ 24 and Docker Compose v2
- 1 GB RAM minimum (2 GB recommended for probe with Playwright)
- Ports 80 / 443 available (production) or 5173 / 8000 (development)

### Development (local)

```bash
git clone https://github.com/AurevLan/WhatIsUp.git
cd whatisup

# Start all services (PostgreSQL, Redis, API, frontend, local probe)
docker compose up -d

# Wait for all services to become healthy
docker compose ps
```

| Service | URL |
|---------|-----|
| Frontend (Vite dev server) | http://localhost:5173 |
| API (FastAPI) | http://localhost:8000 |
| API docs (Swagger UI) | http://localhost:8000/docs |

On first start an **admin account** and a **local probe** are created automatically. Check the logs for credentials:

```bash
docker compose logs server | grep -E "admin|api_key|created"
```

### Production deploy

```bash
bash scripts/deploy.sh
```

The wizard generates secrets, configures Nginx + SSL (Let's Encrypt), and starts the production stack.

#### Manual production setup

```bash
# 1. Copy and edit the environment file
cp .env.example .env

# 2. Generate required secrets
SECRET_KEY=$(openssl rand -hex 32)
FERNET_KEY=$(python3 -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# Add to .env
echo "SECRET_KEY=$SECRET_KEY" >> .env
echo "FERNET_KEY=$FERNET_KEY" >> .env

# 3. Start the production stack
docker compose -f docker-compose.prod.yml up -d

# 4. Apply database migrations
docker compose -f docker-compose.prod.yml exec server alembic upgrade head
```

#### Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | ✅ prod | — | JWT signing key (`openssl rand -hex 32`) |
| `FERNET_KEY` | ✅ prod | — | Fernet key for encrypting alert secrets at rest |
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://whatisup:whatisup@localhost/whatisup` | PostgreSQL connection string |
| `REDIS_URL` | — | `redis://localhost:6379/0` | Redis connection string |
| `CORS_ALLOWED_ORIGINS` | ✅ prod | `http://localhost:5173` | Comma-separated HTTPS origins |
| `ENVIRONMENT` | — | `production` | Set to `development` to relax security checks |
| `REGISTRATION_OPEN` | — | `true` | `false` = invite-only after first user |
| `DATA_RETENTION_DAYS` | — | `90` | Days to keep check results (0 = keep forever) |
| `SMTP_HOST` | — | `localhost` | SMTP server for email alerts |
| `SMTP_PORT` | — | `587` | SMTP port |
| `SMTP_USER` | — | — | SMTP username |
| `SMTP_PASSWORD` | — | — | SMTP password |
| `SMTP_FROM` | — | `noreply@example.com` | Sender address |

---

## Deploying probe agents

Probes are lightweight Python processes that run checks from a given location and report results to the central server. Deploy as many as you need in different datacenters, offices, or cloud regions.

### 1. Register the probe

Go to **Probes → Register probe** in the UI:
1. Enter a **name** (e.g. `paris-dc1`) and **location** (any address, city, or landmark)
2. Click **Locate** — Nominatim resolves the location to GPS coordinates automatically
3. Choose **Network type**: `External` (public internet) or `Internal` (corporate LAN)
4. Save — copy the API key displayed **only once**

### 2. Run the probe

```bash
docker run -d \
  --name whatisup-probe \
  --restart unless-stopped \
  -e CENTRAL_URL=https://your-whatisup.example.com \
  -e PROBE_API_KEY=wiu_your_api_key_here \
  -e PROBE_LOCATION="Paris DC1" \
  ghcr.io/your-org/whatisup-probe:latest
```

Or with Docker Compose:

```yaml
# docker-compose.probe.yml
services:
  probe:
    image: ghcr.io/your-org/whatisup-probe:latest
    restart: unless-stopped
    environment:
      CENTRAL_URL: https://your-whatisup.example.com
      PROBE_API_KEY: wiu_your_api_key_here
      PROBE_LOCATION: "Paris DC1"
      MAX_CONCURRENT_CHECKS: "10"
      HEARTBEAT_INTERVAL: "15"
```

### Probe environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CENTRAL_URL` | ✅ | — | WhatIsUp server base URL |
| `PROBE_API_KEY` | ✅ | — | API key from probe registration |
| `PROBE_LOCATION` | — | `unknown` | Display name in the UI |
| `MAX_CONCURRENT_CHECKS` | — | `10` | Max parallel checks |
| `HEARTBEAT_INTERVAL` | — | `15` | Seconds between server heartbeats |

---

## Heartbeat monitoring (cron jobs)

Create a monitor of type **Heartbeat**, copy the generated ping URL, then call it from your job:

```bash
# In your crontab or CI pipeline
curl -s https://your-whatisup.example.com/api/v1/ping/your-heartbeat-slug
```

WhatIsUp opens an incident automatically if no ping arrives within `interval + grace` seconds.

---

## Custom push metrics

Push any numeric metric from your application and visualise it alongside uptime data:

```bash
curl -X POST https://your-whatisup.example.com/api/v1/metrics/{monitor_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"metric_name": "orders_per_minute", "value": 42.5, "unit": "req/min"}'
```

Metrics appear as time-series graphs grouped by `metric_name` in the monitor detail view.

---

## API reference

Full interactive documentation at `/docs` (Swagger UI) and `/redoc`.

### Authentication

```bash
TOKEN=$(curl -s -X POST https://your-whatisup.example.com/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=your_password" \
  | jq -r '.access_token')

curl https://your-whatisup.example.com/api/v1/monitors/ \
  -H "Authorization: Bearer $TOKEN"
```

### Selected endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/monitors/` | List monitors |
| `POST` | `/api/v1/monitors/` | Create monitor |
| `POST` | `/api/v1/monitors/bulk` | Bulk enable / pause / delete |
| `POST` | `/api/v1/monitors/{id}/trigger-check` | Trigger immediate check |
| `GET` | `/api/v1/monitors/{id}/slo` | SLO / error budget status |
| `GET` | `/api/v1/monitors/{id}/report` | SLA report (custom date range) |
| `GET` | `/api/v1/monitors/{id}/incidents/{inc}/postmortem` | Auto post-mortem (Markdown) |
| `GET` | `/api/v1/monitors/{id}/annotations` | List timeline annotations |
| `POST` | `/api/v1/metrics/{monitor_id}` | Push custom metric |
| `GET` | `/api/v1/metrics/{monitor_id}` | List custom metrics |
| `GET` | `/api/v1/public/pages/{slug}/monitors` | Public status page data (no auth) |
| `POST` | `/api/v1/public/pages/{slug}/subscribe` | Subscribe to status page |
| `GET` | `/api/v1/ping/{slug}` | Heartbeat ping |
| `GET` | `/api/v1/status/monitors` | External status API |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        Browser                           │
│   Vue 3 · Pinia · Vite · Tailwind · ApexCharts · Leaflet│
│   vue-i18n (EN / FR)                                    │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP + WebSocket
┌───────────────────────▼─────────────────────────────────┐
│                    FastAPI server                         │
│  auth · monitors · probes · alerts · metrics · ws        │
│  slowapi · structlog · Alembic · Prometheus metrics      │
└─────┬──────────────────┬──────────────────┬─────────────┘
      │                  │                  │
┌─────▼──────┐  ┌────────▼──────┐  ┌───────▼───────────┐
│ PostgreSQL │  │     Redis     │  │   Probe agent(s)  │
│  (main DB) │  │ cache · pub/  │  │  APScheduler      │
│            │  │ sub · rate    │  │  Playwright        │
└────────────┘  └───────────────┘  └───────────────────┘
```

| Layer | Location |
|-------|----------|
| API endpoints | `server/whatisup/api/v1/` |
| ORM models | `server/whatisup/models/` |
| Pydantic schemas | `server/whatisup/schemas/` |
| Business logic | `server/whatisup/services/` |
| Core (config, security, db) | `server/whatisup/core/` |
| Probe agent | `probe/whatisup_probe/` |
| Frontend | `frontend/src/` |

---

## Development

### Tests & linting

```bash
# Backend
cd server
pip install -e ".[dev]"
pytest
ruff check . && ruff format .
pip-audit

# Frontend
cd frontend
npm run lint
npm audit
```

### Database migrations

```bash
cd server

# Generate after model changes
alembic revision --autogenerate -m "short description"

# Apply
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

---

## Security

- **JWT** — HS256, access 15 min + refresh 7 days, Redis-revocable
- **Probe auth** — `X-Probe-Api-Key` bcrypt 12 rounds + Redis cache 300 s
- **WebSocket auth** — JSON message frame (`{"type":"auth","token":"…"}`), never URL parameter
- **Secrets at rest** — Fernet encryption for alert channel secrets (SMTP passwords, Telegram tokens, webhook secrets, PagerDuty / Opsgenie keys) **and** scenario variables (`secret: true`); `FERNET_KEY` is required in production (server refuses to start without it)
- **SSRF protection** — all outbound webhook URLs (generic + Slack) validated against private/loopback ranges before any HTTP request
- **CORS** — explicit origins only; HTTP origins rejected in production
- **CSP** — `default-src 'self'; script-src 'self'`
- **Rate limiting** — login 10/min, register 5/min, heartbeat 30/min, results 60/min, monitor creation 10/min
- **WebSocket** — per-IP connection limit enforced before the auth handshake; public slug validated against DB before accepting
- **Ownership enforcement** — all mutating endpoints (including alert rule delete) verify resource ownership via JOIN; superadmin bypass is explicit
- **Docker** — non-root user in all images; CPU/memory resource limits in production

See [SECURITY.md](SECURITY.md) for the responsible disclosure policy.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

## License

MIT — see [LICENSE](LICENSE).
