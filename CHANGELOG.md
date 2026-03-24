# Changelog

All notable changes to WhatIsUp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.8.1] - 2026-03-24

### Added

#### Probe health monitoring
- Probe reports live system metrics at each heartbeat: CPU %, RAM %, disk %, load average (1m), active monitor count, concurrent checks in progress
- Metrics collected via `psutil` (no external dependency for the probe agent beyond package install)
- Server stores health in Redis with a 120 s TTL — automatically marked stale when a probe goes offline
- `GET /api/v1/probes/stats` enriched with a `health` field per probe (populated via a single `MGET`, no extra round-trips)
- Portal (superadmin): probe cards show color-coded progress bars (green < 60 %, amber < 80 %, red ≥ 80 %) for CPU / RAM / Disk, plus monitors count, concurrent checks, and load average

#### Tests
- New `server/tests/test_probes.py`: 17 tests covering probe registration, heartbeat POST with/without health, Pydantic field validation, Redis TTL persistence, stats enrichment, stale-health null, auth guards
- New `probe/tests/test_health.py`: 9 tests covering `_collect_health()` keys/types/state, heartbeat POST body, error handling, client reuse

### Changed

#### Probe scalability
- Heartbeat endpoint changed from `GET` to `POST` — probe sends `{"health": {...}}` body alongside the request
- `Reporter`: persistent `httpx.AsyncClient` shared across all pushes — eliminates per-result TCP handshake
- Chromium (scenario checks): launch args `--no-sandbox` + `--disable-dev-shm-usage` — fixes random crashes in Docker non-root containers
- `shm_size: 256mb` added to all probe Docker Compose services (defense-in-depth alongside `--disable-dev-shm-usage`)
- `MAX_CONCURRENT_CHECKS` default: 20 → 10 — avoids OOM when scenario checks (Chromium, ~150–300 MB each) run concurrently
- Rate limit `/api/v1/probes/results`: 60/min → 600/min — previous limit caused 429s for probes with ≥ 30 monitors at 30 s intervals
- Rate limit `/api/v1/probes/heartbeat`: 30/min → 120/min
- DB connection pool: `pool_size` 10 → 20, `max_overflow` 20 → 10 — more permanent connections, fewer spike allocations
- `psutil.cpu_percent()` warm-up call in scheduler `__init__` — prevents the documented first-call 0.0 from appearing in the initial heartbeat

### Fixed
- `deploy.resources.limits` block removed from the `probe` Compose service — this block is Swarm-only and was silently ignored by `docker compose`, giving a false sense of memory capping

---

## [0.8.0] - 2026-03-22

### Added

#### SSO / OIDC (OpenID Connect)
- Full PKCE authorization-code flow: `GET /api/v1/auth/oidc/login` → callback → JWT pair issued
- `OidcCallbackView` in frontend handles the redirect and stores tokens automatically
- OIDC settings persisted in a new `system_settings` DB table — overrides env vars at runtime without a restart
- Admin GUI tab **SSO / OIDC** in the admin panel: enable/disable, configure issuer URL, client ID/secret, redirect URI, scopes, and auto-provision toggle
- `oidc_client_secret` encrypted at rest with Fernet; `oidc_client_secret_set` boolean returned to frontend (secret value never exposed)
- `oidc_sub` field on `User` model for provider-side subject linkage
- Auto-provision: unknown OIDC subjects can create accounts automatically (configurable)
- `_resolve_oidc_settings(db)` helper — reads DB row first, falls back to environment variables
- Public endpoint `GET /api/v1/auth/oidc/config` returns `enabled` flag and authorization URL for login page

#### Admin panel
- New `AdminView` with tabs: Users, Monitors, Probe groups, SSO / OIDC
- **User management** — list, create, update (`is_active`, `can_create_monitors`), delete; cannot delete own account
- **`can_create_monitors` permission** — new boolean on `User`; non-superadmin users without this flag receive 403 on monitor creation
- **Probe groups** — admin-managed groups linking probes to users; regular users see only probes in their groups; full CRUD at `GET/POST /api/v1/admin/probe-groups`, `PATCH/DELETE /{id}`, `POST /{id}/probes`, `DELETE /{id}/probes/{probe_id}`, `POST /{id}/users`, `DELETE /{id}/users/{user_id}`
- **All-monitors view** — superadmin can list every monitor across all users at `GET /api/v1/admin/monitors`
- OIDC settings CRUD at `GET/PUT /api/v1/admin/settings/oidc`

