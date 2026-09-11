<h1 align="center">WhatIsUp</h1>

<p align="center">
  <strong>The only self-hostable uptime platform that watches a service from more than one network at once — and tells you whether it's the service or the network path that broke.</strong>
</p>

<p align="center">
  Multi-probe network correlation (ASN & network position) · real-time dashboard · SLO tracking · intelligent alerting · public status pages · mobile app.
</p>

<p align="center">
  <a href="https://github.com/AurevLan/WhatIsUp/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/AurevLan/WhatIsUp/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://github.com/AurevLan/WhatIsUp/actions/workflows/codeql.yml"><img alt="CodeQL" src="https://github.com/AurevLan/WhatIsUp/actions/workflows/codeql.yml/badge.svg?branch=main"></a>
  <a href="https://score.getplumber.io/github.com/AurevLan/WhatIsUp"><img alt="Plumber Score" src="https://score.getplumber.io/github.com/AurevLan/WhatIsUp.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"></a>
  <img alt="Version" src="https://img.shields.io/badge/version-1.28.0"> <!-- x-release-please-version -->
</p>

<p align="center">
  <img alt="Python 3.12–3.14" src="https://img.shields.io/badge/Python-3.12%E2%80%933.14-blue">
  <img alt="Vue 3.5" src="https://img.shields.io/badge/Vue-3.5-42b883">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.139-009688">
  <img alt="PostgreSQL 16" src="https://img.shields.io/badge/PostgreSQL-16-336791">
  <img alt="Redis 7" src="https://img.shields.io/badge/Redis-7-DC382D">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#why-whatisup">Why</a> ·
  <a href="#recent-highlights">Recent highlights</a> ·
  <a href="#features">Features</a> ·
  <a href="#operating-whatisup">Operating</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#development">Development</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

## Why WhatIsUp

Most uptime tools answer one question: *is it up?* When a check fails, the harder question is
*why* — is the service actually down, or did the path between it and this one vantage point break?
A single probe can't tell the difference: a probe-local blip and a real outage look identical from
one point of observation.

WhatIsUp is built around answering that second question, self-hosted, with three things most tools
don't do well at once:

