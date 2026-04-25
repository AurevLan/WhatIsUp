<h1 align="center">WhatIsUp</h1>

<p align="center">
  <strong>The self-hosted uptime platform that actually tells you <em>where</em> things break — and stops shouting when it shouldn't.</strong>
</p>

<p align="center">
  Multi-probe geographic correlation · real-time dashboard · SLO tracking · intelligent alerting · public status pages · mobile app.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <img alt="Version" src="https://img.shields.io/badge/version-1.5.0-4f9cf9">
  <img alt="Python 3.14" src="https://img.shields.io/badge/Python-3.14-blue">
  <img alt="Vue 3" src="https://img.shields.io/badge/Vue-3.5-42b883">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.125+-009688">
  <img alt="PostgreSQL 16" src="https://img.shields.io/badge/PostgreSQL-16-336791">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#whats-new-in-15">What's new in 1.5</a> ·
  <a href="#why-whatisup">Why WhatIsUp</a> ·
  <a href="#features">Features</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

## Why WhatIsUp

There's no shortage of uptime tools. WhatIsUp focuses on three things most of them don't do well at once:

- 🌍 **Real multi-probe correlation** — deploy lightweight probes in any datacenter, office, or region, and let WhatIsUp tell you if an outage is global, regional, or probe-local. One failed probe no longer means one false page.
- 🔕 **Alerting that shuts up** — flapping suppression, incident groups, dependency-aware cascade suppression, maintenance windows, storm protection, and a brand-new **impact preview** (see v1.1 below) so you calibrate thresholds with data instead of vibes.
- 🎛 **Self-hosted, batteries included** — one `docker compose up`, no SaaS lock-in, no per-monitor pricing. Playwright scenarios, SSO/OIDC, teams & RBAC, IaC import/export, and a mobile app all ship in the box.

It's built for teams who want Datadog-grade monitoring without Datadog-grade bills, and who'd rather own their data than rent it.

---

## What's new in 1.5

**Wave 1 Tier 1 complete** — eight ⭐ items shipped at once to close the SRE adoption + UX backlog. 100% backward-compatible, two additive migrations.

- ⌨️ **Command palette v2 + global shortcuts** (T1-10 / T1-15) — Cmd/Ctrl+K opens fuzzy search across monitors, incidents, recent items and actions. Hover a row to **pause/resume a monitor** or **acknowledge an incident** without leaving the palette. New keyboard shortcuts (`g d/m/i/a/p/s` for navigation, `c` to create, `/` to search, `?` for the cheatsheet) wired everywhere. Recent visits persist in `localStorage` (capped at 12).
- 🔕 **Programmable alert silences** (T1-01) — new `AlertSilence` resource and `Silences` page in the sidebar. Mute alerts for one monitor or all of them during a known-noisy window (cert renewal, deploy storm) without distorting uptime. Built-in 15 m / 1 h / 4 h / 1 d duration presets, status badges (Active / Scheduled / Past). Dispatch is short-circuited *before* any external IO.
- 📱 **Quick-ack & snooze from mobile push** (T1-04) — FCM payload now ships `actions: [ack, snooze_1h, snooze_4h]`. The mobile app calls the matching endpoint on tap, no need to open the UI. New `Incident.snooze_until` field with auto-clear on resolve. Bounded duration (5 min – 24 h).
- ✅ **Multi-select bulk actions enriched** (T1-12) — `MonitorsView` gets two new dropdowns: **Move to group** and **Add tag**. `IncidentsView` gains a per-row checkbox plus an **Acknowledge all** button — one round-trip via the new `POST /incidents/bulk-ack` endpoint.
- 🪄 **CreateMonitor wizard** (T1-14) — new 3-step flow (type → target → review + notifications) replaces the legacy modal for the four most common types (HTTP, TCP, DNS, heartbeat). Mobile-scrollable body. Falls back to the advanced form for scenario / composite / keyword / json_path.
- ✨ **Polish: skeletons, empty states, replayable tour** (T1-16 / T1-18) — generic `SkeletonBox` / `Row` / `Text` components replace `animate-pulse` placeholders on Dashboard, Monitors and MonitorDetail. Six empty states standardised with contextual CTAs and doc links. The onboarding wizard is now replayable from any empty state via `?tour=1`.