#### Network scope filtering
- New `network_scope` field on `Monitor` (`all` / `internal` / `external`) — controls which probe types execute each monitor
- Heartbeat endpoint filters monitors by `or_(network_scope == "all", network_scope == probe.network_type)`
- UI: scope selector in `CreateMonitorModal`; existing monitors default to `all` (no breaking change)

#### Probe improvements
- `ProbeMonitorConfig` now includes `smtp_port`, `smtp_starttls`, `udp_port`, `domain_expiry_warn_days` — these were read by the probe scheduler but never sent, causing SMTP/UDP/domain monitors to silently use hardcoded defaults
- Heartbeat populates all four new fields from the DB row

### Fixed
- **Probe scheduler — scenario/config changes ignored** — `APScheduler.reschedule()` updates the trigger interval but does not update job `args`; adding `existing.modify(args=[monitor])` ensures that scenario steps, variables, and all other config fields are propagated to running jobs after a monitor update. Without this fix, scenario steps edited after initial creation were never picked up until the probe was restarted.
- **Alert channel Telegram text too long** — detail message and validation confirmation string wrapped to stay within ruff E501 limit (no functional change)

### Changed
- Login page shows SSO button when OIDC is enabled (resolved from DB at request time)
- `GET /api/v1/probes/` returns only probes in the caller's probe groups for regular users; superadmin still sees all probes

### Tests
- Full test suite rewritten: 73 passing tests across `test_auth`, `test_monitors`, `test_alerts`, `test_groups`, `test_admin`
- `conftest.py` creates `admin_user` / `regular_user` fixtures directly in the DB (avoids the disabled `/register` endpoint); tokens obtained via `/auth/login`
- New `test_admin.py`: users CRUD, all-monitors list, probe groups CRUD (add/remove probe and user), OIDC settings (env fallback, DB update, secret masking, secret preservation on null, `/auth/oidc/config` reflection)
- New `test_alerts.py`: channel CRUD, cross-user isolation, rule CRUD, events endpoint, auth guard
- New `test_groups.py`: monitor groups CRUD, slug conflict 409, cross-user 403, auth guard

### Migrations
- `d61cfbdf8a24` — add `can_create_monitors` to `users`
- `b4c5d6e7f8a9` — add `oidc_sub` to `users`
- `283efc2c973a` — add `probe_groups`, `probe_group_members`, `user_probe_group_access` tables
- `a3b4c5d6e7f8` — add `network_scope` to `monitors` (`server_default='all'`, backfills existing rows)
- `73c722e67eee` — DNS split-horizon: `dns_split_enabled` flag; remove consistency columns
- `c1d2e3f4a5b7` — add `system_settings` table (OIDC DB-persisted config)

---

## [0.7.0] - 2026-03-20

### Added

#### HTTP Waterfall Timing
- Probe captures `dns_resolve_ms`, `ttfb_ms`, `download_ms` via httpx streaming for HTTP monitors
- Monitor detail view displays a stacked mini-bar with DNS / TTFB / Download breakdown per check

#### Anomaly Detection
- Z-score based response time analysis per alert rule with configurable threshold (1.0–10.0, default 3.0)
- Hour-of-day bucket filtering in SQL to compare against same-time-of-day samples (avoids false positives)
- Z-score computed once per check result, evaluated against each rule's threshold without extra DB queries

#### API Schema Drift Detection
- Probe computes a SHA256 fingerprint of JSON response structure (keys+types, not values) for HTTP monitors
- Baseline auto-set on first successful check when `schema_drift_enabled=true`
- Accept / reset baseline endpoints; drift alerts fire via point-in-time incidents

#### Business Hours Alerting
- Per-rule schedule: timezone, active days, start/end time
- Alerts suppressed outside configured hours (`offhours_suppress` flag)
- UI in AlertsView with day-of-week toggles and timezone selector