- 🔀 **Network-aware correlation** — deploy lightweight probes across networks you control, and each one
  is enriched with its ASN and network position (Team Cymru DNS lookups, no API key). When several probes
  disagree, WhatIsUp classifies the incident as a real service outage, an ASN-level partition (one
  operator's transit breaks), or inconclusive — instead of paging on every probe-local blip. The
  classification runs on the same path as incident detection, not as a side report, and every alert
  channel, the incident view, and the public status page show the verdict. The probe map and incident
  playback illustrate this on a map; geography is not the axis the verdict is built on, network
  topology is.
- 🔕 **Alerting that shuts up** — quorum-based incident detection with a per-rule cooldown against flapping, incident groups, dependency-aware cascade suppression, maintenance windows, storm protection, business-hours schedules, and an impact preview that replays your rules against the last 30 days so you calibrate thresholds with data instead of vibes.
- 🎛 **Self-hosted, batteries included, nothing phones home** — one `docker compose up`, no SaaS tier, no per-monitor pricing, no telemetry leaving your infrastructure. Playwright scenarios, SSO/OIDC, teams & RBAC, IaC import/export, and an Android app all ship in the box, and every extension point (check types, alert channels, alert conditions) is a plugin registry you can add to without forking core code.

Built for teams who want Datadog-grade monitoring without Datadog-grade bills or a Datadog-shaped data
pipeline — and who'd rather own their infrastructure's telemetry than rent it out.

---

## Recent highlights

Full per-version detail lives in [CHANGELOG.md](CHANGELOG.md). This section covers what changed in the current line and why it matters operationally.

### Time-series foundation — the storage layer got serious

The check-result table used to be one flat, ever-growing heap. It now has a shape:

- **Monthly partitioning** of `check_results` (`PARTITION BY RANGE (checked_at)`) — retention becomes `DROP TABLE` instead of a nightly `DELETE` that leaves bloat and autovacuum debt behind. Migrated in place: the old table is attached as the first partition, so no row is ever copied.
- **Hourly rollups** (`check_rollups_1h`) — uptime, status counters and p50/p95/p99 pre-aggregated per monitor-hour. The public status page used to pay a 9.5 s scan to draw 90 days of history; it now reads the rollups for the covered hours and the raw table only for the tail. Exact at every width for uptime and counters; the p95 beyond one hour is an estimate and the API says so (`p95_is_estimate`, rendered as `≈`).
- **Differentiated retention** — `DATA_RETENTION_DAYS` (90) now governs only the per-result detail (scenario traces, TLS audits, DNS answers). `ROLLUP_RETENTION_MONTHS` (13) governs the shape of history, two orders of magnitude cheaper. Dropping the raw window no longer costs you your uptime history — and an interlock stops the purge from ever overtaking the rollup builder, so shortening it mid-backfill can't lose data twice.
- **`custom_metrics` partitioned too**, with `METRICS_RETENTION_DAYS`. Before this it was the one time-series table nothing ever purged.

### The network verdict is real now

Classifying an outage as a real service failure vs. an ASN-level partition existed for a while, but it
sat on a code path that incident opening never actually walked — so the large majority of incidents
carried no verdict at all. It's now computed on the same path the Health Engine uses to open every
availability incident, and shown everywhere an operator looks: all 11 alert channels, the incident list,
the monitor detail view, and the public status page. `AlertRule.suppress_on_network_partition` (opt-in)
uses it to stop paging on-call for an upstream operator's outage instead of your service's.

### A pass of deliberate removal

Seven lots removed what had accumulated but wasn't earning its keep, ahead of a 2.0 release: monitor
templates (replaced by a **Duplicate** button that works for every check type), the `udp` and
`composite` check types, `keyword`/`json_path` as separate check types (they're now an optional
"Assertions" section of an `http` monitor — same functionality, one fewer thing to pick from a list of
10), the browser-extension scenario recorder (replaced by importing a `playwright codegen` script),
separate maintenance/silence objects (merged into one "suppression window" with a checkbox), and
`renotify_after_minutes` (subsumed by a one-rung, repeating escalation ladder). Alert conditions went
from 10 to 4 (`availability`, `ssl_expiry`, `latency_anomaly`, `schema_drift`) — pushed-metric alerting
(`metric_above`/`metric_below`/`metric_absent`) is cut entirely (0 rules, 0 points, 0 series were using
it), replaced by an application endpoint that returns 500 past its own threshold. **Ingestion of pushed
metrics and metric↔incident correlation are untouched** — only alerting *on* a metric is gone. Main
navigation went from 17 entries to 11 (dependency graph and the TLS fleet view folded into the monitor
detail view and the monitors list; audit moved under Settings; on-call became a tab of Alerts). Removing
the browser stack from the default probe image cut it from 1.97 GB to ~480 MB; a `-browser` variant is
published separately for `scenario` monitors.

### Alert conditions are a plugin registry

Conditions used to be dispatched by three parallel `if/elif` chains — what pages, the UI preview, and the impact badge. Every divergence between them was silent, and one had already shipped. Each condition is now a single class holding its dispatch decision and its preview side by side, registered like alert channels and check types already were, and reduced from 10 members to 4 in the same pass. A CI gate fails the build if an `AlertCondition` has no handler.

### The status page tells the truth

A status page used to show a hard-red "major outage" for planned maintenance, never let an operator
narrate an incident without a probe flipping first, exposed a monitor's internal URL/ports/DNS record
types to any visitor, and had no feed to subscribe to. All four are fixed: planned-maintenance windows
render as maintenance, not an outage; manual status announcements can be posted independently of any
probe-detected incident; a monitor gets an optional public-facing name and the public API no longer
leaks its internal configuration; and there's a standard Atom feed per status page.

### Security & supply chain

- Every release image and the Android APK are **signed keylessly with Cosign** (Fulcio/Rekor, GitHub OIDC — no private key to manage), with SBOMs (SPDX) published alongside. `scripts/verify-release.sh <version>` checks all of it in one command — see [SECURITY.md § Vérifier une release](SECURITY.md#10-supply-chain).
- Post-audit structural hardening: SSRF guards **pin the resolved IP** (defeating DNS rebinding, with per-hop redirect re-validation), per-account login lockout with anti-enumeration, zero-downtime `FERNET_KEY` rotation, tenant-scoped WebSocket broadcasts, hardened auth caches with immediate key revocation, and rate limits closed on every mutating endpoint with a CI coverage gate.
- Every GitHub Actions workflow is SHA-pinned with least-privilege `permissions`; a [Plumber](https://getplumber.io) compliance gate (100% / A) runs on every PR and uploads findings to Code Scanning. `main` is ruleset-protected.
- Model↔schema drift is a build failure: `compare_metadata` must return zero diff against a migrated database on every PR.

### Ops & platform

- **Leader election** — singleton background loops (heartbeat, retention, rollups, escalation, digest flush, network verdict…) elect a leader via Redis `SET NX` with fencing tokens, so running several API replicas is safe.
- **Structured JSON logs** with `X-Request-ID` correlation end-to-end, plus Prometheus metrics.
- **Global Health Engine V2** — probes are sensors, the server is the sole judge, and it's the only detection engine (the legacy per-probe decider was retired): a 5-minute rolling p50/p95/p99 aggregator with `quorum_down` / `quorum_slow` SLO rules and per-probe divergence scoring, enabled by default on every new monitor.
- **Network intelligence** — probes are auto-enriched with ASN via Team Cymru; every incident gets a verdict (`service_down` / `network_partition_asn` / `network_partition_geo` / `inconclusive`), computed on the same path that opens the incident (see above), and rules can opt out of paging on upstream operator failures.
- **2FA (TOTP), active session management, teams & RBAC, tag-scoped permissions, OIDC/SSO** configured entirely from the admin GUI.
- **VELOURS design system** on two tokenised themes, with permanent CI accessibility gates (axe audit + anti-artisanal-overlay), a mobile-first responsive pass, and an Android build via Capacitor 8.

---

## Screenshots

> The first three pairs are **real captures** of the VELOURS design system (dark *encre* and light *ivoire* themes); minor details may differ from the current release. The feature tiles below them are **schematic mockups**.

| Dashboard (dark) | Dashboard (light) |
|------------------|-------------------|
| ![Dashboard, dark theme](docs/screenshots/dashboard.png) | ![Dashboard, light theme](docs/screenshots/dashboard-light.png) |

| Monitor detail | Monitors list |
|----------------|---------------|
| ![Monitor detail](docs/screenshots/monitor-detail.png) | ![Monitors](docs/screenshots/monitors-view.png) |

| Probes | Public status page |
|--------|--------------------|
| ![Probes](docs/screenshots/probes-view.png) | ![Status page](docs/screenshots/public-status.png) |

| Alert matrix v2 | Alerting templates |
|-----------------|-------------------|
| ![Alert matrix](docs/screenshots/alert-matrix-cards.svg) | ![Templates](docs/screenshots/alert-templates.svg) |

| Scenario builder |
|------------------|
| ![Scenario](docs/screenshots/scenario-builder.svg) |

---

## Quick start

### Requirements

- Docker ≥ 24 and Docker Compose v2
- Linux amd64 or arm64 (all images are multi-arch)
- 2 GB RAM minimum — see [sizing](#sizing) for anything past a handful of monitors

### Development (local)

```bash
git clone https://github.com/AurevLan/WhatIsUp.git
cd WhatIsUp

docker compose up -d      # PostgreSQL, Redis, API, frontend, local probe
docker compose ps         # wait for services to become healthy
```

| Service | URL |
|---------|-----|
| Frontend (Vite dev server) | http://localhost:5173 |
| API (FastAPI) | http://localhost:8000 |
| API docs (Swagger UI) | http://localhost:8000/docs |

On first start an **admin account** and a **local probe** are created. The admin password is written to `/shared/ADMIN_PASSWORD` inside the server container — a volume the probe cannot read — and the file is **deleted automatically on the first successful admin login**:

```bash
docker compose exec server cat /shared/ADMIN_PASSWORD
```

### Production

> **Recommended** — the interactive wizard handles secrets, `.env`, TLS and first boot:

```bash
bash deploy.sh
```

<details>
<summary>What the wizard does, and its three modes</summary>

| Mode | Description |
|------|-------------|
| **1 — Serveur + sonde centrale** | Full platform with a local probe (recommended for single-server setups) |
| **2 — Serveur seul** | Server only; add remote probes later |
| **3 — Sonde distante** | Standalone probe that auto-enrolls to an existing server via API |

1. **Checks dependencies** — Docker, Docker Compose, `curl`, `openssl`
2. **Generates secrets** — `SECRET_KEY`, `FERNET_KEY`, PostgreSQL and Redis passwords
3. **Prompts for configuration** — domain, SMTP, DNS servers (probe modes), Let's Encrypt email
4. **Writes `.env` / `.env.probe`** with mode `600`
5. **Self-signed certificate** if Let's Encrypt is not configured
6. **Probe auto-enrollment** (mode 3) via `POST /api/v1/probes/register`
7. **Starts the stack**, then **displays the admin credentials once** and deletes the temp file

For Let's Encrypt, make sure port 80 is reachable and your DNS A record is set *before* running the wizard.

</details>

<details>
<summary>Manual production setup</summary>

```bash
cp .env.example .env

SECRET_KEY=$(openssl rand -hex 32)
FERNET_KEY=$(python3 -c \
  "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
echo "SECRET_KEY=$SECRET_KEY" >> .env
echo "FERNET_KEY=$FERNET_KEY" >> .env

docker compose --env-file .env up -d
docker compose --env-file .env exec server alembic upgrade head
```

</details>

---

## Configuration

### Server

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | ✅ prod | — | JWT signing key (`openssl rand -hex 32`). The server refuses to start in production with the default value |
| `FERNET_KEY` | ✅ prod | — | Encrypts alert-channel secrets, scenario variables and custom headers at rest |
| `FERNET_KEY_PREVIOUS` | — | — | Comma-separated old keys, accepted for decryption during a zero-downtime rotation (see `whatisup.tools.rotate_fernet`) |
| `DATABASE_URL` | ✅ | `postgresql+asyncpg://whatisup:whatisup@localhost/whatisup` | PostgreSQL connection string |
| `REDIS_URL` | — | `redis://localhost:6379/0` | Redis connection string |
| `CORS_ALLOWED_ORIGINS` | ✅ prod | `http://localhost:5173` | Comma-separated origins. HTTP origins are rejected in production |
| `ENVIRONMENT` | — | `production` | `development` relaxes the production start-up checks |
| `REGISTRATION_OPEN` | — | `true` | `false` = invite-only after the first user |
| `PUBLIC_BASE_URL` | — | `http://localhost:5173` | Public root used to build status-page email links. Behind a reverse proxy the server cannot infer it — set it, or those links point at localhost |
| `TRUSTED_PROXY_IPS` | — | — | Proxies whose `X-Forwarded-For` is trusted for rate limiting and audit. Unset means the socket peer is used |

#### Retention & storage

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_RETENTION_DAYS` | `90` | Days of **raw** check results (0 = forever). Shortening this drops the per-result detail — scenario traces, TLS audits, DNS answers — while uptime history survives in the rollups. Purged by dropping whole partitions |
| `ROLLUP_RETENTION_MONTHS` | `13` | Months of hourly rollups — the long-term uptime/latency history (0 = forever). 13 covers a rolling year plus the month in progress, so a year-on-year comparison never falls off mid-month |
| `METRICS_RETENTION_DAYS` | `90` | Days of pushed custom metrics (0 = forever). These were never purged before the setting existed, so the first nightly run after upgrading removes what predates the window |
| `ROLLUP_ENABLED` | `true` | Disabling stops the rollup builder; stats fall back to scanning the raw table and retention loses its safety interlock |
| `ROLLUP_INTERVAL_SECONDS` | `300` | How often closed hours are folded |
| `ROLLUP_MAX_BUCKETS_PER_RUN` | `168` | Hours folded per run — this is what paces the initial backfill (a week per run) |
| `ROLLUP_RECOMPUTE_HOURS` | `3` | Hours rebuilt behind the watermark, to catch results that arrived after their hour closed |

#### Alerting

| Variable | Default | Description |
|----------|---------|-------------|
| `METRICS_MAX_POINTS_PER_MINUTE` | `6000` | Ingestion rate ceiling per monitor (0 = unlimited). Refused with 429, never dropped silently |
| `METRICS_MAX_SERIES_PER_MONITOR` | `1000` | Distinct label combinations per monitor (0 = unlimited). This is the ceiling that actually protects the database — one unbounded label and the row count stops being a function of how often you push |
| `METRICS_MAX_BATCH_SIZE` | `1000` | Largest accepted batch |
| `METRICS_MAX_LABELS_PER_POINT` | `10` | Labels are a dimension, not a payload |
| `METRIC_ALERTS_ENABLED` | `true` | Pushed-metric conditions. This loop is the **only** thing that fires them |
| `METRIC_ALERTS_INTERVAL_SECONDS` | `60` | Worst-case alerting delay for pushed metrics. Evaluation is deliberately off the ingestion path so a slow webhook cannot throttle the agent that pushes |
| `SMTP_HOST` / `SMTP_PORT` | `localhost` / `587` | SMTP server for email alerts |
| `SMTP_USER` / `SMTP_PASSWORD` | — | SMTP credentials |
| `SMTP_FROM` | `noreply@example.com` | Sender address |

#### SSO / OIDC

All of these can also be set from the admin GUI, without a restart.

| Variable | Default | Description |
|----------|---------|-------------|
| `OIDC_ENABLED` | `false` | Enable OIDC login |
| `OIDC_ISSUER_URL` | — | Provider discovery URL (e.g. `https://accounts.google.com`) |
| `OIDC_CLIENT_ID` | — | Client ID registered with the provider |
| `OIDC_CLIENT_SECRET` | — | Client secret (stored Fernet-encrypted when set from the GUI, never returned by the API) |
| `OIDC_REDIRECT_URI` | — | Callback URL; auto-detected from the request base URL when empty |
| `OIDC_SCOPES` | `openid email profile` | Space-separated scopes |
| `OIDC_AUTO_PROVISION` | `true` | Create accounts on first OIDC login |

#### PostgreSQL tuning (Compose)

Defaults suit the 2 GB profile. On a larger host, raise them together and keep `POSTGRES_MEM_LIMIT` at roughly 3× `POSTGRES_SHARED_BUFFERS`:

```bash
POSTGRES_SHARED_BUFFERS=1GB POSTGRES_EFFECTIVE_CACHE_SIZE=3GB \
POSTGRES_WORK_MEM=32MB POSTGRES_MEM_LIMIT=3g
```

### Probe

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CENTRAL_API_URL` | ✅ | `http://localhost:8000` | WhatIsUp server base URL |
| `PROBE_API_KEY` | ✅ | — | API key from probe registration |
| `PROBE_NAME` | — | `default-probe` | Name shown in the UI |
| `PROBE_LOCATION` | — | `Unknown` | Human-readable location label |
| `MAX_CONCURRENT_CHECKS` | — | `10` | Max parallel checks |
| `MAX_CONCURRENT_SCENARIOS` | — | `2` | Max concurrent Chromium instances (a subset of the above; reduce on low-memory machines) |
| `HEARTBEAT_INTERVAL` | — | `30` | Seconds between server heartbeats |

---

## Features

### Check types

| Type | What it does |
|------|--------------|
| **HTTP / HTTPS** | Status codes, redirect following, response time, TLS grade (A–F, Mozilla SSTLS), SHA-256 certificate pinning, per-monitor custom headers, optional collapsible "Assertions" block (body regex, header check, keyword scan, JSON path/schema, response-shape drift) |
| **TCP** | Port reachability (databases, SSH, custom services) |
| **DNS** | Record resolution with optional value assertion (A, AAAA, CNAME, MX, TXT, NS), drift detection with baseline auto-learn, cross-probe consistency with split-horizon support |
| **SMTP** | Banner + EHLO handshake with optional STARTTLS; measures banner-to-ready time |
| **Ping** | ICMP round-trip time |
| **Domain expiry** | WHOIS lookup with configurable warning window |
| **Browser scenarios** | Multi-step Playwright automation (navigate, click, fill, assert, extract, screenshot) with Core Web Vitals (LCP, CLS, INP); needs the `-browser` probe image |
| **Heartbeat** | Dead-man's switch for cron jobs — unique ping URL, incident opened when a ping is late |

8 types (down from 10 — `udp` and `composite` were removed, `keyword`/`json_path` folded into HTTP's
assertions block). Tenant-supplied patterns run on an interruptible engine in an isolated thread pool, so a catastrophic regex can't take the probe with it.

### Infrastructure

- **Multi-probe architecture** — lightweight agents anywhere; probes are enriched with their ASN and network position for cross-probe correlation
- **Network type per probe** — `external` (public internet) or `internal` (corporate LAN)
- **Network scope per monitor** — restrict a check to `all`, `internal` or `external` probes
- **Probe map** — Leaflet world map, ASN as outer ring, 24 h uptime as inner colour, ASN filter chip
- **Incident playback** — scrub through how an outage propagated across probes
- **Probe groups** — admin-defined; grant probe visibility per user, and target automatic-discovery sources at a whole group
- **City / address geocoding** — Nominatim, no API key
- **Stale-agent warning** — a probe running an outdated build is flagged on the dashboard and the probes list, not left to skew verdicts silently

### Observability

- **Real-time dashboard** — WebSocket push, no polling
- **SLO / error budget** — configurable target and window, burn-rate tracking
- **SLA reports** — custom date range, uptime %, incident list, P95; JSON download
- **Custom push metrics** — business KPIs alongside uptime data, batched and labeled, with rate and cardinality quotas
- **Annotations** — timestamped notes on the monitor timeline (deployments, changes)
- **Certificates view** — a filterable mode of the monitors list showing certificate grade and expiry across every HTTPS monitor
- **Metric correlation on incident** — ranks the monitor's pushed metrics by how much they moved against the equivalent window just before, in a panel and in the post-mortem. Says *correlation*, never causation, and refuses to invent a figure when there is no baseline, too few samples, or a baseline of zero
- **Auto-diagnostics on incident** — every affected probe runs `traceroute`, `dig +trace`, `openssl s_client`, `ping` and `curl -v` in parallel, persisted and surfaced per incident
- **Prometheus metrics** — `/api/metrics`, fail-closed in production

### Incidents & alerting

- **Automatic lifecycle** — open on failure, resolve on recovery, driven by cross-probe quorum with a per-rule cooldown against rapid re-opening
- **Global Health Engine** — quorum-based judgement (`quorum_down`, `quorum_slow`) with per-probe divergence exclusion; the only detection engine (the legacy per-probe decider was retired), enabled by default on every new monitor
- **Network verdict** — distinguishes a real outage from an upstream ASN-level partition, computed on the same path that opens the incident, and shown in every alert, the incident view and the public status page; rules can opt out of paging on the latter
- **Incident groups** — monitors sharing failing probes within a 90 s window are grouped; one notification instead of N
- **Monitor dependencies** — child incidents suppressed while a parent is down
- **Storm protection** — per-rule rate cap, forced digest past the threshold
- **Suppression windows** — one object covers both planned maintenance (downtime excluded from uptime, publishable) and a plain silence (incident still opens and counts, only dispatch is muted), a checkbox apart
- **Alert matrix v2** — one card per condition, coloured channel chips, collapsible advanced params, and a live `≈ N / 30j` impact badge that replays the config against the last 30 days
- **Alerting templates** — Standard / Strict-Paging / Low-noise presets in one click; superadmins manage their own
- **Conditions** — `availability` (quorum-based, replaces the old `any_down`/`all_down`), `ssl_expiry`, `latency_anomaly` (absolute threshold, rolling-baseline ratio, or z-score — whichever field you set), `schema_drift`
- **Tag-scoped rules** — one rule targets every monitor carrying a tag
- **Acknowledge from Slack / Telegram** — a button in the alert itself. Every button carries a token we minted binding the incident to the channel, verified *before* the provider signature: a provider signature proves the request came from Slack, not which incident the button was for
- **On-call page** — rotations, escalation policies and a "who is on call right now" widget. An uncovered rotation says so rather than rendering blank
- **On-call rotations & timed escalation** — daily / weekly / custom rotations with one-off overrides, and a ladder that pages *different* targets in order (L1, then L2 if nobody acked, then whoever is on call) rather than re-paging the same channels. Handoffs are computed in local calendar days, so a 09:00 rotation does not drift across DST. A rung that reaches nobody is skipped without spending its delay, and a ladder that reaches nobody at all falls back to the rule's channels — attaching a policy never makes an alert quieter than attaching none
- **Quick-ack & snooze from mobile push** — act from the notification, no app round-trip
- **Auto post-mortem** — Markdown report on resolution (timeline, alerts, metrics)
- **Alert channels** — 11 built-in: Email (SMTP), Webhook (HMAC-SHA256), Telegram, Slack, Discord, Mattermost, Microsoft Teams (Adaptive Card), PagerDuty, Opsgenie, [Signal](#signal-alerts), FCM (native mobile push)
- **Persistent digest** — scheduling stored in Redis, survives restarts

### Public status pages

- **Shareable URL** — `/status/{slug}`, no login
- **90-day history bars** — daily uptime per component, served from the rollups
- **Incident timeline** — 30-day log with durations
- **Email subscriptions** — double opt-in, secure unsubscribe token
- **Atom feed** — one entry per availability incident, for anyone who'd rather subscribe than poll
- **Planned maintenance shown as maintenance** — not a red "major outage" banner
- **Manual announcements** — narrate an incident to visitors without a probe having to detect anything first
- **No inventory disclosure** — an optional public-facing name per monitor, and the public API no longer leaks internal URLs, ports, DNS record types or redirect targets

### Platform

- **Teams & RBAC** — 4 roles (`owner` > `admin` > `editor` > `viewer`); monitors, groups, channels and maintenance windows can be team-scoped. Single-user mode is preserved when no team exists
- **Monitor tags & tag-scoped RBAC** — free-form `key:value` tags, filterable everywhere, with `view`/`edit`/`admin` grants scoped to a tag
- **SSO / OIDC** — PKCE flow, optional auto-provisioning, configured from the admin GUI
- **2FA (TOTP) & active sessions** — QR enrolment, recovery codes, per-session revoke and "log out everywhere"
- **Personal API keys** — scoped `read` / `write`
- **Infrastructure-as-Code** — `GET /api/v1/config` exports everything; `PUT` imports declaratively with diff, dry-run and prune
- **Plugin architecture** — check types, alert channels **and alert conditions** are registry-based; extend without touching core code
- **Command palette** — `Cmd/Ctrl+K` fuzzy search over monitors, incidents, recent items and actions, with inline pause/ack
- **Bulk actions** — multi-select enable / pause / delete / move / tag / export CSV
- **Audit trail** — every admin action logged with a before/after diff
- **Multi-language** — English and French; **light / dark theme** auto-detected and persisted
- **Mobile app** — Android build via Capacitor 8, signed APK attached to every release

### Automatic discovery

A probe already sitting inside your network becomes an inventory sensor. Point it at a source and it
reports back what it sees; nothing is ever monitored silently — every discovered service is a
**proposal** you review and accept.

- **Sources**: `docker` (read-only socket — running containers, published ports, labels), `port_scan`
  (bounded TCP connect scan — CIDR ≤ /24, explicit port list), `dns_zone` (AXFR zone transfer against a
  resolver you declare by IP)
- **Review workflow** — `/discovery`: proposed / accepted / dismissed / orphaned states, bulk accept or
  dismiss with a shared reason, prefilled monitor (check type deduced from the port, name/group/tags from
  Docker labels)
- **Stays current** — a service that disappears from a snapshot orphans its monitor; a dismissed service
  whose nature changes (e.g. a container redeployed from a different image on the same port) is
  re-proposed rather than staying silently refused forever
- **Bounded and declared by design** — no CIDR wider than /24, no port range guessing, no AXFR fallback
  scan on a refused transfer, capped payload sizes; every outbound connection goes through the probe's
  SSRF-pinning resolver

To enable it: register a discovery source (`POST /api/v1/discovery/sources`, or from the `/discovery` UI)
against a probe that declares the matching capability at its heartbeat. The `docker` source needs the
probe's Docker socket mounted read-only — commented out by default in `docker-compose.yml` (`probe`
service): uncomment only if you intend to use it, it's a real privilege grant. See `FEATURES.md` § Découverte
for the full design rationale.

### Recording a scenario with Playwright Codegen

Scenarios are written by hand in the **Scenario builder** (drag-and-drop steps, templates), or recorded
with Microsoft's own [`playwright codegen`](https://playwright.dev/docs/codegen) and imported:

```bash
npx playwright codegen https://your-app.example.com
```

Interact with the page in the window it opens; Playwright writes a script as you go. Click **Importer**
in the Scenario builder and pass it the generated script — steps (navigate/click/fill/assert) come in
pre-filled; adjust selectors and mark password fields **secret** (🔒) before saving. Secret variable
values are Fernet-encrypted at rest, masked in every API response, and decrypted only when handed to the
probe at check time.

> A previous version of WhatIsUp shipped a browser extension recorder (`extension/`). It was removed:
> `playwright codegen` is officially maintained, produces the same kind of script, and the Scenario
> builder's import covers the handoff. If you relied on the extension and this doesn't cover your case,
> please open an issue.

---

## Operating WhatIsUp

### Sizing

| Probes | Monitors | CPU | RAM | Disk | PostgreSQL | Redis |
|--------|----------|-----|-----|------|------------|-------|
| 1–3 | ≤ 50 | 2 vCPU | 2 GB | 20 GB SSD | shared (in-stack) | shared (in-stack) |
| 3–10 | 50–200 | 4 vCPU | 4 GB | 40 GB SSD | shared or dedicated | shared |
| 10–30 | 200–1 000 | 4–8 vCPU | 8 GB | 80 GB SSD | dedicated (4 GB RAM) | dedicated (1 GB) |
| 30+ | 1 000+ | 8+ vCPU | 16 GB | 160 GB+ SSD | dedicated (8 GB+ RAM) | dedicated (2 GB+) |

**Disk growth** — a raw check result is ~300 bytes. At 200 monitors × 60 s × 5 probes, expect ~2.5 GB/month of raw data, held for `DATA_RETENTION_DAYS`. The hourly rollups that outlive it cost roughly 140 k rows/year for the same fleet — negligible next to a single day of raw. Retention reclaims space by dropping whole partitions, so disk is released in monthly steps rather than gradually.

| Probe mode | Image | CPU | RAM | Notes |
|------------|-------|-----|-----|-------|
| HTTP / TCP / DNS / Ping / SMTP / heartbeat only | `whatisup-probe:latest` (~480 MB, no browser — measured, `playwright` itself bundles a Node driver even browserless) | 1 vCPU | 256 MB | Runs on any VPS or a Raspberry Pi. A `scenario` monitor assigned here fails with a clear error naming the `-browser` image |
| With Playwright scenarios | `whatisup-probe:latest-browser` (~1.97 GB, Chromium included — unchanged) | 2 vCPU | 1 GB | Set `MAX_CONCURRENT_SCENARIOS=2` |
| High volume (100+ monitors) | either | 2 vCPU | 1–2 GB | Raise `MAX_CONCURRENT_CHECKS` |

| Component | Ports | Protocol |
|-----------|-------|----------|
| Central server (prod) | 80, 443 | HTTP/S via Nginx |
| Central server (dev) | 5173, 8000 | HTTP |
| PostgreSQL | 5432 | TCP, internal only |
| Redis | 6379 | TCP, internal only |
| Probe → Server | 443 (or 8000 dev) | HTTPS **outbound only** |

### Background loops

Every singleton loop is leader-elected through Redis, so N API replicas run each exactly once. Two of them are not housekeeping and deserve monitoring:

| Loop | Interval | If it stops |
|------|----------|-------------|
| **Partition maintainer** | 6 h | **Inserts fail.** If no partition covers the current instant, every check result is rejected. It keeps three months of head-room ahead |
| Rollup builder | 5 min | Stats fall back to the raw table; retention loses its interlock |
| Heartbeat checker | 30 s | Late cron jobs go unnoticed |
| **Escalation engine** | 30 s | **On-call ladders stop advancing** — this is also what re-pages an unacknowledged incident's own channels on a timer (a single-rung, repeating ladder), so this loop stopping means no periodic re-alerting either |
| Digest flusher | 30 s | Grouped alerts stay queued |
| Retention purge | nightly | Disk grows |
| Network verdict | 5 min | Incidents keep their last verdict |
| ASN refresh | 6 h | Probe ASN metadata goes stale |

### Deploying probe agents

1. **Probes → Register probe** in the UI: name, location (**Locate** resolves it via Nominatim), network type. Copy the API key — shown once.
2. Run it:

```bash
docker run -d --name whatisup-probe --restart unless-stopped \
  -e CENTRAL_API_URL=https://your-whatisup.example.com \
  -e PROBE_API_KEY=wiu_your_api_key_here \
  -e PROBE_NAME="paris-dc1" \
  -e PROBE_LOCATION="Paris DC1" \
  ghcr.io/aurevlan/whatisup-probe:latest
```

<details>
<summary>Docker Compose form</summary>

```yaml
services:
  probe:
    image: ghcr.io/aurevlan/whatisup-probe:latest
    restart: unless-stopped
    environment:
      CENTRAL_API_URL: https://your-whatisup.example.com
      PROBE_API_KEY: wiu_your_api_key_here
      PROBE_NAME: "paris-dc1"
      PROBE_LOCATION: "Paris DC1"
      MAX_CONCURRENT_CHECKS: "10"
      HEARTBEAT_INTERVAL: "30"
```

</details>

A probe that cannot reach the server buffers results to a bounded on-disk queue and replays them on reconnect, so a network blip does not become a hole in your history.

### Heartbeat monitoring (cron jobs)

Create a **Heartbeat** monitor, copy the ping URL, call it from your job:

```bash
curl -s https://your-whatisup.example.com/api/v1/ping/your-heartbeat-slug
```

An incident opens automatically if no ping arrives within `interval + grace`.

### Custom push metrics

```bash
curl -X POST https://your-whatisup.example.com/api/v1/metrics/{monitor_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"metric_name": "orders_per_minute", "value": 42.5, "unit": "req/min"}'
```

The same endpoint takes a **batch**, and points carry **labels** so one metric can be broken down by dimension:

```bash
  -d '[
    {"metric_name": "http_latency", "value": 42, "labels": {"route": "/api"}},
    {"metric_name": "http_latency", "value": 12, "labels": {"route": "/health"}}
  ]'
```

A batch is all-or-nothing: if it would breach a quota, nothing is stored and the response is a 429 saying which ceiling was hit. Keep label *values* bounded — a label carrying a user or request id creates one series per value and will hit the cardinality ceiling, which is exactly what that ceiling is for.

Metrics are graphed per series on the monitor detail view, and ranked against an incident's timeline by the metric-correlation panel (see [Observability](#observability)). There is no `metric_above`/`metric_below`/`metric_absent` alerting anymore — a metric threshold worth paging on is better served by an application endpoint that returns 500 past its own threshold, watched with a plain `http` check. A personal API key (`X-Api-Key: wiu_u_…`) works here too, so an application doesn't need a user password.

### Signal alerts

WhatIsUp talks to Signal through [**bbernhard/signal-cli-rest-api**](https://github.com/bbernhard/signal-cli-rest-api), a maintained wrapper around the official `signal-cli` — not to Signal directly.

<details>
<summary>Gateway setup and channel configuration</summary>

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

Register a number (see [the gateway README](https://github.com/bbernhard/signal-cli-rest-api#register-a-number)):

```bash
curl -X POST "http://localhost:8080/v1/register/+33612345678"
curl -X POST "http://localhost:8080/v1/register/+33612345678/verify/123456"
```

Then **Alerts → Add channel → Signal**:

| Field | Example |
|---|---|
| **API URL** | `http://signal-api:8080` (internal hostname if in the same Compose network) |
| **Sender number** | `+33612345678` (E.164) |
| **Recipients** | `+33612345678, +33698765432` (group IDs also accepted) |

Implementation: [`server/whatisup/services/channels/signal.py`](server/whatisup/services/channels/signal.py).

</details>

---

## API reference

Interactive docs at `/docs` (Swagger UI) and `/redoc`.

```bash
TOKEN=$(curl -s -X POST https://your-whatisup.example.com/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@example.com&password=your_password" | jq -r '.access_token')

curl https://your-whatisup.example.com/api/v1/monitors/ -H "Authorization: Bearer $TOKEN"
```

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` `POST` | `/api/v1/monitors/` | List / create monitors |
| `POST` | `/api/v1/monitors/bulk` | Bulk enable / pause / delete |
| `POST` | `/api/v1/monitors/{id}/trigger-check` | Trigger an immediate check |
| `GET` | `/api/v1/monitors/{id}/slo` | SLO / error-budget status |
| `GET` | `/api/v1/monitors/{id}/report` | SLA report over a custom range |
| `GET` | `/api/v1/monitors/{id}/incidents/{inc}/postmortem` | Auto post-mortem (Markdown) |
| `GET` `POST` | `/api/v1/monitors/{id}/annotations` | Timeline annotations |
| `GET` `POST` | `/api/v1/alerts/rules` | Alert rules |
| `POST` | `/api/v1/alerts/rules/{id}/simulate` | "Would this fire right now?" |
| `POST` | `/api/v1/metrics/{monitor_id}` | Push a custom metric |
| `GET` | `/api/v1/metrics/{monitor_id}` `…/summary` | List / aggregate custom metrics |
| `GET` | `/api/v1/metrics/{monitor_id}/series` | List the metric series a monitor reports |
| `GET` | `/api/v1/incidents/{id}/metric-correlation` | Which pushed metrics moved around an incident |
| `GET` | `/api/v1/oncall/schedules/on-call-now` | Who is on call right now, per schedule |
| `POST` | `/api/v1/callbacks/slack` `…/telegram` | Acknowledge from a chat message (signed) |
| `GET` | `/api/v1/public/pages/{slug}/monitors` | Public status page data (no auth) |
| `GET` | `/api/v1/public/pages/{slug}/feed.atom` | Public Atom feed (no auth) |
| `POST` | `/api/v1/public/pages/{slug}/subscribe` | Subscribe to a status page |
| `GET` | `/api/v1/ping/{slug}` | Heartbeat ping |
| `GET` `PUT` | `/api/v1/config/` | Export / import full config (IaC) |
| `GET` `POST` | `/api/v1/teams/` | Teams |
| `GET` | `/api/v1/status/monitors` | External status API |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                         Browser                          │
│  Vue 3 · Pinia · Vite · Tailwind · ApexCharts · Leaflet   │
│  vue-i18n (EN / FR) · Capacitor 8 (Android)               │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP + WebSocket
┌────────────────────────▼─────────────────────────────────┐
│                     FastAPI server                       │
│  auth · monitors · probes · alerts · metrics · ws         │
│  leader-elected background loops · slowapi · structlog    │
│  Alembic · Prometheus                                     │
└─────┬───────────────────┬──────────────────┬─────────────┘
      │                   │                  │
┌─────▼──────┐   ┌────────▼──────┐   ┌───────▼───────────┐
│ PostgreSQL │   │     Redis     │   │   Probe agent(s)  │
│ partitioned│   │ cache · pub/  │   │  APScheduler      │
│ + rollups  │   │ sub · locks   │   │  Playwright       │
└────────────┘   └───────────────┘   └───────────────────┘
```

| Layer | Location |
|-------|----------|
| API endpoints | `server/whatisup/api/v1/` |
| ORM models | `server/whatisup/models/` |
| Pydantic schemas | `server/whatisup/schemas/` |
| Business logic | `server/whatisup/services/` |
| Alert-condition plugins | `server/whatisup/services/conditions/` |
| Alert-channel plugins | `server/whatisup/services/channels/` |
| Core (config, security, db, partitions) | `server/whatisup/core/` |
| Probe agent + check plugins | `probe/whatisup_probe/` |
| Frontend | `frontend/src/` |

### Extending it

All three extension points are registries — add a module, register the class, done:

| To add a… | Write | Register in |
|-----------|-------|-------------|
| Check type | a checker in `probe/whatisup_probe/checkers/` | the dispatcher in that package's `__init__.py` |
| Alert channel | a `BaseAlertChannel` subclass in `services/channels/` | `services/channels/__init__.py` |
| Alert condition | an `AlertConditionHandler` subclass in `services/conditions/` | `services/conditions/__init__.py` |

A condition handler carries both its dispatch decision and its UI preview, so the two cannot drift apart unnoticed — a CI gate fails the build if any `AlertCondition` has no handler.

---

## Development

```bash
# Backend
cd server && pip install -e ".[dev]" && pytest
cd probe  && pip install -e ".[dev]" && pytest
ruff check . && ruff format .
pip-audit

# Frontend — Node 22 LTS required (jsdom 29 does not support Node 25's native localStorage)
cd frontend && npm install && npm test && npm run lint && npm audit
```

Everything also runs in Docker, which is how CI does it:

```bash
docker compose run --rm --no-deps server pytest tests/
docker compose run --rm --no-deps probe  pytest tests/
docker run --rm -v $(pwd):/repo -w /repo/frontend node:22-alpine \
  sh -c "npm ci && npx vitest run"
```

> Mount the **whole repository**, not just `frontend/` or `server/` — a few tests read files outside their own package and fail confusingly otherwise.

### Database migrations

```bash
cd server
alembic revision --autogenerate -m "short description"
alembic upgrade head
alembic downgrade -1
```

Model and schema must not drift: CI runs `scripts/check_model_drift.py` against a migrated database and fails on any diff. Declare PostgreSQL-only indexes in `__table_args__` with `.ddl_if(dialect="postgresql")` so they stay visible to `autogenerate` while staying out of the SQLite `create_all` the tests use.

### CI gates

| Gate | What it enforces |
|------|------------------|
| Server / probe tests | pytest, with a coverage floor |
| Frontend tests | vitest, plus two permanent accessibility gates (axe audit, anti-artisanal-overlay) |
| Lint | `ruff` and `eslint --max-warnings 0` |
| `pip-audit` / `npm audit` | no known-vulnerable dependency |
| Alembic migrations | migrations apply, and **zero** model↔schema drift |
| CodeQL + Plumber | static analysis and supply-chain compliance |

Contribution workflow, release process and the known CI pitfalls are in [CONTRIBUTING.md](CONTRIBUTING.md). Releases are driven by [release-please](https://github.com/googleapis/release-please) from Conventional Commits — merging the release PR builds and publishes the GHCR images and the signed Android APK.

---

## Security

- **JWT** — HS256, 15 min access + 7 day refresh, Redis-revocable; refresh tokens carry per-session metadata and are individually revocable
- **2FA (TOTP)** — opt-in second factor (RFC 6238), recovery codes hashed at rest
- **Account lockout** — per-account throttling with constant-time responses, so failures don't enumerate users
- **Secrets at rest** — Fernet for alert-channel secrets, OIDC client secret, scenario variables marked `secret`, and per-monitor custom header values. `FERNET_KEY` is mandatory in production, and rotates without downtime
- **SSRF protection** — every outbound request (webhooks, OIDC discovery, probe checks, scenario navigation) resolves the host once and **pins the resulting IP** for the connection, defeating DNS rebinding; redirect targets are re-validated per hop
- **Probe auth** — `X-Probe-Api-Key`, bcrypt 12 rounds with a fingerprinted Redis cache that honours immediate revocation
- **WebSocket auth** — a JSON message frame (`{"type":"auth","token":"…"}`), never a URL parameter; per-IP connection cap enforced before the handshake
- **Chat ack callbacks** — the only unauthenticated mutating endpoints. Defended in depth: a token we minted binds the incident to its channel and is checked *first* (it selects which signing secret applies), then the provider signature, then the clicking user's chat identity, then their access to the monitor. A channel with no signing secret shows no button and refuses every callback — never "accept unsigned". All rejections answer identically
- **Ownership enforcement** — every mutating endpoint verifies ownership through a JOIN; superadmin bypass is explicit
- **Input validation** — Pydantic schemas use `extra="forbid"` on every create/update endpoint
- **Rate limiting** — Redis-backed and shared across replicas; a CI gate fails the build if any `api/v1` endpoint ships without one
- **Tenant-supplied compute is bounded** — user regexes and JSON Schemas run on an interruptible engine in an isolated thread pool
- **CORS / CSP** — explicit origins only, HTTP origins rejected in production; `default-src 'self'; script-src 'self'`
- **Docker** — non-root user in every image, resource limits in production

See [SECURITY.md](SECURITY.md) for the security checklist, the OWASP mapping, and the responsible-disclosure policy.

---

## Documentation map

| File | What's in it |
|------|--------------|
| [CHANGELOG.md](CHANGELOG.md) | Per-version history |
| [FEATURES.md](FEATURES.md) | Source of truth for shipped features, by pillar |
| [SECURITY.md](SECURITY.md) | Security checklist, OWASP matrix, disclosure policy |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Workflow, commit conventions, release procedure |
| `CLAUDE.md` | Architecture decisions, invariants and known traps for contributors |
| [docs/archived/plans/](docs/archived/plans/) | Archived engineering plans and their shipped results (plan V2, discovery, …) |

## License

MIT — see [LICENSE](LICENSE).
