# Changelog

All notable changes to WhatIsUp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.2.0] - 2026-03-01

### Added

#### Automatic first-boot initialisation
- `server/whatisup/init_data.py` — runs after Alembic migrations on every start
- Creates `admin@local` with a strong random password (20 chars, alphanum + symbols) if no user exists — credentials printed to stdout via `docker compose logs server`
- Registers `Central-Probe` automatically when `AUTO_REGISTER_PROBE=true`; writes the API key to `/shared/PROBE_API_KEY` (world-readable, chmod 644)

#### Central probe (co-located)
- `probe/docker-entrypoint.sh` — reads `PROBE_API_KEY` from `/shared/PROBE_API_KEY` if the env var is not set
- `docker-compose.yml` — `shared:` named volume bridges server ↔ probe-local; `probe-local` starts by default (no profile required)
- `docker-compose.central-probe.yml` — production override: adds shared volume and `probe-central` service to the prod stack

#### Geographic map — global probes view
- `ProbesView.vue` — new **Carte** tab with a Leaflet.js map
- Coloured markers: green = online (seen < 2 min ago), red = offline
- Click marker → popup (name, location, last_seen, status)
- Probes without coordinates listed below the map

#### Geographic map — per-monitor probe status
- `GET /api/v1/monitors/{monitor_id}/probes` endpoint (superadmin) — returns the last check result per probe for a specific monitor
- `MonitorDetailView.vue` — new **Carte** tab (alongside Disponibilité)
- Markers coloured by last check status for that monitor: green = `up`, red = `down`/`timeout`/`error`, grey = no check yet
- Click marker → popup (name, status, response_time_ms, last_checked_at)

#### Probe editing (lat/lon/location)
- `ProbeUpdate` schema — PATCH with optional `location_name`, `latitude`, `longitude`
- `PATCH /api/v1/probes/{probe_id}` endpoint (superadmin)
- `EditProbeModal.vue` — form with location name, latitude, longitude fields
- ✏️ Edit button on each probe card in ProbesView (superadmin only)
- Editing coordinates instantly moves the marker on the map

#### Interactive deployment wizard
- `deploy.sh` — interactive Bash script, three deployment modes:
  1. **Server + central probe** — full stack with auto-registered co-located probe
  2. **Server only** — platform without a local probe
  3. **Remote probe** — auto-enrollment via the central API (login → register → write `.env.probe` → start)
- Generates all secrets (`SECRET_KEY`, `FERNET_KEY`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`) via `secrets.token_hex` / `base64.urlsafe_b64encode`
- Optional self-signed certificate generation with `openssl`
- Writes `.env` / `.env.probe` with `chmod 600`
- Verifies superadmin rights before probe enrollment
- Compatible with Docker Compose v2 (plugin) and v1 (standalone binary)

### Changed
- `server/docker-entrypoint.sh` — calls `python -m whatisup.init_data` between migrations and server start
- `server/Dockerfile.dev` — same init call added to inline CMD for development mode
- `probe/Dockerfile` — switched from direct `ENTRYPOINT ["whatisup-probe"]` to `ENTRYPOINT ["/entrypoint.sh"]` + `CMD ["whatisup-probe"]`
- `docker-compose.yml` — `probe-local` no longer requires the `probe` profile; started by default alongside the server
- `docker-compose.prod.yml` — probe service renamed; use `docker-compose.central-probe.yml` override for co-located probe
- `ProbesView.vue` — redesigned with tab navigation (Liste / Carte)
- `MonitorDetailView.vue` — added tab navigation (Disponibilité / Carte)
- `frontend/src/api/probes.js` — added `update(id, data)` method
- `frontend/src/api/monitors.js` — added `probeStatus(id)` method

### New schemas
- `ProbeUpdate` — optional fields for PATCH endpoint
- `ProbeMonitorStatus` — per-probe last-check status for a given monitor

---

## [0.1.0] - 2026-02-28

### Added
- HTTP/HTTPS URL monitoring with redirect following
- SSL certificate monitoring (validity, expiry warning)
- Multi-probe architecture with geographic correlation
  - Probes push results to central API via HTTPS
  - Global vs geographic incident detection
- Multi-user authentication with JWT (access 15 min / refresh 7 d)
- Role-based access via tags (view/edit/admin per tag)
- Monitor groups with optional public status pages
- Alert channels: Email (SMTP), Webhook (HMAC-signed), Telegram Bot API
- Alert rules per monitor or group with configurable conditions
- Real-time WebSocket updates for dashboard and public pages
- REST API for external monitoring tool integration (`/api/v1/status/monitors`)
- Vue.js 3 + Vite frontend with Tailwind CSS
- ApexCharts response time timeline and availability bar chart
- Docker Compose (dev + prod with Nginx + TLS)
- Security: rate limiting, security headers, JWT validation, probe API key bcrypt hashing

[Unreleased]: https://github.com/AurevLan/WhatIsUp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/AurevLan/WhatIsUp/releases/tag/v0.1.0