#### Incident Status Updates
- Private timeline per incident: `investigating` → `identified` → `monitoring` → `resolved`
- Updates marked `is_public=true` replicated to public status page with colored status dots
- Delete own updates; full CRUD via `/incidents/{id}/updates`

#### Monitor Templates
- Reusable blueprints with `{{VAR}}` placeholder substitution
- Public/shared visibility; apply modal with default prefill
- Full CRUD at `/templates`

### Fixed
- Ruff E501/I001: line length and import ordering in new files

---

## [0.6.0] - 2026-03-19

### Added

#### Browser extension — scenario recorder

- **Service worker state persistence** — all recording state (`recording`, `steps`, `recordingTabId`, `secretVars`) migrated from in-memory `let` variables to `chrome.storage.session`; survives Manifest V3 service worker termination (idle kill after ~5 s), eliminating dropped steps during recording
- **Password capture with secret variables** — input fields of type `password` are now captured: the real value is stored as `{{password_N}}` placeholder in the step params and the actual secret is kept in a separate `secretVars` store; never written to the step list visible in the popup
- **Navigation-aware content script reactivation** — after every page navigation (`chrome.tabs.onUpdated status=complete`), the background worker re-sends `RECORDING_STARTED` to the content script so `_active` is set correctly on the new page; cross-page recording now works without user interaction
- **`ADD_SECRET_VAR` message type** — new background message; idempotent upsert by name (re-typing a password replaces the previous value)

#### Security hardening

- **Fernet encryption for scenario variables** — `encrypt_scenario_variables()` / `decrypt_scenario_variables()` added to `core/security.py`; all `secret: true` scenario variables are encrypted at rest in the database; decrypted only on probe delivery; masked (`value: ""`) in all API responses
- **`FERNET_KEY` required in production** — `validate_production_settings()` in `config.py` raises `ValueError` at startup if `FERNET_KEY` is empty when `ENVIRONMENT=production`; prevents accidental plaintext secret storage
- **Typed scenario schemas with validation** — `ScenarioStep` (Pydantic model with `type` regex whitelist) and `ScenarioVariable` (alphanum name, 255-char value limit) replace bare `list[dict]` in `MonitorCreate` / `MonitorOut` / `MonitorUpdate`; `MonitorOut.scenario_variables` auto-decrypts and masks via a field validator
- **SSRF guard extended to Slack** — `_validate_webhook_url()` added to all 3 Slack call sites in `services/alert.py` (test, digest loop, `_send_slack`); mirrors the existing protection on generic webhooks
- **WebSocket per-IP limit correctly enforced** — dashboard WebSocket now routes through `manager.connect()` before accepting; on auth failure calls `manager.disconnect()` before closing (was previously bypassing the per-IP limit for the auth window)
- **Public WebSocket slug validation** — `ws /api/v1/ws/public/{slug}` now validates the slug against the database before accepting the connection; unknown slugs close with code 4004
- **`AlertRule` delete ownership fix** — cross-user rule deletion was possible when a rule had zero channels (JOIN returned no rows); replaced with `outerjoin(Monitor)` + `outerjoin(MonitorGroup)` + `or_()` ownership check; superadmin bypass preserved
- **`POST /monitors/` rate limit** — `@limiter.limit("10/minute")` added to `create_monitor`
- **API key storage hardened** — browser extension options migrated from `chrome.storage.sync` (cloud-synced) to `chrome.storage.local`; prevents API keys from being uploaded to the user's Google account

#### New monitoring capabilities

- **DNS drift detection** — new `services/dns.py`; per-monitor `dns_drift_alert` flag auto-learns the initial A/AAAA answer as a baseline; subsequent deviations set result status to `down` with a descriptive error message
- **DNS cross-probe consistency** — per-monitor `dns_consistency_check` flag; compares DNS answers from different probes within a `2 × interval` window; inconsistencies flagged as `down` unless `dns_allow_split_horizon` is set
- **Composite monitors** — new `services/composite.py` with 4 aggregation rules (`all_up`, `any_up`, `majority_up`, `weighted_up`); synthetic `CheckResult` (probe_id=None) drives the normal incident pipeline; recomputed automatically whenever a member monitor result is stored
- **Alert rule enable/disable** — `enabled` boolean column on `AlertRule`; disabled rules are skipped at dispatch time without deletion; toggle exposed in the alert management UI

