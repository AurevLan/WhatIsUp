# WhatIsUp — Guide Claude Code

> **Codemap** : lire `.claude/codemap.md` avant toute exploration large (index file→rôle). Mettre à jour à chaque ajout/suppression/renommage de fichier structurel.

## Stack & ports de développement

| Service | URL | Commande |
|---------|-----|----------|
| Frontend (Vite) | http://localhost:5173 | `cd frontend && npm run dev` |
| API (FastAPI) | http://localhost:8000 | `cd server && uvicorn whatisup.main:app --reload` |
| Swagger UI | http://localhost:8000/docs | — |
| Stack complète | — | `docker compose up -d` |

## Commandes essentielles

```bash
# Dev — backend
cd server && pip install -e ".[dev]"
cd server && pytest                          # tests
cd server && pytest tests/test_auth.py -v   # fichier précis
cd server && ruff check . && ruff format .  # lint + format
cd server && pip-audit                       # audit CVE

# Dev — frontend
cd frontend && npm install
cd frontend && npm run dev
cd frontend && npm run lint
cd frontend && npm audit

# Tests vitest — IMPÉRATIF Node 22 LTS (jsdom 29 ne supporte pas le localStorage
# natif de Node 25, "TypeError: localStorage.clear is not a function" sinon).
# CI utilise déjà Node 22 (ci.yml). Pour tester localement via Docker :
docker run --rm -v $(pwd)/frontend:/app -w /app node:22-alpine \
  sh -c "npm ci && npx vitest run"

# Docker
docker compose --env-file .env up -d         # démarrer la stack complète
docker compose --env-file .env build server  # rebuild après modif pyproject.toml
docker compose --env-file .env build probe   # rebuild probe
docker compose --env-file .env logs server | grep -E "admin|api_key|created"  # credentials premier boot

# Migration Alembic
cd server && alembic revision --autogenerate -m "description"
cd server && alembic upgrade head
cd server && alembic downgrade -1

# Générer des secrets
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
openssl rand -hex 32
```

## Architecture

```
server/whatisup/
  api/v1/       ← auth, monitors, probes, groups, alerts, public, ws,
                   status, audit, maintenance, metrics, ping
  core/         ← config, database, security (JWT+Fernet), middleware, limiter, redis
  models/       ← User, Monitor, MonitorGroup, Probe, CheckResult,
                   Incident, AlertRule, AlertChannel, AuditLog,
                   MaintenanceWindow, CustomMetric, StatusSubscription
  schemas/      ← Pydantic v2 (In / Out / Update par ressource)
  services/     ← incident, alert, stats, audit, maintenance,
                   heartbeat, retention
probe/whatisup_probe/
  checkers/     ← HTTP / TCP / UDP / DNS / SMTP / Ping / DomainExpiry / Scenario (Playwright)
  scheduler.py  ← APScheduler + trigger-now loop Redis
  reporter.py   ← push résultats vers central API
frontend/src/
  stores/       ← auth, websocket (Pinia)
  api/          ← client axios + modules par ressource
  views/        ← une vue par route
  components/   ← monitors/, probes/, shared/
  i18n/         ← en.js, fr.js, index.js (vue-i18n@9 Composition API)
```

## Patterns SQLAlchemy (critiques)

