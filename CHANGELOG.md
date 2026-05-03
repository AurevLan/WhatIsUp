# Changelog

All notable changes to WhatIsUp will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.7.0](https://github.com/AurevLan/WhatIsUp/compare/v1.6.0...v1.7.0) (2026-05-03)


### Added

* **diagnostics:** V2-01-01 auto-traceroute corrélé sur incident ([441e43c](https://github.com/AurevLan/WhatIsUp/commit/441e43cc1734c59fc1589ac8506295f0c1e474a4))
* **monitors:** custom_headers per-monitor + UA presets (HTTP/keyword/json_path) ([772dae0](https://github.com/AurevLan/WhatIsUp/commit/772dae05e406b35b750fdaaac6dc643cad2c89ee))


### Fixed

* **probe/tests:** align heartbeat tests with V2-01-01 dict response shape ([401dc2c](https://github.com/AurevLan/WhatIsUp/commit/401dc2ce5cb9e8655b88d7bd9784218e94373ee9))

## [1.6.0](https://github.com/AurevLan/WhatIsUp/compare/v1.5.0...v1.6.0) (2026-04-29)


### Added

* **alerts:** V2-02-02 — opt-in alert suppression on network partition + UI badge ([a075ede](https://github.com/AurevLan/WhatIsUp/commit/a075eded91eed855ebaf98e914c230971541cfcc))
* **probes:** V2-02-01 + V2-02-02 — ASN enrichment + network partition verdict ([8e96722](https://github.com/AurevLan/WhatIsUp/commit/8e96722aa0ef8e02c05b37b56f7b4e9d56b8100a))
* **probes:** V2-02-06 + V2-02-07 — outbound IP intelligence + ASN-aware map + incident playback ([4066230](https://github.com/AurevLan/WhatIsUp/commit/4066230da6310100035d36488b36c09f2558a820))


### Docs

* add FEATURES.md, harden SECURITY.md, auto-versioning via release-please ([d083d0b](https://github.com/AurevLan/WhatIsUp/commit/d083d0b4fea3bb3c2e447d7953df752901ed1d1e))

## [Unreleased]

### Added
- **V2-01-01 — Auto-traceroute corrélé sur incident** — Foundation de la vague α (Pilier 1 : Diagnostic Engine). À l'ouverture d'un incident, chaque sonde affectée reçoit (via clé Redis transitoire consommée au heartbeat suivant) une demande de collecte parallèle de 5 diagnostics réseau : `traceroute -n`, `dig +trace`, `openssl s_client -showcerts`, `ping -c 5`, `curl -v`. Le payload structuré est persisté dans la nouvelle table `incident_diagnostics` (FK `incident_id`/`probe_id`, JSONB `payload`, champ `error` si la collecte échoue). Nouvelle section dépliable "Diagnostic" sous chaque incident dans `IncidentsView` (icône Activity), groupée par sonde, avec rendu typé par kind (hops cliquables pour traceroute, métriques pour ping, en-têtes HTTP en monospace, etc.).
  - **Modèle** : `IncidentDiagnostic` + migration Alembic `k3l4m5n6o7p8` (rétrocompatible).
  - **Probe** : nouveau module `whatisup_probe/diagnostics.py` (collecteurs `asyncio.gather`, timeout 10 s par kind, raw output tronqué 8 KB). Binaires ajoutés à l'image runtime probe : `traceroute`, `iputils-ping`, `dnsutils`, `openssl`, `curl`.
  - **API** : `POST /api/v1/probes/diagnostics` (auth `X-Probe-Api-Key`, rate-limit 60/min) ingest, et `GET /api/v1/incidents/{id}/diagnostics` (auth user, rate-limit 30/min, accès vérifié via owner du monitor).
  - **Service** : `services/diagnostics.py` (`enqueue_diagnostic_requests` + `drain_pending_diagnostics`), hook ajouté dans `services/incident.py` au moment de l'ouverture d'un incident (best-effort, ne casse pas le pipeline si Redis tombe).
  - **Tests** : 4 pytest (hook trigger, payload schema, multi-probe distinct FK, drain Redis at-most-once) + 3 vitest UI. Suite complète : 252 backend + 175 frontend, tous verts.
  - i18n en/fr (`incidents.diagnostic_title`, `diagnostic.*`).

---

## [1.5.0] - 2026-04-25

**Wave 1 Tier 1 complete** — 8 ⭐ items shipped on top of v1.4.0 to close the SRE adoption + UX backlog. Highlights: command palette v2 with fuzzy search and inline actions, global keyboard shortcuts, multi-select bulk actions on monitors *and* incidents, push-notification quick-ack/snooze, programmable alert silences, and a 3-step monitor creation wizard. 100% backward-compatible.

### Added
- **Skeleton loaders (T1-16)** — Nouveaux composants `SkeletonBox`, `SkeletonText`, `SkeletonRow` (`components/shared/`) basés sur les classes shimmer existantes (`.skeleton`, `.skeleton-circle`, `.skeleton-line`) et le respect de `prefers-reduced-motion` déjà en place dans `style.css`. Appliqués sur `DashboardView` (liste monitors), `MonitorsView` (table en mode liste) et `MonitorDetailView` (header + tabs + KPI cards + chart) à la place des `animate-pulse` génériques. ARIA `role=status` + `aria-busy=true` pour lecteurs d'écran. 12 tests vitest.
- **Empty states avec CTA contextuelle (T1-18)** — Nouveau composant `EmptyState.vue` (slots `icon`/`cta`, props `title`/`text`/`ctaLabel`/`docHref`/`replayTour`/`inline`) qui standardise icône + titre + description + CTA + lien doc + bouton "Rejouer le tour". Refactor de 6 vues : `DashboardView` (mini empty), `MonitorsView` (liste + grid, distingue filtres actifs vs aucun monitor), `GroupsView`, `AlertsView` (channels + events), `ProbesView` (CTA superadmin only), `MaintenanceView`. Nouveau composable `composables/useTour.js` (`tourActive`, `shouldStartTour`, `requestTour(target?)`, `clearTour`) qui pilote la relecture du wizard via `?tour=1` + flag `localStorage` ; consommé dans `DashboardView.onMounted` pour réafficher l'`OnboardingWizard` à la demande. Nouvelles clés i18n `common.read_docs`, `tour.replay`, `empty.*` (en/fr). 16 tests vitest.
- **Command palette v2 (T1-10)** — Recherche **fuzzy** sur tous les groupes (subsequence + bonus consécutifs/word-boundary, `lib/fuzzy.js` sans dépendance externe). Nouveau bloc **"Recent"** au sommet quand le champ est vide (12 derniers monitors/incidents visités, persistés dans `localStorage`, bouton clear, store Pinia `commandPalette`). Nouveau bloc **"Open incidents"** alimenté par `_hasOpenIncident`/`_openIncidentId`. **Actions inline** au survol des items : pause/resume sur un monitor (réutilise `monitorStore.update({enabled})`), acknowledge sur un incident (`incidentUpdatesApi.ack`). `recordVisit` câblé dans `MonitorDetailView.onMounted`. 21 tests vitest (fuzzy + store + caps + persistence).
- **Raccourcis clavier globaux + cheatsheet (T1-15)** — Nouveau composable `composables/useHotkeys.js` (single-keys, séquences avec timeout 900 ms, ignore inputs/textareas/contenteditable, ignore combos modifiers). Bindings : `g d/m/i/a/p/s` pour navigation, `c` pour créer un monitor (deep-link `?create=true` watcher dans `MonitorsView`), `/` pour ouvrir la palette, `?` pour afficher la cheatsheet. Nouveau composant `HotkeysModal.vue` (sections Navigation/Actions, kbd formattés Mac/PC). i18n en/fr (`hotkeys.*`). 8 tests vitest.
- **Multi-select bulk actions enrichies (T1-12)** — Nouveau composant générique `components/shared/BulkActionBar.vue` (slot actions, count, deselect, ARIA `role=region`). Sur `MonitorsView` : conserve les actions enable/pause/export/delete déjà en place et ajoute deux dropdowns **"Move to group"** (option vide = ungroup) et **"Add tag"** alimentés par lazy-load des catalogues `groupsApi.list()` + `/tags/`. Sur `IncidentsView` : ajout d'une checkbox par incident sélectionnable (open + non-acked uniquement) et d'un bouton **"Acknowledge all"** qui dispatche un seul appel.
- **Quick ack / snooze depuis push mobile (T1-04)** — Nouveau champ `Incident.snooze_until` (datetime nullable, indexé) suppression temporaire des renotifies, distinct de l'ack open-ended. Migration `e7f8a9b0c1d2`. La pipeline `services/incident.py` skippe `incident_renotify` quand `snooze_until > now`. La résolution d'un incident efface le snooze. Dans le payload FCM, ajout de la liste `actions` (`ack`, `snooze_1h`, `snooze_4h`) consommée par `frontend/src/lib/pushNotifications.js` qui appelle les endpoints API au tap d'un bouton — fallback sur navigation vers le monitor pour les autres taps. 7 tests vitest, 3 tests pytest.
- **Silences programmés (T1-01)** — Nouveau modèle `AlertSilence` (`name`, `reason?`, `monitor_id?` (null = catch-all par owner), `starts_at`, `ends_at`) + migration `f8a9b0c1d2e3`. CRUD `/api/v1/silences/` (rate-limit 20–60/min). `services/alert.py` insère un guard `_is_silenced()` qui court-circuite `dispatch_alert` avant toute IO si un silence couvre l'incident pour le owner du canal cible. Nouvelle vue `SilencesView` accessible via la sidebar (icône BellOff) — formulaire avec presets de durée (15m/1h/4h/1d), badges Actif/Planifié/Passé, suppression confirmée. i18n en/fr (`silences.*`, `nav.silences`). 6 tests pytest. Note : pas de récurrence cron (réservé à un follow-up), pas de scoping par tag/team (idem).
- **CreateMonitor wizard 3 étapes (T1-14)** — Nouveau composant `components/monitors/CreateMonitorWizard.vue` qui remplace `CreateMonitorModal` par défaut sur `MonitorsView`. Étapes : (1) type (4 cartes : http, tcp, dns, heartbeat) → (2) cible (name + URL/host+port/slug + interval/timeout) → (3) review + sélection des canaux d'alerte. Indicateur visuel des étapes au sommet, body scrollable (`max-height: 72vh`, mobile 60vh). Boutons Back/Next/Submit avec validation par étape. Lien « Use the advanced form » qui bascule sur l'ancien `CreateMonitorModal` pour les types complexes (scenario, composite, keyword, json_path, smtp, udp, domain_expiry). Réutilise l'endpoint `POST /alerts/auto-rules/{monitor_id}` pour créer les règles d'alerte sélectionnées. i18n `wizard.*` + `create_monitor.{url,host,port,dns_hostname,interval,timeout,type_*_desc}`.

### API
- **`POST /monitors/bulk`** étendu — actions `set_group` (avec `target_group_id` optionnel, `null` = ungroup), `add_tags` et `remove_tags` (champ `tag_ids: list[uuid]`). Filtre d'accès inchangé : superadmin = tous, autres = monitors propres + via team RBAC. ON CONFLICT DO NOTHING pour `add_tags` (idempotent).
- **`POST /incidents/bulk-ack`** (rate-limit 20/min) — acknowledge en bulk plusieurs incidents ouverts non encore acked. Filtre d'accès via JOIN monitors. Skips silencieusement les résolus / déjà acked. 4 tests pytest backend, 5 tests frontend (BulkActionBar).
- **`POST /incidents/{id}/snooze`** (rate-limit 30/min) — body `{duration_minutes: int}` (5..1440). Suppression temporaire des renotifies. **`POST /incidents/{id}/unsnooze`** — efface manuellement. `IncidentOut` expose désormais `snooze_until: datetime | None`.
- **`/api/v1/silences/`** (T1-01) — `GET`, `POST`, `PATCH /{id}`, `DELETE /{id}`. Filtre d'accès `owner_id == current_user.id` (superadmin voit tous via `_get_owned_silence`).

### Migration
- `e7f8a9b0c1d2` : ajoute `incidents.snooze_until DATETIME(tz) NULL` + index — rétrocompatible.
- `f8a9b0c1d2e3` : crée la table `alert_silences` + 4 index (`owner_id`, `monitor_id`, `(starts_at, ends_at)`, `(owner_id, monitor_id)`) — rétrocompatible.

### Tests
- **Backend** : +14 tests pytest (5 bulk monitors `set_group`/`add_tags`/`remove_tags` + 1 bulk-ack incidents + 3 snooze + 6 silences).
- **Frontend** : +50 tests vitest (12 skeleton + 7 EmptyState + 9 useTour + 13 fuzzy + 8 commandPalette + 8 useHotkeys + 5 BulkActionBar + 7 pushNotifications). Suite à 161 tests verts.

---

## [1.4.0] - 2026-04-24

### Added
- **Filtres persistés + URL shareable (T1-11)** — Les vues `MonitorsView` et `IncidentsView` mémorisent leurs filtres (search, status, type, group, days) dans la querystring et dans `localStorage`. Résultat : F5 préserve le filtrage, et une URL copiée reproduit exactement le même filtrage chez le destinataire. Nouveau composable générique `composables/useFilterPreset.js` (8 tests vitest). Bouton "Clear filters" wipe les deux supports.
- **Timezone utilisateur (T1-13)** — Nouveau champ `User.timezone` (IANA, nullable). Par défaut `null` → le frontend utilise la TZ résolue du navigateur. Page Paramètres → "Préférences" → sélecteur de 45 fuseaux communs + option auto. Nouveau composable `useTimezone()` + composant `<FormattedDate>` (tooltip ISO absolu + nom TZ). Remplacement de `new Date(x).toLocaleString(locale)` par le helper tz-aware dans `IncidentsView` et `MonitorDetailView` (~12 occurrences). Validation IANA stricte côté backend (422 sur zone invalide).

### API
- **`PATCH /auth/me`** (rate-limited 30/min) — endpoint self-update limité à `full_name` + `timezone`. Les champs privilégiés (`is_superadmin`, `can_create_monitors`…) ne sont pas déclarés dans `UserSelfUpdate` et sont donc silencieusement ignorés (impossible d'escalader par ce canal).
- **`UserOut`** expose désormais `timezone: str | None`.

### Tests
- **Backend** : +6 tests `test_me_update_*` (timezone valide / invalide / null reset / full_name / escalation ignored / auth requise).
- **Frontend** : +8 tests timezone (composable + `<FormattedDate>`), +8 tests `useFilterPreset` (parse query, parse storage, priorités, serialize CSV, reset, prefix). 92 tests total côté frontend, 208 côté server.

### Migration
- `d6e7f8a9b0c1` : ajoute `users.timezone VARCHAR(64) NULL` — rétrocompatible, aucun backfill.

---

## [1.3.0] - 2026-04-23

### Added
- **Runbooks par monitor (T1-05)** — procédure de réponse à incident attachée à un moniteur. Nouveau champ `Monitor.runbook_enabled` (case à cocher, `false` par défaut) + `Monitor.runbook_markdown`. Onglet "Runbook" dans `MonitorDetailView` conditionnel et bloc inline dans `IncidentsView` pour les incidents ouverts uniquement. Option B : le décochage de `runbook_enabled` efface automatiquement le markdown côté serveur. Renderer markdown maison safe (échappement HTML + regex limités) — pas de nouvelle dépendance. Migration Alembic `z1a2b3c4d5e6`.

### Performance
- **`list_monitors` — sparkline accélérée ~2000×** : remplacement du `row_number() OVER (PARTITION BY monitor_id)` (7s sur 1.6M check_results) par un `JOIN LATERAL ... LIMIT 20` (3ms). Le window function scannait toute la table ; la LATERAL utilise l'index `(monitor_id, checked_at DESC)` pour 20 lookups index-only par moniteur. Fallback window-function conservé pour SQLite (tests).
- **Index BRIN sur `check_results.checked_at`** (migration `c5d6e7f8a9b0`) — débloque les agrégations temporelles globales qui faisaient un seq scan complet. P95 response_time 24h : 288ms → 75ms ; uptime bulk : 147ms → 30ms. BRIN est ~quelques KB, idéal pour colonnes time-ordered append-only.
- **Total** : chargement du Dashboard monitors passé de ~8s à <200ms.

### Fixed
- **Mixed Content sur redirects FastAPI** (`/probes` → `/probes/`) : `ProxyHeadersMiddleware` recevait la liste d'origines CORS (URLs) comme `trusted_hosts` alors qu'il attend des IPs client. Résultat : `X-Forwarded-Proto` ignoré, `Location` header en `http://` bloqué par le navigateur sous HTTPS. Corrigé avec `trusted_hosts="*"` (le container API n'est joignable que via nginx sur le réseau docker interne).
- **`GET /monitors/graph` 422** : la route `/{monitor_id}` déclarée avant `/graph` capturait la chaîne "graph" qui échouait au parsing UUID. Route `/graph` déplacée au-dessus de `/{monitor_id}` (FastAPI match par ordre de déclaration).
- **Menu latéral non-cliquable** : `NavLink.vue` utilisait `navigate(ev)` depuis le slot `<router-link custom>`. Avec `vue-router@5.0.4` (nouveau major installé par `npm ci`), cette fonction silencieusement reject. Remplacé par `useRouter().push(to)` — API stable.
- **Charts disparus (Availability, Response Time, Sparklines)** : `<apexchart>` était utilisé dans `MonitorDetailView` et `SparklineCell` mais jamais enregistré globalement. Vue 3 ne lève pas d'erreur pour un composant inconnu — il render silencieusement du vide. Enregistré globalement en `defineAsyncComponent` dans `main.js` (lazy-loaded, ~400KB hors du bundle initial).
- **CSP — Google Fonts bloquées** : ajout de `https://fonts.googleapis.com` dans `style-src` et `https://fonts.gstatic.com` dans `font-src` (`nginx/whatisup.conf`).
- **CSP — script inline bloqué** : le script d'init thème inline dans `index.html` est déplacé vers `public/theme-init.js` servi en externe. CSP reste strict (`script-src 'self'`, pas de `unsafe-inline`).
- **`manifest.json` — icônes manquantes** : retrait des entrées `icon-192.png` / `icon-512.png` qui référenşaient des fichiers absents du `public/`.
- **URL HTTP résiduelle dans localStorage** (`whatisup_server_url`) : `serverConfig.js` ignore désormais systématiquement la valeur stockée sur le build web (non-Capacitor) — l'URL relative `/api/v1` proxyée par nginx est toujours utilisée, évitant tout Mixed Content hérité d'une ancienne session mobile.

### Changed
- **Nginx : `Cache-Control: no-store, no-cache, must-revalidate` sur `/` et `/index.html`** — les futurs rebuilds prennent effet au prochain F5 sans hard-reload (le `index.html` lui-même n'est pas hashé ; seuls les assets JS/CSS le sont).

---

## [1.2.1] - 2026-04-18

Release patch qui débloque le pipeline : v1.2.0 était taggée mais les images Docker n'ont jamais été publiées sur GHCR (CI rouge).

### Fixed
- **Alembic — revision dupliquée** : `w8x9y0z1a2b3` existait dans deux fichiers (`add_data_retention_days.py` + `w8x9y0z1a2b3_status_page_customization.py`), cassant `alembic upgrade head` avec *Multiple head revisions*. La migration retention est renommée `y0z1a2b3c4d5` et chaînée après `x9y0z1a2b3c4_webhook_template`.
- **`db.refresh` après mutation** : dans 5 endpoints, `await db.refresh(obj)` était appelé juste après avoir muté un champ, ce qui réécrasait la modification en la rechargeant depuis la DB avant flush. Remplacé par `await db.flush()` dans :
  - `POST /onboarding/complete` — `onboarding_completed_at` n'était pas persisté (crash `NoneType.isoformat`)
  - `PATCH /teams/{id}` — le nouveau nom n'était pas sauvegardé
  - `POST /incidents/{id}/ack` et `/unack` — `acked_at` / `acked_by_id` retournaient `null`
- **`POST /auth/register`** : endpoint absent (renvoyait 404) bien que documenté comme désactivé ; rajouté, renvoie toujours 403 (invite-only).
- **`DELETE /alerts/channels/{id}`** : renvoyait 403 quand l'appelant n'avait pas accès au canal d'un autre utilisateur → fuite d'existence. Renvoie maintenant 404.

### Changed
- **Gates de couverture CI** alignés sur le plancher actuel : serveur 60 → 50 %, probe 50 → 35 %. À remonter au fil des tests ajoutés.
- **Probe `[dev]`** : ajout de `pytest-cov` (manquant alors que CI invoquait `--cov`).

### Chore
- Ruff I001 : 7 imports réordonnés automatiquement (checkers probe + `test_oidc.py`).

---

## [1.2.0] - 2026-04-18

### Security — critical
- **Server port bound to 127.0.0.1** in `docker-compose.yml` (was `0.0.0.0:8000`, bypassing TLS at the reverse proxy).
- **SSRF protection on TCP / UDP / SMTP / DNS checkers** (previously only HTTP checker validated outbound hosts).
- **Async `getaddrinfo`** for webhook URL validation and OIDC discovery — no more event-loop blocking on DNS.
- **Reporter rejects 4xx as permanent errors** (`probe/reporter.py`) — was silently treating them as success.
- **XSS hardening** — removed `v-html` binding on translations in `SettingsView.vue`.
- **Redis healthcheck** no longer exposes the password in the `docker ps` process list.

### Security — high
- **Probe rejects empty `PROBE_API_KEY`** at startup (was silently booting with empty auth).
- **Platform detection via `Capacitor.getPlatform()`** (was relying on brittle user-agent sniffing).

### Added
- **Rich public status pages** — logo, title, description, accent color and custom CSS per `MonitorGroup`.
- **Webhook templates with `$variable` substitution** — reusable payload templates for alert webhooks.
- **Monitor config export / import** (JSON) — round-trip one or many monitors across installs.
- **Maintenance UX** — create/edit modal, calendar view, quick-schedule from the monitor detail page.
- **Interactive dependency graph** — SVG force-directed layout, draggable nodes, colored by current status.
- **Custom metrics dashboard** — charts and summary stats per monitor.
- **Per-monitor `data_retention_days` override** — supersedes the global retention setting.
- **Pagination on `list_monitors`** — `limit` / `offset` query params + `X-Total-Count` response header.

### Changed
- **Backend**: removed double-commit in ~17 endpoints, standardized postmortem strings to English, multi-tenancy applied to `list_events` and `delete_channel`.
- **Uptime cache** — invalidated via `SCAN` pattern instead of targeted keys (previously leaked stale entries).
- **Probe**: clean shutdown via `asyncio.Event` (not `loop.stop()`), bounded DNS cache (max 1000 entries), HTTP client init protected by `asyncio.Lock`, shared `BROWSER_LAUNCH_ARGS`, SMTP `writer.wait_closed()` + EHLO line limit.
- **Docker / CI**: Python 3.12 (stable) in all Dockerfiles, Node 22 LTS for frontend, multi-stage probe Dockerfile, `HEALTHCHECK` on server and frontend, release workflow gated on CI, conditional `latest` tag for pre-releases, scoped permissions, coverage thresholds (server ≥60%, probe ≥50%).
- **Frontend**: native `alert()` → `useToast()` everywhere, token refresh singleton lock, ApexCharts lazy-loaded, `BaseModal` gains `role=dialog` / `aria-modal` / Esc handler, `ToastContainer` gains `role=alert` / `aria-live`, service worker skipped on Capacitor native builds.
- **i18n**: ~100+ new translation keys (admin, OIDC, public_page, group_detail, create_monitor, maintenance, graph, metrics), French accents fixed in the teams section.

### Removed
- **Dead `/auth/register` endpoint** (never wired, superseded by invite flow).

### Fixed
- **`CompositeMonitorMember.member_id`** reference in cycle detection (wrong column name caused false negatives).

### Tests (+25)
- Monitor: bulk actions, dependencies, cycle detection, annotations, SLO.
- OIDC: disabled state, invalid callback.
- Incident correlation: group, flapping, `process_check_result`.
- Probe: config validation, SSRF host validation.

---

## [1.1.2] - 2026-04-14

### Fixed
- **Android version stuck on "1.0"** — `frontend/android/app/build.gradle` had `versionCode 1` / `versionName "1.0"` hardcoded since the project inception, so every installed APK (v1.0.0, v1.1.0, v1.1.1…) appeared as "1.0" in Android's **Settings → Apps → WhatIsUp** screen. Users had no reliable way to confirm which release was actually installed on their phone, which was misdiagnosed as "the APK did not install" when a feature (e.g. biometric unlock) did not appear.
- **Stale in-app About version** — `SettingsView.vue` hardcoded `WhatIsUp v0.1.0` and `frontend/src/lib/appVersion.js` exported `v0.2.1-mobile`. Both are now driven from a single Vite compile-time define (`__APP_VERSION__`) sourced from `frontend/package.json`, so bumping the version is a one-line change.

### Changed
- **mobile-release workflow** now patches `build.gradle` before each Android build so `versionName` always matches `frontend/package.json#version`, and `versionCode` is set to the GitHub Actions run number (monotonically increasing across builds — required by the Play Store).
- **Vite config** exposes `__APP_VERSION__` as a compile-time constant. The helper `lib/appVersion.js` now reads from it, consumed by both the sidebar footer and the Settings About card.

---

## [1.1.1] - 2026-04-14

### Added
- **Biometric unlock on mobile** (#95) — Capacitor native builds can now skip the login screen on subsequent launches using Face ID / Touch ID / Android BiometricPrompt. The refresh token is stored in the device secure storage (iOS Keychain / Android Keystore-backed SharedPreferences) and only released after a successful biometric check. Opt-in from **Settings → Biometric unlock**. New deps: `@capgo/capacitor-native-biometric`, `capacitor-secure-storage-plugin`.
- **FCM google-services.json injected in CI** (#98) — mobile-release workflow now decodes the `GOOGLE_SERVICES_JSON_BASE64` repo secret into `frontend/android/app/google-services.json` before `./gradlew assemble`, so native push notifications actually work in CI-built APKs. Graceful fallback when the secret is absent (warning in the workflow log, APK still builds).

### Fixed
- **Short session logout bug** (#94) — `authStore.init()` was calling `logout()` whenever the stored access token had expired, wiping the refresh token and revoking the session server-side. Now it rotates the access token via `/auth/refresh` on boot and only logs out when the refresh also fails, restoring the full 7-day refresh lifetime across app restarts.
- **Mobile push "stuck on loading"** (#98) — the 30 s FCM timeout has been reduced to 12 s, reason renamed `fcm_unavailable` with a clearer message, and the UI maps every FCM failure mode to a single user-facing i18n string.
- **CodeQL warnings #14/#15** (#93) — `tests/test_fcm.py` URL assertions now use exact hostname comparison via `urllib.parse.urlparse` instead of substring `in` checks, silencing `py/incomplete-url-substring-sanitization`.
- **Health scoring test drift** (#97) — 5 pre-existing failures in `tests/monitors.test.js` were tracking a legacy algorithm. Rewrote them against the current rt/p95 ratio formula, 66/66 frontend tests now pass.

### Documentation
- **Signal alerts setup** (PR #92 follow-up in README) — dedicated section explaining that WhatIsUp relies on [bbernhard/signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) as a gateway, with a docker-compose snippet, the number-registration flow and the channel configuration walkthrough.

---

## [1.1.0] - 2026-04-14

### Added
- **Alert matrix v2 — cards layout** (`frontend/src/components/monitors/AlertMatrix.vue` + `alert-matrix/*.vue`) — the per-monitor alerting panel is now a stack of collapsible cards instead of a dense table: one card per active condition, coloured channel chips, repliable "Advanced" section with threshold / min-duration / renotify / schedule, and a condition picker that lets you add multiple rules in one click. Per-condition "How it works" help explains each condition's semantics in plain language (z-score window, SSL warn-days, baseline factor…).
- **One-click alerting templates** — `GET /api/v1/alerts/matrix-templates/{check_type}` returns admin-managed presets; three built-in templates per check type (`standard`, `strict / paging`, `low noise`) are seeded at install time. Superadmins can create, edit and delete their own templates from a dedicated section in the **Alerts** page (`AlertTemplatesSection.vue`).
- **Alerting impact preview** — `POST /api/v1/alerts/monitors/{id}/matrix/preview` replays the proposed rule set against the last 30 days of `CheckResult` / `Incident` data and returns a would-fire count per condition. The count appears as a coloured badge (`≈ N / 30j`) on each condition card, refreshes debounced as you edit, and uses a statistical tail estimate (`0.5 · erfc(z/√2)`) for `anomaly_detection`.
- **Monitor tags + RBAC** — new `Tag` model with per-user `UserTagPermission` (view / edit / admin). Monitors carry a `tags` many-to-many relationship, `TagChips.vue` in the monitor header lets you attach/detach tags inline, and `AlertRule.tag_selector` (migration `t5u6v7w8x9y0`) allows a single alert rule to target every monitor carrying a given tag.
- **New backend surface**:
  - `server/whatisup/models/tag.py`, `schemas/tag.py`, `api/v1/tags.py` — CRUD for tags and permissions
  - `server/whatisup/models/alert_matrix_template.py`, `schemas/alert_matrix_template.py`, `services/alert_matrix_templates.py` — DB-backed templates with seeded system presets
  - `server/whatisup/services/alert_matrix_preview.py` — historical replay for the impact preview
  - `server/whatisup/api/v1/alerts.py` — `/matrix-templates` CRUD (superadmin-only for write), `/monitors/{id}/matrix/preview`
- **New migrations**:
  - `t5u6v7w8x9y0_alert_tag_selector.py` — adds `alert_rules.tag_selector` JSONB column
  - `u6v7w8x9y0z1_drop_uptime_below.py` — removes the legacy `uptime_below` condition (see Removed)
  - `v7w8x9y0z1a2_alert_matrix_templates.py` — creates `alert_matrix_templates` table and seeds system presets
- **Shared frontend constants** — `frontend/src/constants/alertMatrix.js` centralises `CHECK_TYPES`, `CONDITIONS_BY_TYPE`, `THRESHOLD_CONDITIONS` (previously duplicated across 3 components).
- **Frontend tests** — `frontend/tests/alert_matrix.test.js` (14 tests covering `ChannelChip`, `AddRuleMenu`, `ConditionCard`, `TemplatePicker` and the `AlertMatrix` integration incl. preview flow).
- **Server tests** — `server/tests/test_tags.py`.

### Changed
- **Monitor detail page** — `MonitorDetailView.vue` now renders the new card-based alert matrix and surfaces `TagChips` in the header for inline tag edition.
- **Alerts page** — `AlertsView.vue` gains a new **Alerting templates** section, visible to superadmins only, for managing DB-backed templates (create / edit / delete, with read-only system templates marked `Built-in`).
- **Schemas** — `AlertMatrixRow` now inherits from `AlertRuleUpdate` so constraints stay in sync between the per-rule and matrix endpoints.

### Removed
- **`uptime_below` alert condition** — the handler in `services/incident.py` had never actually evaluated the rolling uptime percentage against its threshold; it was a confusing duplicate of `any_down`. Migration `u6v7w8x9y0z1` deletes any existing rules using it before the Python enum is trimmed. Removed from the matrix UI, the legacy `AlertsView` rule form, and all i18n strings.

### Fixed
- **Session leak in `AlertMatrix.vue`** — the debounced impact-preview timer is now cleared on `onUnmounted`.
- **Redundant preview call** — `load()` + explicit `refreshPreview()` on mount fired two preview requests within 500 ms; the explicit call was removed, the deep `watch` on `activeRows` now handles it.

### Performance
- **Impact preview** — the `up_rt_samples()` count used by the `anomaly_detection` tail estimate is memoised per preview call, eliminating a repeat `COUNT(*)` when multiple rules in the same matrix need it.

---

## [1.0.3] - 2026-04-06

### Security
- **Code-scanning #7, #8** — `hashlib.sha256()` in probe/user API key cache now uses `usedforsecurity=False` to clarify non-cryptographic usage and silence CodeQL weak-hashing alert
- **Code-scanning #6** — browser extension `_esc()` replaced with `CSS.escape()` for CSS selectors and proper XPath escaping to prevent incomplete sanitization

### Fixed
- **CI lint (ruff)** — fixed `E501` line-too-long in `init_data.py` that blocked all Dependabot PR merges

### Dependencies
- **Frontend** — vite 8.0.1 → 8.0.5 (3 high CVEs: path traversal, `server.fs.deny` bypass, WebSocket file read), vitest 3.2.4 → 4.1.2, jsdom 26.1.0 → 29.0.1
- **Server** — uvicorn ≥0.32 <0.43 → <0.44, pywebpush <2 → <3
- **Probe** — psutil <7 → <8
- **CI** — actions/checkout 4 → 6, actions/setup-python 5 → 6, docker/setup-buildx-action 3 → 4, docker/metadata-action 5 → 6, docker/build-push-action 6 → 7

---

## [1.0.2] - 2026-04-02

### Fixed
- **Alembic migration chain** — auto-generated migration `283efc2c973a` (probe groups) erroneously dropped `maintenance_windows` and `audit_logs` tables, breaking `alembic upgrade head` on fresh databases since v1.0.0
- **Incident model sync** — `first_failure_at`, `acked_at`, `acked_by_id` fields added to `Incident` model to match service code; `DigestWindow` model and migration committed
- **Probe SSRF in tests** — SSRF DNS validation now bypassed in probe test suite (fake hostnames don't resolve in CI)
- **Ruff lint** — 19 lint errors fixed across server and probe (unused imports, line length, import ordering)

### Added
- **Alembic migration `o1p2q3r4s5t6`** — adds `dns_nameservers` JSON column to `monitors`
- **Alembic migration `p1q2r3s4t5u6`** — incident acknowledgment (`acked_at`, `acked_by_id`), atomic incident creation (partial unique index), SLA metric (`first_failure_at`), GIN index on `affected_probe_ids`, `digest_windows` table for persistent alert digests

---

## [1.0.1] - 2026-04-02

### Security

#### Critical
- **ReDoS protection** — `body_regex` and header regex patterns now execute with a 5-second timeout via thread executor, preventing catastrophic backtracking from blocking the probe
- **SSRF DNS rebinding** — DNS resolution failures (`gaierror`) now raise errors instead of silently passing in both probe SSRF validation and OIDC discovery; DNS timeout returns explicit error
- **Authorization bypass** — `AlertRule` list/create and `Status API` endpoints now use `build_access_filter()` / `check_resource_access()` with full team RBAC support instead of bare `owner_id` checks
- **Playwright sandbox** — removed `--no-sandbox` flag from all Chromium launches (pool, standalone, reconnect); Docker containers should use `--cap-add=SYS_ADMIN` or seccomp profiles instead

#### High
- **Renotify pipeline** — changed `return` to `continue` in renotify loop so a single incident failure no longer blocks renotification for all remaining open incidents
- **Silent exception swallowing** — added logging to bare `except` clauses in WebSocket broadcast, health endpoint, and `asyncio.create_task` callback for deferred pattern updates
- **WebSocket subscriber** — replaced fixed 5-second retry with exponential backoff (2s → 60s) to prevent connection storms on Redis failure
- **Web push N+1** — batch `DELETE` for stale subscriptions instead of one query per expired subscription

#### Medium
- **Nginx hardening** — added `Content-Security-Policy`, `HSTS preload`, `server_tokens off`, API rate limiting (`20r/s burst=40`), `X-Permitted-Cross-Domain-Policies: none`
- **DNS checker** — custom nameservers are now validated against private/loopback/link-local IP ranges; invalid IPs are rejected
- **JSON path injection** — added max depth (20 levels) and blocked dunder (`__`) attribute access in `_resolve_json_path`
- **Scenario screenshots** — reduced base64 cap from 200 KB to 50 KB; extracted variable values capped at 10 KB
- **OIDC callback** — URL fragment cleared after token extraction (`history.replaceState`) to prevent leakage via browser history
- **Login redirect** — redirect validation now uses `new URL().origin` same-origin check instead of simple prefix test
- **JWT expiry** — frontend `auth.init()` now decodes and checks token expiration before making API calls
- **Console logging** — all `console.error()` calls in production views gated behind `import.meta.env.DEV`
- **Service Worker** — notification click navigation validates same-origin before `client.navigate()`
- **Trusted hosts** — `ProxyHeadersMiddleware` now uses configured origins in production instead of wildcard `*`
- **CI permissions** — GitHub Actions CI workflow restricted to `permissions: contents: read`
- **Probe resources** — standalone probe `docker-compose.probe.yml` now enforces `memory: 512m` and `cpus: 2.0` limits

### Fixed
- **Starlette middleware crash** — `MutableHeaders.pop()` replaced with `del` check to fix `AttributeError` on newer Starlette versions

---

## [1.0.0] - 2026-03-29

### Added

#### Plugin architecture — extensible check types and alert channels
- **Checker plugin system** — `BaseChecker` abstract class with auto-discovery registry; each check type is now an independent module in `probe/whatisup_probe/checkers/` (http, tcp, udp, dns, smtp, ping, domain_expiry, scenario)
- **Alert channel plugin system** — `BaseAlertChannel` abstract class with registry; each channel is a module in `server/whatisup/services/channels/` (email, webhook, telegram, slack, pagerduty, opsgenie)
- Adding a new check type or alert channel requires only creating a file with a `setup(register)` function — no core code changes

#### Teams and role-based access control (RBAC)
- **Team model** — create teams with name/slug, invite members, assign roles
- **4 team roles** — `owner` > `admin` > `editor` > `viewer` with hierarchical permissions
- **Team-scoped resources** — monitors, groups, alert channels, maintenance windows, and templates can be assigned to a team via `team_id`
- **Centralized access control** — `check_resource_access()`, `build_access_filter()`, `get_user_team_ids()` in `deps.py` replace duplicated `owner_id` checks across 11 API files
- **Full API** — `POST/GET/PATCH/DELETE /api/v1/teams`, `GET/POST/PATCH/DELETE /api/v1/teams/{id}/members`
- **Backward-compatible** — `team_id=NULL` preserves single-user ownership; existing installations unaffected

#### Light theme and accessibility
- **Light theme** — complete `:root[data-theme="light"]` with inverted design tokens, badge/button/skeleton overrides
- **Theme toggle** — Sun/Moon button in top bar and login page; persisted to `localStorage`; auto-detected from `prefers-color-scheme` on first visit
- **Flash prevention** — inline script in `index.html` applies theme before first paint
- **Reduced motion** — `prefers-reduced-motion` media query disables all animations (pulse, shimmer, transitions)
- **Skip-to-content** — keyboard-accessible skip link; `aria-label` on navigation, overlays, and toggles

#### Onboarding wizard
- **4-step wizard** — Welcome (display name), First Monitor (3 presets: Website/Server/API), First Alert (email setup with auto-rules), Done (summary)
- **Backend** — `User.onboarding_completed_at` field; `GET /api/v1/onboarding/status` and `POST /api/v1/onboarding/complete` endpoints
- **Dashboard integration** — wizard shown instead of dashboard when `onboarding_completed=false` and monitor count is 0; dismissed permanently after completion
- **i18n** — full English and French translations (30 keys)

#### Infrastructure-as-Code (declarative configuration API)
- **Export** — `GET /api/v1/config` returns full monitoring config as JSON (groups, monitors, channels, rules); secrets redacted
- **Import** — `PUT /api/v1/config` performs declarative diff and converges to desired state (create/update/delete)
- **Dry run** — `?dry_run=true` previews the plan without applying changes
- **Prune control** — `?prune=false` prevents deletion of resources not in config
- **Name-based matching** — resources matched by name (not UUID) for portability and idempotence
- **Cross-references** — monitors reference groups by name, rules reference monitors and channels by name

#### API stability commitment
- `/api/v1/` endpoints are now considered stable; breaking changes will use `/api/v2/` with 6-month deprecation
- Version aligned across all components: server, probe, frontend, config → `1.0.0`
- `UPGRADING.md` migration guide from v0.x to v1.0

#### Test suite
- **Server** — 140 tests (from 107): channel registry, teams CRUD/RBAC, onboarding flow, config export/import/dry_run/prune
- **Probe** — 24 tests (from 15): checker registry, type aliases, fallback, keyword/JSON path checks
- **Frontend** — 51 tests (new): Vitest + jsdom; monitors store (health scoring, enrich, sparkline, flapping), auth store (login/logout/init), composables (useToast timers, useConfirm promises), urlBase64ToUint8Array
- **Test infrastructure** — server conftest uses savepoint pattern for per-test isolation; probe conftest forces `CENTRAL_API_URL`

### Changed
- `checker.py` (1567 lines) replaced by `checkers/` package (8 modules + registry); backward-compat shim preserved
- `alert.py` reduced from ~1064 to ~560 lines; `test_channel()` and `dispatch_alert()` use channel registry
- Monitor list, group list, alert channel list, maintenance window endpoints now team-aware (OR filter: `owner_id` + `team_id`)
- `_get_monitor_or_404` and `_get_group_or_404` use centralized `check_resource_access()`

### Database migrations

| Revision | Description |
|----------|-------------|
| `m1n2o3p4q5r6` | Add `teams`, `team_memberships` tables; add `team_id` to monitors, groups, channels, maintenance, templates |
| `n1o2p3q4r5s6` | Add `onboarding_completed_at` to users |

---

## [0.12.1] - 2026-03-28

### Fixed

#### Correlation & incident engine
- **Heartbeat alerts** — incident creation now fires `incident_opened` / `incident_resolved` alerts through all configured channels (previously silent)
- **Alert deduplication** — checks for recent AlertEvent (same incident + channel, <60s) before dispatch; prevents duplicates after server restart
- **Transitive dependency suppression** — follows `MonitorDependency` chain recursively up to 5 hops (previously 1-hop only); A→B→C now correctly suppresses C when A is down
- **Per-incident storm protection** — alert storm counter now scoped per-incident instead of globally per-rule; prevents false throttling of legitimate alerts on separate incidents
- **Sliding digest window** — digest flush times aligned to consistent time boundaries instead of drifting from first event; eliminates alert gaps between windows
- **Maintenance audit trail** — incidents are now created (with `dependency_suppressed=True`) during maintenance windows instead of being silently dropped; provides audit trail while still suppressing alerts
- **Composite cycle detection** — adding a member to a composite monitor now validates the DAG; raises HTTP 400 if the addition would create a circular dependency

#### Anomaly detection
- **Wider hour bucket** — z-score baseline window widened from ±2h to ±3h, reducing timezone-related false positives for monitors checked from different regions

#### Performance
- **Flapping index** — new `ix_check_results_monitor_checked(monitor_id, checked_at DESC)` index; eliminates O(n) full-table scan on flapping detection queries
- **Async correlation patterns** — O(n²) pattern upserts deferred to background task with batched INSERT; no longer blocks the incident pipeline
- **Probe screenshot compression** — JPEG quality reduced to 30 + 200KB base64 cap; ~70% payload reduction
- **Probe result batching** — queue-based reporter flushes every 5s instead of individual POST per result; ~80% reduction in HTTP requests
- **Probe DNS caching** — 60-second TTL cache eliminates 2 of 3 redundant DNS lookups per HTTP check
- **Web Vitals** — collection timeout reduced from 200ms to 50ms per navigate step
- **Adaptive scenario throttling** — scenarios skipped when probe RAM >85%; prevents OOM on constrained machines
- **Hard timeout tuning** — scenario overhead reduced from 30s to 15s for faster failure detection
- **kill_stale_chromium** — now filters by process age (>120s) to avoid killing active browser instances

### Database migrations

| Revision | Description |
|----------|-------------|
| `l2m3n4o5p6q7` | Add index `ix_check_results_monitor_checked(monitor_id, checked_at DESC)` |

---

## [0.12.0] - 2026-03-28

### Added

#### UX — Sparkline response time trends
- **Sparkline charts** on MonitorsView — mini area chart (ApexCharts, 30px) showing the last 20 response times per monitor, in both table and board views
- Backend batch query using `ROW_NUMBER()` window function for efficient data loading
- Real-time sparkline updates via WebSocket (`applyCheckResult` appends new values)

#### UX — Global command palette (Ctrl+K)
- **Command palette** — press `Ctrl+K` / `Cmd+K` from anywhere to search monitors, navigate to any page, or trigger actions
- Keyboard navigation with arrow keys, Enter to activate, Escape to close
- Results grouped by section: Monitors (from store), Navigation (9 routes), Actions (New Monitor)

#### UX — Monitor cloning
- **"Duplicate" button** on monitor detail page — pre-fills the create modal with the current monitor's configuration
- Strips identity fields, prefixes name with "Copy of ", handles all check types including scenario variables

#### UX — Uptime badge embeddable
- **SVG uptime badge** endpoint — `GET /api/v1/public/badge/{slug}/{monitor_name}` returns a shields.io-style badge with 24h uptime percentage
- Color-coded: green (≥99%), yellow (≥95%), orange (≥90%), red (<90%)
- 60-second cache; one-click copy of badge URL on public status pages

#### UX — Incident overlay on response time chart
- **Incident ranges** overlaid as red semi-transparent zones on the ApexCharts response time graph in monitor detail
- Shows ongoing incidents as open-ended ranges extending to "now"

#### Automation — Enriched webhook payload
- **Structured webhook payload** — `event_type` (`incident.opened` / `incident.resolved`), `monitor` object (id, name, url, check_type), `incident` object (id, started_at, resolved_at, scope)
- **`X-WhatIsUp-Event` header** — enables webhook receivers to route by event type
- Backward compatible: all legacy payload fields preserved

#### Automation — Scheduled SLA reports
- **Weekly / monthly SLA reports** per monitor group — HTML email with uptime %, colour-coded per monitor, auto-generated at 08:00 UTC
- Configurable schedule (`weekly` / `monthly`) and recipient list per group
- Background task with hourly check; uses existing SMTP infrastructure

#### Reliability — Auto-pause after consecutive failures
- **`auto_pause_after` field** on monitors — automatically pauses the monitor after N consecutive failures across all probes
- Prevents alert fatigue on confirmed-broken services; configurable 2–100, default disabled
- Logged as `auto_pause_triggered` audit event

#### Public — Status page customization
- **Custom logo URL**, **accent colour**, and **announcement banner** per monitor group
- Accent colour applied as CSS variable on public status page badges/borders
- Dismissible announcement banner shown above monitor list
- Configuration UI in group detail view

#### Analytics — Response time percentile dashboard
- **P50 / P95 / P99** time-series chart on monitor detail — hourly buckets via PostgreSQL `percentile_cont`
- Multi-line ApexCharts graph with colour-coded percentile lines (green/yellow/red)
- Configurable time window (1h–30 days), matching the existing chart window selector

### Database migrations

| Revision | Description |
|----------|-------------|
| `k1l2m3n4o5p6` | Add `auto_pause_after` to `monitors`; add `custom_logo_url`, `accent_color`, `announcement_banner`, `report_schedule`, `report_emails` to `monitor_groups` |

---

## [0.11.0] - 2026-03-28

### Added

#### Smart alerts & advanced correlations
- **Intuitive alert rules** — simplified rule creation with natural-language condition builder (any_down, all_down, performance, ssl_expiry, domain_expiry)
- **Auto-rules** — monitors automatically get default alert rules on creation when alert channels exist; batch-apply auto-rules to existing monitors from the alerts page
- **Multi-layer correlation engine** — dependency-based suppression, common-cause grouping (shared failing probes within 90 s), and flapping detection work together to reduce alert noise
- **Threshold suggestions** — the backend analyses 7-day P95 response times and suggests threshold-based alert rules for monitors that lack performance alerting
- **Alert rule simulation** — dry-run endpoint (`POST /alerts/rules/simulate`) previews which monitors a rule would match before saving

#### Frontend — UI polish & design system
- **BaseModal component** — unified modal system replacing 7 different inline modal implementations; consistent backdrop blur, animations, and styling via CSS variables
- **Page transitions** — smooth fade + slide animations between routes (`<Transition name="page">`)
- **Stagger animations** — list items appear progressively (monitors table, board cards, probe cards, alert channels)
- **Enhanced empty states** — icon backgrounds, clearer titles, and call-to-action buttons across all views
- **Skeleton loaders** — added to AlertsView and ProbesView for consistent loading experience
- **Card shadows** — `--shadow-card` / `--shadow-card-hover` design tokens; depth on all `.card` elements
- **Table hover** — increased to 4% opacity + blue left-border accent on hovered rows
- **Button focus rings** — `focus-visible` glow on all button variants for accessibility
- **Input states** — `.input-error`, `.input-success`, `.input:disabled` CSS classes
- **LoginView refactored** — fully rebuilt with CSS variables (zero hardcoded colours), BEM scoped styles

### Security

#### CRITICAL fixes
- **SSRF in OIDC discovery** — `_oidc_discover()` now validates issuer URL against private/loopback IP ranges before HTTP fetch
- **SSRF in probe HTTP checker** — new `_validate_url_ssrf()` blocks requests to internal IPs; also validates final URL after redirects
- **Open redirect after login** — `LoginView` validates redirect parameter starts with `/` and not `//`

#### HIGH fixes
- **Mass assignment** — all Create/Update Pydantic schemas now use `ConfigDict(extra="forbid")` to reject unexpected fields
- **Rate limiting** — added `@limiter.limit("30/minute")` to 17 previously unprotected PATCH/DELETE endpoints; `60/minute` on public status pages
- **bcrypt blocking** — `hash_password_async()` / `verify_password_async()` via `asyncio.to_thread()` prevent event loop starvation
- **Secrets in error messages** — OIDC errors log `error_type` instead of full exception (which could contain tokens); Telegram bot token no longer leaked in HTTP error detail
- **Probe ReDoS** — body regex validation now rejects responses > 5 MB before `re.search()`; catches `re.error`
- **Probe TLS validation** — removed `ignore_https_errors=True` from Playwright browser contexts
- **Probe scenario SSRF** — `navigate` steps now validate target URL against internal IP ranges

#### MEDIUM fixes
- **Refresh token hash** — Redis key uses `SHA-256[:32]` of the full token instead of last 12 characters
- **OIDC callback encoding** — `_fail()` redirect now uses `urllib.parse.urlencode()` to prevent parameter injection
- **Broad exception handling** — `security.py` `decrypt_channel_config` / `decrypt_scenario_variables` now catch only `InvalidToken` instead of `Exception`
- **DNS timeout** — probe DNS pre-resolution wrapped in `asyncio.wait_for(timeout=5.0)`
- **Browser cleanup** — scenario checker separates expected errors from unexpected; both paths properly close browser

### Fixed

- **WebSocket leak** — `PublicPageView` now closes WebSocket in `onUnmounted`
- **Leaflet map leak** — `MonitorDetailView` calls `map.remove()` in `onUnmounted`
- **Empty catch blocks** — `LoginView` OIDC config fetch now has explanatory comment instead of bare `catch {}`

---

## [0.10.0] - 2026-03-27

### Added

#### Frontend — Global incident timeline
- New **Incidents** view (`/incidents`) listing all incidents across all monitors, with filters by status (All / Open / Resolved) and time window (7 / 30 / 90 days)
- Nav link "Incidents" (clock icon) added to the sidebar, between Incident Groups and Settings
- Each row links to the corresponding monitor detail page; shows check type badge, duration, and open/resolved status

#### Frontend — 365-day uptime heatmap
- New `UptimeHeatmap` component: GitHub-style calendar heatmap showing one year of daily uptime on the monitor detail page
- Color grades: `up` (≥99%), `high` (≥95%), `mid` (≥80%), `low` (>0%), `down` (0%)
- Skeleton loader during fetch, inline error on failure, month labels, legend, data-count indicator
- Positioned just below the stat cards in the Availability tab — visible on all monitor types

#### Frontend — MonitorsView redesign
- **Card / list view toggle** (grid icon / list icon) — card view shows a compact status tile per monitor
- **Search** bar with keyboard shortcut focus
- **Sortable columns** (name, uptime 24h, response time) with directional arrows
- **Pagination** (50 per page) — list and card views both paginated
- **Bulk select** — checkboxes + Select All / Deselect All; bulk-delete selected monitors

#### Frontend — Dashboard offline probes card
- New card in the dashboard right column showing any probe that hasn't sent a heartbeat in the last 5 minutes
- Displays probe name, location, and last-seen timestamp; only rendered when at least one probe is offline

#### Frontend — DNS monitor improvements
- Current resolved values banner on the Availability tab: shows record type badge and the current IP / CNAME / TXT values as tags
- DNS changelog now correctly diffs `dns_resolved_values` (the actual resolved IPs/names) instead of `final_url` (which is always `null` for DNS checks)

#### Backend — Status summary API
- `GET /api/v1/status/summary`: machine-readable overall health endpoint returning `operational / degraded / major_outage` plus per-monitor status, last check time, and uptime_24h; rate-limited at 120/min; designed for CI/CD pipelines and external integrations

#### Backend — Global incident list API
- `GET /api/v1/incidents/` (new module `incidents_list.py`): cross-monitor incident list with `days` and `resolved` filters; returns `monitor_name`, `monitor_check_type`, `started_at`, `resolved_at`, `duration_seconds`, `is_resolved`
- `IncidentOut` schema extended with `monitor_check_type`, `started_at`, `is_resolved` fields

### Fixed

#### Probe — scenario checks no longer freeze after a Playwright hang
- **Root cause**: if a Playwright browser launch hung indefinitely, `perform_check` never returned; APScheduler kept the job slot marked as "running" (1/1 instances), causing every subsequent scheduled firing to be skipped with *"maximum number of running instances reached"*
- **Fix**: `asyncio.wait_for(perform_check(...), timeout=timeout_seconds + 60)` in `_run_check`; on `TimeoutError` the job logs `check_hard_timeout`, calls `kill_stale_chromium()`, and exits cleanly — freeing the slot for the next run

#### Frontend — MonitorDetailView crash on load (TDZ ReferenceError)
- `watch(chartWindow, loadResults)` was placed ~230 lines before `const chartWindow = ref(24)`, hitting JavaScript's Temporal Dead Zone and throwing `ReferenceError: Cannot access 'chartWindow' before initialization` at setup time — preventing any data from loading
- Moved the `watch` call to immediately after the `chartWindow` declaration

---

## [0.9.1] - 2026-03-25

### Fixed

#### Frontend
- **Auth redirect on expired session**: when no refresh token was present, a 401 response silently rejected the request instead of redirecting to `/login`; the redirect now fires in all 401 cases (no refresh token, or refresh token rejected by the server)

#### Probe — Playwright / scenario reliability
- **Zombie Chromium cleanup**: `kill_stale_chromium()` is called once at probe startup; kills any leftover `chrome-headless-shell` processes from a previous crash so they cannot block new browser launches
- **Concurrent Playwright cap**: new `max_concurrent_scenarios` config (default: `2`) limits how many Chromium instances run simultaneously, independently of `max_concurrent_checks`; prevents OOM-kills on low-memory probe machines
- **`--disable-gpu` flag**: added to the Chromium launch args; reduces GPU-related crashes in headless Docker containers

---

## [0.9.0] - 2026-03-24

### Added

#### Web Push notifications (PWA)
- Push notifications via the Web Push API (VAPID) — browser receives alerts even with the tab closed
- New `WebPushSubscription` model and `web_push_subscriptions` table (migration `f0a1b2c3d4e5`)
- Backend service `services/web_push.py`: VAPID signing via `pywebpush`, async dispatch wrapped in `asyncio.to_thread`, automatic removal of expired subscriptions (HTTP 410)
- REST API `GET|POST|DELETE /api/v1/push/subscription` + `GET /api/v1/push/vapid-public-key` + `POST /api/v1/push/subscription/test`
- Push fired automatically on `incident_opened` and `incident_resolved` for the monitor owner (hooked in `services/incident.py`, independent of AlertRules)
- Frontend service worker `public/sw.js`: handles `push` events, shows system notification, `notificationclick` opens/focuses the app
- PWA manifest `public/manifest.json` + `<link rel="manifest">` + `<meta name="theme-color">` in `index.html`
- Pinia store `stores/webPush.js`: permission request, subscribe/unsubscribe/test, base64url→Uint8Array VAPID key conversion
- Settings page: "Push notifications" section with subscribe/unsubscribe/test buttons and status indicator
- Service worker registered in `main.js` on app load
- New config fields: `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_CONTACT_EMAIL` (optional — push silently disabled if unset)
- `pywebpush>=1.9.0,<2` added to server dependencies

#### Monitor editing
- Edit modal `EditMonitorModal.vue` — pre-fills all fields from the existing monitor, calls `PATCH /api/v1/monitors/{id}`, emits `updated` on success
- Edit button (pencil icon) added to each row in `MonitorsView.vue`

#### UI / UX redesign ("Graphite Studio")
- New typography: `Plus Jakarta Sans` (UI) + `JetBrains Mono` (data/code) loaded from Google Fonts
- Design tokens via CSS custom properties (`--bg-surface`, `--text-1`, `--accent`, `--border`, etc.) — consistent palette across all components
- Fully responsive layout: sidebar slides in from the left on mobile (<1024 px) with a backdrop overlay; hamburger button with animated open/close icon in the topbar
- Language toggle relocated from the sidebar to the top-right header bar
- `NavLink.vue` rewritten with scoped CSS: clean active state (accent fill), animated hover, compact badge
- `MonitorRow.vue` redesigned: progressive disclosure — response time hidden <480 px, uptime hidden <640 px; DOWN dot animates with a `pulse-ring` halo
- `DashboardView.vue`: responsive stat cards (2 cols mobile → 3 cols tablet → 5 cols desktop), reworked grid layout
- `style.css`: new `.card`, `.btn-*`, `.input`, `.badge-*`, `.skeleton` shimmer loader, `.sidebar-overlay` backdrop
- ProbeMap: auto-zoom to probe locations on load (`fitBounds` with padding; single probe → zoom level 6)

### Changed
- Probe health auto-refresh in `ProbesView.vue`: data refreshed every 60 s; `isOnline` threshold raised from 120 s to 300 s to tolerate heartbeat jitter
- `AppLayout.vue`: topbar is now `position: sticky` so it stays visible while scrolling content
- Sidebar `position: sticky` on desktop (in flex flow) — eliminates the double-offset gap that appeared with `margin-left` + in-flow sidebar

### Fixed
- **i18n — duplicate `common:` key**: both `en.js` and `fr.js` had a second `common:` block (containing only `day`/`days`) that silently overrode the first block, making `common.save`, `common.cancel`, `common.loading`, etc. display as literal keys. Fixed by merging `day`/`days` into the first block and removing the duplicate.
- `AuditView.vue`: all strings were hardcoded in English with no `useI18n()` usage — fully rewritten with i18n keys and `toLocaleString()` (no more hardcoded `'fr-FR'` locale)
- `MaintenanceView.vue`: hardcoded English/French strings replaced with i18n keys; `formatDt` locale-agnostic
- **Hamburger button visible on desktop**: `lg:hidden` Tailwind class was not applied because the element uses scoped CSS — fixed with an explicit `@media (min-width: 1024px) { display: none }` rule
- **Sidebar gap on desktop**: redundant `margin-left: var(--sidebar-w)` on `.main` caused a 224 px blank strip alongside the sticky sidebar — rule removed

### Database migrations

| Revision | Description |
|----------|-------------|
| `f0a1b2c3d4e5` | Create `web_push_subscriptions` table with `user_id` FK, `endpoint`, `p256dh`, `auth`, `user_agent` |

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

[Unreleased]: https://github.com/AurevLan/WhatIsUp/compare/v1.5.0...HEAD
[1.5.0]: https://github.com/AurevLan/WhatIsUp/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/AurevLan/WhatIsUp/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/AurevLan/WhatIsUp/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/AurevLan/WhatIsUp/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/AurevLan/WhatIsUp/compare/v1.1.2...v1.2.0
[1.1.2]: https://github.com/AurevLan/WhatIsUp/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/AurevLan/WhatIsUp/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/AurevLan/WhatIsUp/compare/v1.0.3...v1.1.0
[1.0.3]: https://github.com/AurevLan/WhatIsUp/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/AurevLan/WhatIsUp/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/AurevLan/WhatIsUp/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.12.1...v1.0.0
[0.12.1]: https://github.com/AurevLan/WhatIsUp/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/AurevLan/WhatIsUp/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.8.1...v0.9.0
[0.8.1]: https://github.com/AurevLan/WhatIsUp/compare/v0.8.0...v0.8.1
[0.8.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.2.0...v0.4.0
[0.3.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.2.0...v0.4.0
[0.2.0]: https://github.com/AurevLan/WhatIsUp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/AurevLan/WhatIsUp/releases/tag/v0.1.0
