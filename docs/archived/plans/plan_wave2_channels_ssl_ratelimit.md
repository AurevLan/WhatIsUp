# Plan — Wave 2 (Sprint 3 partiel)

> Lot : T2-10 Discord · T2-11 Mattermost · T2-12 Teams · T2-05 SSL avancé · SC-07 Rate limit Redis distribué.
> Stratégie : 5 commits indépendants, chacun mergeable seul. Pre-commit hooks doivent passer à chaque commit. Release `v1.8.0` à la fin via release-please.

## T2-10 — Channel Discord

| # | Fichier | Action |
|---|---------|--------|
| 1 | `server/whatisup/models/alert.py` | Ajouter `discord = "discord"` à `AlertChannelType` |
| 2 | `server/alembic/versions/o1p2q3r4s5t6_add_discord_mattermost_teams_channels.py` | `op.execute("ALTER TYPE alert_channel_type ADD VALUE IF NOT EXISTS 'discord'")` etc. (down: no-op, enum value removal nécessite recreate — accepter migration irréversible documentée) |
| 3 | `server/whatisup/services/channels/discord.py` | Webhook format Discord : `{"embeds": [{"title", "description", "color", "fields": [{name,value,inline}], "footer", "timestamp"}]}` ; couleur RGB int (rouge `15158332`, vert `3066993`) |
| 4 | `server/whatisup/services/channels/__init__.py` | Importer + register `discord` |
| 5 | `server/tests/test_alert_channels_discord.py` | respx mock + assert payload Discord |
| 6 | `frontend/src/components/alerts/AlertChannelModal.vue` | option "Discord" + champ `webhook_url` |
| 7 | `frontend/src/i18n/{en,fr}.js` | `alerts.channels.discord.*` |

## T2-11 — Channel Mattermost

| # | Fichier | Action |
|---|---------|--------|
| 1 | Idem migration step 2 ci-dessus | Ajouter `mattermost` à l'enum |
| 2 | `services/channels/mattermost.py` | Format webhook Mattermost compatible Slack (`username`, `icon_emoji`, `text`, `attachments`) ; valider URL |
| 3 | `__init__.py` | Register |
| 4 | `tests/test_alert_channels_mattermost.py` | respx mock |
| 5 | `AlertChannelModal.vue` + i18n | Option + `webhook_url` |

## T2-12 — Channel Teams

| # | Fichier | Action |
|---|---------|--------|
| 1 | Migration enum | `teams` |
| 2 | `services/channels/teams.py` | Adaptive Card via webhook Power Automate (legacy MessageCard fonctionne aussi). Format : `{"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {...}}]}`. Couleur via `style: "good"` / `"attention"` |
| 3 | `__init__.py` | Register |
| 4 | `tests/test_alert_channels_teams.py` | respx mock |
| 5 | `AlertChannelModal.vue` + i18n | Option + `webhook_url` |

## T2-05 — SSL avancé

| # | Fichier | Action |
|---|---------|--------|
| 1 | `server/whatisup/models/monitor.py` | Champs `ssl_pin_sha256: str\|None` (64 hex), `ssl_check_chain: bool` (default True), `ssl_min_chain_days: int\|None` |
| 2 | Migration Alembic `p2q3r4s5t6u7_add_ssl_advanced.py` | `add_column` x3 |
| 3 | `server/whatisup/schemas/monitor.py` | Ajouter aux `MonitorIn/Out/Update` + validators (pin = 64 hex lowercase) |
| 4 | `server/whatisup/schemas/probe.py` | Propagation à `ProbeMonitorConfig` |
| 5 | `server/whatisup/api/v1/{monitors,probes}.py` | Construction payload |
| 6 | `server/whatisup/services/config_sync.py` | `_MONITOR_EXPORT_FIELDS` |
| 7 | `probe/whatisup_probe/checkers/_shared.py` | Refactor `extract_ssl_info` → retourne aussi `pin_sha256_hex`, `chain_min_days`, `chain_subjects: list[str]` (via `cert_chain` du `getpeercert(True)` + `cryptography.x509`) |
| 8 | `probe/whatisup_probe/checkers/__init__.py` + `scheduler.py` | Pass-through nouveaux champs |
| 9 | `probe/whatisup_probe/checkers/http.py` | Si `ssl_pin_sha256` configuré et mismatch → status `down` reason `ssl_pin_mismatch` ; idem chain expiry < `ssl_min_chain_days` |
| 10 | `probe/tests/test_ssl_advanced.py` | Mock `_extract_ssl_info_sync` ou serveur TLS local ; tests pin match/mismatch + chain expiry |
| 11 | `server/tests/test_monitors_ssl_advanced.py` | CRUD + validators |
| 12 | UI `Create/EditMonitorModal.vue` | Champs avancés (collapsible existant SSL) |
| 13 | `MonitorDetailView.vue` | Affichage pin + chain |
| 14 | i18n |

## SC-07 — Rate limit distribué

| # | Fichier | Action |
|---|---------|--------|
| 1 | `server/whatisup/core/limiter.py` | `Limiter(key_func=..., default_limits=["200/minute"], storage_uri=settings.redis_url)` ; fallback memory si Redis indispo via `in_memory_fallback_enabled=True` |
| 2 | `server/whatisup/core/config.py` | (déjà : `redis_url` existe) |
| 3 | `server/tests/test_rate_limit_distributed.py` | Vérifier que `limiter.storage_uri` est bien le `redis_url` config quand env var set |

## Vérification globale

- Pre-commit hooks à chaque commit : ruff/bandit/secrets/yaml/json/toml
- `docker compose run --rm server pytest tests/test_alert_channels_*.py tests/test_monitors_ssl_advanced.py tests/test_rate_limit_distributed.py -v`
- `docker compose run --rm probe-local pytest tests/test_ssl_advanced.py -v`
- Build frontend OK
- Push main → CI verte → release-please ouvre Release PR `v1.8.0` → merge → tag auto (config réparée hier)

## Hors scope

- Tests E2E réels Discord/Mattermost/Teams (besoin d'un webhook réel — uniquement smoke par `test()`)
- Templating personnalisé Discord embed (utiliser webhook_template existant si besoin)
- OCSP / CT log (cités dans la roadmap T2-05) → reportés à `T2-05bis` car nécessitent ajouts deps lourds (`cryptography.x509.ocsp`, requêtes async vers responder OCSP du CA). On livre **pinning + chain** dans cette première passe.
