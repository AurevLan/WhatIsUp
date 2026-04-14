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
  checker.py    ← HTTP / TCP / DNS / Keyword / JSONPath / Scenario (Playwright)
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
get_current_probe   # X-Probe-Api-Key (bcrypt + cache Redis SHA-256[:32], TTL 300s)
```

## CheckType (monitor.check_type)

`http` · `tcp` · `dns` · `keyword` · `json_path` · `scenario` · `heartbeat`

## Sécurité — règles absolues

- JWT WebSocket : auth par message `{"type":"auth","token":"..."}` — jamais `?token=` dans l'URL (ANSSI)
- Secrets alert : `encrypt_channel_config(config)` avant DB, `decrypt_channel_config(config)` au dispatch
- Champs chiffrés Fernet : `bot_token`, `webhook_secret`, `webhook_url`, `integration_key` (PagerDuty), `api_key` (Opsgenie)
- URLs HTTP sortantes : appeler `_validate_webhook_url(url)` avant tout `httpx.post` (SSRF)
- `AlertRule` delete / `list_events` : toujours vérifier `owner_id` via JOIN — sans filtre = fuite cross-user
- Nouveaux endpoints : `@limiter.limit("X/minute")` + `request: Request` (slowapi)
- CORS production : pas de wildcard `*` ; origines HTTP rejetées au démarrage (`config.py`)
- SECRET_KEY par défaut : refus de démarrage en production (`ValueError` dans `validate_production_settings`)

## Pièges connus

- `PublicPage` model : jamais utilisé — employer `MonitorGroup.public_slug` directement
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

## Processus de release (SemVer)

```bash
# 1. Mettre à jour CHANGELOG.md (section [X.Y.Z] + liens en bas)
# 2. Commiter sur main (après merge de la PR)
git checkout main && git pull

# 3. Créer le tag annoté (déclenche le workflow release.yml)
git tag -a vX.Y.Z -m "vX.Y.Z — Titre court"
git push origin vX.Y.Z
```

Le workflow `.github/workflows/release.yml` fait automatiquement :
- Extraction des notes de release depuis `CHANGELOG.md`
- Build et push des images Docker sur GHCR (`ghcr.io/aurevlan/whatisup-server:X.Y.Z` + `latest`)
- Création de la GitHub Release avec les notes

**Règles SemVer :**
- `MAJOR` : breaking change API ou DB incompatible
- `MINOR` : nouvelle feature rétrocompatible
- `PATCH` : bugfix / sécurité (release immédiate)
- Pre-releases : suffixe `-alpha`, `-beta`, `-rc1` → marquées comme pre-release sur GitHub

## Mobile (Capacitor / Android)

App ID : `io.github.aurevlan.whatisup` (immuable, ne **jamais** changer après publication store). Capacitor 7 → exige **JDK 21** (déjà en place dans `mobile/Dockerfile` et le workflow CI).

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
- `services/incident.py` : pipeline post-check (flapping → incident → renotify → common_cause)
- `services/alert.py` : dispatch email/webhook/Telegram/Slack/PagerDuty/Opsgenie + SSRF guard + digest Redis
- `services/heartbeat.py` : tâche de fond — ouvre incidents si ping absent > `interval + grace`
- `services/retention.py` : purge nightly des `CheckResult` > `DATA_RETENTION_DAYS` (défaut 90)
- `api/v1/ws.py` : WebSocket dashboard (auth message) + `public/{slug}` (sans auth)
- `core/security.py` : JWT, bcrypt, Fernet (`encrypt_channel_config` / `decrypt_channel_config`)
