# WhatIsUp

Web monitoring platform with multi-probe geographic correlation, real-time dashboard, alerting, and public status pages.

## Features

- **HTTP/HTTPS monitoring** — status codes, redirect following, response time tracking
- **SSL certificate monitoring** — validity checks, expiry warnings (configurable threshold)
- **Multi-probe architecture** — deploy probes in multiple locations, automatically distinguish global outages from geographic ones
- **Real-time dashboard** — WebSocket updates, no manual refresh
- **Alerting** — Email (SMTP), Webhook (HMAC-SHA256 signed), Telegram Bot
- **Public status pages** — shareable `yoursite.com/status/my-services`, no login required
- **RBAC** — tag-based permissions (view / edit / admin per tag group)
- **External API** — `GET /api/v1/status/monitors` for third-party integrations

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI 0.115 + Python 3.12 |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 async |
| Cache / pub-sub | Redis 7 |
| Migrations | Alembic |
| Frontend | Vue.js 3 + Vite + Pinia + Tailwind CSS |
| Charts | ApexCharts |
| Probe scheduler | APScheduler 3 |
| Auth | JWT (access 15 min / refresh 7 d) + bcrypt |

---

## Quick Start (Docker — recommended)

```bash
git clone https://github.com/AurevLan/WhatIsUp.git
cd WhatIsUp
docker compose up -d
```

That's it. Docker Compose will:
1. Start **PostgreSQL** and **Redis** (with healthchecks)
2. Run **Alembic migrations** automatically
3. Start the **API server** on port 8000
4. Start the **Vue.js frontend** on port 5173 (Vite dev server)

Open **http://localhost:5173** and create your first account (the first user becomes superadmin).

### Add a local probe (dev)

```bash
# 1. Register a probe via the API (you need a superadmin token)
curl -s -X POST http://localhost:8000/api/v1/probes/register \
  -H "Authorization: Bearer <your_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "local-probe", "location_name": "Local", "latitude": 48.8566, "longitude": 2.3522}'
# → note the returned api_key (shown only once)

# 2. Start the probe container
PROBE_API_KEY=wiu_... docker compose --profile probe up -d probe-local
```

---

## Running Tests

```bash
# Server (11 tests)
cd server && .venv/bin/pytest tests/ -v --tb=short

# Probe (6 tests)
cd probe && .venv/bin/pytest tests/ -v
```

Or install the dev dependencies first if you haven't already:

```bash
cd server && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
cd probe  && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

---

## Production Deployment

### 1. Prepare environment

```bash
cp .env.example .env
# Edit .env — all fields marked "must be set" are required
```

Required variables:

| Variable | Description |
|----------|-------------|
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `REDIS_PASSWORD` | Redis password |
| `SECRET_KEY` | JWT signing secret (≥ 32 chars, random) |
| `FERNET_KEY` | Encryption key for webhook/Telegram secrets |
| `CORS_ALLOWED_ORIGINS` | JSON array of allowed frontend origins |

Generate `FERNET_KEY`:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 2. TLS certificate

Place your certificate and key in `nginx/ssl/`:
```
nginx/ssl/cert.pem
nginx/ssl/key.pem
```

Update `nginx/whatisup.conf` with your actual `server_name`.

### 3. Start the stack

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d
```

Services started: **PostgreSQL** → **Redis** → **Server** (migrations run automatically) → **Frontend** → **Nginx** (ports 80/443).

### 4. Deploy remote probes

On each remote server, copy `docker-compose.probe.yml` and `.env.probe.example`:

```bash
cp .env.probe.example .env.probe
# Fill in CENTRAL_API_URL and PROBE_API_KEY
docker compose -f docker-compose.probe.yml --env-file .env.probe up -d
```

---

## Architecture

```
                    ┌──────────────────────────────┐
                    │        Nginx (443/80)         │
                    │  TLS termination + reverse    │
                    └─────┬──────────────────┬──────┘
                          │                  │
               ┌──────────▼──────┐  ┌────────▼────────┐
               │  FastAPI server │  │  Vue.js frontend │
               │  :8000          │  │  (built, nginx)  │
               └──────┬──────────┘  └──────────────────┘
                      │
          ┌───────────┼───────────┐
          │           │           │
   ┌──────▼──┐  ┌─────▼───┐  ┌───▼─────────────────────┐
   │Postgres │  │  Redis  │  │  WebSocket pub/sub        │
   │  (BDD)  │  │(cache/  │  │  (real-time dashboard)    │
   └─────────┘  │ pub-sub)│  └───────────────────────────┘
                └─────────┘

Probes (deployed anywhere, push results to the central server):

  ┌───────────────┐   ┌───────────────┐   ┌───────────────┐
  │  Probe Paris  │   │  Probe NY     │   │  Probe Tokyo  │
  │  APScheduler  │   │  APScheduler  │   │  APScheduler  │
  └───────┬───────┘   └───────┬───────┘   └───────┬───────┘
          └───────────────────┼───────────────────┘
                    HTTPS POST /api/v1/probes/results
```

**Incident correlation logic:**
- All probes down → `scope: global` outage
- Some probes down → `scope: geographic` outage
- All probes up → incident resolved automatically

---

## API Documentation

Available at **http://localhost:8000/api/docs** in development mode (`ENVIRONMENT=development`).

Disabled in production for security.

---

## Security

Security-sensitive endpoints are rate-limited (10 req/min on auth, 30 req/min on probe results).
All HTTP responses include security headers (CSP, HSTS, X-Frame-Options, …).
Probe API keys are stored as bcrypt hashes and shown in plain text only once at registration.
Webhook secrets are encrypted at rest with Fernet.

See [SECURITY.md](SECURITY.md) for vulnerability reporting and responsible disclosure policy.

---

## CI / Security scanning

| Check | Trigger |
|-------|---------|
| Lint (`ruff`) | Push / PR to `main` |
| Server tests (`pytest`) | Push / PR to `main` |
| Probe tests (`pytest`) | Push / PR to `main` |
| `pip-audit` (server + probe) | Push / PR + weekly |
| `npm audit` (frontend) | Push / PR + weekly |
| CodeQL (Python + JS) | Push / PR + weekly |

---

## Contributing

1. Fork → feature branch → PR against `main`
2. Fill in the PR template (security checklist mandatory)
3. All CI checks must pass before merge