### Fixed

- `fr.js` — 3 unescaped apostrophes in single-quoted strings (`l'état`, `Règle d'agrégation`, `l'instant`) caused a Vite/Rollup build failure; switched to double-quoted strings
- `SEND_TO_WHATISUP` handler — return value was the raw API JSON object instead of `{ ok: true, result }`; popup displayed `undefined` after successful send; wrapped correctly
- `chrome.storage.sync` in `options.js` — API key and server URL were synced to the user's Google account; migrated to `chrome.storage.local`

### Changed

- `probe/checker.py` — extended to decrypt and use `scenario_variables` received from the server (variables are passed decrypted; the probe never sees Fernet ciphertext)
- `server/whatisup/api/v1/probes.py` — heartbeat response decrypts `scenario_variables` before delivering to probe
- `server/whatisup/api/v1/monitors.py` — `create_monitor` and `update_monitor` encrypt incoming secret variables; update skips re-encryption for masked (empty-value) secrets submitted by the UI
- Dependency updates — `uvicorn` unblocked to `<0.43` (picks up 0.42.0); `@tailwindcss/vite` → 4.2.2, `tailwindcss` → 4.2.2, `vue-router` → 5.0.4, `eslint` → 9.39.4

### Database migrations (in order)

| Revision | Description |
|----------|-------------|
| `d2e3f4a5b6c7` | Add `dns_drift_alert`, `dns_baseline_ips`, `dns_consistency_check`, `dns_allow_split_horizon` to `monitors`; create `composite_monitor_members` table; add `composite_aggregation` to `monitors` |
| `e3f4a5b6c7d8` | Add `enabled` boolean column to `alert_rules` (default `true`) |

---

## [0.5.0] - 2026-03-17

### Added

#### Incident correlation & alert quality

- **Monitor dependencies** — new `MonitorDependency(parent_id, child_id, suppress_on_parent_down)` model; when a parent monitor has an open incident, child incidents are automatically suppressed or tagged `dependency_suppressed`; eliminates cascade alert storms; full CRUD via `GET/POST/DELETE /api/v1/monitors/{id}/dependencies`; dependency panel in monitor detail view
- **Persistent incident groups** — new `IncidentGroup` model backed by PostgreSQL; monitors sharing the same failing probes within a 90 s window are grouped into a single persistent incident group with one notification instead of N; `GET /api/v1/incident-groups/` with ownership filtering; `IncidentGroupsView.vue` with status filter (open / resolved)
- **Per-monitor flapping thresholds** — `flap_threshold` (default: 5) and `flap_window_minutes` (default: 10) columns on `Monitor`; override global defaults per monitor; exposed in the create/edit form under a collapsible section
- **Alert storm protection** — `storm_window_seconds` and `storm_max_alerts` columns on `AlertRule`; when > N alerts fire on the same rule within the window, further alerts are throttled and a forced digest is sent instead
- **Performance baseline alerting** — new `AlertCondition.response_time_above_baseline` condition; baseline = 7-day rolling average at the same hour; `baseline_factor` column on `AlertRule` (e.g. `3.0` = alert if current response time > 3× the baseline); detects slowdowns without a static threshold
- **Persistent alert digest** — digest scheduling migrated from `asyncio.call_later` (lost on restart) to a Redis sorted set (`whatisup:digest_schedule`); a background task flushes due digests every 30 s; survives server restarts and is observable via Redis CLI
- **Group-level maintenance suppression** — when all monitors in a group are down and the group has an active maintenance window with `suppress_alerts=True`, individual alerts are suppressed
- **Probe incident timeline** — `GET /api/v1/probes/{probe_id}/incident-timeline?days=7` returns all incidents in the window grouped by monitor; `ProbeTimelineView.vue` renders proportional timeline bars per monitor; day selector (1 / 7 / 14 / 30 / 90)

#### New check types (probe + UI)

- **UDP** — sends an empty datagram; interprets ICMP port-unreachable as down, timeout as filtered/open
- **SMTP** — connects, reads the `220` banner, sends `EHLO`, optional `STARTTLS`; measures banner-to-ready time
- **Ping** — ICMP ping via subprocess; parses RTT from output; falls back gracefully if `ping` binary is absent
- **Domain expiry** — WHOIS lookup via `python-whois`; warns `N` days before expiry (configurable `domain_expiry_warn_days`); `probe/pyproject.toml` adds `python-whois>=0.9.4`