See the full [CHANGELOG](CHANGELOG.md#150---2026-04-25) for the per-item breakdown, including 14 new pytest cases and 50 new vitest cases (suite at 161 green).

---

## What's new in 1.4

- 🔗 **Shareable filter URLs** (T1-11) — MonitorsView and IncidentsView now persist their filters (search, status, type, group, days) via both the querystring *and* localStorage. Refresh keeps your view; copying the URL reproduces the exact same filtering for a teammate. A new generic `useFilterPreset` composable drives both views with 8 tests.
- 🌍 **User timezone preference** (T1-13) — New `User.timezone` field (IANA, nullable). Default `null` means the browser's resolved zone is used. Settings page gets a "Preferences" card with a 45-zone picker + auto option. Dates across IncidentsView and MonitorDetailView now format in your selected zone; hover a date to see the absolute ISO + zone tooltip. Backend validates against `zoneinfo.available_timezones()` — invalid zones are rejected with 422.
- 🆕 **`PATCH /auth/me`** — self-update endpoint limited to non-privileged fields (`full_name`, `timezone`). Escalation attempts are silently ignored.

See the full [CHANGELOG](CHANGELOG.md#140---2026-04-24) for details.

---

## What's new in 1.3

- 📖 **Per-monitor runbooks** — attach an incident response procedure (markdown) to any monitor. A dedicated `Runbook` tab appears on the detail page *only* when enabled, and the rendered content is shown inline on open incidents in the incidents list — so the on-caller sees the steps-to-take without leaving the page. Unchecking the toggle wipes the content server-side (no orphan data). Built-in safe markdown renderer (headings, task checkboxes, code blocks, http/https links only) — no extra dependency.
- ⚡ **Dashboard load-time — 8 s → < 200 ms** — the monitors list aggregated queries were scanning 1.6 M `check_results` rows on every request. Sparkline switched from a `row_number() OVER (PARTITION BY)` window function (7 s) to a `JOIN LATERAL ... LIMIT 20` (3 ms, index-only per monitor), plus a new BRIN index on `check_results.checked_at` for time-window aggregates (P95 288 ms → 75 ms, uptime bulk 147 ms → 30 ms).
- 🩹 **Stability fixes** — FastAPI `X-Forwarded-Proto` handling (no more HTTPS → HTTP redirect breakage behind nginx), `/monitors/graph` route order (was 422), sidebar menu click (vue-router 5 slot navigate rewrite), charts rendering (`apexchart` global registration), stricter CSP with external theme init, Cache-Control hardening on `/index.html`.

See the full [CHANGELOG](CHANGELOG.md#130---2026-04-23) for details.

---

## What's new in 1.1

<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/alert-matrix-cards.svg" alt="Alert matrix with cards and impact preview"></td>
    <td width="50%"><img src="docs/screenshots/alert-templates.svg" alt="One-click alerting templates"></td>
  </tr>
  <tr>
    <td>
      <strong>Alert matrix v2 — cards + impact preview</strong><br>
      The per-monitor alerting panel is now a stack of collapsible cards: one card per condition, coloured channel chips, an "Advanced" section that hides noise, and a live <code>≈ N / 30j</code> badge that replays the last 30 days of data through your rules so you can calibrate thresholds <em>before</em> they page you.
    </td>
    <td>
      <strong>One-click alerting templates</strong><br>
      Apply a preset (Standard, Strict/Paging, Low noise) in a single click. Built-in templates ship seeded in the database and admins can create, edit and delete their own from a dedicated section in the Alerts page. Channels stay empty — you still decide where alerts fire.
    </td>
  </tr>
  <tr>
    <td colspan="2"><img src="docs/screenshots/tags-rbac.svg" alt="Monitor tags and tag-scoped RBAC"></td>
  </tr>
  <tr>
    <td colspan="2">
      <strong>Monitor tags & tag-scoped RBAC</strong><br>
      Label monitors with <code>env:prod</code>, <code>team:backend</code>, <code>tier:critical</code>, whatever makes sense. Filter dashboards and lists by tag. Target alert rules at a tag (<code>AlertRule.tag_selector</code>) so one rule covers every monitor that carries it. Grant users <code>view</code>/<code>edit</code>/<code>admin</code> access scoped to a tag via <code>UserTagPermission</code>.
    </td>
  </tr>
</table>

See the full [CHANGELOG](CHANGELOG.md#110---2026-04-14) for the complete list, including the removal of the never-implemented `uptime_below` condition.

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

| Alert matrix v2 | Alerting templates |
|-----------------|-------------------|
| ![Alert matrix](docs/screenshots/alert-matrix-cards.svg) | ![Templates](docs/screenshots/alert-templates.svg) |

| Tags & RBAC | Browser extension recorder |
|-------------|----------------------------|
| ![Tags](docs/screenshots/tags-rbac.svg) | ![Extension](docs/screenshots/extension-recorder.svg) |

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
- **Network scope per monitor** — restrict each monitor to `all`, `internal`, or `external` probes; useful for LAN-only services
- **Probe groups** — admin-defined groups; assign probes and grant visibility to specific users
- **City / address geocoding** — type any address or city to auto-resolve GPS coordinates (Nominatim, no API key)

### Observability
- **Real-time dashboard** — WebSocket push, no polling
- **SLO / Error budget** — configurable target (%) and window (days); burn rate and budget-remaining tracking
- **SLA reports** — custom date range, uptime %, incident list, P95 response time; JSON download
- **Custom push metrics** — `POST /api/v1/metrics/{monitor_id}` for business KPIs (orders, latency…)
- **Annotations** — timestamped notes on the monitor timeline (deployments, changes)
- **Response time trend** — 6-hour rolling comparison with colour-coded indicator

### Incidents & alerting
- **Alert matrix v2 (1.1)** — card-based editor: one card per condition, coloured channel chips, repliable "Advanced" params (threshold, min-duration, re-notify, business-hours schedule), multi-select condition picker, and per-condition "How it works" help in plain language
- **Impact preview (1.1)** — live `≈ N / 30j` badge on each rule, computed server-side by replaying the proposed configuration against the last 30 days of check results and incidents (statistical tail estimate for anomaly detection)
- **Alerting templates (1.1)** — apply a preset (Standard, Strict/Paging, Low noise) in one click; templates are stored in DB and managed from a dedicated section in the Alerts page; superadmins create/edit their own, built-in templates are read-only
- **Automatic incident lifecycle** — open on failure, resolve on recovery, flapping detection with per-monitor thresholds
- **Incident groups** — monitors sharing the same failing probes within a 90 s window are grouped into one persistent incident group; one notification instead of N
- **Monitor dependencies** — when a parent monitor is down, child incidents are automatically suppressed; eliminates cascade alert storms
- **Alert storm protection** — per-rule rate cap (`storm_max_alerts` within `storm_window_seconds`); forced digest when threshold is exceeded
- **Performance baseline alerting** — alert when response time exceeds a configurable multiple of the 7-day rolling hourly baseline
- **Anomaly detection** — z-score against a 7-day rolling mean ± stddev, filtered to the same ±3 h window of the day so day/night traffic patterns are respected
- **Tag-scoped alert rules (1.1)** — target a single rule at every monitor carrying a given tag via `AlertRule.tag_selector`
- **Auto post-mortem** — Markdown report generated on incident resolution (timeline, alerts, metrics)
- **Alert channels** — Email (SMTP), Webhook (HMAC-SHA256), Telegram Bot, Slack, PagerDuty, Opsgenie, [Signal](#signal-alerts), FCM (native mobile push)
- **Persistent digest** — digest scheduling stored in Redis; survives server restarts
- **Maintenance windows** — suppress alerts during planned downtime; group-level suppression support

### Public status pages
- **Shareable URL** — `/status/{slug}`, no login required
- **90-day history bars** — daily uptime visualisation per component
- **Incident timeline** — 30-day incident log with duration
- **Email subscriptions** — visitors subscribe to outage updates; secure unsubscribe token

### Platform
- **Monitor tags & tag-scoped RBAC (1.1)** — label monitors with free-form `key:value` tags (`env:prod`, `team:backend`, `tier:critical`); filter lists and dashboards by tag; grant users `view`/`edit`/`admin` access scoped to a tag via `UserTagPermission`; one alert rule can target every monitor carrying a given tag
- **Teams & RBAC** — create teams, invite members with 4 roles (`owner` > `admin` > `editor` > `viewer`); monitors, groups, channels, and maintenance windows can be team-scoped; backward-compatible — single-user mode preserved when no teams are created
- **SSO / OIDC** — OpenID Connect PKCE flow; link user accounts to any OIDC provider (Keycloak, Authentik, Auth0, Google…); optional auto-provisioning of new accounts on first login; configured entirely from the admin GUI (no restart required)
- **Admin panel** — dedicated UI for user management (`is_active`, `can_create_monitors`), probe group access control, all-monitors view, and live OIDC settings
- **Probe groups** — admin-defined groups linking probes to users; regular users see only the probes assigned to their groups
- **Network scope** — per-monitor `network_scope` field (`all` / `internal` / `external`); restricts which probe types run each check (e.g. internal-only services stay on LAN probes)
- **Multi-language** — English (default) and French; toggle in the top bar; persisted to `localStorage`
- **Light / dark theme** — toggle in top bar; auto-detected from `prefers-color-scheme`; persisted to `localStorage`
- **Onboarding wizard** — guided 4-step setup for new users (first monitor, first alert); auto-dismissed after completion
- **Infrastructure-as-Code** — `GET /api/v1/config` exports full config as JSON; `PUT /api/v1/config` imports declaratively with diff, dry-run, and prune support; resources matched by name for idempotence
- **Plugin architecture** — check types and alert channels use a registry-based plugin system; extend without modifying core code
- **Bulk actions** — multi-select monitors; bulk enable / pause / delete / export CSV
- **Audit trail** — every admin action logged with before/after diff
- **Data retention** — configurable auto-purge of old check results (default: 90 days)
- **One-command deploy** — interactive wizard generates secrets, `.env`, and starts the stack
- **Accessibility** — `prefers-reduced-motion` support, skip-to-content link, ARIA labels on interactive elements

### Browser extension — scenario recorder

The WhatIsUp Chrome extension records browser actions and sends them directly to a monitor:

1. Click **Start recording** in the extension popup
2. Navigate and interact with any website — clicks, form fills (including passwords), and navigations are captured automatically
3. Click **Stop** then **Send to WhatIsUp** — the scenario is created as a monitor in one click

**Security**: password values are stored as `{{password_N}}` placeholders in the step list; the real values are kept in a separate encrypted store, encrypted at rest with Fernet, and masked in all API responses. They are decrypted only when delivered to the probe at check time.

Install the extension from `extension/` by loading it as an unpacked extension in Chrome (`chrome://extensions → Load unpacked`).

---

## Minimum requirements

### Central server (API + frontend + PostgreSQL + Redis)

| Probes | Monitors | CPU | RAM | Disk | PostgreSQL | Redis |
|--------|----------|-----|-----|------|------------|-------|
| 1–3 | ≤ 50 | 2 vCPU | 2 GB | 20 GB SSD | shared (in-stack) | shared (in-stack) |
| 3–10 | 50–200 | 4 vCPU | 4 GB | 40 GB SSD | shared or dedicated | shared |
| 10–30 | 200–1 000 | 4–8 vCPU | 8 GB | 80 GB SSD | dedicated (4 GB RAM) | dedicated (1 GB) |
| 30+ | 1 000+ | 8+ vCPU | 16 GB | 160 GB+ SSD | dedicated (8 GB+ RAM) | dedicated (2 GB+) |

**Disk growth** — each check result row is ~300 bytes. With 200 monitors × 60 s interval × 5 probes, expect ~2.5 GB/month in PostgreSQL before retention purge (default: 90 days).

### Probe agent

| Mode | CPU | RAM | Notes |
|------|-----|-----|-------|
| HTTP / TCP / DNS / Ping only | 1 vCPU | 256 MB | Lightweight; runs on any VPS or Raspberry Pi |
| With Playwright scenarios | 2 vCPU | 1 GB | Chromium loaded on demand; set `MAX_CONCURRENT_SCENARIOS=2` |
| High-volume (100+ monitors) | 2 vCPU | 1–2 GB | Increase `MAX_CONCURRENT_CHECKS` (default: 10) |

### Network

| Component | Ports | Protocol |
|-----------|-------|----------|
| Central server (prod) | 80, 443 | HTTP/S (Nginx reverse proxy) |
| Central server (dev) | 5173 (frontend), 8000 (API) | HTTP |
| PostgreSQL | 5432 | TCP (internal only) |
| Redis | 6379 | TCP (internal only) |
| Probe → Server | 443 (or 8000 dev) | HTTPS outbound only |

### Software

- Docker ≥ 24 and Docker Compose v2
- Linux amd64 or arm64 (all images are multi-arch)

---

## Quick start

### Requirements

- Docker ≥ 24 and Docker Compose v2
- 2 GB RAM minimum (see [Minimum requirements](#minimum-requirements) for sizing)
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

On first start an **admin account** and a **local probe** are created automatically. The admin password is written to `/shared/ADMIN_PASSWORD` inside the server container:

```bash
docker compose exec server cat /shared/ADMIN_PASSWORD
# Delete the file after reading
docker compose exec server rm /shared/ADMIN_PASSWORD
```

### Production deploy

> **Recommended** — use the interactive wizard for all deployments:

```bash
bash deploy.sh
```

The wizard generates secrets, writes `.env`, starts the stack, and **displays the admin password on screen** before securely deleting the temp file. See [`deploy.sh`](#deploying-with-deploysh) below for details.

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
| `OIDC_ENABLED` | — | `false` | Enable OIDC login (can also be set from admin GUI) |
| `OIDC_ISSUER_URL` | — | — | OIDC provider discovery URL (e.g. `https://accounts.google.com`) |
| `OIDC_CLIENT_ID` | — | — | Client ID registered with the OIDC provider |
| `OIDC_CLIENT_SECRET` | — | — | Client secret (stored encrypted in DB when set from admin GUI) |
| `OIDC_REDIRECT_URI` | — | — | Callback URL (leave empty to auto-detect from request base URL) |
| `OIDC_SCOPES` | — | `openid email profile` | Space-separated OIDC scopes |
| `OIDC_AUTO_PROVISION` | — | `true` | Create user accounts on first OIDC login |

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
| `MAX_CONCURRENT_SCENARIOS` | — | `2` | Max concurrent Playwright/Chromium instances (subset of `MAX_CONCURRENT_CHECKS`; reduce on low-memory machines) |
| `HEARTBEAT_INTERVAL` | — | `15` | Seconds between server heartbeats |

---

## Signal alerts

WhatIsUp sends Signal messages through a small REST gateway that runs alongside the server — it does not talk to Signal directly. The gateway project is [**bbernhard/signal-cli-rest-api**](https://github.com/bbernhard/signal-cli-rest-api), a maintained wrapper around the official `signal-cli`.

### 1. Run the gateway

Add a service to your `docker-compose.yml`:

```yaml
signal-api:
  image: bbernhard/signal-cli-rest-api:latest
  restart: unless-stopped
  environment:
    - MODE=normal
  volumes:
    - ./signal-data:/home/.local/share/signal-cli
  ports:
    - "8080:8080"
```

### 2. Register a phone number

Follow the [gateway's README](https://github.com/bbernhard/signal-cli-rest-api#register-a-number). Typical flow:

```bash
# Request the SMS code
curl -X POST "http://localhost:8080/v1/register/+33612345678"

# Enter the code you received
curl -X POST "http://localhost:8080/v1/register/+33612345678/verify/123456"
```

### 3. Add a Signal channel in WhatIsUp

In the UI: **Alerts → Add channel → Signal**, then fill:

| Field | Example |
|---|---|
| **API URL** | `http://signal-api:8080` (internal hostname if the gateway is in the same Compose network) |
| **Sender number** | `+33612345678` (E.164 format, the number you registered above) |
| **Recipients** | `+33612345678, +33698765432` (comma-separated; Signal group IDs are also accepted as recipients) |

Click **Test** to send a confirmation message. The channel configuration (`api_url`, `sender_number`, `recipients`) is encrypted at rest with Fernet like every other alert channel.

Implementation: [`server/whatisup/services/channels/signal.py`](server/whatisup/services/channels/signal.py).

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
| `GET` | `/api/v1/config/` | Export full config (IaC) |
| `PUT` | `/api/v1/config/` | Import declarative config (IaC) |
| `POST` | `/api/v1/teams/` | Create team |
| `GET` | `/api/v1/teams/` | List user's teams |
| `POST` | `/api/v1/teams/{id}/members` | Add team member |
| `GET` | `/api/v1/onboarding/status` | Onboarding progress |
| `POST` | `/api/v1/onboarding/complete` | Mark onboarding done |
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
# Backend (server + probe)
cd server && pip install -e ".[dev]" && pytest
cd probe && pip install -e ".[dev]" && pytest
ruff check . && ruff format .
pip-audit

# Frontend (Vitest + jsdom)
cd frontend
npm install
npm test
npm run lint
npm audit
```

Tests also run inside Docker:

```bash
docker compose run --rm --no-deps server pytest tests/
docker compose run --rm --no-deps probe pytest tests/
docker run --rm -v ./frontend:/app -w /app node:25-alpine npx vitest run
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

## Deploying with `deploy.sh`

The root `deploy.sh` script is an interactive wizard (in French) that handles the entire production setup. Run it with:

```bash
bash deploy.sh
```

### Deployment modes

| Mode | Description |
|------|-------------|
| **1 — Serveur + sonde centrale** | Full platform with a local probe (recommended for single-server setups) |
| **2 — Serveur seul** | Server only; add remote probes later |
| **3 — Sonde distante** | Standalone probe agent that auto-enrolls to an existing server via API |

### What the wizard does

1. **Checks dependencies** — Docker, Docker Compose, `curl`, `openssl`
2. **Generates secrets** — `SECRET_KEY` (hex), `FERNET_KEY` (Fernet), PostgreSQL and Redis passwords
3. **Prompts for configuration** — domain name, SMTP settings, DNS servers (for probe modes), Let's Encrypt email
4. **Generates `.env` files** — `.env` for the server stack, `.env.probe` for remote probe mode; file permissions set to `600`
5. **Self-signed certificate** — generates a temporary TLS cert if Let's Encrypt is not configured
6. **Probe auto-enrollment** (mode 3) — registers the probe via `POST /api/v1/probes/register` and writes the API key to `.env.probe`
7. **Starts the stack** — builds and launches Docker Compose services
8. **Displays credentials** — reads the admin password from a temp file, displays it in a framed box, then deletes the file from the container (first boot only)

> **Tip**: for Let's Encrypt, ensure port 80 is reachable from the internet and set your DNS A record before running the wizard.

---

## Security

- **JWT** — HS256, access 15 min + refresh 7 days, Redis-revocable
- **OIDC / SSO** — PKCE authorization-code flow; `oidc_client_secret` encrypted at rest with Fernet; secret never returned by the API
- **Probe auth** — `X-Probe-Api-Key` bcrypt 12 rounds + Redis cache 300 s
- **WebSocket auth** — JSON message frame (`{"type":"auth","token":"…"}`), never URL parameter
- **Secrets at rest** — Fernet encryption for alert channel secrets (SMTP passwords, Telegram tokens, webhook secrets, PagerDuty / Opsgenie keys), OIDC client secret, **and** scenario variables (`secret: true`); `FERNET_KEY` is required in production (server refuses to start without it)
- **SSRF protection** — all outbound HTTP requests (webhooks, OIDC discovery, probe checks, scenario navigation) validated against private/loopback/link-local IP ranges; redirect targets re-validated after following
- **CORS** — explicit origins only; HTTP origins rejected in production
- **CSP** — `default-src 'self'; script-src 'self'`
- **Rate limiting** — all mutating endpoints rate-limited (30/min PATCH/DELETE, 60/min public pages); login 10/min, register 5/min, heartbeat 30/min, results 60/min, monitor creation 10/min
- **Input validation** — Pydantic schemas use `extra="forbid"` to reject unexpected fields on all create/update endpoints
- **WebSocket** — per-IP connection limit enforced before the auth handshake; public slug validated against DB before accepting
- **Ownership enforcement** — all mutating endpoints (including alert rule delete) verify resource ownership via JOIN; superadmin bypass is explicit
- **Docker** — non-root user in all images; CPU/memory resource limits in production

See [SECURITY.md](SECURITY.md) for the responsible disclosure policy.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

## License

MIT — see [LICENSE](LICENSE).
