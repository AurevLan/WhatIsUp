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
# Tuning Postgres via .env (défauts : 256MB shared_buffers / 16MB work_mem / limite conteneur 1g).
# Sur un hôte plus gros : POSTGRES_SHARED_BUFFERS=1GB POSTGRES_EFFECTIVE_CACHE_SIZE=3GB
# POSTGRES_WORK_MEM=32MB POSTGRES_MEM_LIMIT=3g — garder MEM_LIMIT ≳ 3× SHARED_BUFFERS.
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
- Index déclarés dans `__table_args__` : alembic **compare les expressions**. Un index créé `DESC` par migration doit être déclaré `Index(..., text("col DESC"))` dans le modèle, sinon `autogenerate` propose de le reconstruire en ASC (cf. `models/result.py`). `postgresql_using` (BRIN) n'est pas comparé. Après toute migration d'index : relancer `autogenerate` sur une base migrée et vérifier qu'il ne propose rien

### Dérive modèle ↔ schéma — tolérance zéro (gate CI)

Le job CI `Alembic migrations` termine par `python scripts/check_model_drift.py` : sur une base à `head`,
`compare_metadata` doit retourner **0 diff**. Toute PR qui fait diverger les deux côtés casse le build.
Règles qui en découlent :

- **Tout nouveau modèle doit être importé dans `models/__init__.py`** (+ `__all__`). C'est le seul point
  d'entrée qu'`alembic/env.py` charge : un modèle absent de `Base.metadata` fait proposer à `autogenerate`
  de **dropper sa table**.
- Un index **PostgreSQL-only** (GIN, unique partiel) créé par migration doit quand même être déclaré dans
  `__table_args__`, avec `.ddl_if(dialect="postgresql")` pour rester hors du `create_all` SQLite des tests
  (cf. `models/incident.py`). Classe d'opérateurs (`jsonb_path_ops`) → `postgresql_ops`, jamais inline dans
  l'expression : alembic renonce à comparer une expression qui en contient une.
- Contrainte `UNIQUE` nommée en base → `UniqueConstraint(..., name="uq_...")` dans `__table_args__`.
  `unique=True` sur la colonne demande un *index unique* `ix_...`, ce n'est pas la même chose.
- Types JSON : sur PG on veut du `jsonb` → `JSON().with_variant(JSONB(), "postgresql")` (helper `_JSON`
  local au module), jamais `JSON` nu.
- **Pas d'`index=True` sur une PK** : la contrainte PK fournit déjà un btree unique.
- Lancer alembic/les scripts avec le repo en tête de `sys.path`. Un `python <script>` depuis un sous-dossier
  importe le `whatisup` **installé** (potentiellement périmé) et compare alors contre le mauvais modèle,
  **sans erreur** — on croit à une dérive massive qui n'existe pas.
- **Ne jamais interroger la connexion dans `alembic/env.py` avant `context.begin_transaction()`.** Une simple
  requête ouvre une transaction implicite ; alembic considère alors qu'elle appartient à quelqu'un d'autre et
  **ne commite jamais**. `alembic upgrade head` déroule toutes les migrations, sort en 0, et laisse la base
  intacte. C'est pourquoi le filtre `include_object` de `core/partitions.py` est **paresseux**.

### `check_results` est partitionné (plan V2, A-1)

`PARTITION BY RANGE (checked_at)`, une partition par mois UTC. Conséquences à connaître avant d'y toucher :

- **PK composite `(id, checked_at)`** — obligatoire (la clé de partition doit figurer dans toute contrainte
  unique). `id` seul n'est donc plus unique globalement : uuid4 côté client, aucune FK ne le référence.
