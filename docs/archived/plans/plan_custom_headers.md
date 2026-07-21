# Plan — `custom_headers` par monitor (HTTP/keyword/json_path)

> Objectif : permettre de spécifier des headers HTTP personnalisés par monitor (User-Agent, Authorization, Cookie, etc.). Origine du besoin : le monitor "Korben" (https://korben.info) renvoie 403 à toutes les sondes car Cloudflare filtre l'UA `python-httpx/*`. Sans champ par-monitor, la seule option est de changer l'UA global, ce qui n'est pas suffisant pour les cas d'auth/cookies.

## Périmètre

### Inclus
- Champ `Monitor.custom_headers` (JSONB nullable, dict[str,str])
- Validation Pydantic (taille, longueur, blacklist headers dangereux)
- Propagation probe → checker HTTP (et alias `keyword`/`json_path`)
- UA par défaut explicite côté probe (remplace `python-httpx/*`)
- UI MonitorForm : éditeur key/value (add/remove)
- i18n en/fr
- Tests server + probe

### Exclus (hors scope)
- Headers chiffrés (Bearer tokens secrets) → ticket suivant si besoin (réutiliser `encrypt_channel_config` pattern)
- Headers par scenario Playwright (déjà géré via steps)
- Wire-up `body_regex`/`expected_headers`/`json_schema` dans la heartbeat (bug pré-existant — out of scope)

## Validation

- `custom_headers: dict[str, str] | None`
- max **20 entrées**
- nom : 1–100 chars, regex `^[A-Za-z0-9-]+$`
- valeur : 1–500 chars
- **Blacklist** (case-insensitive) : `Host`, `Content-Length`, `Connection`, `Transfer-Encoding` — gérés par httpx, override = casse les requêtes
- (l'override de `User-Agent` est explicitement autorisé — c'est la raison d'être de la feature)

## Étapes

| # | Fichier(s) | Action |
|---|---|---|
| 1 | `server/whatisup/models/monitor.py` | `custom_headers: Mapped[dict\|None] = mapped_column(_JSON, nullable=True)` |
| 2 | `server/alembic/versions/n7p8q9r0s1t2_add_custom_headers.py` | `op.add_column("monitors", sa.Column("custom_headers", JSONB, nullable=True))` — `down_revision = "k3l4m5n6o7p8"` (revision ID `n7p8q9r0s1t2` choisie pour éviter collision avec `m1n2o3p4q5r6_add_teams.py`) |
| 3 | `server/whatisup/schemas/monitor.py` | Ajouter dans `MonitorCreate` / `MonitorUpdate` / `MonitorOut` + `field_validator` (taille, blacklist) |
| 4 | `server/whatisup/schemas/probe.py` | Ajouter `custom_headers` dans `ProbeMonitorConfig` |
| 5 | `server/whatisup/api/v1/monitors.py` | `custom_headers=payload.custom_headers` dans `create_monitor` + import_monitors `config_fields` |
| 6 | `server/whatisup/api/v1/probes.py` | `custom_headers=m.custom_headers` dans la construction `ProbeMonitorConfig` (heartbeat) |
| 7 | `server/whatisup/services/config_sync.py` | Ajouter `custom_headers` dans `_MONITOR_EXPORT_FIELDS` |
| 8 | `probe/whatisup_probe/checkers/_shared.py` | UA explicite par défaut dans `get_http_client` (`headers={"User-Agent": "WhatIsUp-Probe/1.x (+https://github.com/aurevlan/whatisup)"}`) |
| 9 | `probe/whatisup_probe/checkers/__init__.py` | Param `custom_headers: dict\|None` dans `perform_check`, ajouté au config |
| 10 | `probe/whatisup_probe/scheduler.py` | `custom_headers=monitor.get("custom_headers")` |
| 11 | `probe/whatisup_probe/checkers/http.py` | `headers={**(custom_headers or {})}` passés à `client.stream` (par-requête, n'altère pas le client partagé) |
| 12 | `frontend/src/components/monitors/EditMonitorModal.vue` + `CreateMonitorModal.vue` | UI key/value (add row, remove row), bind `monitor.custom_headers` |
| 13 | `frontend/src/views/MonitorDetail.vue` | Affichage read-only des headers configurés |
| 14 | `frontend/src/i18n/{en,fr}.js` | Labels `monitor.customHeaders.*` |
| 15 | `server/tests/test_monitors_custom_headers.py` (nouveau) | CRUD + validations (blacklist, max, types) |
| 16 | `probe/tests/test_http_checker_headers.py` (nouveau) | Headers transmis dans la requête httpx (mock) + UA par défaut |
| 17 | `.claude/codemap.md` | Note sur `custom_headers` (1 ligne dans CheckType / models) |

## Vérification finale

- `docker compose run --rm server ruff check . && ruff format --check .`
- `docker compose run --rm server pytest tests/test_monitors_custom_headers.py -v`
- `docker compose run --rm probe-local pytest tests/test_http_checker_headers.py -v`
- `docker compose --env-file .env up -d --build server probe-local`
- Sur l'UI : éditer le monitor "Korben", ajouter `User-Agent: Mozilla/5.0 ...`, déclencher un check
- Vérifier en DB : `SELECT status, http_status FROM check_results WHERE monitor_id = '5d5abc09-...' ORDER BY checked_at DESC LIMIT 3` → doit passer à `up` / `200`

## Références

- Bug observé 2026-05-02 : Korben.info → 403 sur toutes sondes (Central-Probe, Saran, probe-havannah). Reproduit : UA défaut → 403, UA Chrome → 200.
- Migration Alembic head au démarrage : `k3l4m5n6o7p8` (incident_diagnostics, V2-01-01).