- Toujours `.is_(True)` / `.is_(False)` — jamais `is True` (compare l'objet Python, toujours False en SQLAlchemy)
- N+1 : utiliser `latest_results_subq(where_clause, group_col=CheckResult.xxx)` depuis `services/stats.py`
- Imports : `or_`, `func`, `select` en top-level — jamais inline dans les fonctions
- `uuid.UUID(str)` : utiliser l'import top-level `import uuid` — pas d'alias `import uuid as _uuid`
- `func.date_trunc` + asyncpg : utiliser `text("'day'")` comme premier argument — la version string provoque un `GroupingError` PostgreSQL

## Dépendances API (deps.py)

```python
get_current_user    # JWT obligatoire — utilisateur standard
require_superadmin  # JWT + is_superadmin=True
get_current_probe   # X-Probe-Api-Key (bcrypt + cache Redis SHA-256[:32], TTL 60s)
```

## CheckType (monitor.check_type)

`http` · `tcp` · `udp` · `dns` · `smtp` · `ping` · `domain_expiry` · `keyword` · `json_path` · `scenario` · `heartbeat`

## Sécurité — règles absolues

- JWT WebSocket : auth par message `{"type":"auth","token":"..."}` — jamais `?token=` dans l'URL (ANSSI)
- Secrets alert : `encrypt_channel_config(config)` avant DB, `decrypt_channel_config(config)` au dispatch
- Champs chiffrés Fernet (`_SECRET_FIELDS` dans `core/security.py`) : `secret` (dont HMAC webhook), `bot_token`, `password`, `integration_key` (PagerDuty), `api_key` (Opsgenie) — PAS `webhook_url` (non chiffré, choix assumé)
- URLs HTTP sortantes : appeler `_validate_webhook_url(url)` avant tout `httpx.post` (SSRF)
- `AlertRule` delete / `list_events` : toujours vérifier `owner_id` via JOIN — sans filtre = fuite cross-user
- Nouveaux endpoints : `@limiter.limit("X/minute")` + `request: Request` (slowapi)
- CORS production : pas de wildcard `*` ; origines HTTP rejetées au démarrage (`config.py`)
- SECRET_KEY par défaut : refus de démarrage en production (`ValueError` dans `validate_production_settings`)

## Pièges connus

- `GroupDetailView` : utiliser `monitorsApi.list({ group_id })` (enrichi) et non `groupsApi.monitors(id)` (brut, sans last_status/uptime)
- Champ manquant dans un schema Pydantic `*Out` → silencieusement absent côté frontend (ex: `scenario_result`)
- Playwright Docker (probe) : `ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` + `chmod -R 755` obligatoires pour l'utilisateur non-root
- `compute_daily_history` : `func.date_trunc("day", col)` → utiliser `text("'day'")` sinon `GroupingError` asyncpg
- `PublicPageView.vue` : pas d'alias `@/` dans Vite → utiliser `../api/public.js`
- Interpolation Vue `{{ '{{' + var + '}}' }}` → crash parser ; utiliser `<span v-text="'{{' + var + '}}'"></span>`

## Frontend WebSocket (`stores/websocket.js`)

- Stocker `pingInterval` dans une variable fermée — `clearInterval` dans `onclose` ET `disconnect()`
- `stopped = true` dans `disconnect()` pour bloquer l'auto-reconnect sur fermeture intentionnelle
- Envoyer le frame auth `{"type":"auth","token"}` dans `onopen`, avant tout autre message

## i18n (vue-i18n@9)

```javascript
// index.js : legacy: false (Composition API), locale par défaut 'en'
const { t } = useI18n()   // dans <script setup>
// Changer la langue :
import { setLocale } from '@/i18n'
setLocale('fr')            // persiste dans localStorage('whatisup_lang')
```
- Fichiers de traduction : `frontend/src/i18n/en.js` et `fr.js`
- Toute nouvelle string UI → ajouter dans `en.js` ET `fr.js`

## Responsive (mobile-first) — conventions

> Cible double : navigateur mobile **et** app native Android (Capacitor). Tailwind v4, breakpoints par défaut `sm:640 / md:768 / lg:1024 / xl:1280`. Suivi : `plan_responsive.md`.

- **Mobile-first** : la base CSS = mobile ; on élargit avec `md:`/`lg:`. Ne jamais régresser le rendu desktop.
- **Shell déjà responsive** : `AppLayout` gère drawer off-canvas + hamburger + overlay + scroll-lock (`< 1024px`). Ne pas le retoucher.
- **Tables — deux tiers selon l'usage** :
  - *Contenu primaire* (liste monitors) → **cartes ↔ tableau** (réf. `MonitorsView.vue`) : `<div class="md:hidden">` cartes empilées (touch ≥44px) + `<table class="hidden md:table">` colonnes dégressives (`hidden lg:table-cell` / `hidden sm:table-cell`). Pas de composant `ResponsiveTable` : ce duo fait foi.
  - *Tables denses secondaires/admin* (6-7 colonnes techniques : `AuditView`, `AdminView`, `TlsFleetView`, `GroupDetailView`) → **scroll horizontal** : wrapper `<div class="overflow-x-auto">` + `min-w-[Nrem]` sur le `<table>`. Préserve toutes les colonnes sans dupliquer le markup ; acceptable car surfaces power-user.
- **Grilles fluides sans breakpoint** : préférer `clamp()` pour la typo (cf. hero `DashboardView`) et `grid-template-columns: repeat(auto-fill, minmax(Npx, 1fr))` pour les grilles de cartes.
- **Lignes en grille fixe** (cf. `IncidentsView .inc-row`) : reflow via `@media (max-width: 640px)` ; les colonnes d'actions multi-boutons passent en **ligne pleine largeur** (`grid-column: 1 / -1`) avec `flex-wrap`, jamais comprimées dans une piste étroite.
- **Barres d'actions / filtres** : toujours `flex-wrap` (cf. `.filter-bar` global). Une rangée de boutons sans wrap déborde < 360px.
- **Helpers globaux** : `.fab` (masqué ≥640px), overrides padding `< 640px` dans `style.css` (`## Responsive page content`).
- Touch targets ≥ 44px en mobile (acquis A11Y-5) ; `prefers-reduced-motion` respecté (règle globale).

## Design system — boutons & badges

> Consolidation post-VELOURS (`plan_design_system.md`). Objectif : couche composants homogène par-dessus les tokens.

**Boutons** — variantes × tailles, jamais de surcharge de taille en inline :
- Variantes : `.btn-primary` · `.btn-secondary` · `.btn-ghost` · `.btn-danger` (définies dans `style.css`, couleurs **tokenisées** — `--accent` / `--down`, plus aucun hex codé en dur ; les 2 thèmes en découlent).
- Tailles (modificateurs) : `.btn-sm` (≈28px) · défaut = md (≈32px, rien à ajouter) · `.btn-lg` (≈40px). **Ne pas** remettre `h-8`/`h-9`/`text-xs`/`px-* py-*` en inline sur un `.btn-*` → utiliser `.btn-sm`/`.btn-lg`.
- Bouton-icône : `.btn-icon` (carré, ≥44px tactile mobile). Remplace les boutons-icône ad-hoc (`.ack-btn` etc.).

**Badges de statut** : composant `<StatusBadge :status>` — ne pas réimplémenter `badgeClass`/`dotClass`/`statusLabel` en local.

## Processus de release (release-please — AUTOMATISÉ, pas de tag manuel)

Piloté par les Conventional Commits (`feat:` → MINOR, `fix:`/`perf:` → PATCH, `feat!:` → MAJOR).
release-please maintient une **Release PR** (`chore: release main`) qui agrège les commits ;
**la merger suffit** : `release-please.yml` crée le tag + la GitHub Release puis chaîne
automatiquement (via `workflow_call`) :
- `release.yml` — build/push GHCR (`ghcr.io/aurevlan/whatisup-server` + `-probe`, `X.Y.Z` + `latest`) + notes depuis `CHANGELOG.md`
- `mobile-release.yml` — APK Android signé attaché à la release

Pièges connus (procédure détaillée : CONTRIBUTING.md) :
- Checks requis bloqués sur la Release PR (créée par GITHUB_TOKEN) → `gh pr close N && gh pr reopen N` sous l'identité utilisateur
- Runs en `action_required` après merge → `gh api -X POST .../actions/runs/<id>/approve`
- Le dispatch manuel de `release.yml` reste possible en fallback seulement

**Règles SemVer :**
- `MAJOR` : breaking change API ou DB incompatible
- `MINOR` : nouvelle feature rétrocompatible
- `PATCH` : bugfix / sécurité (release immédiate)
- Pre-releases : suffixe `-alpha`, `-beta`, `-rc1` → marquées comme pre-release sur GitHub

## Mobile (Capacitor / Android)

App ID : `io.github.aurevlan.whatisup` (immuable, ne **jamais** changer après publication store). Capacitor 8 → exige **JDK 21** (déjà en place dans `mobile/Dockerfile` et le workflow CI).

```bash
# Premier setup (génère frontend/android/) — Docker, ne pollue pas l'hôte
mobile/build.sh init

# Après modifs frontend → resync vers le projet Android
mobile/build.sh sync

# Builder un APK debug
mobile/build.sh apk
# → frontend/android/app/build/outputs/apk/debug/app-debug.apk
adb install -r frontend/android/app/build/outputs/apk/debug/app-debug.apk
```

**Live reload sur device physique** (dev rapide) :
```bash
# Lancer vite avec --host pour exposer sur le LAN
cd frontend && npm run dev -- --host
# Puis sur le téléphone (USB + adb), faire pointer Capacitor sur l'IP du PC :
# éditer temporairement capacitor.config.json → server.url = "http://<ip-pc>:5173"
# puis : mobile/build.sh sync && mobile/build.sh apk
```

**URL backend** : sur build natif, l'app affiche `ServerSetupView` au 1er lancement (saisie URL serveur, validée via `/api/health`, persistée en localStorage). Sur build web, l'app utilise le `/api/v1` relatif (proxy nginx) — comportement inchangé.

**Helper unique** : `frontend/src/lib/serverConfig.js` (`apiBaseUrl()`, `wsBaseUrl()`, `isNative()`, `isConfigured()`). Toute nouvelle URL backend dans le frontend doit passer par ce helper, jamais en dur.

**Releases APK** : `.github/workflows/mobile-release.yml` build sur tag `v*`. Secrets requis : `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`.

## Services clés

- `services/stats.py` : `compute_uptime()`, `compute_daily_history()`, `latest_results_subq()`
- `services/incident.py` : pipeline post-check (flapping → incident → renotify → common_cause). Bridge SLO via Health Engine si `Monitor.health_engine_enabled=True` (et flag env `LEGACY_INCIDENT_ENGINE` non set)
- `services/alert.py` : dispatch email/webhook/Telegram/Slack/Discord/Mattermost/Teams/PagerDuty/Opsgenie/Signal + SSRF guard + digest Redis + `suppress_on_network_partition`
- `services/health.py` + `services/slo.py` : **Health Engine V2** — agrégation 5 min p50/p95/p99, quorum_down/quorum_slow, divergence_score probe (seuil 0.5)
- `services/network_verdict.py` : classification incident `service_down` / `network_partition_asn|geo` / `inconclusive` (recompute toutes les 5 min)
- `services/probe_enrichment.py` : ASN lookup Team Cymru DNS (refresh opportuniste sur heartbeat, TTL 24 h)
- `services/diagnostics.py` : V2-01-01 enqueue/drain Redis pour traceroute/dig/openssl/ping/curl à l'ouverture d'incident
- `services/heartbeat.py` : tâche de fond — ouvre incidents si ping absent > `interval + grace`
- `services/retention.py` : purge nightly des `CheckResult` > `DATA_RETENTION_DAYS` (défaut 90)
- `api/v1/ws.py` : WebSocket dashboard (auth message) + `public/{slug}` (sans auth)
- `core/security.py` : JWT, bcrypt, Fernet (`encrypt_channel_config` / `decrypt_channel_config`)

## Health Engine V2 — ops prod

> Engine actif sur 17/17 monitors depuis 2026-05-06. Détails complets : `plan_v2_global_health.md`.

**Knobs critiques :**
- Activation per-monitor : toggle UI panel "Quorum & SLO" dans `MonitorDetailView` ou `PATCH /monitors/{id}` body `{"health_engine_enabled": false}`.
- Rollback global : env `LEGACY_INCIDENT_ENGINE=true` → court-circuite le bridge SLO dans `services/incident.process_check_result`. Aucune migration.
- Règle par défaut migration : `quorum_down` 60% / 5 min / min 2 probes / cooldown 60 s.
- Seuil divergence : `divergence_score > 0.5` → probe exclue du quorum (constante `_DIVERGENCE_EXCLUSION_THRESHOLD` dans `services/slo.py`).

**Diagnostic rapide** quand l'utilisateur signale un comportement bizarre incidents/alertes :
1. `Monitor.health_engine_enabled` ? Toggle ON sans `SLORule` active = monitor silencieux.
2. Faux positif `quorum_down` ? Check `monitor_health_states.probe_health` JSONB pour le `divergence_score` des probes.
3. Pas d'alerte perf alors que p95 élevé ? La migration ne crée que `quorum_down`. Créer manuellement une `quorum_slow`.
4. Comportement bizarre sur tous les monitors d'un coup ? Check `LEGACY_INCIDENT_ENGINE` env + redémarrages.

```sql
-- État engine d'un monitor
SELECT m.health_engine_enabled, sr.rule_type, sr.enabled, sr.quorum_ratio, sr.p95_threshold_ms,
       mhs.sample_count_5m, mhs.p95_5m::int, mhs.quorum_down_ratio, mhs.probe_health
FROM monitors m
LEFT JOIN slo_rules sr ON sr.monitor_id = m.id
LEFT JOIN monitor_health_states mhs ON mhs.monitor_id = m.id
WHERE m.id = '<uuid>';
```