- **Les partitions ne sont pas déclarées dans les modèles**, elles sont créées à l'exécution par
  `core/partitions.py` (boucle `partition_maintainer`, 6 h + au démarrage, 3 mois d'avance). **Si aucune
  partition ne couvre l'instant courant, tous les INSERT de résultats échouent** — c'est la seule tâche de
  fond dont la panne casse le produit, pas juste une commodité.
- **Partition `DEFAULT`** = filet anti-perte (sonde à l'horloge décalée). `ensure_check_result_partitions`
  la *draine* quand elle crée enfin le mois concerné : PG refuse de créer une partition dont la plage a des
  lignes coincées dans la `DEFAULT`, sans ce drainage le mois serait à jamais incréable.
- **Partition `check_results_legacy`** : l'ancienne table, attachée telle quelle (aucune copie de données).
  Couvre `[MINVALUE, début du mois suivant la migration)` et s'éteint d'elle-même une fois hors rétention.
- **Rétention** : `retention.py` droppe les partitions entièrement expirées, avec un cutoff calculé sur la
  rétention **la plus longue en vigueur** (`max(global, tous les `Monitor.data_retention_days`)) — un
  cutoff global détruirait l'historique d'un moniteur configuré pour le garder. Le `DELETE` ligne à ligne
  subsiste pour ce que le drop ne sait pas exprimer (rétention par moniteur). Depuis A-4 tous ces cutoffs
  sont **plafonnés par la frontière du builder de rollups** (cf. § Rétention différenciée).
- **Une requête non bornée dans le temps n'élague rien** : `ORDER BY checked_at DESC LIMIT 1` (le LATERAL de
  `fetch_latest_results`) devient un `Merge Append` sur toutes les partitions. Toujours des index scans, mais
  borner par `checked_at` quand c'est possible reste la bonne réponse si le nombre de partitions grossit.
- **Alembic** : les partitions sont des relations réelles absentes de `Base.metadata` → `env.py` et
  `scripts/check_model_drift.py` les masquent via `make_alembic_include_object` (filtre `relispartition`).
  Sans ça, `autogenerate` propose de **dropper toutes les partitions**.

### Rollups horaires `check_rollups_1h` (plan V2, A-2)

Agrégat horaire de `check_results`, construit par `services/rollup.py` (boucle leader, 5 min).
Lu par `stats.py` depuis A-3 (cf. § suivant).

- **Grain `(monitor_id, bucket)`**, pas `(monitor_id, probe_id, bucket)` : l'uptime est un **consensus
  cross-probe** (`_aggregate_consensus` = « minute up si *une* sonde de la vue l'a vue up »), qu'une ligne
  par sonde ne sait pas exprimer ; et des percentiles ne se réagrègent pas entre sondes. Les fenêtres de
  consensus sont donc résolues à la construction et stockées en compteurs **additifs** (24 lignes horaires
  sommées = exactement le chiffre du jour).
- **Exact à toute largeur** : compteurs de statuts, uptime consensus, avg/min/max (`rt_sum`/`rt_count`, pas
  une moyenne stockée). **Approché au-delà d'une heure** : p50/p95/p99, réagrégés depuis les percentiles
  horaires. `percentile_cont` est réimplémenté en Python à l'identique (test de parité PG) pour ne pas
  décaler les courbes le jour du rebranchement.
- **Agrégation en Python, pas en SQL** : la règle de consensus n'est pas un GROUP BY, et SQLite (tests) n'a
  ni `date_trunc` ni `percentile_cont` — deux implémentations dériveraient et c'est celle de PG qui serait
  non testée. Coût borné : une heure de lignes par run en régime stable.
- **Heure courante jamais agrégée** (elle bouge encore) → le temps réel reste servi par le brut.
- **Pas de table de watermark** : reprise déduite de `max(bucket)`, moins `rollup_recompute_hours` (résultats
  arrivés après la clôture de leur heure), et **avancée au premier `checked_at` réel** — sans ce saut, un
  trou de données plus long que `rollup_max_buckets_per_run` bloquerait la boucle définitivement.
- Knobs : `ROLLUP_ENABLED`, `ROLLUP_INTERVAL_SECONDS` (300), `ROLLUP_MAX_BUCKETS_PER_RUN` (168 = 1 semaine
  par run, ce qui cadence le backfill initial), `ROLLUP_RECOMPUTE_HOURS` (3).
- Rebuild manuel d'une plage (import a posteriori, bug d'agrégation corrigé) : `rebuild_range(db, start, end)`.
- **Purge** : `ROLLUP_RETENTION_MONTHS` (13 mois par défaut), cf. § Rétention différenciée.

### `stats.py` lit rollups + brut (plan V2, A-3)

`compute_daily_history(_bulk)`, `compute_percentile_timeseries` et `compute_uptime_in_range` servent les
heures couvertes depuis `check_rollups_1h` et le reste depuis le brut. À savoir avant d'y toucher :

- **Frontière dérivée, pas configurée** : `max(bucket) + 1 h` (`rollup_boundary()` dans `services/rollup.py`,
  partagée avec la rétention). Table de rollups vide → tout retombe sur le brut, c'est-à-dire le comportement
  d'avant A-3. Aucun knob à régler.
- **Le découpage est toujours sur une frontière d'heure** (`_rollup_window` arrondit start au ceil, end au
  floor). C'est ce qui rend l'addition exacte : une fenêtre de consensus (vue, minute) tient dans une seule
  heure, donc dans une seule source. Un découpage à la minute double-compterait.
- **Un seul accumulateur** (`_Aggregate`) reçoit les deux sources ; le brut y est replié en fenêtres minute
  exactement comme `_aggregate_consensus`. Toute nouvelle statistique doit passer par lui, sinon elle ne
  saura traiter que l'une des deux moitiés.
- **Seule approximation : le p95 au-delà d'une heure** (moyenne des p95 horaires pondérée par les
  échantillons) → `compute_uptime_in_range` renvoie `p95_is_estimate`, affiché en `≈` côté SLA. Le chemin
  tout-brut garde le p95 nearest-rank historique (`_legacy_p95`) pour ne rien décaler sans rollups.
- `compute_percentile_timeseries` **n'approxime rien** : grain rollup == grain bucket, relecture verbatim.
- Parité garantie par `tests/test_stats_rollup_parity.py` : chaque figure calculée deux fois (rollups vides
  puis remplis) et comparée, dont le cas builder **en retard** (l'historique ne doit pas se tronquer).

### Rétention différenciée brut / rollups (plan V2, A-4)

Deux horizons, parce que les deux tables répondent à des questions différentes : le brut porte le **détail
par résultat** (`scenario_result`, `tls_audit`, `dns_*`, horodatage exact) et coûte cher ; les rollups
portent la **forme de l'historique** (uptime, compteurs, percentiles horaires) pour deux ordres de grandeur
de moins.

- `DATA_RETENTION_DAYS` (90 j) ne régit plus que `check_results`. **Ne pas le raccourcir par défaut** :
  c'est un choix par déploiement, jamais quelque chose qu'une mise à jour fait dans le dos de l'exploitant.
- `ROLLUP_RETENTION_MONTHS` (13 mois, 0 = infini) régit `check_rollups_1h`. `DELETE` simple, pas de
  partitionnement : à ~140 k lignes/an la table entière pèse moins qu'un jour de brut. **Mois calendaires**
  (`_months_before`), pas `mois × 30 j` — sinon une comparaison année/année dérive de deux semaines.
- **Interlock : le purge du brut ne dépasse jamais le builder.** Tous les cutoffs (drop de partition,
  `DELETE` global, `DELETE` par moniteur) sont plafonnés par `rollup_boundary()`. Supprimer une ligne brute
  non encore repliée la perd dans **les deux** tables — le rollup qui devait lui survivre n'est jamais
  écrit. C'est ce qui rend sûr de descendre `DATA_RETENTION_DAYS` à 7 j pendant un backfill.
- Pas d'interlock dans deux cas où la frontière ne veut rien dire : `ROLLUP_ENABLED=false` (un watermark
  figé gèlerait le purge pour toujours → disque plein) et table de rollups **vide** (builder qui n'a pas
  encore écrit son premier bucket ; log `retention_no_rollup_floor` si ça persiste = builder cassé).
- La rétention par moniteur (`Monitor.data_retention_days`) reste **brut uniquement** : « je n'ai pas besoin
  du détail de ce moniteur » ≠ « efface son historique d'uptime ». Elle s'applique en revanche aux
  **métriques poussées** (C-2) : une métrique push *est* du détail brut.

### `custom_metrics` est partitionné aussi (plan V2, C-2)

Deuxième table pilotée par le temps, et la seule dont le plafond est fixé par l'application du tenant.
`PARTITION BY RANGE (pushed_at)`, PK composite `(id, pushed_at)`, même bascule que A-1 (rename + attach,
zéro copie — migration `c2d3e4f5a6b7`).

- **`core/partitions.py` est générique depuis C-2** : tout passe par une `PartitionSpec(parent, time_column)`
  — `CHECK_RESULTS`, `CUSTOM_METRICS`, `ALL_SPECS`. Les fonctions `*_check_result_*` restent comme wrappers.
  Une nouvelle table partitionnée = une déclaration, pas une copie du module.
- **Le seam de test a bougé** : `drop_expired_partitions` appelle `list_partitions`, pas le wrapper.
  Un test qui neutralise `list_check_result_partitions` pour borner les candidats ne borne plus rien et
  **droppe réellement** legacy + mois (constaté en écrivant C-2) → patcher `list_partitions`.
- **Rétention** : `METRICS_RETENTION_DAYS` (90 j, 0 = infini), purge par `purge_old_metrics` dans le job
  nocturne. Avant C-2 la table n'était purgée **nulle part** — le premier run après mise à jour supprime
  donc ce qui dépasse la fenêtre ; `0` restaure le comportement d'avant.
- **Pas de rollups pour les métriques** (donc pas d'interlock) : rien ne les agrège encore. Le grain
  d'agrégation dépend des labels que C-1 introduira — les figer avant serait à refaire.
- Faire C-2 **avant** C-1 est le point : convertir la table plate une fois le batch/labels en place serait
  une migration de données, alors qu'aujourd'hui c'est un rename instantané.

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
- `Monitor.custom_headers` : valeurs chiffrées via `encrypt_custom_headers()` / `decrypt_custom_headers()` (noms en clair). Tout nouveau chemin d'écriture (CRUD, import JSON, import IaC) doit chiffrer ; tout chemin de lecture destiné à la probe ou à l'export doit déchiffrer. Pas de masquage : le formulaire d'édition relit et resoumet ces valeurs
- Erreurs de canaux d'alerte : jamais `str(exc)` brut dans un log ou une réponse (l'URL httpx peut porter le token) → `redact_secrets(str(exc), decrypted_config)` de `services/channels/_helpers.py`. Côté probe, `_redact_secrets(text, variables)` avant tout `error_message` / `final_url` de scénario
- URLs HTTP sortantes : appeler `_validate_webhook_url(url)` avant tout `httpx.post` (SSRF)
- Emails : destinataires validés par `core/validators.is_valid_email` (aucun CR/LF → pas d'injection d'en-tête), construction via `EmailMessage` (jamais `MIMEMultipart`/compat32), sujet aplati (`" ".join(s.split())`), et `html.escape()` sur toute valeur utilisateur interpolée dans un corps HTML (nom de monitor/groupe, type, portée)
- Code généré destiné à être exécuté (export Playwright de l'extension) : `_escJs()` pour l'intérieur des littéraux, `_num()` pour les positions **non entourées de guillemets** — une valeur non numérique y devient du code
- Sonde — toute connexion sortante (socket, subprocess, httpx) passe par `_ssrf_resolve_pinned_sync(host)` puis vise **l'IP retournée**, jamais le nom : une seconde résolution rouvre une fenêtre de rebinding. Pour les binaires : `curl --resolve host:port:ip`, `openssl -connect ip:port -servername host`
- Sonde — motifs et `json_schema` fournis par un tenant : jamais `re`/`jsonschema.validate` en direct → `safe_search` / `validate_json_schema_sync` de `checkers/_regex_guard.py` (moteur `regex` interruptible + pool de threads isolé de l'executor par défaut). `asyncio.wait_for` autour d'un `run_in_executor` n'arrête pas le thread
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

- `services/stats.py` : `compute_uptime()`, `compute_daily_history()`, `latest_results_subq()` — lit
  `check_rollups_1h` + brut depuis A-3 (cf. § `stats.py` lit rollups + brut)
- `services/incident.py` : pipeline post-check (flapping → incident → renotify → common_cause). Bridge SLO via Health Engine si `Monitor.health_engine_enabled=True` (et flag env `LEGACY_INCIDENT_ENGINE` non set)
- `services/alert.py` : dispatch email/webhook/Telegram/Slack/Discord/Mattermost/Teams/PagerDuty/Opsgenie/Signal + SSRF guard + digest Redis + `suppress_on_network_partition`
- `services/health.py` + `services/slo.py` : **Health Engine V2** — agrégation 5 min p50/p95/p99, quorum_down/quorum_slow, divergence_score probe (seuil 0.5)
- `services/network_verdict.py` : classification incident `service_down` / `network_partition_asn|geo` / `inconclusive` (recompute toutes les 5 min)
- `services/probe_enrichment.py` : ASN lookup Team Cymru DNS (refresh opportuniste sur heartbeat, TTL 24 h)
- `services/diagnostics.py` : V2-01-01 enqueue/drain Redis pour traceroute/dig/openssl/ping/curl à l'ouverture d'incident
- `services/heartbeat.py` : tâche de fond — ouvre incidents si ping absent > `interval + grace`
- `services/retention.py` : purge nightly — `purge_old_results` (brut > `DATA_RETENTION_DAYS`, défaut 90 :
  drop de partition d'abord, `DELETE` résiduel ensuite) puis `purge_old_rollups`
  (> `ROLLUP_RETENTION_MONTHS`, défaut 13). Cf. §§ `check_results` est partitionné + Rétention différenciée
- `services/rollup.py` : **plan V2, A-2** — `build_rollups` (boucle fond) / `rebuild_range` (plage forcée),
  agrégat horaire `check_rollups_1h` (cf. § Rollups horaires)
- `core/partitions.py` : création/drop des partitions mensuelles de `check_results` + filtre alembic
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