#### Dashboard & UI

- **Probe map on dashboard** — new `ProbeMap.vue` component in the dashboard alongside the monitor list; Leaflet map with per-probe coloured markers (🟢 ≥ 99 % / 🟡 ≥ 90 % / 🔴 < 90 % / ⚫ no data) with glow effect; popup shows uptime, check count, online status; compact probe list below the map; auto-refreshes every 60 s
- **`GET /api/v1/probes/stats`** — returns all probes with `uptime_24h` and `check_count_24h` in a single aggregated query (no N+1); new `ProbeStatsOut` schema
- **Monitors view — filter bar redesign** — 12 overflowing type chips replaced by a compact `<select>` dropdown; status chips now use semantic colours (green/red/orange); paused toggle replaces 3-button enabled filter; view toggle reduced to icon-only buttons with tooltips
- **`MonitorRow.vue` rewrite** — replaced all JavaScript inline styles with Tailwind classes; status badge, dot, uptime colour now use design-system tokens; hover handled via CSS

#### Infrastructure

- **Probe DNS configuration** — `dns: [${PROBE_DNS_1}, ${PROBE_DNS_2}]` added to `probe-local` and `probe` services in `docker-compose.yml` and `docker-compose.probe.yml`; defaults to `8.8.8.8` / `8.8.4.4`; fixes DNS resolution failures when the Docker daemon's embedded resolver has no external nameservers
- **`deploy.sh` — DNS prompt** — interactive wizard now asks for primary and secondary DNS servers (default: Google DNS) in probe deployment modes (mode 1 and mode 3); values written to `.env` / `.env.probe`

### Fixed

- `MonitorDependencies.vue` — import used `@/api/monitors` (alias unsupported in this Vite config); fixed to relative path `../../api/monitors`
- Migration revision collision — `a1b2c3d4e5f6_monitor_dependencies_incident_groups.py` conflicted with existing `a1b2c3d4e5f6_v020_enrichment.py`; new migration renamed to `c1d2e3f4a5b6`

### Database migrations (in order)

| Revision | Description |
|----------|-------------|
| `e1f2a3b4c5d6` | Add `udp_port`, `smtp_port`, `smtp_starttls`, `ping_*`, `domain_expiry_warn_days` to `monitors` |
| `c1d2e3f4a5b6` | Create `incident_groups` and `monitor_dependencies` tables; add `group_id` FK and `dependency_suppressed` to `incidents` |
| `b2c3d4e5f6g7` | Add `flap_threshold`, `flap_window_minutes` to `monitors`; add `storm_window_seconds`, `storm_max_alerts`, `baseline_factor` to `alert_rules`; extend `alert_condition` enum |

---

## [0.4.0] - 2026-03-14

### Added

#### Functional improvements

- **Bulk actions** — multi-select monitors in list view; bulk enable / pause / delete / export CSV (client-side)
- **Advanced HTTP assertions** — regex body check (`body_regex`), response header validation (exact or `/regex/` mode), JSON Schema validation via `jsonschema`; all assertions stop processing on first failure with descriptive error
- **SLO / Error Budget** — configurable `slo_target` (%) and `slo_window_days` per monitor; `GET /monitors/{id}/slo` returns burn rate, budget remaining (minutes), and status (`healthy` / `at_risk` / `critical` / `exhausted`)
- **Auto post-mortem** — `GET /monitors/{id}/incidents/{incident_id}/postmortem` generates a structured Markdown report with incident timeline, alert events, metrics, and annotations; downloadable `.md` from the UI
- **Digest / batch notifications** — `digest_minutes` field on `AlertRule`; alerts within the window are buffered in Redis (`LPUSH`) and dispatched as a single grouped message after the delay
- **Enriched public status page** — 90-day daily history bars (up / degraded / down / no_data), incident timeline (30 days), email subscription with unsubscribe token, global status banner
- **Custom push metrics** — `POST /api/v1/metrics/{monitor_id}` lets external services push business metrics (orders, latency…); displayed as ApexCharts line graphs per metric name in the monitor detail view
- **Core Web Vitals** — Playwright scenario checks now capture LCP, CLS and INP via `PerformanceObserver`; stored in `scenario_result.web_vitals`; displayed with colour-coded thresholds in the UI
- **PagerDuty integration** — new alert channel type using Events API v2 (`trigger` / `resolve` with `dedup_key`); integration key encrypted at rest with Fernet
- **Opsgenie integration** — new alert channel type using Alerts API (US and EU regions); alert create / close lifecycle; API key encrypted at rest

#### Probe improvements

- **City / address geocoding** — "Locate" button in probe registration and edit modals calls Nominatim (OpenStreetMap) to resolve any address, city, or place name to GPS coordinates (4-decimal precision, no API key required)
- **Network type** — new `network_type` field (`external` / `internal`) on probes; shown as coloured badge in list and map popups; used to distinguish corporate LAN failures from public internet outages; PostgreSQL enum `networktype`

#### Internationalisation

- **EN/FR i18n** — `vue-i18n@9` (Composition API mode) with comprehensive locale files (`src/i18n/en.js`, `src/i18n/fr.js`) covering all UI strings
- **Language toggle** — 🇬🇧/🇫🇷 button in the sidebar; preference persisted to `localStorage`
- **English as default** — entire UI now defaults to English; French available via toggle in the admin sidebar

#### UI / UX

- **Unified button system** — all buttons now use semantic CSS classes (`btn-primary`, `btn-secondary`, `btn-ghost`, `btn-danger`) with consistent padding, radius, transition, and disabled state
- **SLO edit form** — inline SLO configuration card in monitor detail (previously read-only); visible even when no SLO is configured
- **Dashboard nav fix** — Dashboard nav link now uses `isExactActive` (`exact` prop) so it only highlights on `/`, not on child routes
- **Address input for probes** — location field accepts full street addresses, not just city names; Nominatim handles geocoding

### Changed

- `compute_daily_history` in `services/stats.py` — replaced parameterised `date_trunc('day', ...)` with `text("'day'")` literal to fix PostgreSQL `GroupingError` with asyncpg
- `POST /public/pages/{slug}/subscribe` — email now sent as JSON body (`SubscribeRequest` schema) instead of query parameter
- Probe list/map — badge colours updated to reflect `network_type` (blue = external, purple = internal)

### Fixed

- `PublicPageView.vue` — import path `@/api/public.js` → `../api/public.js` (no `@` alias configured in Vite)
- `ScenarioBuilder.vue` — `{{ '{{' + varName + '}}' }}` replaced with `<span v-text>` to avoid Vue template parser crash on nested interpolation delimiters

### Database migrations (in order)

| Revision | Description |
|----------|-------------|
| `e5f6a7b8c9d0` | Add `digest_minutes` to `alert_rules` |
| `b8c9d0e1f2a3` | Create `status_subscriptions` table |
| `f6a7b8c9d0e1` | Add `body_regex`, `expected_headers`, `json_schema` to `monitors` |
| `a7b8c9d0e1f2` | Add `slo_target`, `slo_window_days` to `monitors` |
| `c9d0e1f2a3b4` | Create `custom_metrics` table |
| `394eaf748eaf` | Merge point for above migrations |
| `d1e2f3a4b5c6` | Add `network_type` enum column to `probes` |

---

## [0.3.0] - 2026-03-11

### Added

#### New check types — TCP, DNS, Keyword, JSON Path
- **TCP** — `asyncio.open_connection` probe; checks port reachability (databases, SSH, SMTP…)
- **DNS** — `dnspython` resolver; optional record-value assertion (A, AAAA, CNAME, MX, TXT, NS)
- **Keyword** — HTTP response body scan with optional negate mode (alert if keyword IS found)
- **JSON Path** — HTTP response JSON validation via dot-notation path (e.g. `$.status == "ok"`)
- New check-type selector in `CreateMonitorModal.vue` (5-button grid with icons + description)
- Conditional form fields per type (port, DNS record type, keyword, JSON path, expected value)
- `probe/whatisup_probe/checker.py` — dispatcher with 4 dedicated check engines
- `probe/pyproject.toml` — added `dnspython>=2.7.0,<3`
- Alembic migration adds `check_type`, `tcp_port`, `dns_record_type`, `dns_expected_value`, `keyword`, `keyword_negate`, `expected_json_path`, `expected_json_value` columns to `monitors`

#### Audit trail
- `AuditLog` model — records who changed what with before/after diff (JSON)
- `GET /api/v1/audit/` endpoint — filterable by action, object type, date range (superadmin only)
- `AuditView.vue` — paginated table with color-coded action badges and expandable diff panels
- Actions logged: monitor create/update/delete, probe register/delete

#### Maintenance windows
- `MaintenanceWindow` model — per-monitor or per-group scheduled downtime
- Full CRUD via `GET/POST/PATCH/DELETE /api/v1/maintenance/`
- `is_in_maintenance()` service — suppresses incident creation and alerts during active windows
- `MaintenanceView.vue` — management UI with active/upcoming/past indicator

#### Flapping detection
- 5+ status transitions within 10 minutes → suppress incident creation
- Prevents alert storms on unstable services

#### Common-cause correlation
- Monitors sharing the same set of failing probes within a 90 s window are grouped as a single correlated incident

#### Performance-based alert conditions
- `AlertCondition` enum extended: `response_time_above`, `uptime_below`
- `AlertRule.threshold_value` column for numeric thresholds
- `AlertRule.renotify_after_minutes` column for re-notification cadence

#### Slack alert channel
- `AlertChannelType` enum extended: `slack`
- `_send_slack()` — posts rich attachment (color, title, fields, footer) to Slack webhook

#### Uptime history bars
- `UptimeHistoryBars.vue` — 90-day strip chart (green ≥ 99 %, amber ≥ 95 %, red < 95 %)
- `GET /api/v1/monitors/{monitor_id}/history?days=90` endpoint
- P95 response time via PostgreSQL `percentile_cont(0.95)` (replaces in-memory approximation)

#### Prometheus metrics
- `prometheus-fastapi-instrumentator` installed and exposed at `/api/metrics`

### Fixed
- **Critical (BUG-6)**: background task passed a detached ORM object to `process_check_result` → results were never persisted. Fixed: main session commits before the background task runs; background task re-fetches by ID in a fresh session
- **BUG-1**: `Monitor.enabled is True` (Python identity) always evaluated to `False` in SQLAlchemy queries → all monitors excluded from heartbeat and result ingestion. Fixed: `.is_(True)`
- **XSS (BUG-2)**: Leaflet popup interpolations in `ProbesView.vue` were unescaped. Fixed: added `escapeHtml()` applied to all popup fields
- **BUG-3**: `GET /probes/{id}` used `get_current_probe` (probe API key) instead of `require_superadmin`. Fixed
- **BUG-4**: `ProbeCheckResultIn` schema lacked range validators. Fixed: `ge=100,le=599` for `http_status`, `ge=0` for `response_time_ms`, `le=50` for `redirect_count`, `max_length=2048` for `final_url`
- **BUG-5**: Empty `catch` blocks in `ProbesView.vue` silently swallowed errors. Fixed: `showError()` with auto-dismiss banners (5 s)
- **`UserOut.email: EmailStr`**: Pydantic v2 rejects `admin@local` (no TLD) during response serialization → HTTP 500 on `/auth/me`. Fixed: changed to `email: str` in `UserOut` (validation kept on `UserCreate`)

### Changed
- `server/main.py` — audit and maintenance routers registered; Prometheus instrumented
- `server/whatisup/schemas/probe.py` — `ProbeMonitorConfig` extended with all new check-type fields
- `server/whatisup/api/v1/probes.py` — heartbeat passes all new fields; result ingestion commits before background task
- `frontend/src/router/index.js` — added `/maintenance` and `/audit` routes
- `frontend/src/views/layouts/AppLayout.vue` — Maintenance and Audit Log nav links added

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

[Unreleased]: https://github.com/AurevLan/WhatIsUp/compare/v0.8.1...HEAD
[0.8.1]: https://github.com/AurevLan/WhatIsUp/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.2.0...v0.4.0
[0.3.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.2.0...v0.4.0
[0.2.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/AurevLan/WhatIsUp/releases/tag/v0.1.0
